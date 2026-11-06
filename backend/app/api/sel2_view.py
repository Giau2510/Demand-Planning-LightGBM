"""1.4.4: the forecast pages read the published SEL2 run with the numbers of the daily Excel (ml/sel2/export.py).

The rows are built by export._rows - the owner's fixed rule (forecast_used / fallback_reason) is never re-implemented
here - from the same inputs as export.write_daily_export: the numbers of the run (export._run_values), the previous-run
numbers of D-3 .. D-1 (R3'), the AVG_DEMAND values of day D (seller rule of the settings), the forecast source per
SKU x FC and the product names. The run shown is "today's run" of its forecast day: for the newest run of that day the
rows equal those of the Excel of the day (horizon 1..7, sheets DU_BAO_<fc_code>); horizons 8..20 of the Excel are a
weekly estimate (cach_tinh UOC_TINH_THEO_TUAN) and are not shown on the pages.

One view (inputs + forecast_used per SKU x FC x horizon) is kept in memory for VIEW_TTL_SECONDS, keyed by the run,
the AVG_DEMAND read, the seller rule and the source configuration (a change of either builds a new view); at most ONE
view is cached (about 115 MiB at 58k SKU x FC, given back at the next build / expiry) and one build runs at a time.

Forecast source configuration of a run that HAS a daily Excel (export_runs.refresh_run_id = the run): the configuration
AS OF the newest such export (config_as_of: today's table with every later change of the append-only
forecast_source_config_history undone, newest first), so the page keeps showing the numbers of that file after a later
change. When the history cannot explain a row changed after the export (a row written without history),
config_flag = CONFIG_HISTORY_INCOMPLETE (shown in the info line). A run without an export uses today's configuration.
AVG_DEMAND of a run with a daily Excel of its own forecast day: the read and the seller rule that export recorded
(summary_json.avg: source_table, kind, completed_at, rule), so a later read of the day never changes the page; a later
read of the SAME table replaces the stored rows of the export's read (avg_demand_daily keeps the newest read per day and
table), and an export without that record (older format): the day's newest completed read with today's rule and
avg_flag = AVG_READ_NOT_PINNED (shown by the API; the numbers may differ from the file). An export written without any
completed read keeps no AVG_DEMAND value. A run without an export: the day's newest completed read (as the export would
do). The history page never builds a view: it reads the stored published rows (ml/sel2/published.py).
"""
from __future__ import annotations

import json
import math
import threading
import time
from datetime import date, timedelta

from .. import db
from .. import settings_service as ss
from ..ml.sel2 import avg_demand, export
from ..timeutil import VN_TZ, parse_iso

SEL2_PREFIX = "SEL2:"
HORIZON = export.HORIZON                 # the pages show horizon 1..7 (the SEL2 rows of the Excel)
VIEW_TTL_SECONDS = 600
COLS = export.COLUMNS
AVG_FLAG = "AVG_READ_NOT_PINNED"
_I = {c: i for i, c in enumerate(COLS)}
_lock = threading.Lock()
_cache: dict = {}


def is_sel2(run: dict | None) -> bool:
    return bool(run and str(run.get("config_version") or "").startswith(SEL2_PREFIX))


def vn_time(ts: str | None) -> str | None:
    dt = parse_iso(ts)
    return dt.astimezone(VN_TZ).strftime("%Y-%m-%d %H:%M:%S") if dt else None


