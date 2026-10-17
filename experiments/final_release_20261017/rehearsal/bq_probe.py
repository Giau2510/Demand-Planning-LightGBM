"""READ_ONLY_TEST against the REAL BigQuery tables (settings of an ISOLATED copy; never the live DB).
  meta  : table metadata only (free): exists, rows, bytes, last modified, schema, mapping check per feed
  fresh : + small queries (dry run first, byte cap of the app): latest day of D-1 and D-0, price NULL/zero/negative and
          coverage of the newest D-1 days and of the D-0 table
Usage: bq_probe.py meta|fresh <out json>"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ISO = Path(os.environ["DF_DATA_DIR"]).resolve()
assert "scratchpad" in str(ISO).lower(), ISO
sys.path.insert(0, r"D:\Buymed\Lightgbm AI\backend")
from app import settings_service as ss          # noqa: E402
from app.bq import connector                    # noqa: E402

bq = ss.get("bigquery")
client = connector._client(bq)
D1 = f"{bq.project_id}.{bq.dataset_id}.{bq.source_table}"
D0 = bq.d0_table_id
out = {"at": datetime.now(timezone.utc).isoformat(), "mode": sys.argv[1], "tables": {}, "queries": {}}
for kind, tid in (("d1", D1), ("d0", D0)):
    t = client.get_table(tid)
    out["tables"][kind] = {"table_id": tid, "type": t.table_type, "rows": t.num_rows, "bytes": t.num_bytes,
                           "modified": t.modified.isoformat(), "location": t.location,
                           "schema": [(f.name, f.field_type) for f in t.schema]}
if sys.argv[1] == "fresh":
    q = {
        "d1_newest_days": f"""SELECT created_date d, COUNT(*) n, SUM(demand_quantity) qty, COUNTIF(sales_price IS NULL) price_null,
            COUNTIF(sales_price = 0) price_zero, COUNTIF(sales_price < 0) price_neg, COUNT(DISTINCT sku_code) skus,
            COUNT(DISTINCT fc_code) fcs FROM `{D1}` WHERE created_date >= DATE_SUB(CURRENT_DATE('Asia/Ho_Chi_Minh'), INTERVAL 4 DAY)
            GROUP BY 1 ORDER BY 1""",
        "d0_range": f"""SELECT MIN(created_date) mn, MAX(created_date) mx, COUNT(*) n, SUM(demand_quantity) qty,
            COUNTIF(sales_price IS NULL) price_null, COUNTIF(sales_price = 0) price_zero, COUNTIF(sales_price < 0) price_neg,
            COUNT(DISTINCT sku_code) skus, COUNT(DISTINCT fc_code) fcs FROM `{D0}`""",
    }
    for k, sql in q.items():
        dry = connector._run(client, bq, f"probe_{k}", sql, None, dry_run_only=True)["estimated_bytes"]
        res = connector._run(client, bq, f"probe_{k}", sql, None)
        out["queries"][k] = {"estimated_bytes": dry, "rows": res["rows"]}
Path(sys.argv[2]).write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
print(json.dumps({"tables": {k: {x: v[x] for x in ("rows", "modified", "location")} for k, v in out["tables"].items()},
                  "queries": out["queries"]}, indent=1, default=str))
