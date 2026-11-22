"""1.4.15 (lot 2B): settings export / import over HTTP (logic and rules in app/settings_portable.py).

GET  /api/settings-export              the JSON file as a download (cai_dat_<yyyymmdd_hhmm>.json); read-only, nothing
                                       is written on the server (never into the data folder).
POST /api/settings-import/preview      {document}: never writes.
POST /api/settings-import/apply        {document, sections, expected:{section: hash}, confirm_text, reason}: one db.tx.
POST /api/settings-import/undo         {import_id, confirm_text, reason}: one db.tx.
GET  /api/settings-import/history      the latest imports / undos (audit).
Agents and the orchestrator never call apply / undo (only the owner's click in the UI).
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel

from .. import db
from .. import settings_portable as sp
from ..messages import AppError

router = APIRouter(prefix="/api")
MAX_BODY_BYTES = 2 * 1024 * 1024      # a settings file is a few tens of kB


def _limit(request: Request) -> None:
    """413 SETTINGS_IMPORT_TOO_LARGE before the body is parsed (declared length); _check_size checks the parsed one."""
    n = request.headers.get("content-length")
    if n and n.isdigit() and int(n) > MAX_BODY_BYTES:
        raise AppError("SETTINGS_IMPORT_TOO_LARGE", 413, detail=f"{n} bytes > {MAX_BODY_BYTES}")


def _check_size(document: dict) -> None:
    n = len(sp.canonical(document))
    if n > MAX_BODY_BYTES:
        raise AppError("SETTINGS_IMPORT_TOO_LARGE", 413, detail=f"{n} bytes > {MAX_BODY_BYTES}")


@router.get("/settings-export")
def settings_export():
    with db.read() as c:
        doc = sp.export_doc(c)
    body = json.dumps(doc, sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8")
    return Response(body, media_type="application/json; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{sp.file_name()}"'})


class PreviewBody(BaseModel):
    document: dict[str, Any]


@router.post("/settings-import/preview", dependencies=[Depends(_limit)])
def settings_import_preview(body: PreviewBody):
    _check_size(body.document)
    with db.read() as c:
        return sp.preview(c, body.document)


class ApplyBody(BaseModel):
    document: dict[str, Any]
    sections: list[str]
    expected: dict[str, str] = {}
    confirm_text: str | None = None
    reason: str | None = None
    confirm_purchase: str | None = None      # DOI-CAI-DAT-ANH-HUONG-MUA-HANG-<day> when a PURCHASE key changes
    confirm_high: str | None = None          # DOI-CAI-DAT-AN-<day> when a HIGH key changes


@router.post("/settings-import/apply", dependencies=[Depends(_limit)])
def settings_import_apply(body: ApplyBody):
    _check_size(body.document)
    with db.tx() as c:
        return sp.apply(c, body.document, body.sections, body.expected, body.confirm_text, body.reason,
                        body.confirm_purchase, body.confirm_high)


class UndoBody(BaseModel):
    import_id: str
    confirm_text: str | None = None
    reason: str | None = None
    confirm_purchase: str | None = None
    confirm_high: str | None = None


@router.post("/settings-import/undo", dependencies=[Depends(_limit)])
def settings_import_undo(body: UndoBody):
    with db.tx() as c:
        return sp.undo(c, body.import_id, body.confirm_text, body.reason, body.confirm_purchase,
                       body.confirm_high)


@router.get("/settings-import/history")
def settings_import_history():
    with db.read() as c:
        return sp.history(c)
