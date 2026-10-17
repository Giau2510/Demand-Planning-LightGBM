"""Consistent copy of a live SQLite DB. The source is opened READ-ONLY (uri mode=ro); nothing is written to it."""
import json
import sqlite3
import sys

src, dst, info = sys.argv[1:4]
s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
d = sqlite3.connect(dst)
s.backup(d)
d.close()
runs = s.execute("SELECT COUNT(*) FROM forecast_runs").fetchone()[0]
old = s.execute("SELECT id FROM forecast_runs ORDER BY created_at LIMIT 1").fetchone()[0]
cnt, tot = s.execute("SELECT COUNT(*), SUM(yhat) FROM forecast_values WHERE run_id=?", (old,)).fetchone()
ver = s.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
s.close()
json.dump({"runs": runs, "old_run": old, "old_count": cnt, "old_sum": tot, "schema": ver}, open(info, "w"))
print("copied", src, "->", dst, {"runs": runs, "old_run": old, "rows": cnt, "sum": tot, "schema": ver})
