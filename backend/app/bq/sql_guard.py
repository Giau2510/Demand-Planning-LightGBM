"""Static, conservative checks of a user SQL text BEFORE anything is sent to BigQuery.

The text is never rewritten. Checks: one statement only, must be a query (SELECT / WITH), no data-changing, DDL or
scripting keyword at the top level. The final authority is BigQuery's own dry run (`statement_type` must be SELECT),
and the app only ever runs the text as a sub-query `SELECT ... FROM ( <user sql> )`, where a write statement is a
syntax error anyway. Notes (not errors) point at spots that only the dry run can decide, e.g. a trailing comma.
"""
from __future__ import annotations

import re

FORBIDDEN = ("INSERT", "UPDATE", "DELETE", "MERGE", "CREATE", "DROP", "ALTER", "TRUNCATE", "GRANT", "REVOKE",
             "CALL", "EXECUTE", "DECLARE", "SET", "BEGIN", "COMMIT", "ROLLBACK", "EXPORT", "LOAD", "ASSERT", "RAISE",
             "REPLACE")
# REPLACE is also a string function: only flagged as `CREATE OR REPLACE` / `INSERT OR REPLACE` style statements
_FUNC_OK = {"REPLACE"}
MAX_LEN = 100_000


def _mask(sql: str) -> str:
    """Replace comments, string literals and `quoted identifiers` with spaces (same length, positions kept)."""
    out = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if ch == "-" and nxt == "-" or ch == "#":
            j = sql.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif ch == "/" and nxt == "*":
            j = sql.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(" " * (j - i))
            i = j
        elif ch in ("'", '"', "`"):
            triple = sql[i:i + 3] == ch * 3 and ch != "`"
            q = ch * 3 if triple else ch
            j = i + len(q)
            while j < n:
                if sql[j] == "\\" and ch != "`":
                    j += 2
                    continue
                if sql.startswith(q, j):
                    j += len(q)
                    break
                j += 1
            out.append(" " * (min(j, n) - i))
            i = j
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def check(sql: str) -> dict:
    errors, notes = [], []
    if not sql or not sql.strip():
        return {"ok": False, "errors": [{"code": "SQL_EMPTY"}], "notes": []}
    if len(sql) > MAX_LEN:
        errors.append({"code": "SQL_TOO_LONG", "detail": f"> {MAX_LEN} characters"})
    m = _mask(sql)
    body = m.rstrip()
    trailing_semicolon = body.endswith(";")
    if trailing_semicolon:
        body = body[:-1]
    if ";" in body:
        errors.append({"code": "SQL_MULTIPLE_STATEMENTS"})
    first = re.match(r"\s*\(*\s*([A-Za-z_]+)", body)
    if not first or first.group(1).upper() not in ("SELECT", "WITH"):
        errors.append({"code": "SQL_NOT_A_QUERY", "detail": first.group(1).upper() if first else None})
    words = re.findall(r"[A-Za-z_][A-Za-z_0-9]*", body)
    up = [w.upper() for w in words]
    for i, w in enumerate(up):
        if w in FORBIDDEN and w not in _FUNC_OK:
            errors.append({"code": "SQL_FORBIDDEN_KEYWORD", "detail": w})
        elif w == "REPLACE" and i > 0 and up[i - 1] == "OR":
            errors.append({"code": "SQL_FORBIDDEN_KEYWORD", "detail": "OR REPLACE"})
    seen, uniq = set(), []
    for e in errors:
        k = (e["code"], e.get("detail"))
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    if re.search(r",\s*FROM\b", body, re.IGNORECASE):
        line = body[:re.search(r",\s*FROM\b", body, re.IGNORECASE).start()].count("\n") + 1
        notes.append({"code": "TRAILING_COMMA_BEFORE_FROM", "line": line,
                      "detail": "Có dấu phẩy ngay trước FROM. Chỉ dry-run BigQuery xác định đây có phải lỗi cú pháp; "
                                "ứng dụng không tự sửa SQL."})
    if trailing_semicolon:
        notes.append({"code": "TRAILING_SEMICOLON", "detail": "Dấu ';' cuối câu được bỏ khi chạy như truy vấn con."})
    if re.search(r"\bLEFT\s+JOIN\b", body, re.IGNORECASE) and re.search(r"\bWHERE\b", body, re.IGNORECASE):
        notes.append({"code": "LEFT_JOIN_WITH_WHERE", "detail": "Điều kiện WHERE trên cột của bảng LEFT JOIN sẽ loại các "
                                                              "dòng không khớp (tương đương INNER JOIN). Cần xác nhận ý đồ."})
    # on the original text: string literals are blanked in `body`, so CURRENT_DATE('Asia/...') would look empty there
    if re.search(r"\bCURRENT_DATE\s*\(\s*\)", sql, re.IGNORECASE) or re.search(r"\bCURRENT_DATE\b(?!\s*\()", body, re.IGNORECASE):
        notes.append({"code": "CURRENT_DATE_WITHOUT_TIMEZONE", "detail": "CURRENT_DATE() không có múi giờ dùng UTC."})
    if re.search(r"\bDATE\s*\(\s*[A-Za-z_][\w.]*\s*\)", body) and re.search(r"Asia/Ho_Chi_Minh", sql):
        notes.append({"code": "DATE_OF_TIMESTAMP_WITHOUT_TIMEZONE",
                      "detail": "DATE(cột) không có múi giờ dùng UTC nếu cột là TIMESTAMP, trong khi câu lệnh có so sánh theo "
                                "Asia/Ho_Chi_Minh. Cần kiểm tra kiểu cột và ý đồ."})
    return {"ok": not uniq, "errors": uniq, "notes": notes, "trailing_semicolon": trailing_semicolon}


def as_subquery(sql: str) -> str:
    """The user text, unchanged except a single final ';' statement terminator, wrapped for use after FROM."""
    m = _mask(sql).rstrip()
    text = sql.rstrip()
    if m.endswith(";"):
        text = text[:len(m) - 1].rstrip() if len(text) >= len(m) else text.rstrip(";")
    return f"(\n{text}\n)"
