"""Read-only facts of a Demand Forecasting SQLite DB (opened with mode=ro). Usage: db_facts.py <app.db> [out.json]"""
import json
import sqlite3
import sys

db = sys.argv[1]
c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
q = lambda s, *a: c.execute(s, a).fetchone()   # noqa: E731
tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
facts = {
    "schema": q("SELECT MAX(version) FROM schema_migrations")[0],
    "integrity": q("PRAGMA integrity_check")[0],
    "foreign_key_violations": len(c.execute("PRAGMA foreign_key_check").fetchall()),
    "counts": {t: q(f"SELECT COUNT(*) FROM [{t}]")[0] for t in tables},
    "active_batches": [list(r) for r in c.execute("SELECT id, data_source, status FROM import_batches WHERE status='ACTIVE' ORDER BY id")],
    "forecast_runs": [list(r) for r in c.execute("SELECT id, scope_key, created_at FROM forecast_runs ORDER BY created_at")],
    "run_8D88F1_values": list(q("SELECT COUNT(*), ROUND(SUM(yhat), 6) FROM forecast_values WHERE run_id='FCR-20261014080621-8D88F1'")),
    "demand_daily_sum": q("SELECT ROUND(SUM(qty), 6) FROM demand_daily")[0],
    "order_lines_sum": q("SELECT ROUND(SUM(order_qty), 6) FROM order_lines")[0],
    "accepted_trainings": q("SELECT COUNT(*) FROM training_runs WHERE status='ACCEPTED'")[0],
}
c.close()
print(json.dumps(facts, ensure_ascii=False, indent=1))
if len(sys.argv) > 2:
    json.dump(facts, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
