"""Restore test (FOLLOW_SOURCE history sync 02/11; the C1 check of 29/10): compare the restored copy (isolated
folder) with the live counts taken right after the backup.
argv: <c1_live.json> <restored data dir> <out json>"""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

live = json.load(open(sys.argv[1], encoding="utf-8"))
data = Path(sys.argv[2])
c = sqlite3.connect((data / "db" / "app.db").as_uri() + "?mode=ro", uri=True)
ok = c.execute("PRAGMA integrity_check").fetchone()[0]
counts = {n: c.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0]
          for (n,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")}
diff = {t: (live["live_counts_after"].get(t), counts.get(t)) for t in sorted(set(counts) | set(live["live_counts_after"]))
        if live["live_counts_after"].get(t) != counts.get(t)}
models = sorted(p.name for p in (data / "models").glob("*") if p.is_file())
mrows = c.execute("SELECT model_path, model_sha256 FROM training_runs WHERE model_path IS NOT NULL").fetchall()
bad = [p for p, s in mrows if not (data / "models" / p).exists()
       or hashlib.sha256((data / "models" / p).read_bytes()).hexdigest() != s]
res = {"integrity": ok, "tables": len(counts), "rows_total": sum(counts.values()), "count_differences": diff,
       "models_files": len(models), "models_equal_live_list": models == live["models"],
       "training_runs_with_model": len(mrows), "model_sha_mismatch": bad}
json.dump(res, open(sys.argv[3], "w", encoding="utf-8"), indent=1)
print(json.dumps(res, indent=1))
