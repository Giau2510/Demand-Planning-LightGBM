"""1.4.0 T5/T6 fix 2: export versions reserved across processes + unique temporary files, latest copy locked (file open
in Excel) keeps the version, AVG_NO_READ file flag, upload guard of the Excel import (zip bomb, macro, .xlsm), staleness
of every key of an upload preview, read_current only for today. Integration with fakes (isolated temporary database)."""
import io
import json
import struct
from datetime import date

import pytest
from openpyxl import Workbook, load_workbook

from app import cli, db, paths
from app.messages import AppError
from app.ml.sel2 import avg_demand, export
from app.ml.sel2 import source_config as sc

D = "2026-11-02"


def _export_rows():
    with db.read() as c:
        return db.rows(c, "SELECT version, flags, path FROM export_runs WHERE forecast_date=? ORDER BY version", (D,))


def _folder():
    return export.export_root() / "20261102"


# ------------------------------------------------------------------ export
def test_avg_no_read_is_a_file_flag(sel2_on):
    res = export.write_daily_export(D)
    assert "AVG_NO_READ" in res["flags"] and res["summary"]["file_flags"][-1] == "AVG_NO_READ"
    assert "AVG_NO_READ" in _export_rows()[0]["flags"].split(",")
    wb = load_workbook(paths.data_dir() / res["path"], read_only=True)
    summary = {r[0]: r[1] for r in wb["TOM_TAT"].iter_rows(values_only=True)}
    wb.close()
    assert "AVG_NO_READ" in summary["file_flags"].split(",")


def test_latest_copy_locked_keeps_the_version_and_flags_it(sel2_on):
    r1 = export.write_daily_export(D)
    latest = paths.data_dir() / r1["latest_path"]
    with open(latest, "rb"):                                  # held open like Excel: the replace is refused
        r2 = export.write_daily_export(D)
    assert r2["version"] == 2 and "LATEST_COPY_LOCKED" in r2["flags"]
    rows = _export_rows()
    assert [r["version"] for r in rows] == [1, 2]
    assert "LATEST_COPY_LOCKED" in rows[1]["flags"].split(",") and "LATEST_COPY_LOCKED" not in (rows[0]["flags"] or "")
    assert (paths.data_dir() / r2["path"]).is_file()
    assert export._sha256(latest) == r1["sha256"]             # the latest copy is still version 1
    r3 = export.write_daily_export(D)
    assert "LATEST_COPY_LOCKED" not in r3["flags"] and export._sha256(latest) == r3["sha256"]
    assert not list(_folder().glob(".*.tmp")) and not list(_folder().glob(".*.reserved"))


def test_a_version_reserved_by_another_process_is_skipped(sel2_on):
    _folder().mkdir(parents=True, exist_ok=True)
    other = _folder() / ".du_bao_20261102_v1.reserved"       # another process is writing version 1
    other.write_bytes(b"")
    res = export.write_daily_export(D)
    assert res["version"] == 2 and other.exists()
    assert not (_folder() / ".du_bao_20261102_v2.reserved").exists()
    assert [r["version"] for r in _export_rows()] == [2]


def test_temporary_names_are_unique_per_call():
    a, b = export._tmp_name(paths.data_dir(), "x"), export._tmp_name(paths.data_dir(), "x")
    assert a != b and a.name.startswith(".x.") and a.suffix == ".tmp"


