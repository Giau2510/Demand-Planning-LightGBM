"""Morning phone notice of the open-hours lag (owner decision 06/11/2026, release 1.4.5 item C5): when the newest
daily Excel of today (newest export_runs row of the Vietnam day, live DB opened mode=ro through ops_config) carries
the flag OPEN_HOURS_LAG, ONE notification through runner/notify.py with the facts the app recorded in that export
(summary_json.source_build, 1.4.5: newest open-hours day stored, the build times of the open-hours table and of the
demand table, which was built first); an export of an older app version without them -> "khong ro".
Idempotent per day: the state file <REPORTS>\\open-hours-notice\\state.json keeps the last day notified (a second run of
the same day sends nothing). Read-only on the DB; writes only the state file and the log next to it.
usage: open_hours_notice.py [--date YYYY-MM-DD] [--dry-run]   (prints one line; exit 0)
Scheduled by register-open-hours-notice.ps1 (task DemandForecastOpenHoursNotice, daily 07:30, repeated every 30 minutes
until 11:00): NO_EXPORT / NO_FLAG / ERROR store nothing, so a later pass of the same day checks again (an Excel written
after 07:30 is still noticed); only SENT stores the day."""
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "runner"))
import ops_config  # noqa: E402

VN = timezone(timedelta(hours=7))
FLAG = "OPEN_HOURS_LAG"
TITLE = "[OPEN-HOURS]"
UNKNOWN = "khong ro"
STATE_DIR = ops_config.REPORTS / "open-hours-notice"


def _state_file() -> Path:
    return STATE_DIR / "state.json"


def _read_state() -> dict:
    try:
        return json.loads(_state_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_state(st: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _state_file().with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_state_file())


def _log(line: str) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(STATE_DIR / "notice.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(VN):%Y-%m-%d %H:%M:%S} {line}\n")
    except OSError:
        pass


def newest_export(d: date, uri: str | None = None):
    """(version, flags, summary dict) of the newest export_runs row of day d; None without one."""
    c = sqlite3.connect(uri or ops_config.live_db_uri(), uri=True, timeout=30)
    try:
        c.execute("PRAGMA query_only = ON")
        r = c.execute("SELECT version, flags, summary_json FROM export_runs WHERE forecast_date=? "
                      "ORDER BY version DESC, rowid DESC LIMIT 1", (d.isoformat(),)).fetchone()
    finally:
        c.close()
    if r is None:
        return None
    try:
        s = json.loads(r[2] or "{}")
    except ValueError:
        s = {}
    return r[0], [x for x in (r[1] or "").split(",") if x], s if isinstance(s, dict) else {}


def _vn(ts):
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(VN).strftime("%Y-%m-%d %H:%M")


def text_of(summary: dict) -> str:
    """The notice text: the app's TOM_TAT line when recorded (1.4.5), else built from the fields ("khong ro")."""
    sb = summary.get("source_build") if isinstance(summary.get("source_build"), dict) else {}
    if sb.get("text"):
        return str(sb["text"])
    return (f"{FLAG}: gio mo ban moi nhat {sb.get('open_hours_last_day') or UNKNOWN}; "
            f"{sb.get('open_hours_table') or 'bang gio mo ban'} build {_vn(sb.get('open_hours_built_at')) or UNKNOWN}, "
            f"{sb.get('demand_table') or 'bang demand'} build {_vn(sb.get('demand_built_at')) or UNKNOWN} (gio VN); "
            f"build truoc: {sb.get('built_first') or UNKNOWN}")


def run(d: date, dry_run: bool = False, uri: str | None = None, sender=None) -> str:
    """One pass for day d; returns the line printed. sender(title, text) replaces notify.send (tests)."""
    st = _read_state()
    if st.get("notified_day") == d.isoformat():
        return f"ALREADY {d}: notified at {st.get('notified_at')}"
    ex = newest_export(d, uri)
    if ex is None:
        return f"NO_EXPORT {d}"
    version, flags, summary = ex
    if FLAG not in flags:
        return f"NO_FLAG {d}: Excel v{version} without {FLAG}"
    title, text = f"{TITLE} Gio mo ban tre ({d:%d/%m})", f"File du bao v{version}: {text_of(summary)}"
    if dry_run:
        return f"DRY_RUN {d}: would send {title} | {text}"
    if sender is None:
        import notify  # noqa: E402  (runner/notify.py: toast + ntfy, never raises)
        res = notify.send(title, text, "default", log=str(STATE_DIR / "notice.log"))
    else:
        res = sender(title, text)
    _write_state({"notified_day": d.isoformat(), "notified_at": datetime.now(VN).isoformat(timespec="seconds"),
                  "version": version, "result": res})
    return f"SENT {d}: {title} | {text}"


def main(argv) -> int:
    d = date.fromisoformat(argv[argv.index("--date") + 1]) if "--date" in argv else datetime.now(VN).date()
    try:
        line = run(d, dry_run="--dry-run" in argv)
    except Exception as e:  # noqa: BLE001 - a scheduled pass never crashes loudly; the next day runs again
        line = f"ERROR {d}: {type(e).__name__}"
    _log(line)
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
