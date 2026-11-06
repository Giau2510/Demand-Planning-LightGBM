"""Synthetic app-format daily files (1.4.3 / 1.4.2 layout) + fake export_runs, written with the app's xlsx_stream."""
import hashlib
import importlib.util
import os
import random
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.dont_write_bytecode = True
_BACKEND = Path(os.environ.get("DF_X20_APP_BACKEND") or Path(__file__).resolve().parents[3] / "backend")
spec = importlib.util.spec_from_file_location("gen_xs", _BACKEND / "app" / "ml" / "sel2" / "xlsx_stream.py")
xs = importlib.util.module_from_spec(spec)
sys.modules["gen_xs"] = xs
spec.loader.exec_module(xs)

COLS = ["sku_code", "ten_san_pham", "seller_code", "product_code", "fc_code", "nhom", "forecast_date", "target_date",
        "horizon", "lightgbm_forecast", "avg_demand", "forecast_source", "forecast_used", "fallback_reason",
        "model_used", "raw_value", "model_version", "data_cutoff_date", "is_stale", "flags"]
CCOLS = ["sku_code", "fc_code", "ten_san_pham", "seller_code", "product_code", "ghi_chu", "updated_by", "updated_at"]


def split(s):
    a, dot, b = s.partition(".")
    return (None, s) if not dot else (a or None, b or None)


def row(d, sku, fc, h, qty, av, src, used, reason, raw, flags=None, layout="143"):
    seller, product = split(sku)
    r = [sku, "Ten " + sku, seller, product, fc, "G1", d, d + timedelta(days=h - 1), h, qty, av, src, used, reason,
         "V33" if raw is not None else None, raw, "MV-1" if src == "LIGHTGBM" else None, d - timedelta(days=1), 0, flags]
    if layout == "142":
        del r[2:4]
    return r


def write_file(path, d, rows, layout="143", config=None):
    cols = COLS if layout == "143" else [c for c in COLS if c not in ("seller_code", "product_code")]
    ccols = CCOLS if layout == "143" else [c for c in CCOLS if c not in ("seller_code", "product_code")]
    summary = [["forecast_date", d.isoformat()], ["export_version", 3], ["rows_total", len(rows)]]
    config = config or [["A.X1", "BD", "Ten A.X1", "A", "X1", None, "u", "2026-11-05T01:00:00+00:00"]]
    if layout == "142":
        config = [r[:3] + r[5:] for r in config]
    path.parent.mkdir(parents=True, exist_ok=True)
    xs.write_xlsx(path, [xs.Sheet("DU_BAO", cols, rows, len(rows), True, True),
                         xs.Sheet("TOM_TAT", ["muc", "gia_tri"], summary),
                         xs.Sheet("CONFIG", ccols, config, len(config), True, True)])
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_db(db, entries):
    db.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE IF NOT EXISTS export_runs (id TEXT PRIMARY KEY, forecast_date TEXT NOT NULL, version INTEGER "
              "NOT NULL, path TEXT NOT NULL, sha256 TEXT, n_rows INTEGER, is_stale INTEGER NOT NULL DEFAULT 0, flags "
              "TEXT, refresh_run_id TEXT, trigger TEXT, job_id TEXT, created_at TEXT NOT NULL)")
    for e in entries:
        c.execute("INSERT INTO export_runs (id, forecast_date, version, path, sha256, n_rows, created_at) "
                  "VALUES (?,?,?,?,?,?,?)", e)
    c.commit()
    c.close()


def old_ts():
    return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")


def big(path, d, n_bd=32_000, n_hn=26_663, seed=7):
    """real-size file: 58,663 SKU x FC x 7 = 410,641 rows, mixed sources / reasons"""
    rnd = random.Random(seed)
    rows = []
    for fc, n in (("BD", n_bd), ("HN", n_hn)):
        for i in range(n):
            sku = f"S{i % 900}.P{i:06d}-{fc}" if i % 50 else f"NODOT{i}"
            kind = rnd.random()
            for h in range(1, 8):
                raw = round(rnd.random() * 12, 9) if kind > 0.15 else None
                if kind < 0.05:
                    rows.append(row(d, sku, fc, h, None, None, "LIGHTGBM", 0, "NGOAI_PHAM_VI_GAN_0", None))
                elif kind < 0.10:
                    rows.append(row(d, sku, fc, h, None, 2.3, "LIGHTGBM", 3, "STALE", None, "AVG_X"))
                elif kind < 0.15:
                    rows.append(row(d, sku, fc, h, None, None, "AVG_DEMAND", 0, "KHONG_CO_SO_NAO", None))
                elif kind < 0.25:
                    rows.append(row(d, sku, fc, h, raw, 1.7, "AVG_DEMAND", 2, None, raw))
                elif kind < 0.30:
                    rows.append(row(d, sku, fc, h, raw, None, "LIGHTGBM", 0 if raw < .2 else -(-raw // 1),
                                    "DUNG_SO_LAN_CHAY_TRUOC", raw, "LAN_CHAY_TRUOC:2026-11-04"))
                else:
                    rows.append(row(d, sku, fc, h, raw, 1.1, "LIGHTGBM", 0 if raw < .2 else int(-(-raw // 1)), None, raw))
    for r in rows:
        if isinstance(r[12], float):
            r[12] = int(r[12])
    return write_file(path, d, rows), len(rows)


if __name__ == "__main__":
    base = Path(sys.argv[1])
    d = date(2026, 11, 5)
    rel = "exports/du_bao/20261105/du_bao_20261105_v3.xlsx"
    sha, n = big(base / "data" / rel, d)
    make_db(base / "data" / "db" / "app.db", [("E3", d.isoformat(), 3, rel, sha, n, old_ts())])
    print(n, sha)
