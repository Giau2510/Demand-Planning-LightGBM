"""Downloadable report of exact-duplicate source rows (BigQuery history feed).

Written by the duplicate gate (connector.duplicate_gate / full-period validation) when duplicates are found, BEFORE
anything is aggregated or stored. The ingest is blocked whatever happens here: a failed report never lets a load
continue.

File: <reports_dir>/bigquery-duplicates/bq-trung-lap_<start>_<end>_<YYYYMMDD-HHMMSS>.xlsx (Vietnam time; an existing
name is never overwritten, a suffix -2, -3, ... is added). Sheets:
  Summary           check time, source, date range, rows checked, groups, rows in groups, extra rows, BLOCKED
  Duplicate_Rows    EVERY row of every duplicated group. The n rows of a group are identical in every compared column
                    (that is the definition), so the group is written n times with duplicate_occurrence 1..n
  Duplicate_Groups  one row per group: duplicate_group_id, occurrences and the compared values (to look the group up)
Both row sheets end with compared_on: "mapped columns except item_code" (1.2.11: an item code is never a uniqueness
criterion). Rows of a pending order (connector.PENDING_STATUSES) are exempt and never listed; the Summary counts them.
duplicate_group_id (DUP-00001, ...) follows the order of the compared values (BigQuery ORDER BY on every compared
column), so it is stable for the same data. Column headers are the SOURCE column names of the mapping.
If the .xlsx cannot be written, the same three tables are written as UTF-8 CSV files with the same base name.
Only the configured (mapped) columns are written; nothing of this goes to the logs.
"""
from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .. import paths
from ..timeutil import now_vn

log = logging.getLogger("df.bq")

FOLDER = "bigquery-duplicates"
PREFIX = "bq-trung-lap"
NAME_RE = re.compile(rf"^{PREFIX}_[0-9A-Za-z_.\-]+\.(xlsx|csv)$")
SHEETS = ("Summary", "Duplicate_Rows", "Duplicate_Groups")
RULE_VI = ("Hai dòng là trùng hoàn toàn khi MỌI cột được so sánh bằng nhau (BigQuery GROUP BY trên giá trị gốc, "
           "không chuyển sang chuỗi): NULL bằng NULL và khác mọi giá trị; số so theo giá trị trong đúng kiểu của cột; "
           "ngày/giờ so theo giá trị, không đổi múi giờ; chuỗi so chính xác (phân biệt hoa thường, giữ khoảng trắng).")
RULE_EN = ("Two rows are exact duplicates when EVERY compared column is equal (BigQuery GROUP BY on the native "
           "values, no text serialisation): NULL equals NULL and nothing else; numbers by value in the column type; "
           "dates/times by value, no time-zone conversion; strings exactly (case and spaces significant).")
PENDING_VI = ("Miễn trừ (chủ hệ thống, 21/10/2026): dòng của đơn chờ xác nhận (WAIT_TO_CONFIRM, có hoặc chưa có so_code) "
              "KHÔNG bị kiểm tra trùng - không chặn ingest, không bị DROP_EXACT loại bỏ, giữ đủ mọi dòng và số lượng; "
              "không cần so_code, không tạo mã đơn, không gộp đơn; trùng customer_id hay các cột khác không phải lý do "
              "loại dòng. Các dòng này được đếm riêng (kể cả dòng giống nhau ở mọi cột so sánh / mọi cột nguồn - chỉ để "
              "theo dõi). Dòng ở các trạng thái khác giữ nguyên kiểm tra trùng.")
PENDING_EN = ("Exemption (owner, 21/10/2026): rows of an order waiting for confirmation (WAIT_TO_CONFIRM, with or without "
              "so_code) are NOT checked for duplicates - never blocking, never dropped by DROP_EXACT, every row and its "
              "quantity kept; no order code is required or invented, no order is merged; a repeated customer_id or other "
              "matching columns are no reason to reject a row. They are counted apart (including rows identical in every "
              "compared / every source column - informative only). Rows of every other status keep the duplicate check.")