class View:
    """Inputs of export._rows for one run + forecast_used per SKU x FC (7 horizons) for totals."""

    def __init__(self, c, run: dict):
        cfg = ss.get("sel2_pipeline", c)
        self.run = run
        self.d = d = date.fromisoformat(str(run["forecast_date"])[:10])
        self.days = days = [(d + timedelta(days=i)).isoformat() for i in range(HORIZON)]
        # as export.write_daily_export with the run as today's run (not stale, reference run = the run)
        self.run_keys, self.vals = export._run_values(c, run, days)
        prev_runs = export._previous_runs(c, run["scope_key"], d)
        need = {k for k in self.run_keys if self.vals.get(k) is None or None in self.vals[k]}
        self.prev = export._previous_values(c, prev_runs, days, need)
        pin = export_avg(c, run, cfg)
        av = _avg_values(c, d, pin) if pin["pinned"] else avg_demand.avg_value(d, conn=c, cfg=cfg)
        self.avg_flag = pin["flag"]
        self.avg_read = {"read_id": av["read_id"], "source_table": av["source_table"],
                         "completed_at": av["completed_at"]}
        exp = export_of(c, run["id"])
        self.export_run_id = exp["id"] if exp else None
        self.config_as_of = exp["created_at"] if exp else None
        self.conf, self.config_flag = config_as_of(c, self.config_as_of)
        self.names = export._names(c, d.isoformat(), av["source_table"])
        self.avg = av["values"]
        keys = set(self.run_keys) | set(self.avg)
        for k in keys:                                      # SKU x FC of the run without an AVG_DEMAND row
            if k not in self.avg:
                self.avg[k] = {"value": None, "reason": avg_demand.REASON_NO_ROW, "n_sellers": 0}
        self.keys = sorted(keys, key=lambda k: (k[1], k[0]))   # page order: fc_code, sku_code (then horizon)
        self.fcs = sorted({k[1] for k in self.keys})
        self.used: dict[tuple, tuple] = {}
        self.model: dict[tuple, str | None] = {}
        self.source: dict[tuple, str | None] = {}
        rows = self.rows(self.keys)
        i_used, i_m, i_s = _I["forecast_used"], _I["model_used"], _I["forecast_source"]
        for k in self.keys:
            g = [next(rows) for _ in range(HORIZON)]
            self.used[k] = tuple(r[i_used] for r in g)
            self.model[k] = next((r[i_m] for r in g if r[i_m]), None)
            self.source[k] = g[0][i_s]
        self.built_at = time.monotonic()

    def rows(self, keys):
        """export._rows of these SKU x FC (7 rows each, horizon 1..7, COLUMNS order)."""
        stats = {"rows_by_fallback_reason": {}, "flag_rows": {}}
        return export._rows(self.d, keys, self.run, self.run_keys, self.vals, self.avg, self.conf, self.names, False,
                            stats, self.prev, True)

    def filter(self, sku: str | None = None, fc: str | None = None, q: str | None = None,
               group: str | None = None) -> list[tuple]:
        """SKU x FC of the filters: sku / fc exact, q = part of the SKU, the FC or the product name (no case)."""
        s, f, qq = (sku or "").strip(), (fc or "").strip(), (q or "").strip().lower()
        out = []
        for k in self.keys:
            if (s and k[0] != s) or (f and k[1] != f):
                continue
            if group and (self.run_keys.get(k) or (None,))[0] != group:
                continue
            if qq and qq not in k[0].lower() and qq not in k[1].lower() and qq not in (self.names.get(k[0]) or "").lower():
                continue
            out.append(k)
        return out


def row_dict(r: list) -> dict:
    """An export row as a JSON object (dates as ISO strings)."""
    out = dict(zip(COLS, r))
    for c in ("forecast_date", "target_date", "data_cutoff_date"):
        if isinstance(out[c], date):
            out[c] = out[c].isoformat()
    for c in ("lightgbm_forecast", "avg_demand", "raw_value"):
        v = out[c]
        if isinstance(v, float) and not math.isfinite(v):
            out[c] = None
    return out


def _signature(c, run_id: str) -> tuple:
    d = db.one(c, "SELECT forecast_date FROM forecast_refresh_runs WHERE id=?", (run_id,))
    cfg = ss.get("sel2_pipeline", c)
    rd = avg_demand.latest_read(c, str(d["forecast_date"])[:10], cfg) if d else None
    # forecast_source_config: COUNT + MAX(updated_at) (one-second timestamps) AND the newest id of its append-only
    # history (AUTOINCREMENT, one row per change): two changes in the same second still give a new signature
    conf = c.execute("SELECT COUNT(*), MAX(updated_at) FROM forecast_source_config").fetchone()
    hist = c.execute("SELECT MAX(id) FROM forecast_source_config_history").fetchone()[0]
    exp = export_of(c, run_id)
    # any read of the day (the export's own read is pinned; a later read of its table replaces the rows)
    reads = c.execute("SELECT COUNT(*), MAX(rowid) FROM avg_demand_reads WHERE business_date=?",
                      (str(d["forecast_date"])[:10] if d else None,)).fetchone()
    return (run_id, rd["id"] if rd else None, cfg.avg_seller_rule, tuple(conf), hist, exp["id"] if exp else None,
            tuple(reads))


def export_of(c, run_id: str) -> dict | None:
    """Newest daily Excel written from this run (created_at, rowid), None without one."""
    return db.one(c, "SELECT id, created_at FROM export_runs WHERE refresh_run_id=? "
                     "ORDER BY created_at DESC, rowid DESC LIMIT 1", (run_id,))


