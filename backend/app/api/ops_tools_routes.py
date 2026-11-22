"""1.4.15 lot 6: two CLI tools behind the UI gates (the CLI itself is unchanged and only read here).

#18 presets (CLI `apply-preset <name> [--apply]`; app/cli.PRESETS, _preset_values: a retention is never lowered, the
preset does not set log_retention_days):
  GET  /api/presets                     the presets, their keys and values, description (vi / en).
  POST /api/presets/{name}/preview      read-only: every key current -> preset, the keys kept higher (only_increase),
                                        the flows the preset switches ON with their readiness (a flow not ready ->
                                        apply refused, with the reasons), `expected_hash` of the current values.
  POST /api/presets/{name}/apply        {expected_hash, confirm_text AP-DUNG-PRESET-<NAME>-<today, Vietnam>, reason >= 10,
                                        confirm_purchase DOI-CAI-DAT-ANH-HUONG-MUA-HANG-<day> when a PURCHASE key
                                        changes (preview: needs_purchase_confirm, purchase_keys)}; the flow readiness
                                        is checked again inside the write transaction; a flow switch that fails after
                                        the commit -> partial = true + flow_errors (audit PRESET_FLOWS_RESULT), never a
                                        500. An undo of the settings never turns the flows off (undo_warning).
                                        refused when a flow is not ready (PRESET_FLOW_NOT_READY) - checked before any
                                        write -; ONE db.tx: busy gate (data_policy_routes._busy_state over every job
                                        type), current values compared with expected_hash (SETTINGS_CHANGED_ELSEWHERE),
                                        one settings-history row per changed section, the audit PRESET_APPLIED (as the
                                        CLI) and, for the keys the settings registry can edit, an audit row in the
                                        format of settings_advanced_routes (SETTINGS_ADVANCED_APPLIED): the existing
                                        "Undo" of the Advanced settings page puts those keys back. Not undoable there
                                        (listed in `not_undoable`): a READONLY key (daily_forecast.rounding_threshold,
                                        fixed rule - the preset value is the rule's) and the flow switches (own path:
                                        the Schedules page). The flows are switched ON after the commit through
                                        flows.update_flow, exactly as the CLI (a flow refused there is reported).
#17 spike lines (CLI `spike-lines --date D [--initial [--reflag]] --dry-run`):
  POST /api/spike-lines/estimate        {date | today, initial, reflag}: spike_lines.run(dry_run=True) only - the BigQuery
                                        DRY RUN of the line read (estimated bytes, cap = bigquery.maximum_bytes_billed;
                                        a dry run cannot count rows: no row count), nothing written. --initial on a
                                        scope that already has flags needs reflag (SPIKE_LINES_REFLAG_REQUIRED), as the
                                        real run. The real run stays with the runner / CLI (`spike-lines --yes`).
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from .. import cli, db
from .. import settings_registry as reg
from .. import settings_service as ss
from ..jobs import flows, runner
from ..messages import AppError, msg
from ..timeutil import today_vn
from . import held_lines_routes as hl
from . import settings_advanced_routes as sa
from .data_policy_routes import REASON_MAX, REASON_MIN, _busy_state

router = APIRouter(prefix="/api")
log = logging.getLogger("df.ops_tools")

PRESET_DESCRIPTIONS = {"lgbm-chot": ("PRESET_LGBM_CHOT_DESC", "PRESET_NO_LOG_RETENTION", "PRESET_UNDO_PATH")}
SPIKE_DESCRIPTION = ("SPIKE_ESTIMATE_ONLY",)


# ------------------------------------------------------------------ presets
def _preset(name: str) -> dict:
    p = cli.PRESETS.get(name)
    if p is None:
        raise AppError("PRESET_UNKNOWN", 404, detail=name, known=sorted(cli.PRESETS))
    return p


def _confirm_text(name: str) -> str:
    return f"AP-DUNG-PRESET-{name.upper()}-{today_vn().isoformat()}"


def _current(c, preset: dict) -> dict:
    return {s: ss.get(s, c) for s in preset["sections"]}


def _hash(preset: dict, cur: dict, c) -> str:
    vals = {s: {k: getattr(cur[s], k) for k in keys} for s, keys in preset["sections"].items()}
    sched = ss.get("schedule", c)
    fl = {f: bool(getattr(sched, flows.FLOWS[f]["flag"])) for f in preset["flows"]}
    return hashlib.sha256(json.dumps({"values": vals, "flows": fl}, sort_keys=True, default=str).encode()).hexdigest()


def _plan(preset: dict, cur: dict) -> dict:
    vals_of, kept = cli._preset_values(preset, cur)
    changes = []
    for s, vals in vals_of.items():
        for k, v in vals.items():
            if getattr(cur[s], k) != v:
                e = reg.entry(s, k)
                changes.append({"section": s, "key": k, "from": getattr(cur[s], k), "to": v,
                                "risk": reg.risk(e) if e else None, "undoable": bool(e and reg.editable(e))})
    new = {s: {**cur[s].model_dump(), **vals} for s, vals in vals_of.items()}
    try:
        for s, v in new.items():
            ss.SECTIONS[s].model_validate(v)         # nothing is saved unless every section is valid
    except ValueError as e:
        raise AppError("PRESET_INVALID", 422, detail=f"{type(e).__name__}: {e}"[:800]) from None
    sched = ss.get("schedule")
    fl = []
    for f in preset["flows"]:
        on = bool(getattr(sched, flows.FLOWS[f]["flag"]))
        # the preset switches daily_forecast ON before its flows: that reason goes away with it (as the CLI)
        reasons = [] if on else [x for x in flows.readiness(f)["reasons"] if not (
            x.get("code") == "DAILY_FORECAST_DISABLED" and new.get("daily_forecast", {}).get("enabled"))]
        fl.append({"flow": f, "from": on, "to": True, "ready": not reasons, "reasons": cli._codes(reasons)})
    return {"changes": changes, "kept_higher": kept, "flows": fl, "new": new,
            "changed": bool(changes or any(not x["from"] for x in fl))}


def _purchase_keys(plan: dict) -> list[str]:
    return [f"{x['section']}.{x['key']}" for x in plan["changes"] if x["risk"] == "PURCHASE"]


def _public(name: str, plan: dict, h: str) -> dict:
    return {"preset": name, "changes": plan["changes"], "kept_higher": plan["kept_higher"], "flows": plan["flows"],
            "changed": plan["changed"], "ready": all(x["ready"] for x in plan["flows"]), "expected_hash": h,
            "confirm_text": _confirm_text(name), "reason_min_length": REASON_MIN,
            "needs_purchase_confirm": bool(_purchase_keys(plan)), "purchase_keys": _purchase_keys(plan),
            "confirm_purchase": sa._confirm_texts()["PURCHASE"], "undo_warning": msg("PRESET_UNDO_SETTINGS_ONLY"),
            "not_undoable": [f"{x['section']}.{x['key']}" for x in plan["changes"] if not x["undoable"]]
            + [f"flow {x['flow']}" for x in plan["flows"] if not x["from"]],
            "description": [msg(c) for c in PRESET_DESCRIPTIONS.get(name, ())]}


@router.get("/presets")
def presets():
    return {"presets": [{"name": n, "sections": p["sections"], "flows": list(p["flows"]),
                         "confirm_text": _confirm_text(n), "description": [msg(c) for c in PRESET_DESCRIPTIONS.get(n, ())]}
                        for n, p in sorted(cli.PRESETS.items())]}


@router.post("/presets/{name}/preview")
def preset_preview(name: str):
    """Read-only."""
    preset = _preset(name)
    with db.read() as c:
        cur = _current(c, preset)
        h = _hash(preset, cur, c)
        busy = _busy_state(c, runner.JOB_TYPES)
        soon = hl._soon(c)
    return {**_public(name, _plan(preset, cur), h), "busy": busy, "window_soon": soon["window_soon"],
            "schedule_times": soon["schedule_times"], "ops_lock_checked": hl.ops_lock_checked(),
            "ops_lock_source": hl.ops_lock_source(),
            "ops_locks": hl.ops_locks()}


class PresetApplyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_hash: str
    confirm_text: str | None = None
    confirm_purchase: str | None = None
    reason: str | None = None


@router.post("/presets/{name}/apply")
def preset_apply(name: str, body: PresetApplyBody):
    preset = _preset(name)
    reason = " ".join((body.reason or "").split())
    if len(reason) > REASON_MAX:
        raise AppError("PRESET_CONFIRM_REQUIRED", 422, detail=f"reason longer than {REASON_MAX} characters")
    want = _confirm_text(name)
    if (body.confirm_text or "").strip() != want or len(reason) < REASON_MIN:
        raise AppError("PRESET_CONFIRM_REQUIRED", 409, detail=f"type {want} and a reason of at least {REASON_MIN} "
                       "characters", confirm_text=want, reason_min_length=REASON_MIN)
    with db.read() as c:
        plan = _plan(preset, _current(c, preset))
    not_ready = [x for x in plan["flows"] if not x["ready"]]
    if not_ready:
        raise AppError("PRESET_FLOW_NOT_READY", 409, detail=", ".join(x["flow"] for x in not_ready), flows=not_ready)
    audit_id = None
    with db.tx() as c:
        hl.check_ops_locks()                    # OPERATIONS_LOCK_HELD, as the other write buttons
        busy = _busy_state(c, runner.JOB_TYPES)
        soon = hl._soon(c)
        win = None if busy["window"] else soon["window_soon"]
        if busy["busy"] or win or soon["schedule_times"]:
            detail = ", ".join(x for x in (
                busy["detail"], f"production window {win} (Vietnam) starts in {hl.START_MARGIN_MIN} minutes or less"
                if win else None,
                *(f"{x['setting']} {x['time']} (Vietnam) within -{hl.SCHEDULE_BEHIND_MIN}..+{hl.SCHEDULE_AHEAD_MIN} "
                  "minutes" for x in soon["schedule_times"])) if x)
            raise AppError("PRESET_BUSY", 409, detail=detail, window=busy["window"], window_soon=win,
                           schedule_times=soon["schedule_times"], jobs=busy["jobs"],
                           stale_ignored=busy["stale_ignored"], stale_ignored_total=busy["stale_ignored_total"])
        cur = _current(c, preset)
        if _hash(preset, cur, c) != body.expected_hash:
            raise AppError("SETTINGS_CHANGED_ELSEWHERE", 409, detail=f"preset {name}: the current values changed since "
                           "the preview")
        plan = _plan(preset, cur)
        if not plan["changed"]:
            raise AppError("NO_CHANGE", 400, detail=f"preset {name} is already applied")
        not_ready = [x for x in plan["flows"] if not x["ready"]]       # checked again under the write lock
        if not_ready:
            raise AppError("PRESET_FLOW_NOT_READY", 409, detail=", ".join(x["flow"] for x in not_ready),
                           flows=not_ready)
        purchase = _purchase_keys(plan)
        want_p = sa._confirm_texts()["PURCHASE"]
        if purchase and (body.confirm_purchase or "").strip() != want_p:
            raise AppError("PRESET_PURCHASE_CONFIRM_REQUIRED", 409, detail=f"type {want_p}: {', '.join(purchase)}",
                           confirm_purchase=want_p, purchase_keys=purchase)
        changes = plan["changes"]
        sections = sorted({x["section"] for x in changes})
        before = sa._versions(c, sections)
        for s in sections:
            note = f"{cli.PRESET_NOTE} OWNER_CONFIRMED " + "; ".join(
                f"{x['key']} {sa._fmt(x['from'])} -> {sa._fmt(x['to'])}" for x in changes if x["section"] == s)
            ss.save(s, plan["new"][s], note=f"{note}: {reason}", conn=c)
        versions = sa._versions(c, sections)
        db.audit(c, "PRESET_APPLIED", "settings", name,
                 {"changes": [{k: x[k] for k in ("section", "key", "from", "to")} for x in changes],
                  "kept_higher": plan["kept_higher"], "flows": [x["flow"] for x in plan["flows"] if not x["from"]],
                  "reason": reason, "versions_before": before, "versions": versions})
        undoable = [x for x in changes if x["undoable"]]
        if undoable:
            audit_id = sa._audit(c, "SETTINGS_ADVANCED_APPLIED", ",".join(sorted({x["section"] for x in undoable})),
                                 {"changes": [{k: x[k] for k in ("section", "key", "risk", "from", "to")}
                                              for x in undoable],
                                  "reason": reason, "risk": reg.risk_max(x["risk"] for x in undoable),
                                  "versions_before": before, "versions": versions, "source": f"preset {name}",
                                  "undo_warning": "PRESET_UNDO_SETTINGS_ONLY", **sa._stale(busy)})
    res, flow_errors = [], []
    for x in plan["flows"]:          # after the commit, as the CLI: update_flow has its own transaction
        if x["from"]:
            res.append({**x, "to": True})
            continue
        try:
            flows.update_flow(x["flow"], {"enabled": True})
            res.append({**x, "to": True})
        except AppError as e:
            res.append({**x, "to": False, "ready": False,
                        "reasons": cli._codes(e.params.get("reasons") or [{"code": e.code, "detail": e.detail}])})
            flow_errors.append({"flow": x["flow"], "code": e.code, "detail": e.detail})
        except Exception as e:  # noqa: BLE001 - the settings are committed: reported, never a 500
            log.error("preset flow switch failed", exc_info=True, extra={"ctx": {"preset": name, "flow": x["flow"]}})
            res.append({**x, "to": False, "ready": False, "reasons": []})
            flow_errors.append({"flow": x["flow"], "code": "PRESET_FLOW_SWITCH_FAILED",
                                "detail": f"{type(e).__name__}: {e}"[:300]})
    try:
        with db.tx() as c:
            db.audit(c, "PRESET_FLOWS_RESULT", "settings", name,
                     {"flows": [{k: x.get(k) for k in ("flow", "from", "to")} for x in res], "errors": flow_errors})
    except Exception:  # noqa: BLE001 - the answer still reports the flows
        log.error("preset flows result not audited", exc_info=True, extra={"ctx": {"preset": name}})
    return {"preset": name, "applied": [{k: x[k] for k in ("section", "key", "from", "to")} for x in plan["changes"]],
            "partial": bool(flow_errors), "flow_errors": flow_errors,
            "warnings": ["PRESET_FLOWS_NOT_ALL_ON"] if flow_errors else [],
            "undo_warning": msg("PRESET_UNDO_SETTINGS_ONLY"),
            "kept_higher": plan["kept_higher"], "flows": res, "undo_audit_id": audit_id,
            "not_undoable": [f"{x['section']}.{x['key']}" for x in plan["changes"] if not x["undoable"]]
            + [f"flow {x['flow']}" for x in res if not x["from"] and x["to"]]}


# ------------------------------------------------------------------ spike lines: estimate only
class SpikeEstimateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: str | None = None
    initial: bool = False
    reflag: bool = False


def _has_flags(scope_key: str) -> bool:
    with db.read() as c:
        return c.execute("SELECT 1 FROM spike_flag_lines WHERE scope_key=? LIMIT 1", (scope_key,)).fetchone() is not None


@router.post("/spike-lines/estimate")
def spike_estimate(body: SpikeEstimateBody):
    """The BigQuery dry run of the SO-line read only (spike_lines.run(dry_run=True)); never reads rows, never writes."""
    from .. import spike_lines
    try:
        d = date.fromisoformat(body.date) if body.date else today_vn()
    except ValueError:
        raise AppError("SPIKE_ESTIMATE_INVALID_DATE", 422, detail="date must be YYYY-MM-DD") from None
    if body.initial and not body.reflag and _has_flags(spike_lines._scope_key()):
        raise AppError("SPIKE_LINES_REFLAG_REQUIRED", 409, detail="the scope already has spike flags: initial needs "
                       "reflag (as the real run)")
    res = spike_lines.run(d, initial=body.initial, dry_run=True, reflag=body.reflag)
    return {**res, "rows_estimated": None, "description": [msg(c) for c in SPIKE_DESCRIPTION],
            "run_with": "runner / CLI: spike-lines --date D [--initial --reflag] --yes"}
