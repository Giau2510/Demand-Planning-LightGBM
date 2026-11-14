"""1.4.13 (owner order 14/11/2026, Task 10): maintenance pause of ONLY the D-0 slots (job D0_SYNC).

D-0 is an auxiliary monitoring job and must never slow an install. The pause lives in the schedule settings
(d0_paused_until / d0_paused_by), so it is saved through settings_service (validated, history kept) and read by the
running scheduler on its next tick. At most D0_PAUSE_MAX_HOURS from the moment it is set; expiry resumes by itself
(no write needed). Default = not paused: D-0 runs exactly as before. D-1, training, day-end jobs and the forecast
refresh never look at it."""
from __future__ import annotations

from datetime import datetime, timedelta

from . import settings_service as ss
from .messages import AppError
from .timeutil import VN_TZ, now_iso, now_utc, parse_iso

REASON_CODE = "PAUSED_FOR_MAINTENANCE"
WINDOWS_KEEP = timedelta(days=15)       # past pause windows kept in the settings (the scheduler looks back 14 days)


def paused_until(sched, now: datetime | None = None) -> datetime | None:
    """End of the pause when it is active at `now` (UTC or aware), else None."""
    until = parse_iso(sched.d0_paused_until)
    return until if until and (now or now_utc()) < until else None


def is_paused(sched, now: datetime | None = None) -> bool:
    return paused_until(sched, now) is not None


def in_window(sched, slot: datetime) -> bool:
    """A recorded pause window [from, until) contains `slot` (a D-0 slot time): the slot was inside a pause."""
    return any(parse_iso(f) <= slot < parse_iso(u) for f, u in sched.d0_pause_windows)


def slot_paused(sched, slot: datetime, now: datetime) -> bool:
    """The D-0 slot is not run: the pause is active now, or the slot time fell inside a recorded pause window."""
    return is_paused(sched, now) or in_window(sched, slot)


def status(now: datetime | None = None) -> dict:
    sched = ss.get("schedule")
    now = now or now_utc()
    until = paused_until(sched, now)
    return {"paused": until is not None,
            "until": until.isoformat(timespec="seconds") if until else None,
            "until_vn": until.astimezone(VN_TZ).strftime("%d/%m/%Y %H:%M") if until else None,
            "by": sched.d0_paused_by if until else "",
            "remaining_minutes": int((until - now).total_seconds() // 60) + 1 if until else 0,
            "max_hours": ss.D0_PAUSE_MAX_HOURS}


def _by(by: str | None) -> str:
    by = (by or "").strip()
    if len(by) > 60:
        raise AppError("D0_PAUSE_INVALID", 422, detail="by: at most 60 characters")
    return by


def pause(hours: float = ss.D0_PAUSE_MAX_HOURS, by: str | None = None) -> dict:
    """Pause the D-0 slots for `hours` (1 <= hours <= 6) from now; the settings history records it."""
    try:
        hours = float(hours)
    except (TypeError, ValueError):
        raise AppError("D0_PAUSE_INVALID", 422, detail="hours must be a number") from None
    if not 1 <= hours <= ss.D0_PAUSE_MAX_HOURS:
        raise AppError("D0_PAUSE_INVALID", 422, detail=f"hours must be 1..{ss.D0_PAUSE_MAX_HOURS}")
    by = _by(by)
    now = now_utc()
    until = (now + timedelta(hours=hours)).isoformat(timespec="seconds")
    keep = [w for w in ss.get("schedule").d0_pause_windows if parse_iso(w[1]) > now - WINDOWS_KEEP]
    ss.update("schedule", {"d0_paused_until": until, "d0_paused_by": by,
                           "d0_pause_windows": [*keep, [now_iso(), until]]},
              note=f"D-0 maintenance pause until {until} by {by or '-'}")
    return status()


def resume(by: str | None = None) -> dict:
    """End the pause now (a no-op write is skipped when D-0 was not paused)."""
    by = _by(by)
    cur = ss.get("schedule")
    now = now_utc()
    # the window that is open now ends now (slots from now on run); older windows stay as they were
    windows = [[f, now_iso()] if parse_iso(f) <= now < parse_iso(u) else [f, u] for f, u in cur.d0_pause_windows]
    if cur.d0_paused_until or cur.d0_paused_by or windows != cur.d0_pause_windows:
        ss.update("schedule", {"d0_paused_until": "", "d0_paused_by": "", "d0_pause_windows": windows},
                  note=f"D-0 maintenance pause ended at {now_iso()} by {by or '-'}")
    return status()