def export_avg(c, run: dict, cfg=None) -> dict:
    """The AVG_DEMAND read the newest daily Excel of the run's own forecast day used: {pinned, read, rule, flag}.
    pinned False + flag None: no such export (the caller uses the day's newest read); pinned False + AVG_FLAG: not
    recorded, or the rows of that read were replaced by a later read of its table; pinned True + read None: the export
    had no completed read (no AVG_DEMAND value)."""
    cfg = cfg or ss.get("sel2_pipeline", c)
    day = str(run["forecast_date"])[:10]
    exp = db.one(c, "SELECT id, json_extract(summary_json, '$.avg') AS avg FROM export_runs WHERE refresh_run_id=? "
                    "AND forecast_date=? ORDER BY created_at DESC, rowid DESC LIMIT 1", (run["id"], day))
    if exp is None:
        return {"pinned": False, "read": None, "rule": None, "flag": None}
    try:
        a = json.loads(exp["avg"]) if exp["avg"] else None
    except ValueError:
        a = None
    if not isinstance(a, dict) or "completed_at" not in a or not a.get("rule"):
        return {"pinned": False, "read": None, "rule": None, "flag": AVG_FLAG}
    if a["completed_at"] is None:
        return {"pinned": True, "read": None, "rule": a["rule"], "flag": None}
    rd = db.one(c, "SELECT * FROM avg_demand_reads WHERE business_date=? AND source_table=? AND kind=? AND "
                   "completed_at=? ORDER BY rowid DESC LIMIT 1", (day, a.get("source_table"), a.get("source_kind"),
                                                                 a["completed_at"]))
    newest = db.one(c, "SELECT id FROM avg_demand_reads WHERE business_date=? AND source_table=? "
                       "ORDER BY completed_at DESC, rowid DESC LIMIT 1", (day, a.get("source_table")))
    if rd is None or newest is None or newest["id"] != rd["id"]:
        return {"pinned": False, "read": None, "rule": None, "flag": AVG_FLAG}
    return {"pinned": True, "read": rd, "rule": a["rule"], "flag": None}


def _avg_values(c, d: date, pin: dict) -> dict:
    """avg_demand.avg_value of day d for the pinned read and rule (same result shape)."""
    rd, groups = pin["read"], {}
    if rd:
        for r in c.execute("SELECT sku_code, fc_code, seller_code, avg_demand FROM avg_demand_daily "
                           "WHERE business_date=? AND source_table=? ORDER BY sku_code, fc_code, seller_code",
                           (d.isoformat(), rd["source_table"])):
            groups.setdefault((r[0], r[1]), []).append((r[2], r[3]))
    values = {}
    for k, sellers in groups.items():
        v, reason = avg_demand.apply_rule(sellers, pin["rule"])
        values[k] = {"value": v, "reason": reason, "n_sellers": len(sellers)}
    return {"business_date": d.isoformat(), "rule": pin["rule"], "read_id": rd["id"] if rd else None,
            "source_kind": rd["kind"] if rd else None, "source_table": rd["source_table"] if rd else None,
            "source_modified": rd["source_modified"] if rd else None,
            "completed_at": rd["completed_at"] if rd else None, "values": values}


def _incomplete(c, at: str) -> bool:
    """A configuration row changed after `at` without a history row after `at` (cannot be undone)."""
    return c.execute("SELECT 1 FROM forecast_source_config f WHERE f.updated_at > ? AND NOT EXISTS (SELECT 1 FROM "
                     "forecast_source_config_history h WHERE h.sku_code = f.sku_code AND h.fc_code = f.fc_code AND "
                     "h.changed_at > ?) LIMIT 1", (at, at)).fetchone() is not None


def config_as_of(c, at: str | None) -> tuple[dict, str | None]:
    """({(sku, fc): forecast_source}, flag) of the configuration at `at` (UTC ISO; None = today's): today's rows with
    every history change after `at` undone, newest first (old_source NULL = the key was not configured)."""
    conf = {(r[0], r[1]): r[2] for r in c.execute("SELECT sku_code, fc_code, forecast_source FROM forecast_source_config")}
    if not at:
        return conf, None
    for sku, fc, old in c.execute("SELECT sku_code, fc_code, old_source FROM forecast_source_config_history "
                                  "WHERE changed_at > ? ORDER BY id DESC", (at,)):
        if old is None:
            conf.pop((sku, fc), None)
        else:
            conf[(sku, fc)] = old
    return conf, ("CONFIG_HISTORY_INCOMPLETE" if _incomplete(c, at) else None)


