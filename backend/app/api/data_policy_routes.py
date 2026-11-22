"""1.4.15: the guarded data_policy fields (data_routes.DATA_POLICY_GUARDED): window_start_date, history_change_policy,
history_day_check, source_time_travel_hours, training_start_rule.

The generic settings editor (PUT /api/settings/data_policy and its reset) keeps them unchanged; they change only here:
the client sends the values it saw (expected, compared inside the write transaction: a change made elsewhere -> 409
SETTINGS_CHANGED_ELSEWHERE), a high-risk field needs the typed text DOI-CHINH-SACH-DU-LIEU-<today, Vietnam> and a reason,
the other fields acknowledged = true. Each change writes one settings-history row (note OWNER_CONFIRMED ...) and two audit
rows: SETTINGS_SAVED (written by ss.save) and DATA_POLICY_GUARDED_APPLIED (fields, values, reason, version).
Undo has no endpoint of its own: the UI applies the previous_values of a history row the same way (settings only: data
already written by a D-1 is not undone; that needs history_sync.rollback).

window_start_date is LOCKED here (DATA_POLICY_FIELD_LOCKED): it is part of the BigQuery mapping hash, so a change asks
for a new full-period validation (D-1 refused with BQ_VALIDATION_REQUIRED) and then a FULL reload from the new date.
training_start_rule changes the MODEL INPUT window at the next data_window(scope) read (1.3.1 refresh with the model in
use, SEL2 open-hours / actual read floor, data-quality report, feature page, training); the SEL2 lightgbm_forecast
numbers are not changed and no stored data is deleted.
An apply is refused (DATA_POLICY_BUSY) while a job of BUSY_JOB_TYPES is active or in a production window. A job row
left active without a live thread in this process and whose newest time mark is older than STALE (max 6 h, train
timeout + 10 min) does not block: it is listed as stale_ignored (never changed here). A row without a readable mark
blocks.
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ValidationError

from .. import db
from .. import settings_service as ss
from ..data import open_hours
from ..data.demand import bigquery_scope_key, resolve_scope
from ..jobs import runner
from ..jobs.flows import ACTIVE_STATUSES
from ..messages import AppError
from ..timeutil import now_utc, now_vn, parse_iso, today_vn
from .data_routes import DATA_POLICY_GUARDED

router = APIRouter(prefix="/api")
HIGH_RISK = ("history_change_policy", "window_start_date", "training_start_rule")
LOCKED = ("window_start_date",)
LOCKED_REASON_CODE = "WINDOW_START_CHANGES_RELOAD"
REASON_MIN = 10
REASON_MAX = 500
HISTORY_ROWS = 5
HELD_COUNT_CAP = 100_000    # the impact count stops here (index-only scan of the ACTIVE held lines, never the whole table)
# jobs that read the data_policy fields (D-1 sync) or the model-input window (data_window): FORECAST_EXTEND is not
# listed - it rebuilds the panel of its training run's own range (ml/pipeline.extend_forecast, panel_for_run) and never
# calls data_window
BUSY_JOB_TYPES = ("D1_SYNC", "FORECAST_REFRESH", "CANDIDATE_TRAIN", "TRAIN_PUBLISH", "FORECAST_EXPORT", "SPIKE_LINES",
                  "ACCURACY_REPORT")
MAX_LISTED = 10             # jobs / stale_ignored listed in a busy answer (stale_ignored_total gives the full count)
BLOCKED_WINDOWS_VN = (("23:45", "00:15"), ("00:45", "03:45"))      # production slots (Vietnam time), end excluded
STALE_MIN_S = 6 * 3600      # an active job row older than this (and the training timeout + STALE_TRAIN_MARGIN_S) ...
STALE_TRAIN_MARGIN_S = 600  # ... with no live thread in this process does not block (same margin as ml/sel2/store.py)
COVERAGE_TIMEOUT_S = 30     # the preview's open-hours coverage scan is interrupted after this (estimate only)


def _blocked_window() -> str | None:
    t = now_vn().strftime("%H:%M")
    for a, b in BLOCKED_WINDOWS_VN:
        if (a <= t < b) if a < b else (t >= a or t < b):
            return f"{a}-{b}"
    return None


def _stale_seconds(c) -> int:
    return max(STALE_MIN_S, int(ss.get("sel2_pipeline", c).train_timeout_seconds) + STALE_TRAIN_MARGIN_S)


class _BadMark(Exception):
    pass


def _parse_mark(v):
    try:
        return parse_iso(v)
    except (TypeError, ValueError):
        raise _BadMark(v) from None


def _last_mark(j: dict):
    """Newest time mark of a job row (UTC); a RETRY_WAIT row: its next attempt when set. None (= the row BLOCKS) when the
    row has no mark at all or when any of its marks is malformed (its true age is unknown)."""
    try:
        if j["status"] == "RETRY_WAIT" and j.get("next_attempt_at"):
            return _parse_mark(j["next_attempt_at"])
        marks = [_parse_mark(j.get(k)) for k in ("stage_updated_at", "started_at", "created_at")]
    except _BadMark:
        return None
    marks = [m for m in marks if m is not None]
    return max(marks) if marks else None


def _busy_state(c, job_types: tuple[str, ...] = BUSY_JOB_TYPES) -> dict:
    """{busy, detail, window, jobs, stale_ignored, stale_ignored_total}; never raises, never writes. jobs and
    stale_ignored list at most MAX_LISTED rows. job_types: BUSY_JOB_TYPES here; 1.4.15 lot 2 (settings_advanced_routes)
    passes every job type."""
    win = _blocked_window()
    rows = db.rows(c, f"SELECT id, job_type, status, created_at, started_at, stage_updated_at, next_attempt_at "
                      f"FROM job_runs WHERE job_type IN ({','.join('?' * len(job_types))}) "
                      f"AND status IN ({','.join('?' * len(ACTIVE_STATUSES))}) "
                      "ORDER BY created_at DESC, rowid DESC", (*job_types, *ACTIVE_STATUSES))
    live = {j["job_id"] for j in runner.live_jobs()}
    limit = timedelta(seconds=_stale_seconds(c))
    now = now_utc()
    jobs, stale = [], []
    for r in rows:
        mark = _last_mark(r)
        item = {"id": r["id"], "job_type": r["job_type"], "status": r["status"],
                "last_mark": mark.isoformat() if mark else None}
        if r["id"] not in live and mark is not None and now - mark > limit:
            stale.append(item)
        else:
            jobs.append(item)
    details = ([f"production window {win} (Vietnam)"] if win else []) \
        + [f"{j['job_type']} {j['status']}" for j in jobs[:MAX_LISTED]]
    return {"busy": bool(win or jobs), "detail": ", ".join(details) or None, "window": win, "jobs": jobs[:MAX_LISTED],
            "stale_ignored": stale[:MAX_LISTED], "stale_ignored_total": len(stale)}


def _busy(c) -> dict:
    st = _busy_state(c)
    if st["busy"]:
        raise AppError("DATA_POLICY_BUSY", 409, detail=st["detail"], window=st["window"], jobs=st["jobs"],
                       stale_ignored=st["stale_ignored"], stale_ignored_total=st["stale_ignored_total"])
    return st


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

    def _entry(row: dict, prev: dict) -> dict:
        return {**row, "previous_values": prev,          # values before that row: the undo target
                "changed_fields": [k for k in DATA_POLICY_GUARDED if row["values"][k] != prev[k]]}

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
            out.append(_entry(newer, row["values"]))
            if len(out) >= HISTORY_ROWS:
                return out
        newer = row
    if newer is not None and newer["values"] != defaults:
        out.append(_entry(newer, defaults))
    return out[:HISTORY_ROWS]


def _check_patch(patch: dict) -> None:
    n = len(DATA_POLICY_GUARDED)
    if not patch or len(patch) > n:
        raise AppError("DATA_POLICY_UNKNOWN_FIELD", 422, detail=f"patch needs 1..{n} guarded fields")
    unknown = sorted(k for k in patch if k not in DATA_POLICY_GUARDED)
    if unknown:
        raise AppError("DATA_POLICY_UNKNOWN_FIELD", 422, detail=", ".join(unknown))
    locked = [k for k in DATA_POLICY_GUARDED if k in patch and k in LOCKED]
    if locked:
        raise AppError("DATA_POLICY_FIELD_LOCKED", 422, detail=", ".join(locked), reason_code=LOCKED_REASON_CODE)


def _validated(cur, patch: dict) -> dict:
    """The guarded fields after the patch, validated by the settings model (never looser) + no future window start."""
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


def _coverage_start(window_start: str) -> tuple[bool, str | None, bool]:
    """(applies, coverage_start, failure) for the active scope, as data/demand.data_window computes it: the rule only
    applies to a BIGQUERY scope. The scan runs on its own read connection (closed after it) and is interrupted after
    COVERAGE_TIMEOUT_S by a progress handler: failure = NO_ESTIMATE_TIMEOUT (sqlite3 'interrupted') or NO_ESTIMATE_ERROR
    (any other error), coverage_start None; never blocks the preview. No usable scope: (False, None, None)."""
    try:
        scope = resolve_scope()
    except Exception:  # noqa: BLE001 - no usable scope: the rule changes nothing that can be estimated
        return False, None, None
    if not open_hours.mandatory(scope.get("data_source")):
        return False, None, None
    end = str(today_vn() - timedelta(days=1))
    deadline = time.monotonic() + COVERAGE_TIMEOUT_S
    try:
        with db.read() as c:
            c.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1_000)
            try:
                return True, open_hours.coverage_start(c, scope["scope_key"], window_start, end), None
            finally:
                c.set_progress_handler(None, 0)
    except sqlite3.OperationalError as e:
        return True, None, "NO_ESTIMATE_TIMEOUT" if "interrupted" in str(e).lower() else "NO_ESTIMATE_ERROR"
    except Exception:  # noqa: BLE001 - an estimate only
        return True, None, "NO_ESTIMATE_ERROR"


def _effective(rule: str, window_start: str, applies: bool, cov: str | None, known: bool) -> str | None:
    if rule != "OPEN_HOURS_COVERAGE" or not applies:
        return window_start
    if not known:
        return None
    return cov if cov and cov > window_start else window_start


def _training_start_impact(before: dict, after: dict) -> tuple[dict, list[str]]:
    ws = after["window_start_date"]
    applies, cov, failure = _coverage_start(ws)
    known = failure is None
    cur_eff = _effective(before["training_start_rule"], ws, applies, cov, known)
    new_eff = _effective(after["training_start_rule"], ws, applies, cov, known)
    delta = (date.fromisoformat(new_eff) - date.fromisoformat(cur_eff)).days if cur_eff and new_eff else None
    notes = ["TRAINING_START_CHANGES_MODEL_INPUT"] + ([failure] if failure else [])
    # in effect at the next data_window(scope) read (1.3.1 refresh with the model in use, SEL2 open-hours / actual read
    # floor, data-quality report, feature page), not only at the next training; the SEL2 lightgbm_forecast numbers are
    # not changed (ml/sel2 builds its data without this rule)
    return ({"kind": "TRAINING_START", "window_start_date": ws, "coverage_start": cov, "effective_current": cur_eff,
             "effective_after": new_eff, "delta_days": delta, "applies_from": "NEXT_DATA_WINDOW_READ"}, notes)


def _impact(before: dict, after: dict, changed: list[str]) -> tuple[list[dict], list[str], list[str]]:
    """(impacts, warnings, notes); warnings and notes are codes the UI translates."""
    impacts: list[dict] = []
    warnings: list[str] = []
    notes: list[str] = []
    if "history_change_policy" in changed:
        n, capped = _held_lines_active()
        impacts.append({"kind": "HELD_LINES", "active_held_lines": n, "capped": capped, "applies_from": "NEXT_D1"})
        notes += ["APPLIES_AT_NEXT_D1", "FOLLOW_SOURCE_DROPS_REMOVED_LINES"
                  if after["history_change_policy"] == "FOLLOW_SOURCE" else "KEEP_OBSERVED_LINES_HOLDS_REMOVED_LINES"]
    if "training_start_rule" in changed:
        imp, more = _training_start_impact(before, after)
        impacts.append(imp)
        notes += more
    missing = [k for k in changed if k not in ("history_change_policy", "training_start_rule")]
    if missing:
        warnings.append("NO_IMPACT_ESTIMATE:" + ",".join(missing))
    notes.append("UNDO_SETTINGS_ONLY")
    return impacts, warnings, notes


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
    """Read-only: what the patch would change, never writes. `impact` = the first of `impacts` (one per field with an
    estimate) or null; `busy` = whether an apply would be refused now (DATA_POLICY_BUSY)."""
    _check_patch(body.patch)
    cur = ss.get("data_policy")
    before = _fields(cur)
    after = _validated(cur, body.patch)
    changed = _changed(before, after)
    high = any(k in HIGH_RISK for k in changed)
    impacts, warnings, notes = _impact(before, after, changed)
    if not changed:
        warnings.append("NO_CHANGE")
    with db.read() as c:
        busy = _busy_state(c)
    return {"before": before, "after": after, "changed": changed, "high_risk": high, "needs_confirm_text": high,
            "needs_acknowledged": any(k not in HIGH_RISK for k in changed),
            "impact": impacts[0] if impacts else None, "impacts": impacts, "warnings": warnings, "notes": notes,
            "busy": busy, "confirm_text": _confirm_text()}


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
        busy = _busy(c)     # under the write lock: no D-1 / refresh / training row is added between this check and the save
        cur = ss.get("data_policy", c)
        before = _fields(cur)
        stale = [k for k in body.patch if not _same(body.expected[k], before[k])]
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
                  "version": version,
                  "stale_ignored": [{k: j[k] for k in ("id", "job_type", "status")} for j in busy["stale_ignored"]],
                  "stale_ignored_total": busy["stale_ignored_total"]})
    return {"applied": {k: after[k] for k in changed}, "version": version}