def test_a_write_failure_is_an_app_error_and_leaves_nothing(sel2_on, monkeypatch):
    def boom(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(export, "_write_book", boom)
    with pytest.raises(AppError) as e:
        export.write_daily_export(D)
    assert e.value.code == "SEL2_EXPORT_WRITE_FAILED" and e.value.status == 500
    assert _export_rows() == [] and list(_folder().iterdir()) == []


# ------------------------------------------------------------------ upload guard (excel_io.check_xlsx)
def _xlsx_bytes(rows=(("S1", "F1", "LIGHTGBM"),)) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["sku_code", "fc_code", "forecast_source"])
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _declare_size(data: bytes, member: str, size: int) -> bytes:
    """Central directory entry of `member` declaring `size` uncompressed bytes (a zip bomb as seen before reading)."""
    b = bytearray(data)
    i = b.find(b"PK\x01\x02")
    while i >= 0:
        n, m, k = struct.unpack("<HHH", b[i + 28:i + 34])
        if bytes(b[i + 46:i + 46 + n]).decode() == member:
            b[i + 24:i + 28] = struct.pack("<I", size)
            return bytes(b)
        i = b.find(b"PK\x01\x02", i + 46 + n + m + k)
    raise AssertionError(member)


def test_upload_declaring_a_huge_uncompressed_size_is_refused_before_reading(sel2_on, monkeypatch):
    def never(*a, **k):
        raise AssertionError("openpyxl must not read it")
    monkeypatch.setattr(sc, "load_workbook", never)
    data = _declare_size(_xlsx_bytes(), "xl/styles.xml", 0x7FFFFFFF)
    with pytest.raises(AppError) as e:
        sc.preview_upload(io.BytesIO(data), "bomb.xlsx")
    assert e.value.code == "SOURCE_CONFIG_FILE_TOO_LARGE" and e.value.status == 413


def test_upload_with_a_macro_part_or_xlsm_name_is_refused(sel2_on):
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(_xlsx_bytes())) as src, zipfile.ZipFile(buf, "w") as dst:
        for it in src.infolist():
            dst.writestr(it, src.read(it.filename))
        dst.writestr("xl/vbaProject.bin", b"\x00" * 16)
    with pytest.raises(AppError) as e:
        sc.preview_upload(io.BytesIO(buf.getvalue()), "x.xlsx")
    assert e.value.code == "MACRO_NOT_ALLOWED"
    with pytest.raises(AppError) as e:
        sc.preview_upload(io.BytesIO(_xlsx_bytes()), "x.xlsm")
    assert e.value.code == "NOT_XLSX"
    assert sc.preview_upload(io.BytesIO(_xlsx_bytes()), "x.xlsx")["counts"]["changed"] == 1


def test_apply_checks_the_unchanged_rows_of_the_preview_too(sel2_on):
    sc.set_one("S1", "F1", "LIGHTGBM", confirm=True)
    p = sc.preview_upload(io.BytesIO(_xlsx_bytes((("S1", "F1", "LIGHTGBM"), ("S2", "F1", "LIGHTGBM")))), "x.xlsx")
    assert p["counts"]["unchanged"] == 1 and p["counts"]["changed"] == 1
    sc.set_one("S1", "F1", "AVG_DEMAND", confirm=True)          # the unchanged row changed meanwhile
    with pytest.raises(AppError) as e:
        sc.apply_upload(p["preview_id"], confirm=True)
    assert e.value.code == "SOURCE_CONFIG_PREVIEW_STALE" and "S1" in str(e.value.detail)
    with db.read() as c:
        assert sc.get_effective(c, "S2", "F1")["configured"] is False


# ------------------------------------------------------------------ read_current: today only
def test_read_current_refuses_another_day_before_any_query(sel2_on, monkeypatch, capsys):
    monkeypatch.setattr(avg_demand, "today_vn", lambda: date(2026, 11, 2))
    monkeypatch.setattr(avg_demand, "_ctx", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no client")))
    with pytest.raises(AppError) as e:
        avg_demand.read_current("2026-11-01")
    assert e.value.code == "AVG_CURRENT_ONLY_TODAY" and "--hist-from" in e.value.detail
    assert cli.main(["sel2-avg-read", "--date", "2026-11-01", "--yes"]) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["code"] == "AVG_CURRENT_ONLY_TODAY" and "--hist-from" in out["refused"]
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM avg_demand_reads").fetchone()[0] == 0
