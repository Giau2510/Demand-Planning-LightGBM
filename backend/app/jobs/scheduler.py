"""In-process scheduler (runs inside the backend on the Windows workstation; no cloud scheduler).

Every tick (default 30 s) it reads the saved schedule and decides, in Vietnam time, which jobs are due. Each flow has
its own switch (1.1.8, see jobs/flows.py) and is planned only when that switch is ON:
  D0_SYNC       schedule.d0_enabled    at each configured slot (default 08:00..18:00 every 2h)
  D1_SYNC       schedule.d1_enabled    from `d1_signal_poll_start`, polling the completion signal; after
                                       `d1_fallback_time` it verifies the source has a plausible full day before syncing
  TRAIN_PUBLISH schedule.train_enabled at `train_time` (BIGQUERY: only once today's D-1 succeeded - the scheduled
                                       D1_SYNC or, 1.2.1, a manual regular D-1 run of today, see flows.d1_success_today)
  EOD_FORECAST_SNAPSHOT schedule.eod_enabled   at `eod_time` (1.2.6, default OFF, 23:55): backup of the next 7 forecast days
  ACTUAL_CLOSE          schedule.close_enabled at `close_time` (1.2.6, default OFF, 23:59): close of the day's actual
                        Both carry the business date of their slot (params.business_date, Vietnam date): a run after
                        midnight (grace, retry, catch-up) still works on that day. The slot of YESTERDAY is caught up
                        once when it was missed; older days are recorded as missed. Slots before the moment this version
                        first ran (sync_state 'flows_first_seen') are never run or caught up.
  FORECAST_REFRESH      schedule.refresh_enabled AND daily_forecast.enabled (1.3.1, default OFF): forecast refresh of
                        today with the model in use, once today's D-1 succeeded; one attempt every
                        refresh_retry_minutes until PUBLISHED, never
                        after refresh_deadline (train_catchup_policy does not apply). No PUBLISHED by the deadline: ONE
                        STALE_FORECAST record + ERROR alert for the day. Planned before TRAIN_PUBLISH (both heavy).
                        An attempt waiting for its retry (e.g. LOCKED) counts as under way until the deadline; one still
                        waiting after the deadline (or its day) is closed SKIPPED REFRESH_DEADLINE_PASSED.
  ACCURACY_REPORT       schedule.report_enabled AND daily_forecast.enabled (1.3.1, default OFF, light job): weekly, on
                        ISO weekday report_weekday at report_time; a missed slot runs once later the same day, earlier
                        weeks are never caught up.
1.4.0 SEL2 (sel2_pipeline.enabled True; False = the emergency switch: every plan above exactly as 1.3.1):
  TRAIN_PUBLISH         not run: its slot is recorded SKIPPED SEL2_PIPELINE_ACTIVE
  FORECAST_REFRESH      as above (D-1, retries, deadline, stale verdict) but runs the SEL2 pipeline (ml/sel2/jobs.py:
                        AVG_DEMAND read, then sel2-day in a child process; the export follows the publication); published
                        = a SEL2 run of today. On the retraining weekday it waits while today's CANDIDATE_TRAIN is
                        planned / PENDING / RUNNING / RETRY_WAIT until prev_week_deadline, then runs with the previous
                        week's models (flag MODEL_PREV_WEEK); once that training SUCCEEDED, ONE forced re-run of the day
                        (key FORECAST_REFRESH:<day>:RERUN, until refresh_deadline) publishes a new run + export version.
  CANDIDATE_TRAIN       schedule.train_enabled: on ISO weekday retrain_weekday once today's D-1 succeeded (heavy). On
                        another weekday, when a model of this week's origin (the latest retrain_weekday) has no
                        SUCCEEDED training: ONE catch-up CANDIDATE_TRAIN:<origin>:CATCHUP (same origin, same data
                        before it) once today's Excel exists or from export_deadline; once it SUCCEEDED, ONE forced
                        re-run of today (key FORECAST_REFRESH:<day>:RERUN, until refresh_deadline) as above.
  FORECAST_EXPORT       schedule.refresh_enabled: at export_deadline, ONE stale Excel of today when no SEL2 run is
                        published and no export exists (key FORECAST_EXPORT:<day>:STALE); from avg_reexport_time (None =
                        off) ONE job per day re-exporting when the AVG_DEMAND table changed (key FORECAST_EXPORT:<day>:AVG)
  SPIKE_LINES           1.4.8 (SEL2 on, schedule.refresh_enabled, BIGQUERY, today's D-1 succeeded): ONE job per day (key
                        SPIKE_LINES:<day>, never retried; spike_lines.py, child process): SO lines into so_lines_cache,
                        spike flags, excess. sel2_pipeline.spike_cleaning False (default): planned only once today's
                        FORECAST_REFRESH has finished (a SEL2 run of today published, or refresh_deadline passed) and no
                        refresh / CANDIDATE_TRAIN is under way - every other plan exactly as 1.4.7. True: planned right
                        after today's D-1; today's FORECAST_REFRESH and CANDIDATE_TRAIN (weekly and catch-up) wait while
                        it is planned / PENDING / RUNNING, at most spike_lines.WAIT_MAX (45 min) after its row was created.

Missed slots (machine off / app closed) are recorded as SKIPPED (MISSED_SLOT_NO_BACKFILL). For D0 the policy
`d0_catchup_policy` decides: LATEST_ONCE = at most ONE catch-up snapshot of TODAY (stamped with the real time, flagged
catch-up), SKIP = none. Nothing is back-dated; earlier days are never caught up.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from .. import db
from .. import settings_service as ss
from ..timeutil import VN_TZ, now_iso, now_utc, now_vn, parse_iso, vn_slot
from . import resources, runner

log = logging.getLogger("df.scheduler")
MAX_MISSED_LOOKBACK_DAYS = 14
# 1.3.1: a refresh row still PENDING this long after its deadline belongs to no live attempt (a starting job leaves
# PENDING at once); a younger one is left to the job that is starting
PENDING_CLOSE_AFTER = timedelta(minutes=5)
# 1.2.13: explanation caches (a run's whole panel, SHAP traces) are given back after this long without a request
IDLE_CACHE_SECONDS = 30 * 60
_PKG = __name__.rsplit(".", 2)[0]


def d0_key(d: date, hhmm: str) -> str:
    return f"D0_SYNC:{d.isoformat()}T{hhmm}"


DAY_END_FLOWS = (("EOD_FORECAST_SNAPSHOT", "eod"), ("ACTUAL_CLOSE", "close"))     # 1.2.6 (job type, flow)


def plan(now: datetime, sched, active_source: str, last_heartbeat: datetime | None, conn,
         first_seen: dict | None = None, inflight=()) -> list[dict]:
    """Pure-ish planning step (reads job_runs only). Returns actions:
    {"action": "run"|"skip", job_type, key, trigger, scheduled_for, params, reason}
    inflight: keys submitted to the scheduler's workers and not finished yet (1.3.1: used by FORECAST_REFRESH only)."""
    actions: list[dict] = []
    today = now.date()
    existing = {r["idempotency_key"]: r for r in db.rows(
        conn, "SELECT idempotency_key, status, next_attempt_at, created_at FROM job_runs WHERE created_at>=?",
        ((now_utc() - timedelta(days=MAX_MISSED_LOOKBACK_DAYS + 2)).isoformat(),))}
    grace = timedelta(minutes=sched.slot_grace_minutes)
    on = {"D0_SYNC": sched.d0_enabled, "D1_SYNC": sched.d1_enabled, "TRAIN_PUBLISH": sched.train_enabled,
          "EOD_FORECAST_SNAPSHOT": sched.eod_enabled, "ACTUAL_CLOSE": sched.close_enabled,
          "FORECAST_REFRESH": sched.refresh_enabled, "ACCURACY_REPORT": sched.report_enabled}
    since = {"D0_SYNC": parse_iso(sched.d0_enabled_at), "D1_SYNC": parse_iso(sched.d1_enabled_at),
             "TRAIN_PUBLISH": parse_iso(sched.train_enabled_at),
             **{jt: parse_iso(getattr(sched, f"{f}_enabled_at")) or parse_iso((first_seen or {}).get(f))
                for jt, f in DAY_END_FLOWS}}
    day_end_time = {"EOD_FORECAST_SNAPSHOT": sched.eod_time, "ACTUAL_CLOSE": sched.close_time}
    sel2 = ss.get("sel2_pipeline", conn)                # 1.4.0: enabled False = exact 1.3.1 planning
    if sel2.enabled:
        on.update({"CANDIDATE_TRAIN": sched.train_enabled, "FORECAST_EXPORT": sched.refresh_enabled})

    def live(jt: str, slot: datetime) -> bool:
        """The flow is ON and the slot is not earlier than the moment it was switched on. An end-of-day flow without
        that moment (no switch-on time and not yet seen by a scheduler tick) runs nothing."""
        if jt in day_end_time and since[jt] is None:
            return False
        return on[jt] and (since[jt] is None or slot >= since[jt])

    # ---- missed days since the last heartbeat (machine off for whole days) - only flows that are ON
    if last_heartbeat:
        start = max(last_heartbeat.date(), today - timedelta(days=MAX_MISSED_LOOKBACK_DAYS))
        d = start
        while d < today:
            for t in sched.d0_times:
                k = d0_key(d, t)
                if live("D0_SYNC", vn_slot(d, t)) and k not in existing and vn_slot(d, t) > last_heartbeat:
                    actions.append({"action": "skip", "job_type": "D0_SYNC", "key": k, "trigger": "SCHEDULE",
                                    "scheduled_for": vn_slot(d, t).isoformat(), "reason": "MISSED_SLOT_NO_BACKFILL"})
            late = [(jt, day_end_time[jt]) for jt, _f in DAY_END_FLOWS] if d < today - timedelta(days=1) else []
            for jt, t in (("D1_SYNC", sched.d1_fallback_time), ("TRAIN_PUBLISH", sched.train_time), *late):
                k = f"{jt}:{d.isoformat()}"
                if live(jt, vn_slot(d, t)) and k not in existing and vn_slot(d, t) > last_heartbeat:
                    actions.append({"action": "skip", "job_type": jt, "key": k, "trigger": "SCHEDULE",
                                    "scheduled_for": vn_slot(d, t).isoformat(), "reason": "MISSED_SLOT_NO_BACKFILL"})
            d += timedelta(days=1)

    # ---- D0 slots today
    due_slots = [t for t in sched.d0_times if vn_slot(today, t) <= now and live("D0_SYNC", vn_slot(today, t))]
    missed = []
    for t in due_slots:
        k = d0_key(today, t)
        if k in existing:
            continue
        slot = vn_slot(today, t)
        if now - slot <= grace:
            actions.append({"action": "run", "job_type": "D0_SYNC", "key": k, "trigger": "SCHEDULE",
                            "scheduled_for": slot.isoformat(), "params": {"scheduled_slot": slot.isoformat()}})
        else:
            missed.append(t)
            actions.append({"action": "skip", "job_type": "D0_SYNC", "key": k, "trigger": "SCHEDULE",
                            "scheduled_for": slot.isoformat(), "reason": "MISSED_SLOT_NO_BACKFILL"})
    if missed and sched.d0_catchup_policy == "LATEST_ONCE":
        latest = missed[-1]
        later_due = any(vn_slot(today, t) > vn_slot(today, latest) and now - vn_slot(today, t) <= grace
                        for t in due_slots)
        ck = f"D0_SYNC:{today.isoformat()}:CATCHUP"
        if not later_due and ck not in existing:
            actions.append({"action": "run", "job_type": "D0_SYNC", "key": ck, "trigger": "CATCH_UP",
                            "scheduled_for": vn_slot(today, latest).isoformat(),
                            "params": {"scheduled_slot": vn_slot(today, latest).isoformat(), "is_catch_up": True}})

    # ---- D-1 sync (BigQuery only)
    k1 = f"D1_SYNC:{today.isoformat()}"
    d1_slot = vn_slot(today, sched.d1_signal_poll_start)
    if live("D1_SYNC", d1_slot) and d1_slot <= now and k1 not in existing:
        if active_source != "BIGQUERY":
            actions.append({"action": "skip", "job_type": "D1_SYNC", "key": k1, "trigger": "SCHEDULE",
                            "scheduled_for": vn_slot(today, sched.d1_signal_poll_start).isoformat(),
                            "reason": "NOT_APPLICABLE_FOR_SOURCE"})
        else:
            actions.append({"action": "run", "job_type": "D1_SYNC", "key": k1, "trigger": "SCHEDULE",
                            "scheduled_for": vn_slot(today, sched.d1_signal_poll_start).isoformat(), "params": {}})

    # ---- 1.4.8 SO-line step, spike cleaning ON: right after today's D-1, the refresh and the trainings wait for it
    spikes = sel2.enabled and sched.refresh_enabled and active_source == "BIGQUERY"
    spike_wait = (_plan_spike_lines_first(now, conn, existing, k1, actions, inflight)
                  if spikes and sel2.spike_cleaning else False)

    # ---- 1.4.0 weekly training of the SEL2 candidates (before the refresh: on that day the refresh waits for it)
    train_wait = (_plan_candidate_train(now, sel2, active_source, conn, existing, k1, actions, inflight,
                                        spike_wait=spike_wait)
                  if sel2.enabled and sched.train_enabled else False)

    # ---- 1.3.1 forecast refresh: planned first; a training due in the same tick waits for the next tick
    refresh_now = (_plan_refresh(now, sched, active_source, conn, existing, k1, actions, inflight,
                                 sel2=sel2.enabled, train_wait=train_wait or spike_wait)
                   if sched.refresh_enabled else False)
    if sel2.enabled and sched.refresh_enabled and active_source == "BIGQUERY":
        _plan_sel2_followups(now, sched, sel2, conn, existing, actions, inflight)
    if sel2.enabled and sched.train_enabled and not spike_wait:
        _plan_candidate_catchup(now, sel2, active_source, conn, existing, actions, inflight)
    # ---- 1.4.8 SO-line step, spike cleaning OFF: only after today's forecast refresh (the Excel timing unchanged)
    if spikes and not sel2.spike_cleaning:
        _plan_spike_lines_after(now, sched, conn, existing, k1, actions, inflight, refresh_now)

    # ---- training + publish
    kt = f"TRAIN_PUBLISH:{today.isoformat()}"
    train_slot = vn_slot(today, sched.train_time)
    if sel2.enabled:
        if live("TRAIN_PUBLISH", train_slot) and train_slot <= now and kt not in existing:
            actions.append({"action": "skip", "job_type": "TRAIN_PUBLISH", "key": kt, "trigger": "SCHEDULE",
                            "scheduled_for": train_slot.isoformat(), "reason": "SEL2_PIPELINE_ACTIVE"})
    elif live("TRAIN_PUBLISH", train_slot) and train_slot <= now and kt not in existing:
        late = now - train_slot > grace
        d1_ok = existing.get(k1, {}).get("status") == "SUCCEEDED"
        if not d1_ok and active_source == "BIGQUERY":
            from .flows import d1_success_today
            d1_ok = d1_success_today(conn, now) is not None
        if active_source == "BIGQUERY" and not d1_ok:
            pass  # wait for D-1; re-evaluated every tick (visible as pending on the dashboard)
        elif refresh_now:
            pass  # 1.3.1: the forecast refresh starts first (one heavy job at a time); planned again on the next tick
        elif late and sched.train_catchup_policy == "SKIP":
            actions.append({"action": "skip", "job_type": "TRAIN_PUBLISH", "key": kt, "trigger": "SCHEDULE",
                            "scheduled_for": train_slot.isoformat(), "reason": "MISSED_SLOT_NO_BACKFILL"})
        else:
            actions.append({"action": "run", "job_type": "TRAIN_PUBLISH", "key": kt,
                            "trigger": "CATCH_UP" if late else "SCHEDULE", "scheduled_for": train_slot.isoformat(),
                            "params": {}})

    # ---- 1.2.6 end of day: forecast backup + actual close of the slot's business date (yesterday's missed slot once)
    for jt, _f in DAY_END_FLOWS:
        for d in (today - timedelta(days=1), today):
            slot = vn_slot(d, day_end_time[jt])
            k = f"{jt}:{d.isoformat()}"
            if live(jt, slot) and slot <= now and k not in existing:
                actions.append({"action": "run", "job_type": jt, "key": k,
                                "trigger": "SCHEDULE" if now - slot <= grace else "CATCH_UP",
                                "scheduled_for": slot.isoformat(), "params": {"business_date": d.isoformat()}})

    # ---- 1.3.1 weekly accuracy report (light job): its weekday slot; a missed slot runs once later the same day,
    # earlier weeks are never caught up
    if sched.report_enabled:
        _plan_report(now, sched, conn, existing, grace, actions)

    # ---- 1.3.1: a refresh attempt still waiting (LOCKED / retry) after its day's deadline is closed, never left open
    for k, r in existing.items():
        if k.startswith("FORECAST_REFRESH:") and r["status"] in ("RETRY_WAIT", "PENDING") \
                and not _refresh_retry_allowed(k, r.get("created_at"), now, sched) \
                and (r["status"] == "RETRY_WAIT" or _older_than(r.get("created_at"), PENDING_CLOSE_AFTER)):
            actions.append({"action": "close", "job_type": "FORECAST_REFRESH", "key": k, "trigger": "SCHEDULE",
                            "scheduled_for": None, "reason": "REFRESH_DEADLINE_PASSED"})

    # ---- retries that are due (a flow switched OFF is not retried; manual jobs are never retried)
    refresh_first = sched.refresh_enabled and _refresh_under_way(now, sched, conn, existing, inflight, refresh_now)
    for k, r in existing.items():
        if r["status"] == "RETRY_WAIT" and (not r["next_attempt_at"] or parse_iso(r["next_attempt_at"]) <= now_utc()):
            jt = k.split(":", 1)[0]
            if jt == "FORECAST_REFRESH" and not _refresh_retry_allowed(k, r.get("created_at"), now, sched):
                continue    # 1.3.1: only today's attempts, never after refresh_deadline (closed above)
            if jt == "TRAIN_PUBLISH" and refresh_first:
                continue    # 1.3.1: today's forecast refresh goes first (one heavy job at a time); a later tick
            if jt in runner.JOB_TYPES and on.get(jt, True):
                actions.append({"action": "run", "job_type": jt, "key": k, "trigger": "RETRY", "scheduled_for": None,
                                "params": {}})
    return actions


