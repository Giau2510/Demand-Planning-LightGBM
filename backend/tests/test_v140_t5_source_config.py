"""1.4.0 T5: forecast source per SKU x FC (forecast_source_config + append-only history): single change with
confirmation, .xlsx upload preview / apply (one batch, atomic, stale refused), download round-trip and the
/api/sel2/source-config routes. Integration with fakes (isolated temporary database, TestClient)."""
import io
import sqlite3

import pytest
from openpyxl import Workbook, load_workbook

from app import db
from app.messages import AppError
from app.ml.sel2 import source_config as sc


def _xlsx(rows, header=("sku_code", "fc_code", "forecast_source"), note=None) -> io.BytesIO:
    wb = Workbook()
    ws = wb.active
    if note:
        ws.append([note])
    if header:
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


def test_set_one_requires_confirm_validates_and_keeps_history(sel2_on):
    with pytest.raises(AppError) as e:
        sc.set_one("S1", "F1", "LIGHTGBM")
    assert e.value.code == "SOURCE_CONFIG_CONFIRM_REQUIRED" and _config() == {} and _history() == []
    with pytest.raises(AppError) as e:
        sc.set_one("S1", "F1", "PROPHET", confirm=True)
    assert e.value.code == "SOURCE_CONFIG_INVALID_SOURCE"
    with pytest.raises(AppError) as e:
        sc.set_one(" ", "F1", "LIGHTGBM", confirm=True)
    assert e.value.code == "SOURCE_CONFIG_INVALID_KEY"
    out = sc.set_one(" S1 ", "F1", " lightgbm ", ghi_chu="test", confirm=True, changed_by="tester")
    assert out["changed"] and out["before"]["forecast_source"] == "AVG_DEMAND" and not out["before"]["configured"]
    assert _config()[("S1", "F1")]["forecast_source"] == "LIGHTGBM"
    assert sc.set_one("S1", "F1", "LIGHTGBM", ghi_chu="test", confirm=True)["changed"] is False
    sc.set_one("S1", "F1", "AVG_DEMAND", confirm=True, changed_by="tester")
    h = _history()
    assert [(r["old_source"], r["new_source"], r["channel"], r["batch_id"]) for r in h] == [
        (None, "LIGHTGBM", "UI", None), ("LIGHTGBM", "AVG_DEMAND", "UI", None)]
    assert h[0]["changed_by"] == "tester" and h[0]["ghi_chu"] == "test" and h[0]["changed_at"].startswith("20")
    with db.read() as c:
        eff = sc.get_effective(c, "S9", "F9")
    assert eff["forecast_source"] == "AVG_DEMAND" and eff["configured"] is False


def test_history_is_append_only(sel2_on):
    sc.set_one("S1", "F1", "LIGHTGBM", confirm=True)
    for sql in ("UPDATE forecast_source_config_history SET new_source='AVG_DEMAND'",
                "DELETE FROM forecast_source_config_history"):
        with pytest.raises(sqlite3.DatabaseError):
            with db.tx() as c:
                c.execute(sql)
    assert len(_history()) == 1


def test_writes_refused_while_the_pipeline_is_off(sel2_off):
    with pytest.raises(AppError) as e:
        sc.set_one("S1", "F1", "LIGHTGBM", confirm=True)
    assert e.value.code == "SEL2_PIPELINE_DISABLED" and _config() == {}


def test_list_search_filter_paging(sel2_on):
    for i in range(5):
        sc.set_one(f"SKU{i}", "FC-A" if i % 2 else "FC-B", "LIGHTGBM", confirm=True)
    # AVG_DEMAND on a key without a row is no change (missing = AVG_DEMAND): nothing stored
    assert sc.set_one("SKU9", "FC-A", "AVG_DEMAND", confirm=True)["changed"] is False
    for i in (3, 4):
        sc.set_one(f"SKU{i}", "FC-A" if i % 2 else "FC-B", "AVG_DEMAND", confirm=True)
    with db.read() as c:
        assert sc.list_config(c)["total"] == 5
        assert sc.list_config(c, fc_code="fc-a")["total"] == 2
        assert sc.list_config(c, source="lightgbm")["total"] == 3
        page = sc.list_config(c, sku_code="sku", limit=2, offset=2)
        assert page["total"] == 5 and len(page["items"]) == 2
        assert sc.list_config(c)["configured_by_source"] == {"AVG_DEMAND": 2, "LIGHTGBM": 3}
        with pytest.raises(AppError):
            sc.list_config(c, source="X")


