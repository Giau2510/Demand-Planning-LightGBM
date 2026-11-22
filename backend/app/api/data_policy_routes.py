"""1.4.15: the four guarded data_policy fields (data_routes.DATA_POLICY_GUARDED): window_start_date, history_change_policy,
history_day_check, source_time_travel_hours.

The generic settings editor (PUT /api/settings/data_policy and its reset) keeps them unchanged; they change only here:
the client sends the values it saw (expected, compared inside the write transaction: a change made elsewhere -> 409
SETTINGS_CHANGED_ELSEWHERE), a high-risk field needs the typed text DOI-CHINH-SACH-DU-LIEU-<today, Vietnam> and a reason,
the other fields acknowledged = true. Each change writes one settings-history row (note OWNER_CONFIRMED ...) and two audit
rows: SETTINGS_SAVED (written by ss.save) and DATA_POLICY_GUARDED_APPLIED (fields, values, reason, version).
Undo has no endpoint of its own: the UI applies the previous_values of a history row the same way (settings only: data
already written by a D-1 is not undone; that needs history_sync.rollback).

window_start_date is LOCKED here (DATA_POLICY_FIELD_LOCKED): it is part of the BigQuery mapping hash, so a change asks
for a new full-period validation (D-1 refused with BQ_VALIDATION_REQUIRED) and then a FULL reload from the new date.
An apply is refused (DATA_POLICY_BUSY) while a D-1 / refresh / training job is active or in a production window.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ValidationError

from .. import db
from .. import settings_service as ss
from ..data.demand import bigquery_scope_key
from ..jobs.flows import ACTIVE_STATUSES
from ..messages import AppError
from ..timeutil import now_vn, today_vn
from .data_routes import DATA_POLICY_GUARDED

router = APIRouter(prefix="/api")
HIGH_RISK = ("history_change_policy", "window_start_date")
LOCKED = ("window_start_date",)
LOCKED_REASON_CODE = "WINDOW_START_CHANGES_RELOAD"
REASON_MIN = 10
REASON_MAX = 500
HISTORY_ROWS = 5
HELD_COUNT_CAP = 100_000    # the impact count stops here (index-only scan of the ACTIVE held lines, never the whole table)
BUSY_JOB_TYPES = ("D1_SYNC", "FORECAST_REFRESH", "CANDIDATE_TRAIN", "TRAIN_PUBLISH")
BLOCKED_WINDOWS_VN = (("23:45", "00:15"), ("00:45", "03:45"))      # production slots (Vietnam time), end excluded


def _blocked_window() -> str | None:
    t = now_vn().strftime("%H:%M")
    for a, b in BLOCKED_WINDOWS_VN:
        if (a <= t < b) if a < b else (t >= a or t < b):
            return f"{a}-{b}"
    return None


def _busy(c) -> None:
    win = _blocked_window()
    if win:
        raise AppError("DATA_POLICY_BUSY", 409, detail=f"production window {win} (Vietnam)", window=win)
    jobs = db.rows(c, f"SELECT id, job_type, status FROM job_runs WHERE job_type IN "
                      f"({','.join('?' * len(BUSY_JOB_TYPES))}) AND status IN ({','.join('?' * len(ACTIVE_STATUSES))}) "
                      "ORDER BY created_at DESC, rowid DESC LIMIT 10", (*BUSY_JOB_TYPES, *ACTIVE_STATUSES))
    if jobs:
        raise AppError("DATA_POLICY_BUSY", 409, detail=", ".join(f"{j['job_type']} {j['status']}" for j in jobs),
                       jobs=jobs)


def _confirm_text() -> str:
    return f"DOI-CHINH-SACH-DU-LIEU-{today_vn().isoformat()}"


def _fields(model) -> dict:
    return {k: getattr(model, k) for k in DATA_POLICY_GUARDED}


def _defaults() -> dict:
    return _fields(ss.DataPolicySettings())


def _version(c) -> int:
    r = c.execute("SELECT MAX(id) FROM settings_history WHERE section='data_policy'").fetchone()
    return int(r[0] or 0)


def _same(a, b) -> bool:
    return type(a) is type(b) and a == b       # True is not 1, 160.0 is not 160


def _fmt(v) -> str:
    return ("true" if v else "false") if isinstance(v, bool) else str(v)


def _history(c) -> list[dict]:
    """The newest settings-history rows of data_policy that changed a guarded field (compared with the row before it;
    the first row ever with the code defaults, which were the values in effect before any save)."""
    out: list[dict] = []
    defaults = _defaults()
    newer = None
    cur = c.execute("SELECT id, value_json, changed_at, note FROM settings_history WHERE section='data_policy' "
                    "ORDER BY id DESC")
    for r in cur:
        try:
            raw = json.loads(r["value_json"])
        except (TypeError, ValueError):
            raw = {}
        row = {"id": r["id"], "changed_at": r["changed_at"], "note": r["note"],
               "values": {k: raw.get(k, defaults[k]) for k in DATA_POLICY_GUARDED}}
        if newer is not None and newer["values"] != row["values"]:
            out.append({**newer, "previous_values": row["values"]})     # values before that row: the undo target
            if len(out) >= HISTORY_ROWS:
                return out
        newer = row
    if newer is not None and newer["values"] != defaults:
        out.append({**newer, "previous_values": defaults})
    return out[:HISTORY_ROWS]


def _check_patch(patch: dict) -> None:
    if not patch or len(patch) > len(DATA_POLICY_GUARDED):
        raise AppError("DATA_POLICY_UNKNOWN_FIELD", 422, detail="patch needs 1..4 guarded fields")
    unknown = sorted(k for k in patch if k not in DATA_POLICY_GUARDED)
    if unknown:
        raise AppError("DATA_POLICY_UNKNOWN_FIELD", 422, detail=", ".join(unknown))
    locked = [k for k in DATA_POLICY_GUARDED if k in patch and k in LOCKED]
    if locked:
        raise AppError("DATA_POLICY_FIELD_LOCKED", 422, detail=", ".join(locked), reason_code=LOCKED_REASON_CODE)


def _validated(cur, patch: dict) -> dict:
    """The four fields after the patch, validated by the settings model (never looser) + no future window start."""
    try:
        new = ss.DataPolicySettings.model_validate({**cur.model_dump(), **patch})
    except ValidationError as e:
        raise AppError("DATA_POLICY_INVALID_VALUE", 422,
                       detail="; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())) from None
    if "window_start_date" in patch and date.fromisoformat(new.window_start_date) > today_vn():
        raise AppError("DATA_POLICY_INVALID_VALUE", 422, detail=f"window_start_date {new.window_start_date} is in the future")
    return _fields(new)


def _changed(before: dict, after: dict) -> list[str]:
    return [k for k in DATA_POLICY_GUARDED if not _same(before[k], after[k])]


def _held_lines_active() -> tuple[int | None, bool]:
    """ACTIVE held lines of the BigQuery scope (the one D-1 reads), counted through the partial index idx_dhl_active
    only and stopped at HELD_COUNT_CAP; (None, False) when that is not cheap or not sure (no index, BigQuery not set)."""
    try:
        bq = ss.get("bigquery")
        if not (bq.dataset_id and bq.source_table):
            return None, False
        with db.read() as c:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_dhl_active'").fetchone():
                return None, False
            n = c.execute("SELECT COUNT(*) FROM (SELECT 1 FROM demand_held_lines INDEXED BY idx_dhl_active "
                          "WHERE scope_key=? AND status='ACTIVE' LIMIT ?)",
                          (bigquery_scope_key(bq), HELD_COUNT_CAP + 1)).fetchone()[0]
    except Exception:  # noqa: BLE001 - an estimate only: never blocks the preview
        return None, False
    return min(n, HELD_COUNT_CAP), n > HELD_COUNT_CAP


def _impact(after: dict, changed: list[str]) -> tuple[dict | None, list[str], list[str]]:
    """(impact, warnings, notes); notes are codes the UI translates."""
    impact = None
    warnings: list[str] = []
    notes: list[str] = []
    if "history_change_policy" in changed:
        n, capped = _held_lines_active()
        impact = {"kind": "HELD_LINES", "active_held_lines": n, "capped": capped, "applies_from": "NEXT_D1"}
        notes += ["APPLIES_AT_NEXT_D1", "FOLLOW_SOURCE_DROPS_REMOVED_LINES"
                  if after["history_change_policy"] == "FOLLOW_SOURCE" else "KEEP_OBSERVED_LINES_HOLDS_REMOVED_LINES"]
    missing = [k for k in changed if k != "history_change_policy"]
    if missing:
        warnings.append("khong co uoc tinh tac dong / no impact estimate: " + ", ".join(missing))
    notes.append("UNDO_SETTINGS_ONLY")
    return impact, warnings, notes


# ------------------------------------------------------------------ read
@router.get("/data-policy/guarded")
def guarded_get():
    with db.read() as c:
        cur = ss.get("data_policy", c)
        return {"fields": _fields(cur), "defaults": _defaults(), "version": _version(c),
                "confirm_text": _confirm_text(), "high_risk_fields": list(HIGH_RISK),
                "locked_fields": list(LOCKED), "locked_reason_code": LOCKED_REASON_CODE,
                "reason_min_length": REASON_MIN, "history": _history(c)}


class PreviewBody(BaseModel):
    patch: dict[str, Any]


@router.post("/data-policy/guarded/preview")
def guarded_preview(body: PreviewBody):
    """Read-only: what the patch would change, never writes."""
    _check_patch(body.patch)
    cur = ss.get("data_policy")
    before = _fields(cur)
    after = _validated(cur, body.patch)
    changed = _changed(before, after)
    high = any(k in HIGH_RISK for k in changed)
    impact, warnings, notes = _impact(after, changed)
    if not changed:
        warnings.append("NO_CHANGE")
    return {"before": before, "after": after, "changed": changed, "high_risk": high, "needs_confirm_text": high,
            "needs_acknowledged": any(k not in HIGH_RISK for k in changed), "impact": impact, "warnings": warnings,
            "notes": notes, "confirm_text": _confirm_text()}


class ApplyBody(BaseModel):
    patch: dict[str, Any]
    expected: dict[str, Any] = {}
    confirm_text: str | None = None
    reason: str | None = None
    acknowledged: bool = False


@router.post("/data-policy/guarded")
def guarded_apply(body: ApplyBody):
    _check_patch(body.patch)
    missing = [k for k in body.patch if k not in body.expected]
    if missing:
        raise AppError("DATA_POLICY_EXPECTED_REQUIRED", 422, detail=", ".join(missing))
    reason = " ".join((body.reason or "").split())
    if len(reason) > REASON_MAX:
        raise AppError("DATA_POLICY_INVALID_VALUE", 422, detail=f"reason longer than {REASON_MAX} characters")
    with db.tx() as c:
        _busy(c)            # under the write lock: no D-1 / refresh / training starts between this check and the save
        cur = ss.get("data_policy", c)
        before = _fields(cur)
        stale =[k for k in body.patch if not _same(body.expected[k], before[k])]
        if stale:
            raise AppError("SETTINGS_CHANGED_ELSEWHERE", 409, detail=", ".join(stale), current=before,
                           version=_version(c))
        after = _validated(cur, body.patch)
        changed = _changed(before, after)
        if not changed:
            raise AppError("NO_CHANGE", 400)
        expected_text = _confirm_text()
        if any(k in HIGH_RISK for k in changed):
            if (body.confirm_text or "").strip() != expected_text:
                raise AppError("DATA_POLICY_CONFIRM_REQUIRED", 409, detail=f"type {expected_text}",
                               confirm_text=expected_text)
            if len(reason) < REASON_MIN:
                raise AppError("DATA_POLICY_CONFIRM_REQUIRED", 409, detail=f"reason of at least {REASON_MIN} characters",
                               confirm_text=expected_text)
        if any(k not in HIGH_RISK for k in changed) and not body.acknowledged:
            raise AppError("DATA_POLICY_CONFIRM_REQUIRED", 409, detail="acknowledged = true", confirm_text=expected_text)
        note = "OWNER_CONFIRMED data_policy " + "; ".join(f"{k} {_fmt(before[k])} -> {_fmt(after[k])}" for k in changed)
        if reason:
            note += f": {reason}"
        ss.save("data_policy", {**cur.model_dump(), **{k: after[k] for k in changed}}, note=note, conn=c)
        version = _version(c)
        db.audit(c, "DATA_POLICY_GUARDED_APPLIED", "settings", "data_policy",
                 {"changes": {k: {"from": before[k], "to": after[k]} for k in changed}, "reason": reason or None,
                  "version": version})
    return {"applied": {k: after[k] for k in changed}, "version": version}
