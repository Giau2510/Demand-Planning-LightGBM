"""Peak memory of the heaviest step of a DIRECT training (final model on the full panel + 15-day forecast), measured
with GetProcessMemoryInfo (PeakWorkingSetSize / PeakPagefileUsage). Isolated DB copy, read-only. Usage: peak_mem_l7.py <db>"""
import ctypes
import ctypes.wintypes as wt
import json
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, r"D:\Buymed\Lightgbm AI\backend")
from app import settings_service as ss                 # noqa: E402
from app.ml import model                               # noqa: E402
from app.ml.features import build_panel                # noqa: E402


class PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


k32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
k32.GetCurrentProcess.restype = wt.HANDLE
psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(PMC), wt.DWORD]
psapi.GetProcessMemoryInfo.restype = wt.BOOL


def mem():
    c = PMC()
    c.cb = ctypes.sizeof(PMC)
    assert psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb)
    return {"peak_working_set_gb": round(c.PeakWorkingSetSize / 2**30, 2),
            "peak_private_gb": round(c.PeakPagefileUsage / 2**30, 2)}


db = Path(sys.argv[1])
assert "scratchpad" in str(db).lower()
c = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)
r = c.execute("SELECT feature_config_json, train_start, train_end FROM training_runs WHERE id='TRN-20261016095451-697A11'").fetchone()
cfg = ss.ModelSettings(**{**json.loads(r[0])["config"], "forecast_strategy": "DIRECT"})
d = pd.read_sql_query("SELECT order_date, sku_id, fc_id, qty, n_orders, avg_unit_price, avg_discount_rate, promo_share, "
                      "voucher_share FROM demand_daily WHERE scope_key=? AND order_date>=? AND order_date<=?", c,
                      params=["BIGQUERY:lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm", r[1], r[2]])
c.close()
p = build_panel(d, max_days=cfg.max_train_days)
del d
print("after load", mem(), flush=True)
t = time.time()
b, info = model.train(p, cfg)
print("after final train", round(time.time() - t, 1), "s rows", info["n_rows"], mem(), flush=True)
model.forecast(p, b, cfg, 15)
print("after forecast", mem(), flush=True)
