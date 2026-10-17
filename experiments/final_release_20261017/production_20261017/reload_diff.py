"""READ-ONLY comparison of the BIGQUERY demand rows before (DB inside a backup zip, extracted to scratch) and after (live DB,
opened mode=ro) the D-1 full reload with prices: per-day new / removed / updated rows and quantities, price coverage.
Usage: reload_diff.py <before app.db> <after app.db> <out json>"""
import json
import sqlite3
import sys

import pandas as pd

SK = "BIGQUERY:lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm"


def load(path):
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    d = pd.read_sql_query("SELECT order_date, sku_id, fc_id, qty, avg_unit_price FROM demand_daily WHERE scope_key=?", c,
                          params=(SK,))
    other = c.execute("SELECT scope_key, COUNT(*), SUM(qty) FROM demand_daily WHERE scope_key<>? GROUP BY 1", (SK,)).fetchall()
    c.close()
    return d, other


b, ob = load(sys.argv[1])
a, oa = load(sys.argv[2])
m = b.merge(a, on=["order_date", "sku_id", "fc_id"], how="outer", suffixes=("_b", "_a"), indicator=True)
m["kind"] = "unchanged"
m.loc[m["_merge"] == "left_only", "kind"] = "removed"
m.loc[m["_merge"] == "right_only", "kind"] = "new"
both = m["_merge"] == "both"
m.loc[both & ((m["qty_b"] - m["qty_a"]).abs() > 1e-9), "kind"] = "updated"
by_day = (m[m["kind"] != "unchanged"].groupby(["order_date", "kind"])
          .agg(rows=("kind", "size"), qty_before=("qty_b", "sum"), qty_after=("qty_a", "sum")).reset_index())
out = {
    "before": {"rows": len(b), "qty": float(b["qty"].sum()), "priced": int(b["avg_unit_price"].notna().sum()),
               "first": b["order_date"].min(), "last": b["order_date"].max()},
    "after": {"rows": len(a), "qty": float(a["qty"].sum()), "priced": int(a["avg_unit_price"].notna().sum()),
              "null_price": int(a["avg_unit_price"].isna().sum()), "zero_price": int((a["avg_unit_price"] == 0).sum()),
              "negative_price": int((a["avg_unit_price"] < 0).sum()),
              "coverage": float(a["avg_unit_price"].notna().mean()), "first": a["order_date"].min(), "last": a["order_date"].max()},
    "counts": m["kind"].value_counts().to_dict(),
    "days_with_changes": by_day["order_date"].nunique(),
    "changes_before_2026_10_10": int((by_day["order_date"] < "2026-10-10").sum()),
    "changes_by_day_last_15": by_day[by_day["order_date"] >= "2026-10-02"].to_dict("records"),
    "changes_by_month": m[m["kind"] != "unchanged"].assign(month=lambda x: x["order_date"].str[:7])
                       .groupby(["month", "kind"]).size().unstack(fill_value=0).to_dict("index"),
    "other_scopes_unchanged": ob == oa,
    "price_coverage_by_month": a.assign(month=a["order_date"].str[:7]).groupby("month")["avg_unit_price"]
                               .apply(lambda s: round(float(s.notna().mean()), 5)).to_dict(),
}
open(sys.argv[3], "w", encoding="utf-8").write(json.dumps(out, indent=1, default=str))
print(json.dumps({k: v for k, v in out.items() if k != "changes_by_day_last_15"}, indent=1, default=str))
