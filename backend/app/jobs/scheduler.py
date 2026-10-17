"""In-process scheduler (runs inside the backend on the Windows workstation; no cloud scheduler).

Every tick (default 30 s) it reads the saved schedule and decides, in Vietnam time, which jobs are due. Each flow has
its own switch (1.1.8, see jobs/flows.py) and is planned only when that switch is ON:
  D0_SYNC       schedule.d0_enabled    at each configured slot (default 08:00..18:00 every 2h)
  D1_SYNC       schedule.d1_enabled    from `d1_signal_poll_start`, polling the completion signal; after
                                       `d1_fallback_time` it verifies the source has a plausible full day before syncing
  TRAIN_PUBLISH schedule.train_enabled at `train_time` (BIGQUERY: only once today's D-1 succeeded - the scheduled
                                       D1_SYNC or, 1.2.1, a manual regular D-1 run of today, see flows.d1_success_today)

Missed slots (machine off / app closed) are recorded as SKIPPED (MISSED_SLOT_NO_BACKFILL). For D0 the policy
`d0_catchup_policy` decides: LATEST_ONCE = at most ONE catch-up snapshot of TODAY (stamped with the real time, flagged
catch-up), SKIP = none. Nothing is back-dated; earlier days are never caught up.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from .. import db
from .. import settings_service as ss
from ..timeutil import now_iso, now_utc, now_vn, parse_iso, vn_slot
from . import runner

log = logging.getLogger("df.scheduler")
MAX_MISSED_LOOKBACK_DAYS = 14


def d0_key(d: date, hhmm: str) -> str:
    return f"D0_SYNC:{d.isoformat()}T{hhmm}"


def plan(now: datetime, sched, active_source: str, last_heartbeat: datetime | None, conn) -> list[dict]:
    """Pure-ish planning step (reads job_runs only). Returns actions:
    {"action": "run"|"skip", job_type, key, trigger, scheduled_for, params, reason}"""
    actions: list[dict] = []
    today = now.date()
    existing = {r["idempotency_key"]: r for r in db.rows(
        conn, "SELECT idempotency_key, status, next_attempt_at FROM job_runs WHERE created_at>=?",
        ((now_utc() - timedelta(days=MAX_MISSED_LOOKBACK_DAYS + 2)).isoformat(),))}
    grace = timedelta(minutes=sched.slot_grace_minutes)
    on = {"D0_SYNC": sched.d0_enabled, "D1_SYNC": sched.d1_enabled, "TRAIN_PUBLISH": sched.train_enabled}
    since = {"D0_SYNC": parse_iso(sched.d0_enabled_at), "D1_SYNC": parse_iso(sched.d1_enabled_at),
             "TRAIN_PUBLISH": parse_iso(sched.train_enabled_at)}

    def live(jt: str, slot: datetime) -> bool:
        """The flow is ON and the slot is not earlier than the moment it was switched on."""
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
            for jt, t in (("D1_SYNC", sched.d1_fallback_time), ("TRAIN_PUBLISH", sched.train_time)):
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

    # ---- training + publish
    kt = f"TRAIN_PUBLISH:{today.isoformat()}"
    train_slot = vn_slot(today, sched.train_time)
    if live("TRAIN_PUBLISH", train_slot) and train_slot <= now and kt not in existing:
        late = now - train_slot > grace
        d1_ok = existing.get(k1, {}).get("status") == "SUCCEEDED"
        if not d1_ok and active_source == "BIGQUERY":
            from .flows import d1_success_today
            d1_ok = d1_success_today(conn, now) is not None
        if active_source == "BIGQUERY" and not d1_ok:
            pass  # wait for D-1; re-evaluated every tick (visible as pending on the dashboard)
        elif late and sched.train_catchup_policy == "SKIP":
            actions.append({"action": "skip", "job_type": "TRAIN_PUBLISH", "key": kt, "trigger": "SCHEDULE",
                            "scheduled_for": train_slot.isoformat(), "reason": "MISSED_SLOT_NO_BACKFILL"})
        else:
            actions.append({"action": "run", "job_type": "TRAIN_PUBLISH", "key": kt,
                            "trigger": "CATCH_UP" if late else "SCHEDULE", "scheduled_for": train_slot.isoformat(),
                            "params": {}})

    # ---- retries that are due (a flow switched OFF is not retried; manual jobs are never retried)
    for k, r in existing.items():
        if r["status"] == "RETRY_WAIT" and (not r["next_attempt_at"] or parse_iso(r["next_attempt_at"]) <= now_utc()):
            jt = k.split(":", 1)[0]
            if jt in runner.JOB_TYPES and on.get(jt, True):
                actions.append({"action": "run", "job_type": jt, "key": k, "trigger": "RETRY", "scheduled_for": None,
                                "params": {}})
    return actions


class Scheduler:
    def __init__(self, tick_seconds: int = 30):
        self.tick_seconds = tick_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="df-job")
        self._inflight: set[str] = set()
        self._lock = threading.Lock()
        self.last_tick: str | None = None
        self.started_at: str | None = None
        self.loaded: dict | None = None     # flows ON in the configuration this scheduler last read

    def reload(self) -> dict:
        """Read the saved schedule NOW (no job is run): lets the UI confirm right after a save that the running
        scheduler has the new state. Ticks do the same before planning."""
        sched = ss.get("schedule")
        self.loaded = {"at": now_iso(), "flows": {"d1": sched.d1_enabled, "d0": sched.d0_enabled,
                                                  "train": sched.train_enabled}}
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

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.safe_tick()
            self._stop.wait(self.tick_seconds)

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
        self.loaded = {"at": now_iso(), "flows": {"d1": sched.d1_enabled, "d0": sched.d0_enabled,
                                                  "train": sched.train_enabled}}
        now = now or now_vn()
        with db.read() as c:
            hb = db.one(c, "SELECT value_json FROM sync_state WHERE name='scheduler_heartbeat'")
            last_hb = parse_iso(json.loads(hb["value_json"])["at"]) if hb else None
            general = ss.get("general", c)
            actions = plan(now, sched, general.active_source, last_hb, c)
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
            if a["trigger"] == "CATCH_UP":
                if runs >= sched.max_catchup_jobs_per_tick:
                    continue  # controlled catch-up: the rest will be picked up on later ticks
                runs += 1
            with self._lock:
                if a["key"] in self._inflight:
                    continue
                self._inflight.add(a["key"])
            fut = self._pool.submit(self._run, a)
            futures.append(fut)
        if wait:
            for f in futures:
                f.result()
        return actions

    def _run(self, a: dict) -> None:
        try:
            runner.execute(a["job_type"], a["key"], a["trigger"], a.get("scheduled_for"), a.get("params") or {})
        finally:
            with self._lock:
                self._inflight.discard(a["key"])

    def status(self) -> dict:
        return {"running": bool(self._thread and self._thread.is_alive()), "started_at": self.started_at,
                "last_tick": self.last_tick, "inflight": sorted(self._inflight), "loaded": self.loaded}


SCHEDULER: Scheduler | None = None