def _refresh_day(key: str, created_at: str | None) -> str | None:
    """Business date of a refresh attempt: from its key FORECAST_REFRESH:<day>:<suffix>, else (a manual job of the
    flow API, FORECAST_REFRESH:MANUAL:<id>) the Vietnam day it was created on."""
    parts = key.split(":")
    if len(parts) >= 3 and len(parts[1]) == 10 and parts[1][4] == "-" and parts[1][7] == "-":
        return parts[1]
    at = parse_iso(created_at)
    return at.astimezone(VN_TZ).date().isoformat() if at else None


def _refresh_retry_allowed(key: str, created_at: str | None, now: datetime, sched) -> bool:
    """A waiting refresh attempt may still run: it belongs to today and today's refresh_deadline has not passed."""
    return _refresh_day(key, created_at) == now.date().isoformat() and now <= vn_slot(now.date(), sched.refresh_deadline)


def _older_than(created_at: str | None, age: timedelta) -> bool:
    at = parse_iso(created_at)
    return at is None or now_utc() - at > age


def _refresh_under_way(now: datetime, sched, conn, existing: dict, inflight, refresh_now: bool) -> bool:
    """1.3.1 (schedule.refresh_enabled is ON): a forecast refresh attempt of today is planned in this tick, or before
    today's refresh_deadline it is PENDING, RUNNING, RETRY_WAIT or in the scheduler's workers, with daily_forecast ON:
    a due TRAIN_PUBLISH retry then waits for a later tick."""
    if refresh_now:
        return True
    today = now.date()
    if now > vn_slot(today, sched.refresh_deadline) or not ss.get("daily_forecast", conn).enabled:
        return False
    prefix = runner.refresh_key(today.isoformat(), "")
    return any(k.startswith(prefix) for k in inflight) or any(
        k.startswith("FORECAST_REFRESH:") and r["status"] in ("PENDING", "RUNNING", "RETRY_WAIT")
        and _refresh_day(k, r.get("created_at")) == today.isoformat() for k, r in existing.items())


