"""1.4.0 T6b: streaming XLSX writer of the daily export (ml/sel2/xlsx_stream.py): valid package (zip test, openpyxl
normal and read-only), escaping, forbidden characters removed, empty cells omitted, exact float round trip, dates,
bold header, frozen header and autofilter. Unit (temporary files only)."""
import re
import zipfile
from datetime import date, datetime

import pytest
from openpyxl import load_workbook

from app.ml.sel2.xlsx_stream import Sheet, column_letter, write_xlsx

HEADER = ("txt", "num", "flt", "day", "empty_mid", "flag", "tail")


def _write(tmp_path, rows, **kw):
    p = tmp_path / "t.xlsx"
    write_xlsx(p, [Sheet("DU_BAO", HEADER, rows, len(rows), freeze_header=True, autofilter=True),
                   Sheet("TOM_TAT", ("muc", "gia_tri"), iter([["a", 1]])), *kw.get("more", [])])
    return p


def _values(p, read_only=False):
    wb = load_workbook(p, read_only=read_only)
    return wb, [list(r) for r in wb["DU_BAO"].iter_rows(values_only=True)]


def test_package_is_valid_and_opens(tmp_path):
    p = _write(tmp_path, [["a", 1, 0.5, date(2026, 11, 2), None, True, "z"]])
    with zipfile.ZipFile(p) as z:
        assert z.testzip() is None
        names = set(z.namelist())
        assert {"[Content_Types].xml", "_rels/.rels", "xl/workbook.xml", "xl/_rels/workbook.xml.rels",
                "xl/styles.xml", "xl/worksheets/sheet1.xml", "xl/worksheets/sheet2.xml"} <= names
        assert all(i.compress_type == zipfile.ZIP_DEFLATED for i in z.infolist())
        wbx = z.read("xl/workbook.xml").decode()
        assert ('<definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">'
                "'DU_BAO'!$A$1:$G$2</definedName>") in wbx
        assert "localSheetId=\"1\"" not in wbx                         # TOM_TAT: no autofilter
    for ro in (False, True):
        wb, rows = _values(p, read_only=ro)
        assert wb.sheetnames == ["DU_BAO", "TOM_TAT"]
        assert rows == [list(HEADER), ["a", 1, 0.5, datetime(2026, 11, 2), None, True, "z"]]
    wb = load_workbook(p)
    ws = wb["DU_BAO"]
    assert ws.freeze_panes == "A2" and ws.auto_filter.ref == "A1:G2"
    assert all(c.font.b for c in ws[1]) and not ws["A2"].font.b
    assert ws["D2"].number_format == "yyyy-mm-dd" and ws["D2"].is_date
    assert wb["TOM_TAT"].freeze_panes is None and wb["TOM_TAT"].auto_filter.ref is None
    assert [list(r) for r in wb["TOM_TAT"].iter_rows(values_only=True)] == [["muc", "gia_tri"], ["a", 1]]


def test_escaping_and_forbidden_characters(tmp_path):
    texts = ['A & B <c> "q" \'s\'', "x\x01y\x1fz\x0b", "  lead and trail  ", "line1\r\nline2\tTab", "Thuốc ống 10ml",
             "</t></is></c><c>", "&amp;"]
    p = _write(tmp_path, [[t, None, None, None, None, None, None] for t in texts])
    for ro in (False, True):
        _, rows = _values(p, read_only=ro)
        assert [r[0] for r in rows[1:]] == ['A & B <c> "q" \'s\'', "xyz", "  lead and trail  ",
                                            "line1\r\nline2\tTab", "Thuốc ống 10ml", "</t></is></c><c>", "&amp;"]
    with zipfile.ZipFile(p) as z:
        xml = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "\x01" not in xml and "&amp;amp;" in xml and '<t xml:space="preserve">  lead' in xml


def test_empty_cells_are_omitted_never_zero(tmp_path):
    rows = [[None, 5, None, None, None, None, "end"], ["s", None, None, None, None, None, None],
            [None] * 7, ["k", None, float("nan"), None, None, None, float("inf")]]
    p = _write(tmp_path, rows)
    with zipfile.ZipFile(p) as z:
        xml = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert '<row r="2"><c r="B2"><v>5</v></c><c r="G2" t="inlineStr"><is><t>end</t></is></c></row>' in xml
    assert '<row r="4"></row>' in xml and "nan" not in xml.lower() and "inf" not in xml.lower()
    for ro in (False, True):
        _, got = _values(p, read_only=ro)
        assert got[1:] == [[None, 5, None, None, None, None, "end"], ["s"] + [None] * 6, [None] * 7, ["k"] + [None] * 6]


def test_numbers_round_trip_exactly(tmp_path):
    floats = [0.1, 1 / 3, 2.6, 1e-300, 123456789.123456789, -0.0001, 1e20]
    p = _write(tmp_path, [[None, 2 ** 40 + 1, f, None, None, False, -7] for f in floats])
    for ro in (False, True):
        _, rows = _values(p, read_only=ro)
        assert [r[2] for r in rows[1:]] == floats                          # exact equality: repr round trip
        assert all(repr(r[2]) == repr(f) for r, f in zip(rows[1:], floats))
        assert all(r[1] == 2 ** 40 + 1 and type(r[1]) is int and r[5] is False and r[6] == -7 for r in rows[1:])


def test_dates_and_datetimes(tmp_path):
    rows = [[None, None, None, date(2026, 1, 1), None, None, datetime(2026, 11, 2, 7, 30, 15)],
            [None, None, None, date(1900, 3, 1), None, None, None]]
    p = _write(tmp_path, rows)
    for ro in (False, True):
        _, got = _values(p, read_only=ro)
        assert got[1][3] == datetime(2026, 1, 1) and got[1][6] == datetime(2026, 11, 2, 7, 30, 15)
        assert got[2][3] == datetime(1900, 3, 1)
    with zipfile.ZipFile(p) as z:
        xml = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert '<c r="D2" s="2"><v>46023</v></c>' in xml                       # Excel serial of 2026-01-01


def test_row_count_must_match_the_announced_count(tmp_path):
    with pytest.raises(ValueError):
        write_xlsx(tmp_path / "x.xlsx", [Sheet("S", ("a",), iter([[1], [2]]), 3, autofilter=True)])


def test_unknown_type_is_refused(tmp_path):
    with pytest.raises(TypeError):
        write_xlsx(tmp_path / "x.xlsx", [Sheet("S", ("a",), [[object()]])])


def test_column_letters_and_streamed_rows(tmp_path):
    assert [column_letter(i) for i in (1, 18, 26, 27, 52, 703)] == ["A", "R", "Z", "AA", "AZ", "AAA"]
    n = 4500                                                               # more than one write chunk
    p = tmp_path / "big.xlsx"
    write_xlsx(p, [Sheet("DU_BAO", ("i", "x"), ((i, f"v{i}") for i in range(n)), n, autofilter=True)])
    wb = load_workbook(p, read_only=True)
    rows = list(wb["DU_BAO"].iter_rows(values_only=True))
    assert len(rows) == n + 1 and rows[-1] == (n - 1, f"v{n - 1}")
    with zipfile.ZipFile(p) as z:
        assert z.testzip() is None
        assert re.search(r'<autoFilter ref="A1:B4501"/>', z.read("xl/worksheets/sheet1.xml").decode())
