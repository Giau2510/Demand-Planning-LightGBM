"""open_hours_notice.py (1.4.5 C5) on a temporary DB (isolate(): every ops_config path in a temp folder; never the live
DB, never a real notification - a fake sender):
  1. no export of the day -> NO_EXPORT, nothing sent, no state;
  2. newest export without OPEN_HOURS_LAG (an older version has it) -> NO_FLAG;
  3. newest export with the flag -> ONE notice with the app's TOM_TAT text, state written;
  4. a second pass of the same day -> ALREADY, nothing sent (idempotent); the next day is checked again;
  5. an export of an older app version (no source_build) -> the text says "khong ro";
  6. --dry-run sends nothing and writes no state; the DB is opened read-only (a write raises)."""
import json
import sqlite3
import sys
from datetime import date

from ops_test_env import isolate  # noqa: E402

T = isolate("ops_ohn_")
import open_hours_notice as ohn  # noqa: E402

RESULTS = []
DB = T / "app.db"
URI = f"file:{DB.as_posix()}?mode=ro"


def ok(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


def add(day, version, flags, summary):
    c = sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS export_runs (id TEXT PRIMARY KEY, forecast_date TEXT NOT NULL, version "
              "INTEGER NOT NULL, path TEXT, flags TEXT, summary_json TEXT)")
    c.execute("INSERT INTO export_runs VALUES (?,?,?,?,?,?)", (f"E-{day}-{version}", day, version, "x", flags,
                                                               json.dumps(summary)))
    c.commit()
    c.close()


sent = []


def sender(title, text):
    sent.append((title, text))
    return {"fake": True}


D1, D2, D3 = date(2026, 11, 7), date(2026, 11, 8), date(2026, 11, 9)
SB = {"source_build": {"text": "OPEN_HOURS_LAG: gio mo ban moi nhat 2026-11-05; tbl build 2026-11-07 01:10:00, "
                               "demand build 2026-11-07 00:40:00 (gio VN); build truoc: demand"}}
add("2026-11-01", 1, "STALE", {})
line = ohn.run(D1, uri=URI, sender=sender)
ok("no export -> NO_EXPORT", line.startswith("NO_EXPORT") and not sent and not ohn._state_file().exists(), line)
add(D1.isoformat(), 1, "OPEN_HOURS_LAG,AVG_NO_ROW", SB)
add(D1.isoformat(), 2, "AVG_NO_ROW", SB)
line = ohn.run(D1, uri=URI, sender=sender)
ok("newest export without the flag -> NO_FLAG", line.startswith("NO_FLAG") and not sent, line)
add(D1.isoformat(), 3, "AVG_NO_ROW,OPEN_HOURS_LAG", SB)
line = ohn.run(D1, dry_run=True, uri=URI, sender=sender)
ok("dry run sends nothing, no state", line.startswith("DRY_RUN") and not sent and not ohn._state_file().exists(), line)
line = ohn.run(D1, uri=URI, sender=sender)
ok("flag -> one notice with the TOM_TAT text", line.startswith("SENT") and len(sent) == 1
   and "v3" in sent[0][1] and SB["source_build"]["text"] in sent[0][1] and sent[0][0].startswith("[OPEN-HOURS]"), line)
st = json.loads(ohn._state_file().read_text(encoding="utf-8"))
ok("state written", st["notified_day"] == D1.isoformat() and st["version"] == 3, st)
line = ohn.run(D1, uri=URI, sender=sender)
ok("second pass same day -> ALREADY, nothing sent", line.startswith("ALREADY") and len(sent) == 1, line)
add(D2.isoformat(), 1, "OPEN_HOURS_LAG", {"scope_key": "S"})            # export of an older app version
line = ohn.run(D2, uri=URI, sender=sender)
ok("next day notified again; old export -> khong ro", line.startswith("SENT") and len(sent) == 2
   and "khong ro" in sent[1][1], line)
add(D3.isoformat(), 1, "OPEN_HOURS_LAG", {"source_build": {"open_hours_last_day": "2026-11-07",
                                                           "open_hours_built_at": "2026-11-08T18:10:00+00:00",
                                                           "built_first": "openhours"}})
line = ohn.run(D3, uri=URI, sender=sender)
ok("fields without text -> built text, VN time", "2026-11-07" in sent[2][1] and "2026-11-09 01:10" in sent[2][1]
   and "bang demand build khong ro" in sent[2][1], sent[2][1])
c = sqlite3.connect(URI, uri=True)
try:
    c.execute("CREATE TABLE x (a)")
    ro = False
except sqlite3.OperationalError:
    ro = True
c.close()
ok("DB opened read-only", ro)
print(f"{sum(1 for _, r in RESULTS if r)}/{len(RESULTS)} passed")
sys.exit(0 if all(r for _, r in RESULTS) else 1)