def _plan_refresh(now: datetime, sched, active_source: str, conn, existing: dict, k1: str, actions: list,
                  inflight=(), sel2: bool = False, train_wait: bool = False) -> bool:
    """1.3.1 FORECAST_REFRESH of today (schedule.refresh_enabled is ON). Appends its action(s); True when an attempt
    is planned in this tick. Every attempt has its own key FORECAST_REFRESH:<day>:<HH:MM>. inflight: keys still in the
    scheduler's workers (an attempt submitted there has no job row until it starts).
    1.4.0 sel2: the SEL2 pipeline runs (daily_forecast.enabled not required), published = a SEL2 run of today;
    train_wait: today's CANDIDATE_TRAIN goes first (until prev_week_deadline)."""
    today = now.date()
    deadline = vn_slot(today, sched.refresh_deadline)
    since = parse_iso(sched.refresh_enabled_at)
    if since is not None and since > deadline:
        return False            # switched on after today's deadline: starts tomorrow, no stale alert for today
    if not sel2 and not ss.get("daily_forecast", conn).enabled:
        return False
    try:                        # published for the ACTIVE scope only (the refresh log is kept per scope)
        from ..data.demand import resolve_scope
        sk = resolve_scope(conn)["scope_key"]
    except Exception:  # noqa: BLE001 - no active scope
        sk = None
    if active_source == "BIGQUERY" and sk is None:
        return False            # nothing to refresh, no stale verdict
    if sel2:
        from ..ml.sel2 import jobs as sel2_jobs
        if sk is not None and sel2_jobs.published_run(conn, today):
            return False
    elif sk is not None and db.one(conn, "SELECT id FROM forecast_refresh_runs WHERE forecast_date=? AND "
                                         "status='PUBLISHED' AND scope_key=? LIMIT 1", (today.isoformat(), sk)):
        return False
    prefix = runner.refresh_key(today.isoformat(), "")
    if active_source != "BIGQUERY":
        k = prefix + "NA"
        if k not in existing:
            actions.append({"action": "skip", "job_type": "FORECAST_REFRESH", "key": k, "trigger": "SCHEDULE",
                            "scheduled_for": None, "reason": "NOT_APPLICABLE_FOR_SOURCE"})
        return False
    from .flows import _vn_day_start_utc
    rows = db.rows(conn, "SELECT idempotency_key, status, created_at FROM job_runs WHERE job_type='FORECAST_REFRESH' "
                         "AND created_at>=?", (_vn_day_start_utc(now),))
    # an attempt is under way, also one waiting for its retry (e.g. LOCKED by a heavy job) until the deadline: no
    # second attempt meanwhile; a stale verdict waits for its end (after the deadline a waiting one is closed)
    waiting = ("PENDING", "RUNNING") + (("RETRY_WAIT",) if now <= deadline else ())
    if any(r["status"] in waiting for r in rows) or any(k.startswith(prefix) for k in inflight):
        return False
    if now > deadline:
        k = prefix + "STALE"
        if k not in existing:
            actions.append({"action": "stale", "job_type": "FORECAST_REFRESH", "key": k, "trigger": "SCHEDULE",
                            "scheduled_for": deadline.isoformat(), "reason": "STALE_FORECAST",
                            "params": {"business_date": today.isoformat()}})
        return False
    d1_ok = existing.get(k1, {}).get("status") == "SUCCEEDED"
    if not d1_ok:
        from .flows import d1_success_today
        d1_ok = d1_success_today(conn, now) is not None
    if not d1_ok:
        return False            # waits for today's D-1
    if train_wait:
        return False            # 1.4.0: today's CANDIDATE_TRAIN first, until prev_week_deadline
    last = max((parse_iso(r["created_at"]) for r in rows), default=None)
    if last is not None and now - last < timedelta(minutes=sched.refresh_retry_minutes):
        return False
    slot = now.replace(second=0, microsecond=0)
    k = prefix + slot.strftime("%H:%M")
    if k in existing:
        return False
    actions.append({"action": "run", "job_type": "FORECAST_REFRESH", "key": k, "trigger": "SCHEDULE",
                    "scheduled_for": slot.isoformat(), "params": {"business_date": today.isoformat()}})
    return True


