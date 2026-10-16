"""Time helpers. Business time is Asia/Ho_Chi_Minh (UTC+7); storage timestamps are UTC ISO-8601."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

# Tests may freeze time by assigning a callable returning an aware datetime.
_now_override = None


def set_now_override(fn) -> None:
    global _now_override
    _now_override = fn


def now_utc() -> datetime:
    if _now_override is not None:
        return _now_override().astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def now_vn() -> datetime:
    return now_utc().astimezone(VN_TZ)


def today_vn() -> date:
    return now_vn().date()


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def now_iso() -> str:
    return iso(now_utc())


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def vn_slot(d: date, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(d.year, d.month, d.day, h, m, tzinfo=VN_TZ)


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)