ITEM_VI = ("item_code (listing của SKU) không bao giờ là tiêu chí phân biệt: hai dòng giống nhau ở mọi cột khác, chỉ khác "
           "item_code, là trùng (ví dụ một dòng đơn bị join nhân ra theo các listing của SKU).")
ITEM_EN = ("item_code (the SKU's listing) is never a uniqueness criterion: two rows identical in every other compared column "
           "that differ only in their item code are duplicates (e.g. an order line fanned out over the SKU's listings by a join).")
MAPPED = "mapped columns except item_code"


def folder() -> Path:
    p = paths.reports_dir() / FOLDER
    p.mkdir(parents=True, exist_ok=True)
    return p


def _p(chk: dict, k: str):
    return (chk.get("pending_orders") or {}).get(k, 0)


def _cell(v):
    """Excel cannot store time-zone aware datetimes: TIMESTAMP values are written as ISO text with their offset
    (the exact source value); dates stay real dates, numbers stay numbers."""
    if isinstance(v, datetime):
        return v.isoformat() if v.tzinfo else v
    return v


def tables(chk: dict) -> dict[str, pd.DataFrame]:
    cols = chk["columns"]                    # [{"field", "alias", "column"}] in mapping order
    names = [c["column"] for c in cols]
    rows, groups = [], []
    for i, g in enumerate(chk.get("groups") or [], start=1):
        gid = f"DUP-{i:05d}"
        vals = [_cell(g["values"].get(c["alias"])) for c in cols]
        on = MAPPED
        groups.append([gid, g["occurrences"], *vals, on])
        for k in range(1, int(g["occurrences"]) + 1):
            rows.append([gid, k, *vals, on])
    summary = [
        ("Thời điểm kiểm tra (giờ Việt Nam) / Checked at", chk.get("checked_at_vn")),
        ("Bảng nguồn / Source table", chk.get("table")),
        ("Nguồn dữ liệu / Source mode", chk.get("source_label")),
        ("Nơi chạy / Run by", chk.get("context")),
        ("Phạm vi ngày / Date range", f"{chk['range']['start']} .. {chk['range']['end']}"),
        ("Số dòng nguồn đã kiểm tra / Source rows checked", chk.get("rows_checked")),
        ("Tổng demand_quantity đã kiểm tra / Quantity checked", chk.get("qty_checked")),
        ("Số nhóm trùng hoàn toàn / duplicate_groups", chk.get("duplicate_groups")),
        ("Tổng số dòng thuộc các nhóm trùng / duplicate_rows", chk.get("duplicate_rows")),
        ("Số dòng dư (mỗi nhóm giữ 1) / extra_duplicate_rows", chk.get("extra_duplicate_rows")),
        ("Trạng thái ingest / Ingest status", chk.get("ingest_status", "BLOCKED")),
        (f"Cột được so sánh ({len(names)}) / Compared columns", ", ".join(names)),
        ("Cột nguồn không so sánh (không ánh xạ, hoặc item_code) / Source columns not compared (not mapped, or item_code)",
         ", ".join(chk.get("not_compared") or []) or "-"),
        ("Quy tắc so sánh", RULE_VI),
        ("Comparison rule", RULE_EN),
        ("item_code", ITEM_VI),
        ("item_code (EN)", ITEM_EN),
        ("Đơn chờ xác nhận (WAIT_TO_CONFIRM)", PENDING_VI),
        ("Pending orders (WAIT_TO_CONFIRM)", PENDING_EN),
        ("Số dòng đơn chờ xác nhận (miễn trừ, giữ nguyên) / pending_orders rows", _p(chk, "rows")),
        ("Trong đó chưa có so_code / of which without order code", _p(chk, "without_order_code_rows")),
        ("Trong đó: nhóm / dòng giống nhau ở mọi cột so sánh (không chặn) / identical in every compared column (not blocking)",
         f"{_p(chk, 'identical_groups')} / {_p(chk, 'identical_rows')}"),
        ("Trong đó: nhóm / dòng giống nhau ở MỌI cột nguồn (không chặn, cần xem nếu nghi nhân dòng) / identical in every "
         "source column (not blocking; review for a possible join fan-out)",
         f"{_p(chk, 'whole_row_groups')} / {_p(chk, 'whole_row_rows')}"),
        ("Số nhóm có trong báo cáo / Groups in this report", len(groups)),
        ("Số dòng có trong báo cáo / Rows in this report", len(rows)),
    ]
    if chk.get("truncated"):
        summary.append(("CẢNH BÁO / WARNING", "Báo cáo bị giới hạn kích thước: chỉ có một phần các nhóm. Số đếm ở trên "
                                              "là đầy đủ. / The report is size-limited: only part of the groups."))
    return {"Summary": pd.DataFrame(summary, columns=["Mục / Item", "Giá trị / Value"]),
            "Duplicate_Rows": pd.DataFrame(rows, columns=["duplicate_group_id", "duplicate_occurrence", *names,
                                                          "compared_on"]),
            "Duplicate_Groups": pd.DataFrame(groups, columns=["duplicate_group_id", "occurrences", *names, "compared_on"])}