def _plan_candidate_train(now: datetime, sel2, active_source: str, conn, existing: dict, k1: str, actions: list,
                          inflight=(), spike_wait: bool = False) -> bool:
    """1.4.0 CANDIDATE_TRAIN:<day> on ISO weekday sel2.retrain_weekday (origin = today) once today's D-1 succeeded
    (BIGQUERY only). True when today's FORECAST_REFRESH must wait for it: the training is planned in this tick or
    PENDING / RUNNING / RETRY_WAIT (or in the workers) and prev_week_deadline has not passed.
    1.4.8 spike_wait (spike cleaning ON, today's SPIKE_LINES under way): not planned yet (the refresh waits as well)."""
    today = now.date()
    if today.isoweekday() != sel2.retrain_weekday or active_source != "BIGQUERY":
        return False
    k = f"CANDIDATE_TRAIN:{today.isoformat()}"
    before = now < vn_slot(today, sel2.prev_week_deadline)
    if k in inflight:
        return before
    if k in existing:
        return before and existing[k]["status"] in ("PENDING", "RUNNING", "RETRY_WAIT")
    d1_ok = existing.get(k1, {}).get("status") == "SUCCEEDED"
    if not d1_ok:
        from .flows import d1_success_today
        d1_ok = d1_success_today(conn, now) is not None
    if not d1_ok:
        return False
    if spike_wait:
        return before
    actions.append({"action": "run", "job_type": "CANDIDATE_TRAIN", "key": k, "trigger": "SCHEDULE",
                    "scheduled_for": now.replace(second=0, microsecond=0).isoformat(),
                    "params": {"origin": today.isoformat()}})
    return before


