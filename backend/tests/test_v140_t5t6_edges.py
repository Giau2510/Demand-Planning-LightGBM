"""1.4.0 T5/T6 edge cases: forecast source upload (header / value variants, empty file, long notes, limits, preview
store eviction / expiry / single use / stale), URL-encoded keys on the PUT route, append-only history through the API,
download -> upload round trips, AVG_DEMAND read precedence, export run choice (two SEL2 runs, non-SEL2 runs, stale
horizon), the streaming XLSX writer (Vietnamese sheet names, -0.0 / 1e21, row-count limit) and the export download
headers / path parameter. Integration with fakes (isolated temporary database, TestClient) + unit (temporary files)."""
import hashlib
import io
import itertools
import json
import threading
import zipfile
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from openpyxl import Workbook, load_workbook

from app import db, paths
from app import settings_service as ss
from app.messages import AppError
from app.ml.sel2 import avg_demand, export
from app.ml.sel2 import source_config as sc
from app.ml.sel2.xlsx_stream import Sheet, write_xlsx

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HDR = ("sku_code", "fc_code", "forecast_source")
HDR_NOTE = ("sku_code", "fc_code", "forecast_source", "ghi_chu")
D = date(2026, 11, 2)
SCOPE = "SC-EDGE"


# ------------------------------------------------------------------ helpers
def _xlsx(rows, header=HDR, pre=()) -> io.BytesIO:
    wb = Workbook()
    ws = wb.active
    for p in pre:
        ws.append(list(p))
    if header is not None:
        ws.append(list(header))
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _config():
    with db.read() as c:
        return {(r["sku_code"], r["fc_code"]): r for r in db.rows(c, "SELECT * FROM forecast_source_config")}


def _history():
    with db.read() as c:
        return db.rows(c, "SELECT * FROM forecast_source_config_history ORDER BY id")


@pytest.fixture
def previews(sel2_on, monkeypatch):
    """Empty in-process preview store for this test only (the module-level dict is shared by the process)."""
    store: dict = {}
    monkeypatch.setattr(sc, "_previews", store)
    return store


# ------------------------------------------------------------------ upload: header / value variants
def test_header_case_whitespace_and_column_order_are_accepted(previews):
    f = _xlsx([("note 1", "LightGBM", " F1 ", "S1"), ("", "  lightgbm\t", "F1", "S2"),
               (None, " AVG_DEMAND ", "F1", "S3")],
              header=("  Ghi_Chu ", "FORECAST_SOURCE", "Fc_Code", " SKU_CODE "))
    p = sc.preview_upload(f)
    assert p["has_ghi_chu"] is True and p["counts"] == {"rows": 3, "changed": 2, "unchanged": 1, "errors": 0}
    assert [(c["sku_code"], c["fc_code"], c["new_source"], c["ghi_chu"]) for c in p["changes"]] == [
        ("S1", "F1", "LIGHTGBM", "note 1"), ("S2", "F1", "LIGHTGBM", None)]


def test_vietnamese_header_and_value_variants_are_pinned(previews):
    # "Ghi chú" (Vietnamese, with a space) is not the ghi_chu column: the file is read as without notes
    f = _xlsx([("S1", "F1", "LIGHTGBM", "ghi chú tiếng Việt")], header=("sku_code", "fc_code", "forecast_source", "Ghi chú"))
    p = sc.preview_upload(f)
    assert p["has_ghi_chu"] is False and p["changes"][0]["ghi_chu"] is None
    # Vietnamese words for the sources are not sources (no guessing); diacritics in keys / notes are kept exactly
    f = _xlsx([("S1", "F1", "Trung bình"), ("S2", "F1", "LIGHT GBM"), ("S3", "F1", "lightgbm."),
               ("SKU-Đà-Nẵng", "FC Hà Nội", "lightgbm", "Chuyển sang LightGBM – đợt 1")], header=HDR_NOTE)
    p = sc.preview_upload(f)
    assert [(e["row"], e["reason"], e["forecast_source"]) for e in p["errors"]] == [
        (2, "UNKNOWN_SOURCE", "Trung bình"), (3, "UNKNOWN_SOURCE", "LIGHT GBM"), (4, "UNKNOWN_SOURCE", "lightgbm.")]
    assert [c["sku_code"] for c in p["changes"]] == ["SKU-Đà-Nẵng"] and p["counts"]["errors"] == 3
    assert p["can_apply"] is False                              # any error row blocks the whole file
    f = _xlsx([("SKU-Đà-Nẵng", "FC Hà Nội", "lightgbm", "Chuyển sang LightGBM – đợt 1")], header=HDR_NOTE)
    p = sc.preview_upload(f)
    sc.apply_upload(p["preview_id"], confirm=True, changed_by="tester")
    row = _config()[("SKU-Đà-Nẵng", "FC Hà Nội")]
    assert row["forecast_source"] == "LIGHTGBM" and row["ghi_chu"] == "Chuyển sang LightGBM – đợt 1"