def test_upload_preview_counts_errors_duplicates_and_writes_nothing(sel2_on):
    sc.set_one("S1", "F1", "LIGHTGBM", confirm=True)
    f = _xlsx([("S1", "F1", "lightgbm"),          # unchanged (case-insensitive)
               ("S2", "F1", "AVG_DEMAND"),        # unchanged: missing row = AVG_DEMAND
               (" S3 ", " F1 ", "LightGBM"),      # changed (trimmed)
               ("S1", "F2", "AVG_DEMAND "),       # unchanged
               ("", "F1", "LIGHTGBM"),            # error: missing sku
               ("S4", None, "LIGHTGBM"),          # error: missing fc
               ("S5", "F1", None),                # error: missing source
               ("S6", "F1", "PROPHET"),           # error: unknown source
               ("S7", "F1", "LIGHTGBM"), ("S7", "F1", "AVG_DEMAND"),   # duplicates: both errors
               (None, None, None)])               # empty row ignored
    before = (_config(), _history())
    p = sc.preview_upload(f, "x.xlsx")
    assert p["counts"] == {"rows": 10, "changed": 1, "unchanged": 3, "errors": 6}
    assert p["changes"] == [{"row": 4, "sku_code": "S3", "fc_code": "F1", "old_source": None,
                             "effective_old_source": "AVG_DEMAND", "new_source": "LIGHTGBM", "old_ghi_chu": None,
                             "ghi_chu": None}]
    assert sorted(e["reason"] for e in p["errors"]) == ["DUPLICATE_IN_FILE", "DUPLICATE_IN_FILE", "MISSING_FC_CODE",
                                                         "MISSING_SKU_CODE", "MISSING_SOURCE", "UNKNOWN_SOURCE"]
    assert p["can_apply"] is False and (_config(), _history()) == before
    with pytest.raises(AppError) as e:
        sc.apply_upload(p["preview_id"], confirm=True)
    assert e.value.code == "SOURCE_CONFIG_UPLOAD_HAS_ERRORS" and (_config(), _history()) == before


def test_upload_bad_header_and_not_xlsx(sel2_on):
    with pytest.raises(AppError) as e:
        sc.preview_upload(_xlsx([("S1", "F1", "LIGHTGBM")], header=("sku", "fc_code", "forecast_source")))
    assert e.value.code == "SOURCE_CONFIG_BAD_HEADER"
    with pytest.raises(AppError) as e:
        sc.preview_upload(io.BytesIO(b"sku_code,fc_code,forecast_source\nS1,F1,LIGHTGBM\n"))
    assert e.value.code == "SOURCE_CONFIG_FILE_INVALID"


def test_apply_one_batch_confirm_and_single_use(sel2_on):
    p = sc.preview_upload(_xlsx([("S1", "F1", "LIGHTGBM", "a"), ("S2", "F1", "LIGHTGBM", None)],
                                header=("sku_code", "fc_code", "forecast_source", "ghi_chu")))
    with pytest.raises(AppError) as e:
        sc.apply_upload(p["preview_id"])
    assert e.value.code == "SOURCE_CONFIG_CONFIRM_REQUIRED" and _config() == {}
    out = sc.apply_upload(p["preview_id"], confirm=True, changed_by="tester")
    assert out["applied"] == 2 and out["batch_id"]
    h = _history()
    assert {r["batch_id"] for r in h} == {out["batch_id"]} and {r["channel"] for r in h} == {"UPLOAD"}
    assert _config()[("S1", "F1")]["ghi_chu"] == "a"
    with pytest.raises(AppError) as e:
        sc.apply_upload(p["preview_id"], confirm=True)
    assert e.value.code == "SOURCE_CONFIG_PREVIEW_NOT_FOUND"


