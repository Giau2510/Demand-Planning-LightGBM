"""1.3.1 daily forecast refresh, B3-B8 (docs/ke_hoach_lgbm_chot.md 1-3, 6.3).

For forecast day D (Vietnam): the model IN USE (pipeline.incumbent; never trained, never replaced here) forecasts the
horizon H = refresh_horizon() from a panel of the data window ending at D-1, with the category codes saved in its model
json and its OWN stored configuration (features, fallback rules). The published quantity of every value is
published_qty() (B3: 0 below daily_forecast.rounding_threshold, otherwise rounded up); the raw LightGBM value (float)
is kept with it. The result is ONE forecast_refresh_runs record + its forecast_refresh_values (one transaction, with
the group A / B / C of each series, report only). Then actual_daily is refreshed for D-14..D-1 and the log retention
runs. Nothing is written to forecast_runs / forecast_values / training_runs and no setting is changed: every number of
the 1.2.14 screens and exports stays as it is. Every row carries the active data scope (scope_key) or the source table
+ seller of its BigQuery read; reads filter by them.

run() returns {status: PUBLISHED | NOT_READY | SKIPPED | FAILED, reason_code, ...}. SKIPPED DAILY_FORECAST_DISABLED =
daily_forecast.enabled is False (nothing read or written). NOT_READY = an input of D is not there yet (D-1 load, model
in use, data up to D-1, open hours of the demand); the scheduler retries it until refresh_deadline. The open-hours read
from BigQuery (B6) never blocks the forecast: an error is recorded in the run detail + ONE WARNING alert per day. A
failure of the actual_daily step or of the retention after the run is published leaves the result PUBLISHED (error in
the result + a WARNING alert); the next refresh does both again.
compute() is the pure part (model, codes, panel, groups injected): a reproduction runs it with any model.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timedelta

import numpy as np

from .. import db, paths
from .. import settings_service as ss
from ..bq import aux_sources
from ..bq.aux_sources import NotReady
from ..data import open_hours, open_hours_override
from ..data.demand import data_window, load_demand, resolve_scope
from ..messages import AppError
from ..timeutil import VN_TZ, now_iso, now_vn, today_vn
from . import extra_features, model, pipeline, sku_group
from .features import build_panel, feature_names, is_direct

log = logging.getLogger("df.refresh")
# open hours: read again from (last day of the last COMPLETED read - OPEN_HOURS_REREAD_DAYS) to D-1 (late corrections
# of the source); the whole group window (sku_group.WINDOW_DAYS + OPEN_HOURS_REREAD_DAYS days, clipped to the data
# window) while no completed read reaches inside it (first refresh, after a long pause, or every read failed midway)
OPEN_HOURS_REREAD_DAYS = 3
# a longer range is read as consecutive sub-ranges of at most this many days, oldest first, each one its own completed
# read (an interrupted FULL read goes on INCREMENTALLY from its last completed sub-range)
OPEN_HOURS_READ_DAYS = 15
ACTUAL_DAYS = 14                # actual_daily refreshed for D-14 .. D-1
SHORT_DAYS = 7                  # B4: H is at least this; B8: the days kept of a run a later run superseded
ACTUAL_DAILY_ALERT = "DAILY_ACTUAL_FAILED"
OPEN_HOURS_ALERT = "OPEN_HOURS_READ_FAILED"
RETENTION_ALERT = "DAILY_RETENTION_FAILED"
FAILED_CODE = "FORECAST_REFRESH_FAILED"
SOURCE_NOT_REFRESHED = "OPEN_HOURS_SOURCE_NOT_REFRESHED"
FLAG_CODE_UNKNOWN = "CODE_UNKNOWN"   # a model input code (SKU / FC) not in the model's saved category codes
FLAG_GROUP_MISSING = "GROUP_MISSING"  # no group A / B / C for the series


# ------------------------------------------------------------------ pure part
def published_qty(values, threshold: float) -> np.ndarray:
    """B3 published quantity (int64, same shape): v = values rounded to 6 decimals; 0 where v < threshold, ceil(v)
    elsewhere. A missing (NaN) or infinite value is refused (ValueError), never published as a number."""
    a = np.asarray(values, dtype=float)
    if not np.isfinite(a).all():
        raise ValueError("published_qty: missing or infinite value")
    v = np.round(a, 6)
    return np.where(v < threshold, 0.0, np.ceil(v)).astype(np.int64)


def refresh_horizon(enabled, mcfg) -> int:
    """B4: H = max(7, max(horizons.enabled)), never more than the horizons a DIRECT model was trained for."""
    h = max(SHORT_DAYS, max(enabled, default=SHORT_DAYS))
    if is_direct(mcfg):
        h = min(h, model.direct_max_horizon(mcfg))
    return int(h)


def config_version(model_fingerprint: str | None, threshold: float, horizon: int) -> str:
    """Short hash of what decides the published numbers of a run besides the data: the model configuration
    fingerprint, the rounding threshold and the horizon."""
    return hashlib.sha256(json.dumps({"model_fingerprint": model_fingerprint, "rounding_threshold": float(threshold),
                                      "horizon": int(horizon)}, sort_keys=True).encode()).hexdigest()[:12]


def compute(panel, booster, mcfg, horizon: int, d: date, *, sku_codes: dict | None, fc_codes: dict | None,
            groups: dict, threshold: float, baseline: bool = False, cancel=None, deal_active=None) -> dict:
    """Forecast of every series of `panel` for the `horizon` days starting at d (= the day after the panel).

    booster / sku_codes / fc_codes: the model and the category codes saved with it (never the panel's own codes);
    baseline: the model in use published the 28-day baseline (no booster). groups: {(fc_code, sku_code): group code}.
    Returns keys [(fc_code, sku_code)], dates [ISO], raw (S x H float, the model output), final (S x H int64,
    published_qty(raw, threshold)), methods, groups (code or None), flags (per series, comma-separated or None).
    1.3.2: deal_active = S x H 0 / 1 of the deal table per series and target day (extra_features.deal_active_matrix),
    returned as given (None = deals not configured: stored NULL). No DB, no network."""
    if str(panel.dates[-1].date()) != str(d - timedelta(days=1)):
        raise ValueError(f"panel ends {panel.dates[-1].date()}, expected {d - timedelta(days=1)}")
    if deal_active is not None:
        deal_active = np.asarray(deal_active, dtype=np.int8)
        if deal_active.shape != (panel.n_series, horizon):
            raise ValueError(f"deal_active {deal_active.shape}, expected {(panel.n_series, horizon)}")
    if baseline:
        fc = model.baseline_run(panel, horizon)
    else:
        fc = model.forecast(panel, booster, mcfg, horizon, cancel, sku_codes=sku_codes, fc_codes=fc_codes)
    raw = np.asarray(fc["yhat"], dtype=float)
    final = published_qty(raw, threshold)
    keys = [(fcid, sku) for sku, fcid in panel.keys]            # (fc_code, sku_code) = demand_daily (fc_id, sku_id)
    g = np.array([groups.get(k) for k in keys], dtype=object)
    names = set(feature_names(mcfg))
    check_sku = not baseline and "sku_code" in names
    check_fc = not baseline and "fc_code" in names
    flags = []
    for (fcid, sku), grp in zip(keys, g):
        f = []
        if (check_sku and sku not in (sku_codes or {})) or (check_fc and fcid not in (fc_codes or {})):
            f.append(FLAG_CODE_UNKNOWN)
        if grp is None:
            f.append(FLAG_GROUP_MISSING)
        flags.append(",".join(f) or None)
    return {"keys": keys, "dates": [str(x.date()) for x in fc["dates"]], "raw": raw, "final": final,
            "methods": np.asarray(fc["methods"], dtype=object), "groups": g, "flags": flags,
            "unknown_codes": sum(1 for f in flags if f and FLAG_CODE_UNKNOWN in f), "deal_active": deal_active}


# ------------------------------------------------------------------ model in use + panel
def _vn_moment(d: date) -> datetime:
    """'Now' as seen from business day d: the real time on d, the end of d for another day (reproductions)."""
    now = now_vn()
    return now if now.date() == d else datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=VN_TZ)


def _model_in_use(c, scope: dict) -> dict:
    inc = pipeline.incumbent(scope["scope_key"], c)
    if not inc:
        raise NotReady("NO_MODEL_IN_USE", f"no published forecast for {scope['scope_key']}")
    return inc


def _load_model(tr: dict, baseline: bool):
    """(booster, sku_codes, fc_codes) loaded exactly like promote_candidate: refused when the file is missing or its
    sha256 differs from the training run; the codes come from the model json saved with it (never guessed)."""
    if baseline:
        return None, None, None
    mpath = paths.models_dir() / (tr.get("model_path") or "")
    if not tr.get("model_path") or not mpath.exists() \
            or hashlib.sha256(mpath.read_bytes()).hexdigest() != tr.get("model_sha256"):
        raise AppError("MODEL_FILE_MISMATCH", 409, detail=f"{tr.get('model_path')} missing or modified")
    meta_path = mpath.with_suffix(".json")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        sku_codes, fc_codes = meta["sku_codes"], meta["fc_codes"]
    except (OSError, ValueError, KeyError) as e:
        raise AppError("MODEL_FILE_MISMATCH", 409, detail=f"{meta_path.name}: category codes unavailable "
                                                          f"({type(e).__name__})") from e
    if not isinstance(sku_codes, dict) or not isinstance(fc_codes, dict) or not sku_codes or not fc_codes:
        raise AppError("MODEL_FILE_MISMATCH", 409, detail=f"{meta_path.name}: category codes unavailable")
    import lightgbm as lgb
    return lgb.Booster(model_file=str(mpath)), sku_codes, fc_codes


def build_refresh_panel(scope: dict, d: date, mcfg):
    """The panel of the data window ending at d-1, built the way the training builds it (open-hours check and the
    owner's override, load_demand, build_panel with the model's max_train_days). NotReady when the data does not reach
    d-1 or an open hours value the model needs is missing."""
    with db.read() as c:
        window = data_window(c, today=d, scope=scope)
        oh_ovr = (open_hours_override.resolve(c, scope["scope_key"], window["start"], window["end"])
                  if open_hours.mandatory(scope["data_source"]) else None)
        oh_chk = (open_hours.window_check(c, scope["scope_key"], window["start"], window["end"],
                                          overrides=oh_ovr["applied"]) if oh_ovr is not None else None)
    if oh_chk is not None and oh_chk["not_ok"]:
        raise NotReady("OPEN_HOURS_INVALID", open_hours.blocking_detail(oh_chk))
    demand = load_demand(scope["scope_key"], start=window["start"], end=window["end"])
    if demand.empty:
        raise NotReady("DATA_NOT_UP_TO_DATE", f"no demand row in {window['start']}..{window['end']}")
    problems = []
    if oh_ovr and oh_ovr["applied"]:
        demand, problems = open_hours_override.fill(demand, oh_ovr["applied"])
    if getattr(mcfg, "feature_open_hours", None) and (problems or demand["open_hours"].isna().any()):
        raise NotReady("OPEN_HOURS_INVALID", f"{int(demand['open_hours'].isna().sum())} demand row(s) without open hours")
    panel = build_panel(demand, max_days=mcfg.max_train_days)
    del demand
    if str(panel.dates[-1].date()) != str(d - timedelta(days=1)):
        raise NotReady("DATA_NOT_UP_TO_DATE", f"last demand day {panel.dates[-1].date()}, expected "
                                              f"{d - timedelta(days=1)}", last_day=str(panel.dates[-1].date()))
    # 1.3.2: the extra features of the model's own feature set, data up to d-1; only the origin d is computed (CHOT:
    # nothing). The same input checks as the training (history and deal lines loaded for every day read, a missing day
    # is never 0): not there yet -> NotReady with the uncovered days (retried until the deadline); the checks are kept
    # in the run detail (extra_features.sources)
    chk = None
    if extra_features.extra_names(mcfg):
        try:
            with db.read() as c:
                chk = extra_features.check_sources(c, mcfg, scope["scope_key"], d - timedelta(days=1),
                                                   window_start=window["configured_start"], first_origin=d)
        except AppError as e:
            raise NotReady(e.code, e.detail or "") from e
    extra_features.attach(panel, scope["scope_key"], mcfg, first_origin=d, sources=chk)
    return panel, window


# ------------------------------------------------------------------ the refresh
def run(business_date=None, job_id: str | None = None, cancel=None, progress=None, trigger: str = "SCHEDULE") -> dict:
    d = aux_sources._day(business_date) if business_date else today_vn()
    stage = progress or (lambda *a, **k: None)
    cfg = ss.get("daily_forecast")
    if not cfg.enabled:
        return {"status": "SKIPPED", "reason_code": "DAILY_FORECAST_DISABLED", "business_date": str(d)}
    try:
        return _refresh(d, cfg, job_id, cancel, stage, trigger)
    except NotReady as e:
        log.info("forecast refresh not ready", extra={"ctx": {"business_date": str(d), "code": e.code,
                                                              "detail": (e.detail or "")[:300]}})
        return {"status": "NOT_READY", "reason_code": e.code, "detail": e.detail, "business_date": str(d), **e.params}
    except model.Cancelled:
        raise
    except Exception as e:  # noqa: BLE001 - reported as a failed attempt (retried by the schedule until the deadline)
        code = e.code if isinstance(e, AppError) else FAILED_CODE
        detail = (e.detail if isinstance(e, AppError) else None) or f"{type(e).__name__}: {e}"
        log.exception("forecast refresh failed", extra={"ctx": {"business_date": str(d), "code": code}})
        return {"status": "FAILED", "reason_code": code, "error": detail[:2000], "business_date": str(d)}


def _refresh(d: date, cfg, job_id, cancel, stage, trigger) -> dict:
    stage("VALIDATING_DATA")
    from ..jobs import flows
    with db.read() as c:
        scope = resolve_scope(c)
        # a scheduled attempt never publishes a second run of the day (a MANUAL run does: the owner's explicit choice)
        done = None if trigger == "MANUAL" else db.one(
            c, "SELECT id FROM forecast_refresh_runs WHERE scope_key=? AND forecast_date=? AND status='PUBLISHED' "
               "ORDER BY created_at DESC, rowid DESC LIMIT 1", (scope["scope_key"], str(d)))
        if done:
            return {"status": "SKIPPED", "reason_code": "ALREADY_PUBLISHED", "business_date": str(d),
                    "refresh_run_id": done["id"]}
        if scope["data_source"] != "BIGQUERY":
            raise NotReady("NOT_APPLICABLE_FOR_SOURCE", f"active source {scope['data_source']}")
        d1 = flows.d1_success_today(c, _vn_moment(d))
        if not d1:
            raise NotReady("REFRESH_WAITS_FOR_D1", f"no successful D-1 load of {d} ending {d - timedelta(days=1)}")
        inc = _model_in_use(c, scope)
        hcfg = ss.get("horizons", c)
    fr, tr = inc["forecast_run"], inc["training_run"]
    baseline = pipeline.is_baseline_run(fr)
    fcj = json.loads(tr.get("feature_config_json") or "{}")
    # the model's OWN configuration (features, fallback rules, strategy), never today's settings
    mcfg = ss.ModelSettings.model_validate(fcj["config"])
    horizon = refresh_horizon(hcfg.enabled, mcfg)

    # the model file + codes can refuse first; then the BigQuery read, BEFORE the panel is built (a FULL read never
    # runs while the panel is held in memory)
    stage("VERIFYING_MODEL")
    booster, sku_codes, fc_codes = _load_model(tr, baseline)
    stage("SYNCING")
    sk = scope["scope_key"]
    oh_source = aux_sources.open_hours_source(cfg)
    with db.read() as c:
        oh_floor = data_window(c, today=d, scope=scope)["start"]
    oh = sync_open_hours(d, oh_floor, cfg)
    if cancel and cancel():
        raise model.Cancelled()
    stage("PREPARING_DATA")
    panel, window = build_refresh_panel(scope, d, mcfg)
    if cancel and cancel():
        raise model.Cancelled()
    grp = sku_group.ensure_groups(d, sk, window["start"], oh_source)
    # 1.3.2: output column deal_active (a valid deal of the deal table covers the target day; None = not configured)
    with db.read() as c:
        deal_active, deal_src = extra_features.deal_active_matrix(
            c, panel.keys, [d + timedelta(days=h) for h in range(horizon)])
    stage("FORECASTING")
    res = compute(panel, booster, mcfg, horizon, d, sku_codes=sku_codes, fc_codes=fc_codes, groups=grp["groups"],
                  threshold=cfg.rounding_threshold, baseline=baseline, cancel=cancel, deal_active=deal_active)
    if cancel and cancel():
        raise model.Cancelled()

    stage("PUBLISHING")
    fingerprint = fcj.get("config_fingerprint")
    cv = config_version(fingerprint, cfg.rounding_threshold, horizon)
    run_id = db.new_id("FRR")
    detail = _detail(res, panel, window, grp, oh, d1, baseline, horizon, cfg, deal_src)
    n, n_lgb = _persist(run_id, d, res, grp, inc, cv, fingerprint, cfg, horizon, job_id, trigger, detail, scope_key=sk)
    log.info("daily forecast published", extra={"ctx": {"run_id": run_id, "business_date": str(d), "rows": n,
                                                         "model_version": fr["model_version"]}})
    out = {"status": "PUBLISHED", "reason_code": "DAILY_FORECAST_PUBLISHED", "refresh_run_id": run_id,
           "business_date": str(d), "rows": n, "n_series": len(res["keys"]), "n_fallback": len(res["keys"]) - n_lgb,
           "horizon": horizon, "model_version": fr["model_version"], "training_run_id": tr["id"],
           "config_version": cv, "open_hours": detail["open_hours_read"]}
    # the run is published: a failure of a later step never turns it into a failed refresh (done again next refresh)
    try:
        out["actual_daily_rows"] = refresh_actual_daily(sk, d - timedelta(days=ACTUAL_DAYS), d - timedelta(days=1),
                                                        oh_source, floor=window["start"])
    except Exception as e:  # noqa: BLE001 - reported with the published result + one WARNING alert
        out["actual_daily_rows"] = None
        out["actual_daily_error"] = f"{type(e).__name__}: {e}"[:500]
        log.exception("daily actual refresh failed", extra={"ctx": {"run_id": run_id, "business_date": str(d)}})
        _warn(ACTUAL_DAILY_ALERT, {"business_date": str(d), "run_id": run_id, "error": out["actual_daily_error"]},
              "forecast_refresh_run", run_id)
    try:
        out["retention"] = apply_retention(sk, d, cfg.log_retention_days)
    except Exception as e:  # noqa: BLE001 - reported with the published result + one WARNING alert
        out["retention"] = None
        out["retention_error"] = f"{type(e).__name__}: {e}"[:500]
        log.exception("daily forecast log retention failed", extra={"ctx": {"run_id": run_id, "business_date": str(d)}})
        _warn(RETENTION_ALERT, {"business_date": str(d), "run_id": run_id, "error": out["retention_error"]},
              "forecast_refresh_run", run_id)
    return out


def _warn(code: str, params: dict, entity_type: str, entity_id: str, once: bool = False) -> None:
    """One WARNING alert (best effort; with once=True not repeated for the same entity)."""
    try:
        with db.tx() as c:
            if once and c.execute("SELECT 1 FROM alerts WHERE code=? AND entity_type=? AND entity_id=? LIMIT 1",
                                  (code, entity_type, entity_id)).fetchone():
                return
            db.alert(c, "WARNING", code, params, entity_type, entity_id)
    except Exception:  # noqa: BLE001 - the alert is best effort; the error stays in the job result
        log.warning("alert not written", exc_info=True, extra={"ctx": {"code": code}})


def open_hours_range(d: date, floor=None, cfg=None) -> tuple[date, date, str]:
    """(start, end, mode) of the open-hours read of forecast day d: INCREMENTAL = (last day of the last COMPLETED read
    of the configured table / seller, at most D-1, - OPEN_HOURS_REREAD_DAYS) .. D-1; FULL = the group window +
    OPEN_HOURS_REREAD_DAYS days (start clipped to `floor`, the data window start) .. D-1, when no completed read reaches
    inside it (a sub-range read that failed midway records nothing: the next attempt starts from the last completed
    sub-range, or reads the full range again when none completed)."""
    end = d - timedelta(days=1)
    full_start = d - timedelta(days=sku_group.WINDOW_DAYS + OPEN_HOURS_REREAD_DAYS)
    if floor:
        full_start = max(full_start, date.fromisoformat(str(floor)[:10]))
    with db.read() as c:
        done = aux_sources.last_completed_read(c, aux_sources.KIND_OPEN_HOURS, *aux_sources.open_hours_source(cfg))
    last = done["last_day"] if done else None
    if last is None or last < str(full_start):
        return full_start, end, "FULL"
    base = min(date.fromisoformat(last), end)
    return max(base - timedelta(days=OPEN_HOURS_REREAD_DAYS), full_start), end, "INCREMENTAL"


def sync_open_hours(d: date, floor=None, cfg=None) -> dict:
    """B6, never blocking: read the open hours of open_hours_range() when the source table changed since the last
    completed read (its last-modified time differs, or either value is unknown, or the stored reads do not reach the
    FULL range, or the last completed read ends before D-2: an interrupted read); otherwise nothing is read (skipped =
    OPEN_HOURS_SOURCE_NOT_REFRESHED). The range is read as sub-ranges of at most OPEN_HOURS_READ_DAYS days (aligned on
    D-1), oldest first, each one fetch_open_hours call (own dry run + cap,
    recorded as its own completed read with source_modified); rows / kept_on_conflict are summed, last_day is the one of
    the last sub-range. A failing sub-range stops the loop (the earlier ones stay recorded): the error is returned in the
    result with ONE WARNING alert OPEN_HOURS_READ_FAILED per forecast day."""
    cfg = cfg or ss.get("daily_forecast")
    start, end, mode = open_hours_range(d, floor, cfg)
    out = {"start": str(start), "end": str(end), "mode": mode, "rows": 0}
    try:
        modified = aux_sources.source_modified(cfg)
        with db.read() as c:
            done = aux_sources.last_completed_read(c, aux_sources.KIND_OPEN_HOURS, *aux_sources.open_hours_source(cfg))
        seen = done.get("source_modified") if done else None
        # a last completed read ending before D-2 (an interrupted read, or none since yesterday's) is read again
        whole = done is not None and str(done.get("range_end")) >= str(end - timedelta(days=1))
        if mode == "INCREMENTAL" and modified is not None and seen is not None and modified == seen and whole:
            return {**out, "skipped": SOURCE_NOT_REFRESHED, "source_modified": modified,
                    "last_day": done.get("last_day")}
        out.update(kept_on_conflict=0, estimated_bytes=0, last_day=None, source_modified=modified, reads=0)
        subs, e = [], end           # aligned on D-1: only the OLDEST sub-range can be shorter
        while e >= start:
            subs.append((max(e - timedelta(days=OPEN_HOURS_READ_DAYS - 1), start), e))
            e = subs[-1][0] - timedelta(days=1)
        for s, e in reversed(subs):
            # the last day read by the earlier sub-ranges stays the watermark of an empty one
            r = aux_sources.fetch_open_hours(s, e, cfg, source_modified=modified, last_day=out["last_day"])
            out.update(rows=out["rows"] + r["rows"], kept_on_conflict=out["kept_on_conflict"] + r["kept_on_conflict"],
                       estimated_bytes=out["estimated_bytes"] + (r.get("estimated_bytes") or 0),
                       last_day=r["last_day"], reads=out["reads"] + 1)
        return out
    except Exception as e:  # noqa: BLE001 - the forecast goes on with the stored open hours
        err = (f"{e.code}: {e.detail or ''}" if isinstance(e, AppError) else f"{type(e).__name__}: {e}")[:500]
        log.warning("daily forecast open hours read failed", extra={"ctx": {"business_date": str(d), "error": err}})
        _warn(OPEN_HOURS_ALERT, {"business_date": str(d), "error": err, "start": str(start), "end": str(end)},
              "forecast_refresh_date", str(d), once=True)
        return {**out, "error": err}


def _counts(values) -> dict:
    u, n = np.unique(np.asarray([str(v) for v in values], dtype=object), return_counts=True)
    return {str(k): int(v) for k, v in zip(u, n)}


def _detail(res, panel, window, grp, oh, d1, baseline, horizon, cfg, deal_src=None) -> dict:
    flags = [t for f in res["flags"] for t in (f.split(",") if f else [])]
    return {"horizon": horizon, "rounding_threshold": cfg.rounding_threshold,
            "panel": {"start": str(panel.dates[0].date()), "end": str(panel.dates[-1].date()),
                      "series": panel.n_series},
            "data_window": {k: window.get(k) for k in ("start", "end", "rule")},
            "groups": _counts(res["groups"]), "flags": _counts(flags) if flags else {},
            "methods": _counts(res["methods"]), "unknown_category_codes": res["unknown_codes"],
            "baseline_model": baseline, "group_computed_for": grp["computed_for"], "group_computed_now": grp["computed"],
            "group_window": {"start": grp.get("window_start"), "end": grp.get("window_end")},
            **({"groups_deferred": grp["deferred"]} if grp.get("deferred") else {}),
            "open_hours_last_day": grp.get("open_hours_last_day"),
            "open_hours_read": {k: oh.get(k) for k in ("start", "end", "rows", "last_day", "mode", "kept_on_conflict",
                                                       "source_modified", "skipped", "error")},
            "d1_job_id": d1.get("id"),
            # 1.3.2: the deal-table snapshot behind deal_active (None = deals not configured) and the extra-features
            # context the model read (None = feature set CHOT)
            "deal_snapshot_id": (deal_src or {}).get("snapshot_id"),
            "deal_active": ({k: deal_src[k] for k in ("table", "snapshot_id", "n_deals")} if deal_src else None),
            "extra_features": panel.extra.info if panel.extra is not None else None}


def _num(x):
    return None if x is None or not np.isfinite(x) else float(x)


def _persist(run_id, d, res, grp, inc, cv, fingerprint, cfg, horizon, job_id, trigger, detail, *,
             scope_key: str) -> tuple[int, int]:
    """forecast_refresh_runs + forecast_refresh_values in ONE transaction (only inserted, never updated: the run is
    PUBLISHED when written). Returns (values written, series forecast by LightGBM)."""
    fr, tr = inc["forecast_run"], inc["training_run"]
    at = now_iso()

    da = res.get("deal_active")     # 1.3.2: None = deals not configured (NULL)

    def rows():                     # the S x H value tuples, generated while written (never one full list)
        for s, k in enumerate(res["keys"]):
            m, g, fl = str(res["methods"][s]), res["groups"][s], res["flags"][s]
            for h, td in enumerate(res["dates"]):
                yield (run_id, h + 1, td, k[0], k[1], _num(res["raw"][s, h]), int(res["final"][s, h]), m, g, fl,
                       None if da is None else int(da[s, h]))
    n_lgb = int(np.sum(res["methods"] == model.METHOD_LGBM))
    n_series = len(res["keys"])
    with db.tx() as c:
        c.execute("INSERT INTO forecast_refresh_runs(id, scope_key, forecast_date, data_as_of, status, trigger, "
                  "training_run_id, model_version, model_fingerprint, config_version, trial_mode, horizon, n_series, "
                  "n_lightgbm, n_fallback, group_computed_for, job_id, created_at, detail_json) "
                  "VALUES (?,?,?,?, 'PUBLISHED', ?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (run_id, scope_key, str(d), str(d - timedelta(days=1)), trigger, tr["id"], fr["model_version"],
                   fingerprint, cv, int(bool(cfg.trial_mode)), int(horizon), n_series, n_lgb, n_series - n_lgb,
                   grp["computed_for"], job_id, at, json.dumps(detail, default=str)))
        n = c.executemany("INSERT INTO forecast_refresh_values(run_id, horizon, target_date, fc_code, sku_code, "
                          "lgb_raw, final_qty, method, group_code, flags, deal_active) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                          rows()).rowcount
        db.audit(c, "DAILY_FORECAST_PUBLISHED", "forecast_refresh_run", run_id,
                 {"forecast_date": str(d), "model_version": fr["model_version"], "rows": n,
                  "config_version": cv, "trial_mode": bool(cfg.trial_mode), "trigger": trigger,
                  "methods": detail["methods"]})
    return n, n_lgb


def refresh_actual_daily(scope_key: str, start: date, end: date, oh_source: tuple[str, str] | None = None,
                         floor=None) -> int:
    """actual_daily of the scope for [start, end]: demand = demand_daily qty of the scope; a day with open hours > 0
    and no demand row = 0, only on a day where the scope has at least one demand row (a day without any demand row of
    the scope is a data gap = unknown: none of its keys gets a row, never 0); total_open_hours from open_hours_daily of
    oh_source = (source_table, seller_code) (default: the configured open-hours read; NULL when not known). A day closed
    (hours 0 / unknown) without demand gets no row. The range is replaced (the scope's rows of [start, end] deleted and
    written again in one transaction: a row that no longer qualifies disappears); returns the number of rows written.
    floor: the data window start; start is clipped to it (no day before the data window is read or replaced)."""
    if floor:
        start = max(aux_sources._day(start), aux_sources._day(floor))
    tbl, seller = oh_source or aux_sources.open_hours_source()
    at = now_iso()
    p = {"k": scope_key, "s": str(start), "e": str(end), "at": at, "t": tbl, "sel": seller}
    with db.tx() as c:
        c.execute("DELETE FROM actual_daily WHERE scope_key=:k AND date BETWEEN :s AND :e", p)
        cur = c.execute(
            "INSERT INTO actual_daily(scope_key, date, fc_code, sku_code, demand, total_open_hours, updated_at) "
            "SELECT :k, k.day, k.fc, k.sku, COALESCE(d.qty, CASE WHEN o.total_open_hours > 0 THEN 0 END), "
            "o.total_open_hours, :at "
            "FROM (SELECT order_date AS day, fc_id AS fc, sku_id AS sku FROM demand_daily WHERE scope_key=:k AND "
            "order_date BETWEEN :s AND :e UNION SELECT open_date, fc_code, sku_code FROM open_hours_daily WHERE "
            "source_table=:t AND seller_code=:sel AND open_date BETWEEN :s AND :e AND total_open_hours > 0 "
            "AND open_date IN (SELECT order_date FROM demand_daily WHERE scope_key=:k AND order_date BETWEEN :s AND :e)"
            ") k "
            "LEFT JOIN demand_daily d ON d.scope_key=:k AND d.order_date=k.day AND d.sku_id=k.sku AND d.fc_id=k.fc "
            "LEFT JOIN open_hours_daily o ON o.source_table=:t AND o.seller_code=:sel AND o.open_date=k.day "
            "AND o.fc_code=k.fc AND o.sku_code=k.sku", p)
        return cur.rowcount


def apply_retention(scope_key: str, d: date, retention_days: int) -> dict:
    """B8 log retention of the scope, after a published refresh of day d (short transactions, one horizon day of one
    run or one actual day each): the values with horizon > SHORT_DAYS of every run except the latest PUBLISHED run of
    the scope (latest forecast_date, then created_at); every value of the runs with forecast_date < d -
    retention_days; the actual_daily rows with date < d - retention_days. The run records are kept (immutable)."""
    cutoff = str(d - timedelta(days=int(retention_days)))
    out = {"cutoff": cutoff, "superseded_values": 0, "old_values": 0, "actual_rows": 0}
    with db.read() as c:
        runs = db.rows(c, "SELECT id, forecast_date FROM forecast_refresh_runs WHERE scope_key=? "
                          "ORDER BY forecast_date DESC, created_at DESC, rowid DESC", (scope_key,))
        work = []
        for i, r in enumerate(runs):
            old = r["forecast_date"] < cutoff
            if not old and i == 0:
                continue                    # the latest run keeps every day of its horizon
            hs = [x[0] for x in c.execute("SELECT DISTINCT horizon FROM forecast_refresh_values WHERE run_id=? "
                                          "AND horizon > ?", (r["id"], 0 if old else SHORT_DAYS))]
            work += [(r["id"], h, "old_values" if old else "superseded_values") for h in hs]
        days = [x[0] for x in c.execute("SELECT DISTINCT date FROM actual_daily WHERE scope_key=? AND date < ?",
                                        (scope_key, cutoff))]
    for run_id, h, kind in work:
        with db.tx() as c:
            out[kind] += c.execute("DELETE FROM forecast_refresh_values WHERE run_id=? AND horizon=?",
                                   (run_id, h)).rowcount
    for day in days:
        with db.tx() as c:
            out["actual_rows"] += c.execute("DELETE FROM actual_daily WHERE scope_key=? AND date=?",
                                            (scope_key, day)).rowcount
    if out["superseded_values"] or out["old_values"] or out["actual_rows"]:
        log.info("daily forecast log retention", extra={"ctx": {"scope_key": scope_key, **out}})
    return out
