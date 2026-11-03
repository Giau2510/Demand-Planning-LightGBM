"""1.4.0 SEL2: small streaming XLSX writer (stdlib zipfile + string building) for the daily export.

openpyxl's XML writer took about 380 s for 420k rows x 18 columns; this writer builds the sheet XML as text and streams
it in chunks into a deflated zip entry (the whole sheet is never held in memory). Output: one workbook with the given
sheets, a bold header row (a None header entry = no cell: the header row can be a single note over a wider table),
optional header freeze (pane at A2) and autofilter on the header (with the hidden _xlnm._FilterDatabase name Excel
expects). A sheet holds at most MAX_DATA_ROWS data rows (Excel: 1,048,576 rows including the header); more is refused
with ValueError before any row beyond the limit is written. Cell types: str -> inline string (XML-escaped, characters XML 1.0 forbids
removed), int / float -> number (float written with repr: exact round trip), bool -> boolean, date -> serial number
with the yyyy-mm-dd style, datetime -> serial number with the yyyy-mm-dd h:mm:ss style, None -> no cell. A float that
is NaN or infinite has no Excel value and is left empty (never 0).
"""
from __future__ import annotations

import math
import numbers
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import IO, Iterable, Sequence

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_PR = "http://schemas.openxmlformats.org/package/2006/relationships"
_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml"
_EPOCH = date(1899, 12, 30).toordinal()     # Excel 1900 date system (serial 61 = 1900-03-01)
_STYLE_HEADER, _STYLE_DATE, _STYLE_DATETIME = 1, 2, 3
_CHUNK_ROWS = 2000
MAX_DATA_ROWS = 1_048_575                   # Excel: 1,048,576 rows per sheet, header row included
# characters that need escaping or removal (XML 1.0 forbids C0 controls except tab / LF / CR, surrogates, FFFE / FFFF)
_SLOW = re.compile('[&<>"\r\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]')
_ILLEGAL = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]')
_ESC = str.maketrans({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "\r": "&#13;"})


@dataclass
class Sheet:
    """One sheet: header (bold), rows (any iterable, consumed once when the sheet is written), n_rows = the number of
    data rows when known in advance (rows is then streamed; otherwise it is materialised to count it)."""
    name: str
    header: Sequence[str]
    rows: Iterable
    n_rows: int | None = None
    freeze_header: bool = False
    autofilter: bool = False


def column_letter(i: int) -> str:
    """1 -> A, 26 -> Z, 27 -> AA."""
    s = ""
    while i > 0:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _text(v: str) -> str:
    """<t> element of a string (escaped, forbidden characters removed, spaces kept)."""
    if _SLOW.search(v):
        v = _ILLEGAL.sub("", v).translate(_ESC)
    if v != v.strip():
        return f'<t xml:space="preserve">{v}</t>'
    return f"<t>{v}</t>"


def _other(ref: str, v) -> str:
    """Cell of the less common types (bool, datetime, numeric types other than int / float)."""
    if isinstance(v, bool):
        return f'<c r="{ref}" t="b"><v>{int(v)}</v></c>'
    if isinstance(v, datetime):
        if v.tzinfo is not None:
            v = v.replace(tzinfo=None)
        serial = (v.toordinal() - _EPOCH) + (v.hour * 3600 + v.minute * 60 + v.second + v.microsecond / 1e6) / 86400
        return f'<c r="{ref}" s="{_STYLE_DATETIME}"><v>{serial!r}</v></c>'
    if isinstance(v, date):
        return f'<c r="{ref}" s="{_STYLE_DATE}"><v>{v.toordinal() - _EPOCH}</v></c>'
    if isinstance(v, str):
        return f'<c r="{ref}" t="inlineStr"><is>{_text(str(v))}</is></c>'
    if isinstance(v, numbers.Integral):
        return f'<c r="{ref}"><v>{int(v)}</v></c>'
    if isinstance(v, numbers.Real):
        f = float(v)
        return f'<c r="{ref}"><v>{f!r}</v></c>' if math.isfinite(f) else ""
    raise TypeError(f"cannot write {type(v).__name__} to an Excel cell ({ref})")


def _row(r: int, values, letters) -> str:
    rs = str(r)
    out = [f'<row r="{rs}">']
    for col, v in zip(letters, values):
        if v is None:
            continue
        t = type(v)
        if t is str:
            out.append(f'<c r="{col}{rs}" t="inlineStr"><is>{_text(v)}</is></c>')
        elif t is int:
            out.append(f'<c r="{col}{rs}"><v>{v}</v></c>')
        elif t is float:
            if math.isfinite(v):
                out.append(f'<c r="{col}{rs}"><v>{v!r}</v></c>')
        elif t is date:
            out.append(f'<c r="{col}{rs}" s="{_STYLE_DATE}"><v>{v.toordinal() - _EPOCH}</v></c>')
        else:
            out.append(_other(col + rs, v))
    out.append("</row>")
    return "".join(out)