def _plan_sel2_followups(now: datetime, sched, sel2, conn, existing: dict, actions: list, inflight=()) -> None:
    """1.4.0 (SEL2 on, refresh flow ON, BIGQUERY): the forced re-run of today after the weekly training, the stale
    export at export_deadline and the AVG_DEMAND re-export (avg_reexport_time). Each one key, at most once per day."""
    from ..ml.sel2 import jobs as sel2_jobs
    today = now.date()
    day = today.isoformat()
    run = sel2_jobs.published_run(conn, today)
    # forced re-run: today's run used the previous week's models and this week's training (or its catch-up) has
    # SUCCEEDED since
    kr = runner.refresh_key(day, "RERUN")
    origin = today - timedelta(days=(today.isoweekday() - sel2.retrain_weekday) % 7)
    kt = f"CANDIDATE_TRAIN:{origin.isoformat()}"
    busy = any(k.startswith(runner.refresh_key(day, "")) for k in inflight) or any(
        k.startswith("FORECAST_REFRESH:") and r["status"] in ("PENDING", "RUNNING", "RETRY_WAIT")
        and _refresh_day(k, r.get("created_at")) == day for k, r in existing.items())
    trained = any(existing.get(k, {}).get("status") == "SUCCEEDED" for k in (kt, f"{kt}:CATCHUP"))
    if run is not None and kr not in existing and not busy and trained \
            and "MODEL_PREV_WEEK" in sel2_jobs.run_flags(run) and now <= vn_slot(today, sched.refresh_deadline):
        actions.append({"action": "run", "job_type": "FORECAST_REFRESH", "key": kr, "trigger": "SCHEDULE",
                        "scheduled_for": now.replace(second=0, microsecond=0).isoformat(),
                        "params": {"business_date": day, "force": True}})
    # stale export: no SEL2 run of today and no export of today at export_deadline
    ks = f"FORECAST_EXPORT:{day}:STALE"
    slot = vn_slot(today, sel2.export_deadline)
    if now >= slot and ks not in existing and ks not in inflight and run is None \
            and sel2_jobs.latest_export(conn, today) is None:
        actions.append({"action": "run", "job_type": "FORECAST_EXPORT", "key": ks, "trigger": "SCHEDULE",
                        "scheduled_for": slot.isoformat(), "params": {"business_date": day, "mode": "STALE"}})
    # AVG_DEMAND re-export (off while avg_reexport_time is None): one job per day once an export of today exists; the
    # job itself re-checks the table every refresh_retry_minutes until it changed (or the day ends)
    ka = f"FORECAST_EXPORT:{day}:AVG"
    if sel2.avg_reexport_time and now >= vn_slot(today, sel2.avg_reexport_time) and ka not in existing \
            and ka not in inflight and sel2_jobs.latest_export(conn, today) is not None:
        actions.append({"action": "run", "job_type": "FORECAST_EXPORT", "key": ka, "trigger": "SCHEDULE",
                        "scheduled_for": vn_slot(today, sel2.avg_reexport_time).isoformat(),
                        "params": {"business_date": day, "mode": "AVG"}})


