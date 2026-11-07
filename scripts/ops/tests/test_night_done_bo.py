"""night_done.py (1.4.5 data-review fix) on a temporary DB: the newest export_runs row of D points to vN.xlsx but only
vN_bo.xlsx exists (an export killed between its rename and its record): the check reads the _bo file (sha256 of the
record) and reports DONE; without either file it still reports the missing file. Read-only, temp folder only."""
import hashlib
import json
import sqlite3
import sys
from datetime import date

from ops_test_env import isolate  # noqa: E402

T = isolate("ops_ndbo_")
import night_done  # noqa: E402

RESULTS = []


def ok(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


D = date(2026, 11, 10)                       # a Tuesday (no weekly training check)
data = T / "data"
folder = data / "exports" / "du_bao" / "20261110"
folder.mkdir(parents=True)
content = b"xlsx bytes"
(folder / "du_bao_20261110_v2_bo.xlsx").write_bytes(content)
(folder / "du_bao_20261110.xlsx").write_bytes(content)
db = T / "app.db"
c = sqlite3.connect(db)
c.execute("CREATE TABLE job_runs (job_type TEXT, status TEXT, started_at TEXT, result_json TEXT)")
c.execute("CREATE TABLE export_runs (forecast_date TEXT, version INTEGER, path TEXT, sha256 TEXT, n_rows INTEGER, "
          "created_at TEXT)")
c.execute("INSERT INTO job_runs VALUES ('D1_SYNC', 'SUCCEEDED', '2026-11-09T18:00:00', ?)",
          (json.dumps({"watermark": "2026-11-09"}),))
c.execute("INSERT INTO job_runs VALUES ('FORECAST_REFRESH', 'SUCCEEDED', '2026-11-09T19:00:00', ?)",
          (json.dumps({"business_date": "2026-11-10", "status": "PUBLISHED"}),))
c.execute("INSERT INTO export_runs VALUES ('2026-11-10', 2, 'exports/du_bao/20261110/du_bao_20261110_v2.xlsx', ?, 5, "
          "'2026-11-09T19:30:00+00:00')", (hashlib.sha256(content).hexdigest(),))
c.commit()
c.close()
done, why = night_done.check(D, db, data)
ok("record on vN.xlsx, only vN_bo.xlsx exists -> DONE", done and "v2" in why, why)
ok("nothing renamed back", not (folder / "du_bao_20261110_v2.xlsx").exists())
(folder / "du_bao_20261110_v2_bo.xlsx").unlink()
done, why = night_done.check(D, db, data)
ok("no file at all -> missing", not done and "missing" in why, why)
print(f"{sum(1 for _, r in RESULTS if r)}/{len(RESULTS)} passed")
sys.exit(0 if all(r for _, r in RESULTS) else 1)
