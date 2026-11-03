"""1.4.0 T5 fix 1: the forecast source download / history workbooks are written by xlsx_stream (text never becomes a
formula, long notes are not truncated) and the streaming writer refuses more data rows than an Excel sheet holds.
Integration with fakes (isolated temporary database) + unit (temporary files)."""
import io
import itertools
import zipfile

import pytest
from openpyxl import load_workbook

from app import db
from app.ml.sel2 import source_config as sc
from app.ml.sel2 import xlsx_stream
from app.ml.sel2.xlsx_stream import Sheet, write_xlsx


@pytest.fixture
def previews(sel2_on, monkeypatch):
    store: dict = {}
    monkeypatch.setattr(sc, "_previews", store)
    return store


def _sheet_xml(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return z.read("xl/worksheets/sheet1.xml").decode("utf-8")


# ------------------------------------------------------------------ download / history: text stays text
def test_download_keeps_formula_like_and_spaced_notes_as_text(previews):
    notes = {"S1": "=1+1", "S2": "+SUM(A1)", "S3": "-2", "S4": "@x", "S5": "  hai đầu  ", "S6": "a\r\nb"}
    for sku, note in notes.items():
        sc.set_one(sku, "F1", "LIGHTGBM", ghi_chu=note, confirm=True)
    data = sc.download_xlsx()
    xml = _sheet_xml(data)
    assert "<f>" not in xml and "<f " not in xml
    rows = list(load_workbook(io.BytesIO(data)).worksheets[0].iter_rows(values_only=True))
    assert "AVG_DEMAND" in rows[0][0] and all(v is None for v in rows[0][1:])       # one note cell, no "None" text
    assert rows[1] == ("sku_code", "fc_code", "forecast_source", "ghi_chu", "updated_by", "updated_at")
    assert {r[0]: r[3] for r in rows[2:]} == {k: v.strip() for k, v in notes.items()}
    p = sc.preview_upload(io.BytesIO(data))
    assert p["counts"] == {"rows": 6, "changed": 0, "unchanged": 6, "errors": 0}


def test_download_with_no_configured_row_is_note_and_header_only(previews):
    data = sc.download_xlsx()
    rows = list(load_workbook(io.BytesIO(data)).worksheets[0].iter_rows(values_only=True))
    assert len(rows) == 2 and rows[1][0] == "sku_code"
    assert sc.preview_upload(io.BytesIO(data))["counts"] == {"rows": 0, "changed": 0, "unchanged": 0, "errors": 0}


def test_history_xlsx_keeps_formula_like_notes_as_text(previews):
    sc.set_one("S1", "F1", "LIGHTGBM", ghi_chu='=HYPERLINK("http://example.invalid","x")', confirm=True)
    sc.set_one("S1", "F1", "AVG_DEMAND", ghi_chu="=1+1", confirm=True)
    with db.read() as c:
        data = sc.history_xlsx(c, sku_code="S1")
    assert "<f>" not in _sheet_xml(data)
    rows = list(load_workbook(io.BytesIO(data)).worksheets[0].iter_rows(values_only=True))
    cols = [c.strip() for c in sc.HISTORY_COLS.split(",")]
    assert list(rows[0]) == cols and len(rows) == 3
    got = [dict(zip(cols, r)) for r in rows[1:]]
    assert [(g["ghi_chu"], g["new_source"], g["channel"]) for g in got] == [
        ("=1+1", "AVG_DEMAND", "UI"), ('=HYPERLINK("http://example.invalid","x")', "LIGHTGBM", "UI")]
    assert isinstance(got[0]["id"], int)


# ------------------------------------------------------------------ xlsx_stream: Excel row limit
def test_row_limit_constant_matches_excel():
    assert xlsx_stream.MAX_DATA_ROWS == 1_048_576 - 1


def test_announced_rows_at_the_limit_pass_and_one_more_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(xlsx_stream, "MAX_DATA_ROWS", 3)
    p = tmp_path / "ok.xlsx"
    write_xlsx(p, [Sheet("S", ("v",), [[1], [2], [3]], 3)])
    assert len(list(load_workbook(p, read_only=True)["S"].iter_rows(values_only=True))) == 4
    q = tmp_path / "over.xlsx"
    with pytest.raises(ValueError, match="at most 3"):
        write_xlsx(q, [Sheet("S", ("v",), [[1], [2], [3], [4]], 4)])


def test_unannounced_rows_over_the_limit_are_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(xlsx_stream, "MAX_DATA_ROWS", 3)
    with pytest.raises(ValueError, match="at most 3"):
        write_xlsx(tmp_path / "x.xlsx", [Sheet("S", ("v",), [[i] for i in range(4)])])     # counted (n_rows None)


def test_streamed_rows_beyond_the_limit_stop_before_the_extra_row(tmp_path, monkeypatch):
    """An iterator that yields more rows than announced is stopped at the first row past the limit."""
    monkeypatch.setattr(xlsx_stream, "MAX_DATA_ROWS", 3)
    pulled = []

    def rows():
        for i in itertools.count():
            pulled.append(i)
            yield [i]

    with pytest.raises(ValueError, match="more than 3 data rows"):
        write_xlsx(tmp_path / "x.xlsx", [Sheet("S", ("v",), rows(), 3)])
    assert len(pulled) == 4                                     # the 4th row was read, refused, never written


def test_write_to_a_binary_file_object():
    buf = io.BytesIO()
    write_xlsx(buf, [Sheet("S", ("a", None, "c"), [["x", "=1", 2]], 1)])
    rows = list(load_workbook(io.BytesIO(buf.getvalue()))["S"].iter_rows(values_only=True))
    assert rows == [("a", None, "c"), ("x", "=1", 2)]