def test_numeric_keys_are_read_as_text_without_decimal_point(previews):
    p = sc.preview_upload(_xlsx([(123, 7.0, "LIGHTGBM"), (1.5, "F1", "LIGHTGBM")]))
    assert [(c["sku_code"], c["fc_code"]) for c in p["changes"]] == [("123", "7"), ("1.5", "F1")]


def test_header_only_file_has_zero_rows_and_applies_nothing(previews):
    p = sc.preview_upload(_xlsx([], header=HDR_NOTE))
    assert p["counts"] == {"rows": 0, "changed": 0, "unchanged": 0, "errors": 0}
    assert p["can_apply"] is False and p["changes"] == [] and p["errors"] == []
    out = sc.apply_upload(p["preview_id"], confirm=True)
    assert out == {"batch_id": None, "applied": 0, "counts": p["counts"]}
    assert _config() == {} and _history() == []
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM audit_log WHERE action='FORECAST_SOURCE_UPLOAD_APPLIED'").fetchone()[0] == 0


def test_empty_workbook_and_header_beyond_the_scan_rows(previews):
    with pytest.raises(AppError) as e:
        sc.preview_upload(_xlsx([], header=None))
    assert e.value.code == "SOURCE_CONFIG_BAD_HEADER"
    # header on row 10 (9 rows before) is found; on row 11 it is not
    p = sc.preview_upload(_xlsx([("S1", "F1", "LIGHTGBM")], pre=[("x",)] * 9))
    assert p["changes"][0]["row"] == 11
    with pytest.raises(AppError) as e:
        sc.preview_upload(_xlsx([("S1", "F1", "LIGHTGBM")], pre=[("x",)] * 10))
    assert e.value.code == "SOURCE_CONFIG_BAD_HEADER"


def test_row_and_byte_limits(previews, monkeypatch):
    monkeypatch.setattr(sc, "MAX_UPLOAD_ROWS", 3)
    with pytest.raises(AppError) as e:
        sc.preview_upload(_xlsx([(f"S{i}", "F1", "LIGHTGBM") for i in range(4)]))
    assert e.value.code == "SOURCE_CONFIG_FILE_TOO_LARGE" and e.value.status == 413
    assert sc.preview_upload(_xlsx([(f"S{i}", "F1", "LIGHTGBM") for i in range(3)]))["counts"]["changed"] == 3
    monkeypatch.setattr(sc, "MAX_UPLOAD_BYTES", 100)
    with pytest.raises(AppError) as e:
        sc.preview_upload(_xlsx([("S1", "F1", "LIGHTGBM")]))
    assert e.value.code == "SOURCE_CONFIG_FILE_TOO_LARGE"
    assert len(previews) == 1                                   # the refused files left no preview


def test_very_long_note_is_stored_unchanged(previews):
    note = ("Ghi chú dài – " * 3000)[:32767]                     # Excel's maximum characters per cell
    p = sc.preview_upload(_xlsx([("S1", "F1", "LIGHTGBM", note)], header=HDR_NOTE))
    sc.apply_upload(p["preview_id"], confirm=True, changed_by="tester")
    assert _config()[("S1", "F1")]["ghi_chu"] == note and _history()[0]["ghi_chu"] == note
    # no length limit on the single change (UI / API): pinned
    out = sc.set_one("S2", "F1", "LIGHTGBM", ghi_chu="x" * 100_000, confirm=True)
    assert out["changed"] and len(_config()[("S2", "F1")]["ghi_chu"]) == 100_000


def test_round_trip_of_a_note_longer_than_an_excel_cell(previews):
    """A note > 32,767 characters can be set by PUT; the download must still upload back with 0 changes."""
    sc.set_one("S1", "F1", "LIGHTGBM", ghi_chu="y" * 40_000, confirm=True)
    p = sc.preview_upload(io.BytesIO(sc.download_xlsx()))
    assert p["counts"] == {"rows": 1, "changed": 0, "unchanged": 1, "errors": 0}


def test_note_column_absent_keeps_the_stored_note_and_empty_cell_clears_it(previews):
    sc.set_one("S1", "F1", "LIGHTGBM", ghi_chu="giữ", confirm=True)
    sc.set_one("S2", "F1", "LIGHTGBM", ghi_chu="xoá", confirm=True)
    p = sc.preview_upload(_xlsx([("S1", "F1", "AVG_DEMAND"), ("S2", "F1", "LIGHTGBM")]))
    assert p["counts"]["changed"] == 1 and p["changes"][0]["ghi_chu"] == "giữ"
    p = sc.preview_upload(_xlsx([("S1", "F1", "LIGHTGBM", "giữ"), ("S2", "F1", "LIGHTGBM", "   ")], header=HDR_NOTE))
    assert [(c["sku_code"], c["old_ghi_chu"], c["ghi_chu"]) for c in p["changes"]] == [("S2", "xoá", None)]
    sc.apply_upload(p["preview_id"], confirm=True)
    assert _config()[("S2", "F1")]["ghi_chu"] is None and _config()[("S1", "F1")]["ghi_chu"] == "giữ"