def _xlsx_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for name, df in sheets.items():
            df.to_excel(w, sheet_name=name, index=False)
            ws = w.sheets[name]
            ws.freeze_panes = "A2"
            for col in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col[:200])
                ws.column_dimensions[col[0].column_letter].width = min(max(12, width + 2), 80)
    return buf.getvalue()


def _free(base: Path) -> Path:
    """First unused base name: an existing report (.xlsx or its CSV fallback) is never overwritten."""
    cand, n = base, 2
    while (cand.parent / f"{cand.name}.xlsx").exists() or any(cand.parent.glob(f"{cand.name}_*.csv")):
        cand = base.parent / f"{base.name}-{n}"
        n += 1
    return cand


def write(chk: dict) -> dict:
    """Write the report; returns {"format": "xlsx", "file": name} or, when the .xlsx fails, the CSV fallback
    {"format": "csv", "files": [...], "xlsx_error": "..."}; {"format": None, "error": "..."} if nothing could be written."""
    def err(e):
        return f"{type(e).__name__}: {(str(e).splitlines() or [''])[0][:300]}"
    try:
        stamp = now_vn().strftime("%Y%m%d-%H%M%S")
        base = _free(folder() / f"{PREFIX}_{chk['range']['start']}_{chk['range']['end']}_{stamp}")
        sheets = tables(chk)
    except Exception as e:  # noqa: BLE001 - reported; the ingest stays blocked
        return {"format": None, "error": err(e)}
    target = base.parent / f"{base.name}.xlsx"
    try:
        target.write_bytes(_xlsx_bytes(sheets))
        return {"format": "xlsx", "file": target.name}
    except Exception as e:  # noqa: BLE001
        xlsx_error = err(e)
        log.error("duplicate report xlsx failed", extra={"ctx": {"error": xlsx_error}})
        target.unlink(missing_ok=True)          # never leave a half-written workbook
    try:
        files = []
        for name, df in sheets.items():
            p = base.parent / f"{base.name}_{name}.csv"
            df.to_csv(p, index=False, encoding="utf-8-sig")
            files.append(p.name)
        return {"format": "csv", "files": files, "xlsx_error": xlsx_error}
    except Exception as e:  # noqa: BLE001
        return {"format": None, "xlsx_error": xlsx_error, "error": err(e)}


def list_reports(limit: int = 30) -> list[dict]:
    try:
        d = folder()
    except Exception:  # noqa: BLE001 - no storage yet: nothing to list
        return []
    out = [{"name": p.name, "size": p.stat().st_size,
            "modified": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")}
           for p in d.iterdir() if p.is_file() and NAME_RE.match(p.name)]
    out.sort(key=lambda x: (x["modified"], x["name"]), reverse=True)
    return out[:limit]


def path_of(name: str) -> Path | None:
    """Only a report file of this folder (strict name pattern, no path separators)."""
    if not NAME_RE.match(name or ""):
        return None
    p = folder() / name
    return p if p.is_file() and p.parent == folder() else None