def _write_sheet(zf: zipfile.ZipFile, arc: str, sheet: Sheet, selected: bool) -> str | None:
    """Stream one worksheet part; returns the absolute autofilter range ($A$1:$R$36) or None."""
    width = len(sheet.header)
    letters = [column_letter(i + 1) for i in range(max(width, 1))]
    rows = sheet.rows
    if sheet.n_rows is None:
        rows = list(rows)
        n = len(rows)
    else:
        n = sheet.n_rows
    if n > MAX_DATA_ROWS:
        raise ValueError(f"sheet {sheet.name}: {n} data rows, Excel holds at most {MAX_DATA_ROWS} (plus the header)")
    last =f"{letters[-1]}{n + 1}"
    ref = f"A1:{last}"
    view = '<sheetView tabSelected="1" workbookViewId="0"' if selected else '<sheetView workbookViewId="0"'
    if sheet.freeze_header:
        view += ('><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
                 '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/></sheetView>')
    else:
        view += "/>"
    head = "".join(f'<c r="{letters[i]}1" t="inlineStr" s="{_STYLE_HEADER}"><is>{_text(str(h))}</is></c>'
                   for i, h in enumerate(sheet.header) if h is not None)
    with zf.open(arc, "w") as f:
        f.write((f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<worksheet xmlns="{_NS}" '
                 f'xmlns:r="{_NS_R}"><dimension ref="{ref}"/><sheetViews>{view}</sheetViews>'
                 f'<sheetFormatPr defaultRowHeight="15"/><sheetData><row r="1">{head}</row>').encode("utf-8"))
        buf: list[str] = []
        r = 1
        for values in rows:
            r += 1
            if r > MAX_DATA_ROWS + 1:
                raise ValueError(f"sheet {sheet.name}: more than {MAX_DATA_ROWS} data rows (Excel's limit)")
            buf.append(_row(r, values, letters))
            if len(buf) >= _CHUNK_ROWS:
                f.write("".join(buf).encode("utf-8"))
                buf.clear()
        if buf:
            f.write("".join(buf).encode("utf-8"))
        if r - 1 != n:
            raise ValueError(f"sheet {sheet.name}: {r - 1} rows written, {n} announced")
        tail = "</sheetData>"
        if sheet.autofilter:
            tail += f'<autoFilter ref="{ref}"/>'
        tail += '<pageMargins left="0.75" right="0.75" top="1" bottom="1" header="0.5" footer="0.5"/></worksheet>'
        f.write(tail.encode("utf-8"))
    return f"$A$1:${letters[-1]}${n + 1}" if sheet.autofilter else None


def _attr(v: str) -> str:
    return _ILLEGAL.sub("", v).translate(_ESC)


_STYLES = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<styleSheet xmlns="{_NS}">'
           '<numFmts count="2"><numFmt numFmtId="164" formatCode="yyyy-mm-dd"/>'
           '<numFmt numFmtId="165" formatCode="yyyy-mm-dd h:mm:ss"/></numFmts>'
           '<fonts count="2"><font><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
           '<font><b/><sz val="11"/><name val="Calibri"/><family val="2"/></font></fonts>'
           '<fills count="2"><fill><patternFill patternType="none"/></fill>'
           '<fill><patternFill patternType="gray125"/></fill></fills>'
           '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
           '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
           '<cellXfs count="4"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
           '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
           '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
           '<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>'
           '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
           '</styleSheet>')


def write_xlsx(target: Path | IO[bytes], sheets: Sequence[Sheet], compresslevel: int = 6) -> None:
    """Write the workbook to target, a path or a binary file object (the caller handles temporary file / rename). Sheets are written in order, so a
    later sheet may hold rows computed while an earlier one was consumed."""
    n = len(sheets)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=compresslevel) as zf:
        zf.writestr("[Content_Types].xml",
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                    f'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                    '<Default Extension="xml" ContentType="application/xml"/>'
                    f'<Override PartName="/xl/workbook.xml" ContentType="{_CT}.sheet.main+xml"/>'
                    + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" '
                              f'ContentType="{_CT}.worksheet+xml"/>' for i in range(n))
                    + f'<Override PartName="/xl/styles.xml" ContentType="{_CT}.styles+xml"/></Types>')
        zf.writestr("_rels/.rels",
                    f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{_NS_PR}">'
                    f'<Relationship Id="rId1" Type="{_NS_R}/officeDocument" Target="xl/workbook.xml"/>'
                    '</Relationships>')
        zf.writestr("xl/styles.xml", _STYLES)
        filters = []
        for i, sh in enumerate(sheets):
            ref = _write_sheet(zf, f"xl/worksheets/sheet{i + 1}.xml", sh, i == 0)
            if ref:
                name = _attr(sh.name.replace("'", "''"))
                filters.append(f'<definedName name="_xlnm._FilterDatabase" localSheetId="{i}" hidden="1">'
                               f"'{name}'!{ref}</definedName>")
        zf.writestr("xl/_rels/workbook.xml.rels",
                    f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{_NS_PR}">'
                    + "".join(f'<Relationship Id="rId{i + 1}" Type="{_NS_R}/worksheet" '
                              f'Target="worksheets/sheet{i + 1}.xml"/>' for i in range(n))
                    + f'<Relationship Id="rId{n + 1}" Type="{_NS_R}/styles" Target="styles.xml"/></Relationships>')
        zf.writestr("xl/workbook.xml",
                    f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<workbook xmlns="{_NS}" '
                    f'xmlns:r="{_NS_R}"><bookViews><workbookView activeTab="0"/></bookViews><sheets>'
                    + "".join(f'<sheet name="{_attr(sh.name)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>'
                              for i, sh in enumerate(sheets))
                    + "</sheets>"
                    + (f"<definedNames>{''.join(filters)}</definedNames>" if filters else "")
                    + "</workbook>")
