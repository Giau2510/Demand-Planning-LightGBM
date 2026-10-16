"""READ-ONLY checks of the price data on the ISOLATED price-experiment copy (never the live DB): mapping, dtype,
missing prices (NULL, never 0), value range, coverage, registry decision, and price availability at the forecast origin
for the DIRECT layout. Usage: price_verify.py <copy app.db> <out json>"""
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:\Buymed\Lightgbm AI\backend")
from app import settings_service as ss                       # noqa: E402
from app.ml import feature_registry as registry              # noqa: E402
from app.ml.features import build_panel, feature_names, origin_features, static_codes  # noqa: E402

src = Path(sys.argv[1]).resolve()
assert "scratchpad" in str(src).lower(), src
c = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
out = {}
bq = json.loads(c.execute("SELECT value_json FROM app_settings WHERE section='bigquery'").fetchone()[0])
mrow = c.execute("SELECT value_json FROM app_settings WHERE section='model'").fetchone()
model = json.loads(mrow[0]) if mrow else {}
out["mapping_unit_price"] = bq["field_mapping"]["unit_price"]
out["model_section_saved"] = bool(mrow)
out["model_feature_price"] = ss.ModelSettings.model_validate(model).feature_price
sk = "BIGQUERY:{}.{}.{}".format(bq["project_id"], bq["dataset_id"], bq["source_table"])
out["scope_key"] = sk
r = c.execute("SELECT COUNT(*), SUM(qty), COUNT(avg_unit_price), SUM(avg_unit_price IS NULL), SUM(avg_unit_price = 0), "
              "SUM(avg_unit_price < 0), MIN(avg_unit_price), MAX(avg_unit_price), MIN(order_date), MAX(order_date), "
              "SUM(typeof(avg_unit_price) = 'real'), SUM(typeof(avg_unit_price) NOT IN ('real', 'null')) "
              "FROM demand_daily WHERE scope_key=?", (sk,)).fetchone()
out["demand_daily"] = dict(zip(["rows", "qty", "priced_rows", "null_price_rows", "zero_price_rows", "negative_price_rows",
                                "min_price", "max_price", "first_day", "last_day", "real_typed", "other_typed"], r))
out["null_price_by_qty"] = [list(x) for x in c.execute(
    "SELECT CASE WHEN qty <= 0 THEN 'qty<=0' ELSE 'qty>0' END, COUNT(*), SUM(avg_unit_price IS NULL) FROM demand_daily "
    "WHERE scope_key=? GROUP BY 1", (sk,))]
st = c.execute("SELECT value_json FROM sync_state WHERE name=?", (f"last_d1_sync:{sk}",)).fetchone()
st = json.loads(st[0]) if st else {}
out["last_d1_sync"] = {k: st.get(k) for k in ("mode", "full_reload", "window_start", "window_end", "rows_read", "qty_valid",
                                              "series_days_written", "series_days_updated", "series_days_unchanged",
                                              "series_days_new", "series_days_removed", "exact_duplicate_rows")}
cov = registry.coverage(c, sk)
out["coverage"] = cov
cfg = ss.ModelSettings(**{**ss.ModelSettings.model_validate(model).model_dump(), "forecast_strategy": "DIRECT"})
resolved, dec = registry.resolve(cfg, cov)
out["decision_price"] = dec["price"]
names = feature_names(resolved)
out["direct_features"] = names
# price availability at the forecast origin (the day after the last data day), exactly as inference builds it
d = pd.read_sql_query("SELECT order_date, sku_id, fc_id, qty, n_orders, avg_unit_price, avg_discount_rate, promo_share "
                      "FROM demand_daily WHERE scope_key=? AND order_date BETWEEN '2026-01-01' AND '2026-10-15'", c, params=(sk,))
p = build_panel(d, max_days=resolved.max_train_days)
sc, fcc = static_codes(p)
X = origin_features(p, p.Y, p.price, p.disc, p.promo, p.dates, p.T, resolved, sc, fcc)
on = [n for n in names if n not in ("horizon",) and n not in ("dow", "dom", "month", "weekofyear", "is_weekend", "days_to_month_end")]
i_pl, i_pr = on.index("price_last"), on.index("price_rel_28")
pl, pr = X[:, i_pl], X[:, i_pr]
raw_last = p.price[:, p.T - 1]
out["origin"] = {"panel": [str(p.dates[0].date()), str(p.dates[-1].date())], "series": p.n_series,
                 "price_last_known_share": float(np.isfinite(pl).mean()),
                 "price_rel_28_known_share": float(np.isfinite(pr).mean()),
                 "price_last_equals_last_known_price": bool(np.array_equal(pl, raw_last.astype(np.float32), equal_nan=True)),
                 "price_rel_28_quantiles": [float(x) for x in np.nanquantile(pr, [0.01, 0.25, 0.5, 0.75, 0.99])],
                 "price_last_quantiles": [float(x) for x in np.nanquantile(pl, [0.01, 0.5, 0.99])]}
# how often the price of a series changes from one priced day to the next (signal available to the model)
dd = d.dropna(subset=["avg_unit_price"]).sort_values(["sku_id", "fc_id", "order_date"])
chg = dd.groupby(["sku_id", "fc_id"])["avg_unit_price"].apply(lambda s: (s.pct_change().abs() > 0.01).mean())
out["price_change_share_per_series"] = [float(x) for x in chg.quantile([0.25, 0.5, 0.75, 0.9])]
Path(sys.argv[2]).write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
print(json.dumps({k: v for k, v in out.items() if k != "direct_features"}, default=str, indent=1))