def _plan_candidate_catchup(now: datetime, sel2, active_source: str, conn, existing: dict, actions: list,
                            inflight=()) -> None:
    """1.4.0 ONE catch-up CANDIDATE_TRAIN:<origin>:CATCHUP on a weekday other than retrain_weekday, origin = this week's
    retraining weekday, when a model of that origin has no SUCCEEDED training in the active scope (app closed on that
    day, training failed, SEL2 switched on later in the week). Planned once today's Excel exists or from
    export_deadline (the day's forecast goes first); the child trains on the data before the origin exactly as the
    weekly training, finished models are skipped. BIGQUERY only; not while the weekly training is still under way."""
    today = now.date()
    if today.isoweekday() == sel2.retrain_weekday or active_source != "BIGQUERY":
        return
    origin = today - timedelta(days=(today.isoweekday() - sel2.retrain_weekday) % 7)
    kw = f"CANDIDATE_TRAIN:{origin.isoformat()}"
    kc = f"{kw}:CATCHUP"
    if kc in existing or kc in inflight or kw in inflight \
            or existing.get(kw, {}).get("status") in ("PENDING", "RUNNING", "RETRY_WAIT"):
        return              # once per origin; the weekly training (or its retry) is still under way
    from ..ml.sel2 import jobs as sel2_jobs
    if now < vn_slot(today, sel2.export_deadline) and sel2_jobs.latest_export(conn, today) is None:
        return
    if not sel2_jobs.models_missing(conn, origin):
        return
    actions.append({"action": "run", "job_type": "CANDIDATE_TRAIN", "key": kc, "trigger": "SCHEDULE",
                    "scheduled_for": now.replace(second=0, microsecond=0).isoformat(),
                    "params": {"origin": origin.isoformat()}})


def _d1_ok(conn, existing: dict, k1: str, now: datetime) -> bool:
    if existing.get(k1, {}).get("status") == "SUCCEEDED":
        return True
    from .flows import d1_success_today
    return d1_success_today(conn, now) is not None


def _plan_spike_lines_first(now: datetime, conn, existing: dict, k1: str, actions: list, inflight=()) -> bool:
    """1.4.8, spike cleaning ON: SPIKE_LINES:<day> once today's D-1 succeeded. True while today's FORECAST_REFRESH and
    CANDIDATE_TRAIN must wait: the step is planned in this tick, in the workers before its row exists, or PENDING /
    RUNNING less than spike_lines.WAIT_MAX after its row was created or, still queued, after it was planned (inflight
    given as a dict key -> submission time); then they go on: its failure never blocks."""
    from .. import spike_lines
    k = spike_lines.job_key(now.date())
    r = existing.get(k)
    if r is not None:
        at = parse_iso(r.get("created_at"))
        return r["status"] in ("PENDING", "RUNNING") and at is not None and now_utc() - at < spike_lines.WAIT_MAX
    if k in inflight:
        at = inflight.get(k) if isinstance(inflight, dict) else None
        return at is None or now_utc() - at < spike_lines.WAIT_MAX
    if not _d1_ok(conn, existing, k1, now):
        return False
    actions.append({"action": "run", "job_type": spike_lines.JOB_TYPE, "key": k, "trigger": "SCHEDULE",
                    "scheduled_for": now.replace(second=0, microsecond=0).isoformat(),
                    "params": {"business_date": now.date().isoformat()}})
    return True