def view(c, run_id: str) -> View | None:
    """The view of a SEL2 run (None for a run that is not SEL2 / does not exist)."""
    run = db.one(c, "SELECT * FROM forecast_refresh_runs WHERE id=?", (run_id,))
    if not is_sel2(run):
        return None
    sig = _signature(c, run_id)
    with _lock:
        v = _cache.get("view")
        if v is not None and _cache.get("sig") == sig and time.monotonic() - v.built_at < VIEW_TTL_SECONDS:
            return v
        _cache.clear()                                      # one view at a time (memory)
        v = View(c, run)
        _cache.update(view=v, sig=sig)
        return v


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def page(v: View, keys: list[tuple], horizon: int | None, offset: int, limit: int,
         date_from: str | None = None, date_to: str | None = None, h_max: int | None = None) -> tuple[int, list[dict]]:
    """(total rows, rows of one page) of these SKU x FC: horizon = one horizon, h_max = horizons 1..h_max, date_from /
    date_to = target date range; order = the order of `keys` (given by the caller), then horizon."""
    hs = [h for h in range(1, HORIZON + 1) if (horizon is None or h == horizon) and (h_max is None or h <= h_max)
          and (not date_from or v.days[h - 1] >= date_from) and (not date_to or v.days[h - 1] <= date_to)]
    per = len(hs)
    total = per * len(keys)
    if not per or offset >= total:
        return total, []
    k0, k1 = offset // per, -(-(offset + limit) // per)
    sel = set(hs)
    rows = [r for r in v.rows(keys[k0:k1]) if r[_I["horizon"]] in sel]
    start = offset - k0 * per
    return total, [row_dict(r) for r in rows[start:start + limit]]


def latest_run(c, scope_key: str | None) -> dict | None:
    """Newest published SEL2 run of the scope (forecast_date, created_at, rowid)."""
    if scope_key is None:
        return None
    return db.one(c, "SELECT id, scope_key, forecast_date, data_as_of, created_at, model_version, config_version "
                     "FROM forecast_refresh_runs WHERE scope_key=? AND status='PUBLISHED' AND config_version LIKE ? "
                     "ORDER BY forecast_date DESC, created_at DESC, rowid DESC LIMIT 1", (scope_key, SEL2_PREFIX + "%"))


def info(c, scope_key: str | None) -> dict:
    """The info line of the forecast pages: source (SEL2 run / LightGBM cu / Avg), refresh time (VN), data cut-off
    date of the run the Daily Forecast page shows = the newest PUBLISHED refresh run of the scope (SEL2, or a 1.3.1
    refresh run after the emergency switch-off: LIGHTGBM_CU); else the newest 1.3.x forecast run; else the newest
    AVG_DEMAND read. source None when the scope has no forecast at all."""
    r = db.one(c, "SELECT id, forecast_date, data_as_of, created_at, config_version FROM forecast_refresh_runs "
                  "WHERE scope_key=? AND status='PUBLISHED' ORDER BY forecast_date DESC, created_at DESC, rowid DESC "
                  "LIMIT 1", (scope_key,)) if scope_key is not None else None
    if r:
        out = {"source": "SEL2" if is_sel2(r) else "LIGHTGBM_CU", "run_id": r["id"],
               "refreshed_at": vn_time(r["created_at"]), "data_cutoff_date": r["data_as_of"],
               "forecast_date": r["forecast_date"]}
        exp = export_of(c, r["id"]) if is_sel2(r) else None
        if exp and _incomplete(c, exp["created_at"]):         # the page cannot rebuild the file's configuration
            out["config_flag"] = "CONFIG_HISTORY_INCOMPLETE"
        if is_sel2(r) and (flag := export_avg(c, r)["flag"]):   # the page cannot use the file's AVG_DEMAND read
            out["avg_flag"] = flag
        return out
    if scope_key is not None:
        old = db.one(c, "SELECT id, created_at, data_as_of FROM forecast_runs WHERE scope_key=? "
                        "ORDER BY created_at DESC, rowid DESC LIMIT 1", (scope_key,))
        if old:
            return {"source": "LIGHTGBM_CU", "run_id": old["id"], "refreshed_at": vn_time(old["created_at"]),
                    "data_cutoff_date": old["data_as_of"], "forecast_date": None}
    rd = db.one(c, "SELECT business_date, completed_at FROM avg_demand_reads WHERE completed_at IS NOT NULL "
                   "ORDER BY business_date DESC, completed_at DESC, rowid DESC LIMIT 1")
    if rd:
        return {"source": "AVG", "run_id": None, "refreshed_at": vn_time(rd["completed_at"]),
                "data_cutoff_date": None, "forecast_date": rd["business_date"]}
    return {"source": None, "run_id": None, "refreshed_at": None, "data_cutoff_date": None, "forecast_date": None}