def test_apply_is_atomic_and_refuses_a_stale_preview(sel2_on, monkeypatch):
    p = sc.preview_upload(_xlsx([("S1", "F1", "LIGHTGBM"), ("S2", "F1", "LIGHTGBM")]))
    sc.set_one("S2", "F1", "LIGHTGBM", confirm=True)          # changed after the preview
    with pytest.raises(AppError) as e:
        sc.apply_upload(p["preview_id"], confirm=True)
    assert e.value.code == "SOURCE_CONFIG_PREVIEW_STALE"
    assert set(_config()) == {("S2", "F1")} and len(_history()) == 1        # S1 not written either

    p = sc.preview_upload(_xlsx([("S3", "F1", "LIGHTGBM"), ("S4", "F1", "LIGHTGBM")]))
    real, calls = sc._write, []

    def fail_second(*a, **k):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("crash mid-apply")
        return real(*a, **k)
    monkeypatch.setattr(sc, "_write", fail_second)
    with pytest.raises(RuntimeError):
        sc.apply_upload(p["preview_id"], confirm=True)
    assert set(_config()) == {("S2", "F1")} and len(_history()) == 1


def test_download_round_trip_has_no_change(sel2_on):
    sc.set_one("S1", "F1", "LIGHTGBM", ghi_chu="note", confirm=True)
    sc.set_one("S2", "F2", "LIGHTGBM", confirm=True)
    sc.set_one("S2", "F2", "AVG_DEMAND", confirm=True)              # an explicit AVG_DEMAND row
    data = sc.download_xlsx()
    ws = load_workbook(io.BytesIO(data)).worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    assert "AVG_DEMAND" in rows[0][0] and rows[1][:4] == ("sku_code", "fc_code", "forecast_source", "ghi_chu")
    assert len(rows) == 4
    p = sc.preview_upload(io.BytesIO(data))
    assert p["counts"] == {"rows": 2, "changed": 0, "unchanged": 2, "errors": 0}


def test_api_routes(sel2_on, client):
    assert client.get("/api/sel2/source-config/S1/F1").json()["forecast_source"] == "AVG_DEMAND"
    r = client.put("/api/sel2/source-config/S1/F1", json={"forecast_source": "LIGHTGBM"})
    assert r.status_code == 409 and r.json()["code"] == "SOURCE_CONFIG_CONFIRM_REQUIRED"
    r = client.put("/api/sel2/source-config/S1/F1", json={"forecast_source": "X", "confirm": True})
    assert r.status_code == 422
    r = client.put("/api/sel2/source-config/S1/F1", json={"forecast_source": "LIGHTGBM", "confirm": True})
    assert r.status_code == 200 and r.json()["after"]["forecast_source"] == "LIGHTGBM"
    r = client.put("/api/sel2/source-config/S2/F1", json={"forecast_source": "LIGHTGBM", "confirm": True},
                   headers={"X-DF-Client": ""})
    assert r.status_code == 403
    lst = client.get("/api/sel2/source-config", params={"source": "LIGHTGBM"}).json()
    assert lst["total"] == 1 and lst["items"][0]["sku_code"] == "S1"

    up = client.post("/api/sel2/source-config/upload",
                     files={"file": ("cfg.xlsx", _xlsx([("S2", "F1", "LIGHTGBM")]).getvalue(), sc_xlsx())})
    assert up.status_code == 200 and up.json()["counts"]["changed"] == 1
    pid = up.json()["preview_id"]
    assert client.post("/api/sel2/source-config/apply", json={"preview_id": pid}).status_code == 409
    ap = client.post("/api/sel2/source-config/apply", json={"preview_id": pid, "confirm": True})
    assert ap.status_code == 200 and ap.json()["applied"] == 1
    assert client.post("/api/sel2/source-config/apply", json={"preview_id": pid, "confirm": True}).status_code == 404

    hist = client.get("/api/sel2/source-config/history").json()
    assert hist["total"] == 2 and hist["items"][0]["channel"] == "UPLOAD"          # newest first
    hx = client.get("/api/sel2/source-config/history", params={"format": "xlsx"})
    assert hx.status_code == 200 and hx.headers["content-type"] == sc_xlsx()
    dl = client.get("/api/sel2/source-config/download")
    assert dl.status_code == 200 and dl.headers["content-type"] == sc_xlsx()
    assert len(list(load_workbook(io.BytesIO(dl.content)).worksheets[0].iter_rows())) == 4
    bad = client.post("/api/sel2/source-config/upload", files={"file": ("x.xlsx", b"not a workbook", sc_xlsx())})
    assert bad.status_code == 422 and bad.json()["code"] == "SOURCE_CONFIG_FILE_INVALID"


def sc_xlsx() -> str:
    return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