def _plan_spike_lines_after(now: datetime, sched, conn, existing: dict, k1: str, actions: list, inflight=(),
                            refresh_now: bool = False) -> None:
    """1.4.8, spike cleaning OFF: SPIKE_LINES:<day> once today's FORECAST_REFRESH has finished - a SEL2 run of today is
    published or refresh_deadline has passed - with no refresh attempt nor CANDIDATE_TRAIN planned, waiting, running or
    in the workers, and today's D-1 succeeded. It changes no other decision."""
    from .. import spike_lines
    from ..ml.sel2 import jobs as sel2_jobs
    day = now.date().isoformat()
    k = spike_lines.job_key(now.date())
    if k in existing or k in inflight or refresh_now or any(
            a["action"] == "run" and a["job_type"] in ("FORECAST_REFRESH", "CANDIDATE_TRAIN") for a in actions):
        return                  # a refresh (re-run) or a training planned in this tick goes first
    busy = ("PENDING", "RUNNING", "RETRY_WAIT")
    if any(x.startswith(runner.refresh_key(day, "")) or x.startswith("CANDIDATE_TRAIN:") for x in inflight) or any(
            ((x.startswith("FORECAST_REFRESH:") and _refresh_day(x, v.get("created_at")) == day)
             or x.startswith("CANDIDATE_TRAIN:")) and v["status"] in busy for x, v in existing.items()):
        return
    if not (sel2_jobs.published_run(conn, now.date()) or now > vn_slot(now.date(), sched.refresh_deadline)):
        return
    if not _d1_ok(conn, existing, k1, now):
        return
    actions.append({"action": "run", "job_type": spike_lines.JOB_TYPE, "key": k, "trigger": "SCHEDULE",
                    "scheduled_for": now.replace(second=0, microsecond=0).isoformat(),
                    "params": {"business_date": day}})


def _plan_report(now: datetime, sched, conn, existing: dict, grace: timedelta, actions: list) -> None:
    """1.3.1 ACCURACY_REPORT (schedule.report_enabled is ON): on ISO weekday report_weekday at report_time (Vietnam),
    key ACCURACY_REPORT:<day>, only while daily_forecast.enabled and not before the moment the flow was switched on."""
    today = now.date()
    if today.isoweekday() != sched.report_weekday:
        return
    slot = vn_slot(today, sched.report_time)
    since = parse_iso(sched.report_enabled_at)
    k = f"ACCURACY_REPORT:{today.isoformat()}"
    if slot > now or (since is not None and slot < since) or k in existing:
        return
    if not ss.get("daily_forecast", conn).enabled:
        return
    actions.append({"action": "run", "job_type": "ACCURACY_REPORT", "key": k,
                    "trigger": "SCHEDULE" if now - slot <= grace else "CATCH_UP", "scheduled_for": slot.isoformat(),
                    "params": {"business_date": today.isoformat()}})


def loaded_flows(sched) -> dict:
    """Flows ON in a schedule as the running scheduler reports them. 1.3.1: refresh / report are listed only while ON
    (switched OFF the report is exactly the one of 1.2.14)."""
    out = {"d1": sched.d1_enabled, "d0": sched.d0_enabled, "train": sched.train_enabled, "eod": sched.eod_enabled,
           "close": sched.close_enabled}
    out.update({f: True for f, on in (("refresh", sched.refresh_enabled), ("report", sched.report_enabled)) if on})
    return out


