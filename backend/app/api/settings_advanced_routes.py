"""1.4.15 (lot 2): "Cai dat nang cao" - the guarded editor of the registry fields (settings_registry.ENTRIES).

GET  /api/settings-advanced           registry + current / default values, risk, versions, today's texts, history.
POST /api/settings-advanced/preview   {changes:[{section,key,value}]}: never writes; before / after, highest risk, the
                                      confirmation needed, busy (as an apply would see it), warning / note CODES.
POST /api/settings-advanced/apply     {changes, expected:{section:{key:value}}, confirm_text, reason, acknowledged}
POST /api/settings-advanced/undo      {audit_id, confirm_text, reason, acknowledged}
An apply / undo runs in ONE db.tx(): busy gate (every job type, production windows; a stale job row as in lot 1b does
not block and is audited), the expected value of every key (409 SETTINGS_CHANGED_ELSEWHERE), READONLY / OWN_PATH /
unknown keys 422, a decrease of an only_increase key 422 RETENTION_DECREASE_NOT_ALLOWED, the whole section validated by
its settings model (cross-field rules), at most MAX_KEYS keys, the typed text of the highest risk + a reason; then one
settings-history row per section and the audit SETTINGS_ADVANCED_APPLIED / _UNDONE (every key from -> to).
Settings only: data already written under a setting is never undone. Agents and the orchestrator never call apply /
undo (only the owner's click in the UI).
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ValidationError

from .. import db
from .. import settings_registry as reg
from .. import settings_service as ss
from ..jobs import runner
from ..messages import AppError
from ..timeutil import today_vn
from .data_policy_routes import _busy_state

router = APIRouter(prefix="/api")
MAX_KEYS = 10
REASON_MIN = 10
REASON_MAX = 500
HISTORY_ROWS = 20
BUSY_JOB_TYPES = runner.JOB_TYPES      # every job type: a run may read any registry field (safer when in doubt)
ACTIONS = ("SETTINGS_ADVANCED_APPLIED", "SETTINGS_ADVANCED_UNDONE")


def _confirm_texts() -> dict:
    d = today_vn().isoformat()
    return {"HIGH": f"DOI-CAI-DAT-AN-{d}", "PURCHASE": f"DOI-CAI-DAT-ANH-HUONG-MUA-HANG-{d}"}


def _versions(c, sections) -> dict:
    out = {}
    for s in sorted(set(sections)):
        r = c.execute("SELECT MAX(id) FROM settings_history WHERE section=?", (s,)).fetchone()
        out[s] = int(r[0] or 0)
    return out


def _busy(c) -> dict:
    st = _busy_state(c, BUSY_JOB_TYPES)
    if st["busy"]:
        raise AppError("SETTINGS_ADVANCED_BUSY", 409, detail=st["detail"], window=st["window"], jobs=st["jobs"],
                       stale_ignored=st["stale_ignored"], stale_ignored_total=st["stale_ignored_total"])
    return st


def _entry(section: str, key: str) -> reg.Entry:
    e = reg.entry(section, key)
    if e is None:
        raise AppError("SETTINGS_ADVANCED_UNKNOWN_KEY", 422, detail=f"{section}.{key}")
    if not reg.editable(e):
        raise AppError("SETTINGS_ADVANCED_NOT_EDITABLE", 422, detail=f"{section}.{key}", risk=reg.risk(e),
                       reason_code=reg.reason_code(e), own_path=e.own_path)
    return e


def _check_changes(changes: list[dict]) -> dict[str, dict[str, Any]]:
    """{section: {key: value}} of 1..MAX_KEYS editable keys, each once."""
    if not changes or len(changes) > MAX_KEYS:
        raise AppError("SETTINGS_ADVANCED_KEY_COUNT", 422, detail=f"1..{MAX_KEYS} keys per change, got {len(changes)}")
    out: dict[str, dict[str, Any]] = {}
    for ch in changes:
        s, k = ch["section"], ch["key"]
        _entry(s, k)
        if k in out.get(s, {}):
            raise AppError("SETTINGS_ADVANCED_DUPLICATE_KEY", 422, detail=f"{s}.{k}")
        out.setdefault(s, {})[k] = ch["value"]
    return out


def _validated(section: str, cur, patch: dict):
    """The WHOLE section after the patch, validated by its settings model (cross-field rules included)."""
    ctx = {"stored": True} if section == "schedule" else None     # d0_paused_until is never in a patch here
    try:
        return ss.SECTIONS[section].model_validate({**cur.model_dump(), **patch}, context=ctx)
    except ValidationError as e:
        raise AppError("SETTINGS_ADVANCED_INVALID_VALUE", 422, detail=f"{section}: " + "; ".join(
            f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())) from None


def _rules(section: str, before: dict, after: dict, keys) -> None:
    for k in keys:
        e = reg.entry(section, k)
        if e.path_rule and not reg.path_ok(e, after[k]):
            raise AppError("SETTINGS_PATH_INVALID", 422, detail=f"{section}.{k} = {after[k]!r}")
        if e.only_increase and not reg.same(before[k], after[k]) and after[k] < before[k]:
            raise AppError("RETENTION_DECREASE_NOT_ALLOWED", 422, detail=f"{section}.{k} {before[k]} -> {after[k]}",
                           current=before[k])


def _plan(c, patches: dict[str, dict]) -> list[dict]:
    """[{section, key, risk, from, to, changed}] after validation of every touched section (no write)."""
    rows = []
    for s, patch in patches.items():
        cur = ss.get(s, c)
        before = cur.model_dump()
        after = _validated(s, cur, patch).model_dump()
        _rules(s, before, after, patch)
        for k in patch:
            e = reg.entry(s, k)
            rows.append({"section": s, "key": k, "risk": reg.risk(e), "from": before[k], "to": after[k],
                         "changed": not reg.same(before[k], after[k])})
    return rows


def _notes(changed: list[dict]) -> tuple[list[str], list[str]]:
    warnings, notes = [], []
    if not changed:
        warnings.append("NO_CHANGE")
    if any(r["risk"] == "PURCHASE" for r in changed):
        warnings.append("PURCHASE_NUMBERS_CHANGE")
    if any(r["section"] == "sel2_pipeline" and r["key"] in reg.SPIKE_KEYS for r in changed):
        warnings.append("SPIKE_OWNER_DECISION")
    if changed:
        notes.append("APPLIES_FROM_NEXT_RUN")
    if any(reg.entry(r["section"], r["key"]).only_increase for r in changed):
        notes.append("RETENTION_DATA_NOT_RESTORED")
    notes.append("UNDO_SETTINGS_ONLY")
    return warnings, notes


def _confirm(changed: list[dict], confirm_text: str | None, reason: str, acknowledged: bool) -> str:
    """Checks the typed text of the highest risk + the reason, and acknowledged for a LOW key; returns the risk."""
    top = reg.risk_max(r["risk"] for r in changed)
    texts = _confirm_texts()
    if top in ("HIGH", "PURCHASE"):
        if (confirm_text or "").strip() != texts[top]:
            raise AppError("SETTINGS_ADVANCED_CONFIRM_REQUIRED", 409, detail=f"type {texts[top]}",
                           confirm_text=texts[top], risk=top)
        if len(reason) < REASON_MIN:
            raise AppError("SETTINGS_ADVANCED_CONFIRM_REQUIRED", 409, detail=f"reason of at least {REASON_MIN} characters",
                           confirm_text=texts[top], risk=top)
    if any(r["risk"] == "LOW" for r in changed) and not acknowledged:
        raise AppError("SETTINGS_ADVANCED_CONFIRM_REQUIRED", 409, detail="acknowledged = true",
                       confirm_text=texts.get(top), risk=top)
    return top


def _reason(text: str | None) -> str:
    reason = " ".join((text or "").split())
    if len(reason) > REASON_MAX:
        raise AppError("SETTINGS_ADVANCED_INVALID_VALUE", 422, detail=f"reason longer than {REASON_MAX} characters")
    return reason


def _fmt(v) -> str:
    return json.dumps(v, ensure_ascii=False, default=str)


def _save(c, changed: list[dict], tag: str, reason: str) -> None:
    """One settings-history row per section; only the changed keys move (re-validated as a whole section)."""
    by_section: dict[str, dict] = {}
    for r in changed:
        by_section.setdefault(r["section"], {})[r["key"]] = r["to"]
    for s, patch in by_section.items():
        cur = ss.get(s, c)
        new = _validated(s, cur, patch)
        note = f"OWNER_CONFIRMED {tag} {s}: " + "; ".join(
            f"{r['key']} {_fmt(r['from'])} -> {_fmt(r['to'])}" for r in changed if r["section"] == s)
        if reason:
            note += f": {reason}"
        ss.save(s, new, note=note, conn=c)


def _audit(c, action: str, entity_id: str, details: dict) -> int:
    db.audit(c, action, "settings_advanced", entity_id, details)
    return int(c.execute("SELECT last_insert_rowid()").fetchone()[0])


def _history(c) -> list[dict]:
    rows = db.rows(c, f"SELECT id, at, action, entity_id, details_json FROM audit_log WHERE action IN "
                      f"({','.join('?' * len(ACTIONS))}) ORDER BY id DESC LIMIT ?", (*ACTIONS, HISTORY_ROWS))
    undone = {r["entity_id"] for r in db.rows(c, "SELECT entity_id FROM audit_log WHERE action='SETTINGS_ADVANCED_UNDONE'")}
    out = []
    for r in rows:
        try:
            d = json.loads(r["details_json"] or "{}")
        except ValueError:
            d = {}
        out.append({"id": r["id"], "at": r["at"], "action": r["action"], "details": d,
                    "undone": r["action"] == "SETTINGS_ADVANCED_APPLIED" and str(r["id"]) in undone})
    return out


def _stale(busy: dict) -> dict:
    return {"stale_ignored": [{k: j[k] for k in ("id", "job_type", "status")} for j in busy["stale_ignored"]],
            "stale_ignored_total": busy["stale_ignored_total"]}


# ------------------------------------------------------------------ read
@router.get("/settings-advanced")
def advanced_get():
    sections = sorted({e.section for e in reg.ENTRIES})
    with db.read() as c:
        cur = {s: ss.get(s, c).model_dump() for s in sections}
        versions = _versions(c, sections)
        history = _history(c)
    defaults = {s: ss.SECTIONS[s]().model_dump() for s in sections}
    entries = [{"section": e.section, "key": e.key, "risk": reg.risk(e), "editable": reg.editable(e),
                "label_vi": e.label_vi, "label_en": e.label_en, "desc_vi": e.desc_vi, "desc_en": e.desc_en,
                "only_increase": e.only_increase, "path_rule": e.path_rule, "reason_code": reg.reason_code(e),
                "own_path": e.own_path, "exportable": reg.exportable(e), "constraints": reg.constraints(e.section, e.key),
                "value": cur[e.section][e.key], "default": defaults[e.section][e.key]} for e in reg.ENTRIES]
    return {"entries": entries, "versions": versions, "confirm_texts": _confirm_texts(), "reason_min_length": REASON_MIN,
            "max_keys": MAX_KEYS, "history": history}


class Change(BaseModel):
    section: str
    key: str
    value: Any


class PreviewBody(BaseModel):
    changes: list[Change]


@router.post("/settings-advanced/preview")
def advanced_preview(body: PreviewBody):
    patches = _check_changes([ch.model_dump() for ch in body.changes])
    with db.read() as c:
        rows = _plan(c, patches)
        busy = _busy_state(c, BUSY_JOB_TYPES)
        versions = _versions(c, patches)
    changed = [r for r in rows if r["changed"]]
    top = reg.risk_max(r["risk"] for r in changed)
    warnings, notes = _notes(changed)
    return {"changes": rows, "changed": [f"{r['section']}.{r['key']}" for r in changed], "max_risk": top,
            "needs_confirm_text": top in ("HIGH", "PURCHASE"), "needs_reason": top in ("HIGH", "PURCHASE"),
            "needs_acknowledged": any(r["risk"] == "LOW" for r in changed),
            "confirm_text": _confirm_texts().get(top), "warnings": warnings, "notes": notes, "busy": busy,
            "versions": versions}


class ApplyBody(BaseModel):
    changes: list[Change]
    expected: dict[str, dict[str, Any]] = {}
    confirm_text: str | None = None
    reason: str | None = None
    acknowledged: bool = False


@router.post("/settings-advanced/apply")
def advanced_apply(body: ApplyBody):
    patches = _check_changes([ch.model_dump() for ch in body.changes])
    missing = [f"{s}.{k}" for s, p in patches.items() for k in p if k not in body.expected.get(s, {})]
    if missing:
        raise AppError("SETTINGS_ADVANCED_EXPECTED_REQUIRED", 422, detail=", ".join(missing))
    reason = _reason(body.reason)
    with db.tx() as c:
        busy = _busy(c)          # under the write lock: no job row is added between this check and the save
        before_versions = _versions(c, patches)
        current = {s: ss.get(s, c).model_dump() for s in patches}
        stale = [f"{s}.{k}" for s, p in patches.items() for k in p if not reg.same(body.expected[s][k], current[s][k])]
        if stale:
            raise AppError("SETTINGS_CHANGED_ELSEWHERE", 409, detail=", ".join(stale),
                           current={s: {k: current[s][k] for k in p} for s, p in patches.items()},
                           versions=before_versions)
        rows = _plan(c, patches)
        changed = [r for r in rows if r["changed"]]
        if not changed:
            raise AppError("NO_CHANGE", 400)
        top = _confirm(changed, body.confirm_text, reason, body.acknowledged)
        _save(c, changed, "settings-advanced", reason)
        versions = _versions(c, patches)
        audit_id = _audit(c, "SETTINGS_ADVANCED_APPLIED", ",".join(sorted({r["section"] for r in changed})),
                          {"changes": [{k: r[k] for k in ("section", "key", "risk", "from", "to")} for r in changed],
                           "reason": reason or None, "risk": top, "versions_before": before_versions,
                           "versions": versions, **_stale(busy)})
    return {"applied": [{k: r[k] for k in ("section", "key", "from", "to")} for r in changed], "versions": versions,
            "audit_id": audit_id}


class UndoBody(BaseModel):
    audit_id: int
    confirm_text: str | None = None
    reason: str | None = None
    acknowledged: bool = False


@router.post("/settings-advanced/undo")
def advanced_undo(body: UndoBody):
    """Puts back the keys that one apply changed, only where the current value is still that apply's `to`."""
    reason = _reason(body.reason)
    with db.tx() as c:
        busy = _busy(c)
        row = db.one(c, "SELECT id, details_json FROM audit_log WHERE id=? AND action='SETTINGS_ADVANCED_APPLIED'",
                     (body.audit_id,))
        if row is None:
            raise AppError("SETTINGS_ADVANCED_AUDIT_NOT_FOUND", 404, detail=str(body.audit_id))
        if db.one(c, "SELECT id FROM audit_log WHERE action='SETTINGS_ADVANCED_UNDONE' AND entity_id=?",
                  (str(body.audit_id),)):
            raise AppError("SETTINGS_ADVANCED_ALREADY_UNDONE", 409, detail=str(body.audit_id))
        done = json.loads(row["details_json"] or "{}").get("changes") or []
        patches: dict[str, dict] = {}
        for ch in done:
            _entry(ch["section"], ch["key"])            # still editable (a key made read-only since -> 422)
            patches.setdefault(ch["section"], {})[ch["key"]] = ch["from"]
        before_versions = _versions(c, patches)
        current = {s: ss.get(s, c).model_dump() for s in patches}
        moved = [f"{ch['section']}.{ch['key']}" for ch in done
                 if not reg.same(current[ch["section"]][ch["key"]], ch["to"])]
        if moved:
            raise AppError("SETTINGS_CHANGED_ELSEWHERE", 409, detail=", ".join(moved),
                           current={s: {k: current[s][k] for k in p} for s, p in patches.items()},
                           versions=before_versions)
        rows = _plan(c, patches)             # whole sections validated, only_increase: an undo never shortens a retention
        changed = [r for r in rows if r["changed"]]
        if not changed:
            raise AppError("NO_CHANGE", 400)
        top = _confirm(changed, body.confirm_text, reason, body.acknowledged)
        _save(c, changed, f"settings-advanced undo of {body.audit_id}", reason)
        versions = _versions(c, patches)
        audit_id = _audit(c, "SETTINGS_ADVANCED_UNDONE", str(body.audit_id),
                          {"undo_of": body.audit_id,
                           "changes": [{k: r[k] for k in ("section", "key", "risk", "from", "to")} for r in changed],
                           "reason": reason or None, "risk": top, "versions_before": before_versions,
                           "versions": versions, **_stale(busy)})
    return {"undone": [{k: r[k] for k in ("section", "key", "from", "to")} for r in changed], "versions": versions,
            "audit_id": audit_id}