# ------------------------------------------------------------------ preview store
def test_sixth_preview_evicts_the_oldest(previews):
    ids = [sc.preview_upload(_xlsx([(f"S{i}", "F1", "LIGHTGBM")]))["preview_id"] for i in range(6)]
    assert len(set(ids)) == 6 and set(previews) == set(ids[1:])
    with pytest.raises(AppError) as e:
        sc.apply_upload(ids[0], confirm=True)
    assert e.value.code == "SOURCE_CONFIG_PREVIEW_NOT_FOUND" and e.value.status == 404
    assert sc.apply_upload(ids[1], confirm=True)["applied"] == 1
    assert set(_config()) == {("S1", "F1")}


def test_preview_expires_after_30_minutes(previews, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(sc, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    a = sc.preview_upload(_xlsx([("S1", "F1", "LIGHTGBM")]))["preview_id"]
    b = sc.preview_upload(_xlsx([("S2", "F1", "LIGHTGBM")]))["preview_id"]
    clock[0] += sc.PREVIEW_TTL_SECONDS - 0.5
    assert sc.apply_upload(a, confirm=True)["applied"] == 1
    clock[0] += 0.5                                             # exactly 30 min after b: expired
    with pytest.raises(AppError) as e:
        sc.apply_upload(b, confirm=True)
    assert e.value.code == "SOURCE_CONFIG_PREVIEW_NOT_FOUND" and set(_config()) == {("S1", "F1")}
    assert previews == {}


def test_apply_twice_and_concurrent_apply_write_one_batch(previews, client):
    up = client.post("/api/sel2/source-config/upload",
                     files={"file": ("cfg.xlsx", _xlsx([("S1", "F1", "LIGHTGBM"), ("S2", "F1", "LIGHTGBM")]).getvalue(),
                                     XLSX)})
    pid = up.json()["preview_id"]
    results, errors = [], []

    def go():
        try:
            results.append(sc.apply_upload(pid, confirm=True, changed_by="tester"))
        except AppError as e:
            errors.append(e.code)
    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert len(results) == 1 and results[0]["applied"] == 2
    assert errors in (["SOURCE_CONFIG_PREVIEW_STALE"], ["SOURCE_CONFIG_PREVIEW_NOT_FOUND"])
    h = _history()
    assert len(h) == 2 and {r["batch_id"] for r in h} == {results[0]["batch_id"]}
    r = client.post("/api/sel2/source-config/apply", json={"preview_id": pid, "confirm": True})
    assert r.status_code == 404 and r.json()["code"] == "SOURCE_CONFIG_PREVIEW_NOT_FOUND" and len(_history()) == 2


def test_note_only_change_between_preview_and_apply_is_stale(previews):
    sc.set_one("S1", "F1", "LIGHTGBM", confirm=True)
    p = sc.preview_upload(_xlsx([("S1", "F1", "AVG_DEMAND"), ("S2", "F1", "LIGHTGBM")]))
    sc.set_one("S1", "F1", "LIGHTGBM", ghi_chu="đổi ghi chú", confirm=True)     # same source, other note
    with pytest.raises(AppError) as e:
        sc.apply_upload(p["preview_id"], confirm=True)
    assert e.value.code == "SOURCE_CONFIG_PREVIEW_STALE" and e.value.status == 409
    assert set(_config()) == {("S1", "F1")} and len(_history()) == 2
    # the refused preview is kept and stays refused (no partial retry)
    with pytest.raises(AppError) as e:
        sc.apply_upload(p["preview_id"], confirm=True)
    assert e.value.code == "SOURCE_CONFIG_PREVIEW_STALE"


def test_change_of_another_key_or_an_earlier_upload_between_preview_and_apply(previews):
    p1 = sc.preview_upload(_xlsx([("S1", "F1", "LIGHTGBM")]))
    p2 = sc.preview_upload(_xlsx([("S1", "F1", "LIGHTGBM"), ("S2", "F1", "LIGHTGBM")]))
    sc.set_one("S9", "F9", "LIGHTGBM", confirm=True)              # a key outside the preview: not stale
    assert sc.apply_upload(p1["preview_id"], confirm=True)["applied"] == 1
    with pytest.raises(AppError) as e:                           # S1 written by p1 since p2 was made
        sc.apply_upload(p2["preview_id"], confirm=True)
    assert e.value.code == "SOURCE_CONFIG_PREVIEW_STALE" and ("S2", "F1") not in _config()


def test_preview_allowed_but_apply_refused_while_the_pipeline_is_off(previews):
    p = sc.preview_upload(_xlsx([("S1", "F1", "LIGHTGBM")]))
    ss.update("sel2_pipeline", {"enabled": False}, note="tests: switch off between preview and apply")
    with pytest.raises(AppError) as e:
        sc.apply_upload(p["preview_id"], confirm=True)
    assert e.value.code == "SEL2_PIPELINE_DISABLED" and _config() == {} and _history() == []


# ------------------------------------------------------------------ PUT route: keys with special characters
@pytest.mark.parametrize("sku, fc", [("SKU 1", "FC A"), ("SKU%", "50%"), ("SKU+1", "F#1"), ("SKU-Đ", "Hà Nội"),
                                     ("SKU?x=1", "F&1")])
def test_put_with_url_encoded_keys(previews, client, sku, fc):
    """Keys with spaces, '%', '+', '#', '?', '&' and Vietnamese letters, percent-encoded. (A key holding an encoded
    escape such as 'SKU%20' cannot be tested here: Starlette's TestClient unquotes the already decoded path a second
    time, starlette/testclient.py:220/248; uvicorn decodes once.)"""
    from urllib.parse import quote
    url = f"/api/sel2/source-config/{quote(sku, safe='')}/{quote(fc, safe='')}"
    r = client.put(url, json={"forecast_source": "LIGHTGBM", "confirm": True})
    assert r.status_code == 200, r.text
    assert set(_config()) == {(sku, fc)}
    got = client.get(url).json()
    assert (got["sku_code"], got["fc_code"], got["forecast_source"], got["configured"]) == (sku, fc, "LIGHTGBM", True)


def test_put_with_an_encoded_slash_in_the_key_is_pinned(previews, client):
    """%2F is decoded before routing: 'A/B' never reaches the handler as one key (pinned: 404/405, nothing stored).
    A key with '/' can only be set by upload."""
    r = client.put("/api/sel2/source-config/A%2FB/F1", json={"forecast_source": "LIGHTGBM", "confirm": True})
    assert r.status_code in (404, 405) and _config() == {}
    p = sc.preview_upload(_xlsx([("A/B", "F1", "LIGHTGBM")]))
    sc.apply_upload(p["preview_id"], confirm=True)
    assert set(_config()) == {("A/B", "F1")}


def test_put_trims_edge_spaces_of_the_url_keys(previews, client):
    r = client.put("/api/sel2/source-config/%20S1%20/F1%20", json={"forecast_source": "LIGHTGBM", "confirm": True})
    assert r.status_code == 200 and set(_config()) == {("S1", "F1")}
    r = client.put("/api/sel2/source-config/%20/F1", json={"forecast_source": "LIGHTGBM", "confirm": True})
    assert r.status_code == 422 and r.json()["code"] == "SOURCE_CONFIG_INVALID_KEY"


# ------------------------------------------------------------------ history append-only through the API
def test_history_has_no_update_or_delete_path_in_the_api(previews, client):
    client.put("/api/sel2/source-config/S1/F1", json={"forecast_source": "LIGHTGBM", "confirm": True})
    client.put("/api/sel2/source-config/S1/F1", json={"forecast_source": "AVG_DEMAND", "confirm": True})
    before = _history()
    assert len(before) == 2
    for method in ("PUT", "PATCH", "DELETE", "POST"):
        r = client.request(method, "/api/sel2/source-config/history", json={})
        assert r.status_code == 405, (method, r.status_code)
    for method in ("PATCH", "DELETE", "POST"):
        r = client.request(method, "/api/sel2/source-config/S1/F1", json={})
        assert r.status_code == 405, (method, r.status_code)
    assert client.delete("/api/sel2/source-config").status_code == 405
    # setting the same value again writes no history row; a change appends one and never rewrites earlier ones
    client.put("/api/sel2/source-config/S1/F1", json={"forecast_source": "AVG_DEMAND", "confirm": True})
    assert _history() == before
    client.put("/api/sel2/source-config/S1/F1", json={"forecast_source": "LIGHTGBM", "confirm": True})
    after = _history()
    assert after[:2] == before and len(after) == 3 and after[2]["old_source"] == "AVG_DEMAND"
    # the configuration row of S1 is never deleted by setting AVG_DEMAND: it becomes an explicit row
    assert _config()[("S1", "F1")]["forecast_source"] == "LIGHTGBM"
    hist = client.get("/api/sel2/source-config/history", params={"sku_code": "S1", "limit": 1}).json()
    assert hist["total"] == 3 and hist["items"][0]["id"] == after[2]["id"]


# ------------------------------------------------------------------ download -> upload round trip
def test_round_trip_with_both_sources_vietnamese_notes_and_leading_zero_keys(previews):
    sc.set_one("00123", "F1", "LIGHTGBM", ghi_chu="Thuốc cảm – ưu tiên", confirm=True)
    sc.set_one("S2", "FC Hà Nội", "LIGHTGBM", confirm=True)
    sc.set_one("S2", "FC Hà Nội", "AVG_DEMAND", ghi_chu="quay về TB", confirm=True)
    sc.set_one("S3", "F1", "LIGHTGBM", ghi_chu='<a & "b">', confirm=True)
    data = sc.download_xlsx()
    p = sc.preview_upload(io.BytesIO(data))
    assert p["counts"] == {"rows": 3, "changed": 0, "unchanged": 3, "errors": 0} and p["has_ghi_chu"] is True
    # edit one cell of the downloaded file and drop one row: one change; the dropped row is NOT reset to the default
    wb = load_workbook(io.BytesIO(data))
    ws = wb.worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    i = next(n for n, r in enumerate(rows) if r[0] == "00123")
    ws.cell(row=i + 1, column=3, value="avg_demand")
    j = next(n for n, r in enumerate(rows) if r[0] == "S3")
    ws.delete_rows(j + 1)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    p = sc.preview_upload(buf)
    assert p["counts"] == {"rows": 2, "changed": 1, "unchanged": 1, "errors": 0}
    assert (p["changes"][0]["sku_code"], p["changes"][0]["new_source"], p["changes"][0]["ghi_chu"]) == \
        ("00123", "AVG_DEMAND", "Thuốc cảm – ưu tiên")
    sc.apply_upload(p["preview_id"], confirm=True)
    assert _config()[("S3", "F1")]["forecast_source"] == "LIGHTGBM"


def test_round_trip_of_a_note_that_looks_like_a_formula(previews):
    """A note starting with '=' must come back as the same text (no formula in the downloaded file)."""
    sc.set_one("S1", "F1", "LIGHTGBM", ghi_chu="=1+1", confirm=True)
    sc.set_one("S2", "F1", "LIGHTGBM", ghi_chu='=HYPERLINK("http://example.invalid","x")', confirm=True)
    data = sc.download_xlsx()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        sheet = z.read("xl/worksheets/sheet1.xml").decode()
    assert "<f>" not in sheet
    p = sc.preview_upload(io.BytesIO(data))
    assert p["counts"] == {"rows": 2, "changed": 0, "unchanged": 2, "errors": 0}


# ------------------------------------------------------------------ AVG_DEMAND read precedence
def _avg_rows(day: str, table: str, rows, read_kind: str | None, completed="2026-11-02T03:20:00+00:00"):
    """rows [(sku, fc, seller, value)]; read_kind None = rows stored without a completed read."""
    with db.tx() as c:
        c.executemany("INSERT INTO avg_demand_daily(business_date, sku_code, fc_code, seller_code, avg_demand, "
                      "product_name, source_table, source_modified, loaded_at) VALUES (?,?,?,?,?,NULL,?,NULL,?)",
                      [(day, s, f, sel, v, table, completed) for s, f, sel, v in rows])
        if read_kind:
            c.execute("INSERT INTO avg_demand_reads(id, source_table, business_date, kind, n_rows, source_modified, "
                      "completed_at) VALUES (?,?,?,?,?,NULL,?)",
                      (db.new_id("ADR"), table, day, read_kind, len(rows), completed))


def test_unrecorded_current_rows_are_ignored_and_the_historical_read_is_used(sel2_on):
    cfg = ss.get("sel2_pipeline")
    _avg_rows("2026-11-02", cfg.avg_demand_table, [("S1", "F1", "M", 9.0)], None)          # no completed read
    _avg_rows("2026-11-02", cfg.avg_demand_hist_table, [("S1", "F1", "M", 4.0)], "HISTORICAL")
    res = avg_demand.avg_value("2026-11-02", rule="SUM")
    assert res["source_kind"] == "HISTORICAL" and res["values"][("S1", "F1")]["value"] == 4.0
    # a CURRENT read of ANOTHER day does not count for D
    _avg_rows("2026-11-01", cfg.avg_demand_table, [("S1", "F1", "M", 8.0)], "CURRENT")
    assert avg_demand.avg_value("2026-11-02", rule="SUM")["source_kind"] == "HISTORICAL"
    # a read recorded with the wrong kind for its table is not used either (CURRENT must come from the current table)
    _avg_rows("2026-11-03", cfg.avg_demand_hist_table, [("S1", "F1", "M", 3.0)], "CURRENT")
    assert avg_demand.avg_value("2026-11-03", rule="SUM")["source_kind"] is None
    # once the current read of D is recorded it wins over the historical one
    with db.tx() as c:
        c.execute("INSERT INTO avg_demand_reads(id, source_table, business_date, kind, n_rows, source_modified, "
                  "completed_at) VALUES (?,?,?,?,1,NULL,?)",
                  (db.new_id("ADR"), cfg.avg_demand_table, "2026-11-02", "CURRENT", "2026-11-01T00:00:00+00:00"))
    res = avg_demand.avg_value("2026-11-02", rule="SUM")
    assert res["source_kind"] == "CURRENT" and res["values"][("S1", "F1")]["value"] == 9.0


def test_current_read_of_an_old_table_is_ignored_after_a_settings_change(sel2_on):
    cfg = ss.get("sel2_pipeline")
    old = cfg.avg_demand_table
    _avg_rows("2026-11-02", old, [("S1", "F1", "M", 9.0)], "CURRENT")
    _avg_rows("2026-11-02", cfg.avg_demand_hist_table, [("S1", "F1", "M", 4.0)], "HISTORICAL")
    other = cfg.model_copy(update={"avg_demand_table": old + "_v2"})
    res = avg_demand.avg_value("2026-11-02", rule="SUM", cfg=other)
    assert res["source_kind"] == "HISTORICAL" and res["values"][("S1", "F1")]["value"] == 4.0


def test_latest_read_tie_on_completed_at_uses_the_last_inserted(sel2_on):
    cfg = ss.get("sel2_pipeline")
    _avg_rows("2026-11-02", cfg.avg_demand_table, [("S1", "F1", "M", 1.0)], "CURRENT")
    with db.tx() as c:
        c.execute("INSERT INTO avg_demand_reads(id, source_table, business_date, kind, n_rows, source_modified, "
                  "completed_at) VALUES ('ADR-ZZ-LAST', ?, '2026-11-02', 'CURRENT', 1, NULL, '2026-11-02T03:20:00+00:00')",
                  (cfg.avg_demand_table,))
    with db.read() as c:
        assert avg_demand.latest_read(c, "2026-11-02")["id"] == "ADR-ZZ-LAST"


def test_avg_value_null_and_zero_are_distinct(sel2_on):
    cfg = ss.get("sel2_pipeline")
    _avg_rows("2026-11-02", cfg.avg_demand_table, [("S0", "F1", "M", 0.0), ("SN", "F1", "M", None),
                                                    ("S2", "F1", "A", 0.0), ("S2", "F1", "B", 0.0)], "CURRENT")
    v = avg_demand.avg_value("2026-11-02", rule="SUM")["values"]
    assert v[("S0", "F1")] == {"value": 0.0, "reason": None, "n_sellers": 1}
    assert v[("SN", "F1")] == {"value": None, "reason": "AVG_DEMAND_NULL", "n_sellers": 1}
    assert v[("S2", "F1")] == {"value": 0.0, "reason": None, "n_sellers": 2}
    # SELLER:<code> only needs that seller's value: a NULL of another seller does not matter
    assert avg_demand.apply_rule([("A", None), ("B", 2.0)], "SELLER:B") == (2.0, None)
    assert avg_demand.apply_rule([("A", None), ("B", 2.0)], "SELLER:A") == (None, "AVG_DEMAND_NULL")
    assert avg_demand.apply_rule([("A", None), ("B", 2.0)], "MAX") == (None, "AVG_DEMAND_NULL")
    with pytest.raises(AppError):
        avg_demand.apply_rule([("A", 1.0), ("B", 2.0)], "MEAN")


# ------------------------------------------------------------------ export
def _run(run_id, fdate: date, series: dict, created: str, config_version="SEL2:abcdef012345", scope=SCOPE):
    """series {(sku, fc): {horizon: qty}}."""
    with db.tx() as c:
        c.execute("INSERT INTO forecast_refresh_runs(id, scope_key, forecast_date, data_as_of, status, trigger, "
                  "model_version, config_version, trial_mode, horizon, n_series, n_lightgbm, n_fallback, created_at, "
                  "detail_json) VALUES (?,?,?,?, 'PUBLISHED', 'test', ?, ?, 1, 7, ?, ?, 0, ?, '{}')",
                  (run_id, scope, fdate.isoformat(), (fdate - timedelta(days=1)).isoformat(), f"MV-{run_id}",
                   config_version, len(series), len(series), created))
        for (sku, fc), hs in series.items():
            for h, qty in hs.items():
                c.execute("INSERT INTO forecast_refresh_values(run_id, horizon, target_date, fc_code, sku_code, lgb_raw, "
                          "final_qty, method, group_code, flags) VALUES (?,?,?,?,?,?,?,'MOC+DOW4','A',NULL)",
                          (run_id, h, (fdate + timedelta(days=h - 1)).isoformat(), fc, sku, float(qty), qty))


def _cfg_rows(rows):
    with db.tx() as c:
        c.executemany("INSERT INTO forecast_source_config(sku_code, fc_code, forecast_source, ghi_chu, updated_by, "
                      "updated_at) VALUES (?,?,?,NULL, 'tester', '2026-11-01T01:00:00+00:00')", rows)


def _main(res) -> list[dict]:
    wb = load_workbook(paths.data_dir() / res["path"], read_only=True)
    rows = list(wb["DU_BAO"].iter_rows(values_only=True))
    out = [dict(zip(rows[0], r)) for r in rows[1:]]
    wb.close()
    return out


def test_lightgbm_key_missing_from_run_and_avg_is_counted_without_rows(sel2_on):
    cfg = ss.get("sel2_pipeline")
    _run("R1", D, {("S1", "F1"): {h: h for h in range(1, 8)}}, "2026-11-01T23:00:00+00:00")
    _avg_rows(D.isoformat(), cfg.avg_demand_table, [("S1", "F1", "M", 1.0)], "CURRENT")
    _cfg_rows([("S1", "F1", "LIGHTGBM"), ("SX", "F1", "LIGHTGBM"), ("SY", "F2", "LIGHTGBM"), ("SZ", "F1", "AVG_DEMAND")])
    res = export.write_daily_export(D, scope_key=SCOPE)
    rows = _main(res)
    assert {r["sku_code"] for r in rows} == {"S1"} and res["n_rows"] == 7
    sku_fc = res["summary"]["sku_fc"]
    assert (sku_fc["total"], sku_fc["configured_lightgbm"], sku_fc["configured_lightgbm_not_in_file"]) == (1, 3, 2)
    wb = load_workbook(paths.data_dir() / res["path"], read_only=True)
    assert [r[:2] for r in list(wb["CONFIG"].iter_rows(values_only=True))[1:]] == [("S1", "F1"), ("SX", "F1"),
                                                                                    ("SY", "F2")]
    wb.close()


def test_two_sel2_runs_of_the_day_latest_created_wins_and_non_sel2_runs_are_ignored(sel2_on):
    _cfg_rows([("S1", "F1", "LIGHTGBM")])
    _run("R-EARLY", D, {("S1", "F1"): {1: 10}}, "2026-11-01T22:00:00+00:00")
    _run("R-LATE", D, {("S1", "F1"): {1: 20}}, "2026-11-01T23:00:00+00:00")
    _run("R-1.3.1", D, {("S1", "F1"): {1: 99}}, "2026-11-02T01:00:00+00:00", config_version="V33:xyz")
    _run("R-NOPREFIX", D, {("S1", "F1"): {1: 98}}, "2026-11-02T02:00:00+00:00", config_version="XSEL2:abc")
    res = export.write_daily_export(D, scope_key=SCOPE)
    assert res["summary"]["refresh_run_id"] == "R-LATE" and res["is_stale"] is False
    assert _main(res)[0]["lightgbm_forecast"] == 20
    # same created_at (one-second resolution): the run inserted last wins (rowid DESC)
    _run("R-TIE", D, {("S1", "F1"): {1: 30}}, "2026-11-01T23:00:00+00:00")
    res = export.write_daily_export(D, scope_key=SCOPE)
    assert res["summary"]["refresh_run_id"] == "R-TIE" and _main(res)[0]["lightgbm_forecast"] == 30


def test_stale_uses_the_latest_earlier_day_and_recomputes_the_horizon(sel2_on):
    _cfg_rows([("S1", "F1", "LIGHTGBM")])
    _run("R-D3", D - timedelta(days=3), {("S1", "F1"): {h: 300 + h for h in range(1, 8)}}, "2026-11-01T23:59:00+00:00")
    _run("R-D1", D - timedelta(days=1), {("S1", "F1"): {h: 100 + h for h in range(1, 8)}}, "2026-10-31T23:00:00+00:00")
    _run("R-NEXT", D + timedelta(days=1), {("S1", "F1"): {h: 900 + h for h in range(1, 8)}}, "2026-11-02T23:00:00+00:00")
    res = export.write_daily_export(D, scope_key=SCOPE)
    s = res["summary"]
    assert res["is_stale"] is True and s["refresh_run_id"] == "R-D1" and s["stale_reason"] == "NO_RUN_FOR_DAY"
    by = {r["horizon"]: r for r in _main(res)}
    # target D is horizon 2 of the run of D-1 -> horizon 1 of the file; D+5 = run horizon 7; D+6 not covered
    assert [(h, by[h]["lightgbm_forecast"], by[h]["fallback_reason"]) for h in range(1, 8)] == [
        (1, 102, None), (2, 103, None), (3, 104, None), (4, 105, None), (5, 106, None), (6, 107, None),
        (7, None, "STALE")]
    assert by[1]["target_date"].date() == D and by[7]["target_date"].date() == D + timedelta(days=6)
    # only a run of a LATER day exists in another scope: not used (no SEL2 run for D or before; runs are immutable)
    _run("R-LATER", D + timedelta(days=1), {("S1", "F1"): {1: 5}}, "2026-11-02T23:00:00+00:00", scope="SC-LATER")
    res = export.write_daily_export(D, scope_key="SC-LATER")
    assert res["summary"]["refresh_run_id"] is None and res["summary"]["stale_reason"] == "NO_SEL2_RUN"
    assert res["n_rows"] == 0 and res["version"] == 2


def test_export_with_nothing_at_all_writes_an_empty_valid_file(sel2_on):
    res = export.write_daily_export(D, scope_key=SCOPE)
    assert res["n_rows"] == 0 and res["is_stale"] is True
    wb = load_workbook(paths.data_dir() / res["path"])
    assert [list(r) for r in wb["DU_BAO"].iter_rows(values_only=True)][1:] == []
    assert wb["DU_BAO"].auto_filter.ref == "A1:R1"


# ------------------------------------------------------------------ API export download
@pytest.fixture
def two_versions(sel2_on, client, monkeypatch):
    monkeypatch.setattr(export, "_scope_key", lambda conn: (SCOPE, None))
    _avg_rows(D.isoformat(), ss.get("sel2_pipeline").avg_demand_table, [("S1", "F1", "M", 1.0)], "CURRENT")
    def post():     # 1.4.0 S5: a FORECAST_EXPORT job; the client fixture runs it before the response returns
        return json.loads(client.post("/api/sel2/export", json={"date": D.isoformat(), "confirm": True})
                          .json()["result_json"])["result"]
    r1 = post()
    _cfg_rows([("S1", "F1", "LIGHTGBM")])
    r2 = post()
    return r1, r2


def test_download_headers_give_the_latest_version_and_its_sha(two_versions, client):
    r1, r2 = two_versions
    assert (r1["version"], r2["version"]) == (1, 2) and r1["sha256"] != r2["sha256"]
    r = client.get("/api/sel2/export/2026-11-02")
    assert r.status_code == 200 and r.headers["content-type"] == XLSX
    assert r.headers["x-df-export-version"] == "2" and r.headers["x-df-export-sha256"] == r2["sha256"]
    assert hashlib.sha256(r.content).hexdigest() == r2["sha256"]
    assert 'filename="du_bao_20261102.xlsx"' in r.headers["content-disposition"]
    # basic ISO date (accepted by date.fromisoformat) gives the same file
    assert client.get("/api/sel2/export/20261102").headers["x-df-export-version"] == "2"
    # the latest version file is gone -> 404 (an older version is not served instead)
    (paths.data_dir() / r2["path"]).unlink()
    r = client.get("/api/sel2/export/2026-11-02")
    assert r.status_code == 404 and r.json()["code"] == "SEL2_EXPORT_NOT_FOUND"


@pytest.mark.parametrize("day", ["..%2Fx", "..%2F..%2Fdb%2Fapp.db", "..%5Cx", "..", "%2E%2E", "2026-11-02%00",
                                 "2026-11-02%2F..%2F..%2Fdb", "x", "2026-11-02..", "C:%5Cx"])
def test_export_day_parameter_traversal_is_refused(two_versions, client, day):
    for url in (f"/api/sel2/export/{day}", f"/api/sel2/export/{day}/runs"):
        r = client.get(url)
        assert r.status_code in (404, 405, 422), (url, r.status_code)
        assert r.headers.get("x-df-export-sha256") is None and not r.content.startswith(b"PK")


def test_export_post_rejects_traversal_in_the_body(two_versions, client):
    r = client.post("/api/sel2/export", json={"date": "../../x", "confirm": True})
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM export_runs").fetchone()[0] == 2


# ------------------------------------------------------------------ xlsx_stream
def test_vietnamese_and_quoted_sheet_names(tmp_path):
    p = tmp_path / "vn.xlsx"
    write_xlsx(p, [Sheet("DỰ_BÁO", ("mã", "số lượng"), [["Thuốc A", 1]], 1, freeze_header=True, autofilter=True),
                   Sheet("Tóm tắt 'x'", ("mục", "giá trị"), [["a", 2]], autofilter=True)])
    wb = load_workbook(p)
    assert wb.sheetnames == ["DỰ_BÁO", "Tóm tắt 'x'"]
    assert [list(r) for r in wb["DỰ_BÁO"].iter_rows(values_only=True)] == [["mã", "số lượng"], ["Thuốc A", 1]]
    with zipfile.ZipFile(p) as z:
        wbx = z.read("xl/workbook.xml").decode("utf-8")
    assert "'Tóm tắt ''x'''!$A$1:$B$2" in wbx


@pytest.mark.parametrize("v, expected", [(-0.0, 0.0), (1e21, 1e21), (-1e-300, -1e-300), (2 ** 63, 2 ** 63),
                                         (10 ** 21, 10 ** 21), (0.1 + 0.2, 0.30000000000000004)])
def test_number_edge_values(tmp_path, v, expected):
    p = tmp_path / "n.xlsx"
    write_xlsx(p, [Sheet("S", ("v",), [[v]], 1)])
    with zipfile.ZipFile(p) as z:
        xml = z.read("xl/worksheets/sheet1.xml").decode()
    assert f"<v>{v!r}</v>" in xml and "t=\"inlineStr\"" not in xml.split("<sheetData>")[1].split("</row>", 1)[1]
    got = list(load_workbook(p, read_only=True)["S"].iter_rows(values_only=True))[1][0]
    assert got == expected and isinstance(got, (int, float))


def test_numpy_numbers_are_written_as_plain_numbers(tmp_path):
    np = pytest.importorskip("numpy")
    p = tmp_path / "np.xlsx"
    write_xlsx(p, [Sheet("S", ("a", "b", "c"), [[np.float64(1.5), np.int64(7), np.float64("nan")]], 1)])
    with zipfile.ZipFile(p) as z:
        xml = z.read("xl/worksheets/sheet1.xml").decode()
    assert "<v>1.5</v>" in xml and "<v>7</v>" in xml and "np." not in xml and 'r="C2"' not in xml


def test_excel_row_limit_is_guarded(tmp_path):
    """Excel holds 1,048,576 rows (header + 1,048,575 data rows). A sheet announced one row over the limit is refused
    with ValueError before any row is written (the daily export stays far below: about 420k rows)."""
    n = 1_048_576                                              # data rows: header + n = one row over Excel's limit
    p = tmp_path / "big.xlsx"
    with pytest.raises(ValueError, match="1048575"):
        write_xlsx(p, [Sheet("S", ("v",), itertools.repeat((None,), n), n)], compresslevel=1)