class Scheduler:
    def __init__(self, tick_seconds: int = 30):
        self.tick_seconds = tick_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="df-job")
        # 1.4.8: SPIKE_LINES runs in its own worker: D0 / FORECAST_EXPORT / ... never queue behind it in the pool
        self._spike_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="df-spike")
        self._inflight: set[str] = set()
        self._inflight_at: dict[str, object] = {}       # key -> UTC time it was submitted (planned)
        self._lock = threading.Lock()
        self.last_tick: str | None = None
        self.started_at: str | None = None
        self.loaded: dict | None = None     # flows ON in the configuration this scheduler last read

    def reload(self) -> dict:
        """Read the saved schedule NOW (no job is run): lets the UI confirm right after a save that the running
        scheduler has the new state. Ticks do the same before planning."""
        sched = ss.get("schedule")
        self.loaded = {"at": now_iso(), "flows": loaded_flows(sched)}
        return self.loaded

    def start(self) -> None:
        n = runner.recover_interrupted()
        if n:
            log.warning("interrupted jobs recovered", extra={"ctx": {"count": n}})
        self.started_at = now_iso()
        self._thread = threading.Thread(target=self._loop, name="df-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._spike_pool.shutdown(wait=False, cancel_futures=True)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.safe_tick()
            self.release_idle_caches()
            self._stop.wait(self.tick_seconds)

    @staticmethod
    def release_idle_caches(max_idle_s: float = IDLE_CACHE_SECONDS) -> int:
        """1.2.13: the server keeps no explanation panel / SHAP trace while nobody uses them: after max_idle_s without
        a request they are dropped and the heap given back. Only modules already loaded are checked (nothing heavy is
        imported for it). Never raises; returns the number of cache entries dropped."""
        try:
            n = 0
            for name in ("ml.explain", "ml.shap_audit"):
                mod = sys.modules.get(f"{_PKG}.{name}")
                if mod is not None:
                    n += mod.release_idle(max_idle_s)
            if n:
                log.info("idle explanation caches released", extra={"ctx": {"entries": n, **resources.release_memory()}})
            return n
        except Exception:  # noqa: BLE001 - housekeeping only
            log.warning("idle cache release failed", exc_info=True)
            return 0

    def safe_tick(self) -> str:
        """One loop iteration. A long write transaction (e.g. a D-1 full reload) can hold the database lock longer than
        the busy timeout: that tick is deferred with a WARNING (SCHEDULER_TICK_DEFERRED) and the next tick plans the
        same slots again (idempotency keys prevent double runs). Any other error stays an ERROR."""
        try:
            self.tick()
            return "OK"
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() or "busy" in str(e).lower():
                self.deferred_ticks = getattr(self, "deferred_ticks", 0) + 1
                log.warning("scheduler tick deferred: database busy",
                            extra={"ctx": {"code": "SCHEDULER_TICK_DEFERRED", "error": str(e)[:200],
                                           "deferred_ticks": self.deferred_ticks}})
                return "DEFERRED"
            log.exception("scheduler tick failed")
            return "ERROR"
        except Exception:  # pragma: no cover - logged, loop continues
            log.exception("scheduler tick failed")
            return "ERROR"

    def tick(self, now: datetime | None = None, wait: bool = False) -> list[dict]:
        sched = ss.get("schedule")
        self.loaded = {"at": now_iso(), "flows": loaded_flows(sched)}
        now = now or now_vn()
        first_seen = self._first_seen(now)
        with db.read() as c:
            hb = db.one(c, "SELECT value_json FROM sync_state WHERE name='scheduler_heartbeat'")
            last_hb = parse_iso(json.loads(hb["value_json"])["at"]) if hb else None
            general = ss.get("general", c)
            with self._lock:
                inflight = {k: self._inflight_at.get(k) for k in self._inflight}   # read only, with planned time
            actions = plan(now, sched, general.active_source, last_hb, c, first_seen, inflight)
        with db.tx() as c:
            c.execute("INSERT INTO sync_state(name, value_json, updated_at) VALUES ('scheduler_heartbeat', ?, ?) "
                      "ON CONFLICT(name) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                      (json.dumps({"at": now.isoformat(), "flows": self.loaded["flows"]}), now_iso()))
        self.last_tick = now_iso()
        runs = 0
        futures = []
        for a in actions:
            if a["action"] == "skip":
                runner.record_skipped(a["job_type"], a["key"], a["trigger"], a["scheduled_for"], a["reason"])
                continue
            if a["action"] == "stale":
                runner.record_stale(a["key"], a["params"]["business_date"], a["scheduled_for"])
                continue
            if a["action"] == "close":
                runner.close_waiting(a["key"], a["reason"])
                continue
            if a["trigger"] == "CATCH_UP":
                if runs >= sched.max_catchup_jobs_per_tick:
                    continue  # controlled catch-up: the rest will be picked up on later ticks
                runs += 1
            with self._lock:
                if a["key"] in self._inflight:
                    continue
                self._inflight.add(a["key"])
                self._inflight_at[a["key"]] = now_utc()
            fut = (self._spike_pool if a["job_type"] == "SPIKE_LINES" else self._pool).submit(self._run, a)
            futures.append(fut)
        if wait:
            for f in futures:
                f.result()
        return actions

    @staticmethod
    def _first_seen(now: datetime) -> dict:
        """1.2.6: moment a scheduler first saw each end-of-day flow (stored once, kept across restarts). Its slots before
        that moment are neither run nor caught up: installing the version never back-dates a snapshot or a close. Read
        only, except the first time (no write lock taken on every tick)."""
        def read(c) -> dict:
            r = db.one(c, "SELECT value_json FROM sync_state WHERE name='flows_first_seen'")
            return json.loads(r["value_json"]) if r else {}
        with db.read() as c:
            seen = read(c)
        if all(f in seen for _jt, f in DAY_END_FLOWS):
            return seen
        with db.tx() as c:
            seen = read(c)
            seen.update({f: now.isoformat(timespec="seconds") for _jt, f in DAY_END_FLOWS if f not in seen})
            c.execute("INSERT INTO sync_state(name, value_json, updated_at) VALUES ('flows_first_seen', ?, ?) "
                      "ON CONFLICT(name) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                      (json.dumps(seen), now_iso()))
        return seen

    def _run(self, a: dict) -> None:
        try:
            runner.execute(a["job_type"], a["key"], a["trigger"], a.get("scheduled_for"), a.get("params") or {})
        finally:
            with self._lock:
                self._inflight.discard(a["key"])
                self._inflight_at.pop(a["key"], None)

    def status(self) -> dict:
        return {"running": bool(self._thread and self._thread.is_alive()), "started_at": self.started_at,
                "last_tick": self.last_tick, "inflight": sorted(self._inflight), "loaded": self.loaded}


SCHEDULER: Scheduler | None = None
