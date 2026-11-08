"""1.4.0 SEL2 storage (migration 0012): candidate trainings + model files, candidate forecasts of a day, the history
read of the selection, retention, and the publication of the selected forecast into the 1.3.1 tables
forecast_refresh_runs / forecast_refresh_values (marked config_version 'SEL2:<hash>').

Model files: <models dir>/sel2/<scope hash>/<origin>/<model>_<run id>.txt (LightGBM) or <model>_clf_<run id>.txt +
<model>_reg_<run id>.txt (two-stage): two trainings never write the same file; paths + sha256 recorded in
candidate_train_runs.model_files_json, every load reads the recorded paths and verifies the sha256.
A training writes its pid into candidate_train_runs.detail_json while RUNNING; start_train marks a RUNNING record of the
scope as FAILED (INTERRUPTED) when its process is gone or it is older than train_timeout_seconds + 10 minutes.
candidate_forecasts has no scope / run column: a day belongs to the scope of its candidate_runs (one SUCCEEDED run per
scope_key x forecast_date x model); a whole day is written in ONE transaction (the day's rows of its models deleted,
then inserted sorted by the primary key) and a day that has runs of another scope is refused (SEL2_SCOPE_CONFLICT)."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, timedelta
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from ... import db, paths
from ... import settings_service as ss
from ...timeutil import now_iso, parse_iso
from .errors import MODEL_FILE_MISMATCH, SCOPE_CONFLICT, Sel2Error

CONFIG_PREFIX = "SEL2:"
HIST_ROWS = 200_000
STALE_TRAIN_MARGIN_S = 600      # a RUNNING training older than train_timeout_seconds + this is interrupted
INTERRUPTED = "INTERRUPTED"


# ------------------------------------------------------------------ trainings
def scope_dir(scope_key: str) -> Path:
    """<models dir>/sel2/<12 hex of the scope key> (a scope key holds ':' and '.', not used as a folder name)."""
    return paths.models_dir() / "sel2" / hashlib.sha256(str(scope_key).encode()).hexdigest()[:12]


def model_dir(origin, scope_key: str) -> Path:
    return scope_dir(scope_key) / str(origin)


def pid_alive(pid: int) -> bool:
    """True when a process with this id runs (a reused id counts as running: the age rule still applies)."""
    if os.name == "nt":
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = ctypes.c_void_p
        h = k32.OpenProcess(0x1000, False, int(pid))            # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5                  # ACCESS_DENIED: exists, owned by another user
        try:
            code = ctypes.c_ulong()
            ok = k32.GetExitCodeProcess(ctypes.c_void_p(h), ctypes.byref(code))
            return not ok or code.value == 259                   # STILL_ACTIVE
        finally:
            k32.CloseHandle(ctypes.c_void_p(h))
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def succeeded_train(conn, scope_key: str, model: str, origin) -> dict | None:
    return db.one(conn, "SELECT * FROM candidate_train_runs WHERE scope_key=? AND model=? AND origin_date=? AND "
                        "status='SUCCEEDED' ORDER BY created_at DESC, rowid DESC LIMIT 1", (scope_key, model, str(origin)))


def mark_interrupted(scope_key: str) -> list[str]:
    """RUNNING trainings of the scope whose process is gone (recorded pid, not this process) or older than
    sel2_pipeline.train_timeout_seconds + STALE_TRAIN_MARGIN_S -> FAILED with detail INTERRUPTED (their files, if any,
    are never loaded: only a SUCCEEDED record is)."""
    limit = int(ss.get("sel2_pipeline").train_timeout_seconds) + STALE_TRAIN_MARGIN_S
    now = parse_iso(now_iso())
    done = []
    with db.tx() as c:
        for r in db.rows(c, "SELECT id, created_at, detail_json FROM candidate_train_runs WHERE scope_key=? AND "
                            "status='RUNNING'", (scope_key,)):
            try:
                pid = (json.loads(r["detail_json"] or "{}") or {}).get("pid")
            except ValueError:
                pid = None
            old = (now - parse_iso(r["created_at"])).total_seconds() > limit
            gone = pid is not None and int(pid) != os.getpid() and not pid_alive(int(pid))
            if old or gone:
                c.execute("UPDATE candidate_train_runs SET status='FAILED', finished_at=?, detail_json=? WHERE id=? "
                          "AND status='RUNNING'", (now_iso(), json.dumps({"error": INTERRUPTED, "pid": pid,
                                                                         "reason": "AGE" if old else "PROCESS_GONE"}),
                                                   r["id"]))
                done.append(r["id"])
    return done


def start_train(scope_key: str, model: str, origin, job_id=None) -> str:
    """A RUNNING record (pid of this process in detail_json), after the interrupted ones of the scope are closed."""
    mark_interrupted(scope_key)
    rid = db.new_id("CTR")
    with db.tx() as c:
        c.execute("INSERT INTO candidate_train_runs(id, scope_key, model, origin_date, status, job_id, created_at, "
                  "detail_json) VALUES (?,?,?,?, 'RUNNING', ?,?,?)",
                  (rid, scope_key, model, str(origin), job_id, now_iso(), json.dumps({"pid": os.getpid()})))
    return rid


def fail_train(run_id: str, err: BaseException) -> None:
    with db.tx() as c:
        c.execute("UPDATE candidate_train_runs SET status='FAILED', finished_at=?, detail_json=? WHERE id=?",
                  (now_iso(), json.dumps({"error": f"{type(err).__name__}: {err}"[:500]}), run_id))


def finish_train(run_id: str, model: str, origin, models: dict, info: dict, data_as_of: str, seconds: float) -> dict:
    """Model files of this run (its id in the names; temporary name, then replaced) written and hashed, the run
    SUCCEEDED with its configuration."""
    with db.read() as c:
        scope_key = c.execute("SELECT scope_key FROM candidate_train_runs WHERE id=?", (run_id,)).fetchone()[0]
    d = model_dir(origin, scope_key)
    d.mkdir(parents=True, exist_ok=True)
    files = {}
    for part, m in models.items():
        p = d / (f"{model}_{run_id}.txt" if len(models) == 1 else f"{model}_{part}_{run_id}.txt")
        tmp = p.with_suffix(".tmp")
        m.save_model(str(tmp))
        os.replace(tmp, p)
        files[part] = {"path": str(p.relative_to(paths.models_dir())), "sha256": _sha(p)}
    cfg = info["cfg"]
    detail = {"names": info["names"], "sku_codes": info["sku_codes"], "fc_codes": info["fc_codes"],
              "decisions": info["decisions"], "config_fingerprint": info.get("config_fingerprint"),
              "flags": info.get("flags", []), "label_start": info.get("label_start"), "label_end": info.get("label_end"),
              "n_origins": info.get("n_origins"), "n_rows_positive": info.get("n_rows_positive")}
    if info.get("spike_cleaning") is not None:          # 1.4.8: only when spike cleaning is ON
        detail["spike_cleaning"] = info["spike_cleaning"]
    with db.tx() as c:
        c.execute("UPDATE candidate_train_runs SET status='SUCCEEDED', data_as_of=?, config_json=?, fingerprint=?, "
                  "model_files_json=?, n_rows=?, n_series=?, n_features=?, train_seconds=?, finished_at=?, detail_json=? "
                  "WHERE id=?", (data_as_of, cfg.model_dump_json(), info.get("config_fingerprint"), json.dumps(files),
                                 int(info["n_rows"]), int(info["n_series"]), int(info["n_features"]), round(seconds, 1),
                                 now_iso(), json.dumps(detail, default=str), run_id))
    return files


def load_train(run: dict) -> tuple[dict, dict]:
    """(models, trained info for lgbm.forecast) of a SUCCEEDED training; every file checked against its sha256."""
    files = json.loads(run["model_files_json"] or "{}")
    models = {}
    for part, f in files.items():
        p = paths.models_dir() / f["path"]
        if not p.exists() or _sha(p) != f["sha256"]:
            raise Sel2Error(MODEL_FILE_MISMATCH, detail=f"{run['id']}: {f['path']}")
        models[part] = lgb.Booster(model_file=str(p))
    if not models:
        raise Sel2Error(MODEL_FILE_MISMATCH, detail=f"{run['id']}: no model file")
    det = json.loads(run["detail_json"])
    trained = {"cfg": ss.ModelSettings.model_validate_json(run["config_json"]), "names": det["names"],
               "sku_codes": det["sku_codes"], "fc_codes": det["fc_codes"]}
    return models, trained


# ------------------------------------------------------------------ candidate forecasts of a day
def day_runs(conn, scope_key: str, d) -> list[dict]:
    return db.rows(conn, "SELECT * FROM candidate_runs WHERE scope_key=? AND forecast_date=? AND status='SUCCEEDED' "
                         "ORDER BY model", (scope_key, str(d)))


def day_complete(conn, scope_key: str, d, models) -> bool:
    """Every model has a SUCCEEDED run of the day AND stored rows (a day whose rows were purged by apply_retention is
    computed again, never selected on empty rows)."""
    have = {r["model"] for r in day_runs(conn, scope_key, d)}
    if not have >= set(models):
        return False
    return all(conn.execute("SELECT 1 FROM candidate_forecasts WHERE forecast_date=? AND model=? LIMIT 1",
                            (str(d), m)).fetchone() for m in models)


def write_day(scope_key: str, d: date, data_as_of: date, cands: dict, train_ids: dict, flags: dict, job_id=None,
              detail: dict | None = None) -> int:
    """cands: model -> frame (sku_code, fc_code, horizon, value). ONE transaction: refuse a day of another scope, delete
    the day's runs and rows of these models, insert the runs, then the rows sorted by the primary key."""
    if not data_as_of < d:
        raise ValueError(f"data_as_of {data_as_of} must be before the forecast day {d}")
    names = sorted(cands)
    parts = []
    for m in names:
        f = cands[m]
        v = f["value"].to_numpy(dtype=float)
        if not np.isfinite(v).all() or (v < 0).any():
            raise ValueError(f"{m}: missing, infinite or negative value")
        parts.append(pd.DataFrame({"sku_code": f["sku_code"].to_numpy(dtype=object), "fc_code": f["fc_code"].to_numpy(dtype=object),
                                   "model": m, "horizon": f["horizon"].to_numpy().astype(np.int64), "value": v}))
    rows = pd.concat(parts, ignore_index=True).sort_values(["sku_code", "fc_code", "model", "horizon"], kind="stable")
    ds = str(d)
    tds = {h: str(d + timedelta(days=h - 1)) for h in range(1, 8)}
    qs = ",".join("?" * len(names))
    at = now_iso()
    with db.tx() as c:
        other = c.execute("SELECT DISTINCT scope_key FROM candidate_runs WHERE forecast_date=? AND scope_key<>?",
                          (ds, scope_key)).fetchall()
        if other:
            raise Sel2Error(SCOPE_CONFLICT, detail=f"{ds}: runs of {', '.join(r[0] for r in other)}")
        c.execute(f"DELETE FROM candidate_forecasts WHERE forecast_date=? AND model IN ({qs})", (ds, *names))
        c.execute(f"DELETE FROM candidate_runs WHERE scope_key=? AND forecast_date=? AND model IN ({qs})",
                  (scope_key, ds, *names))
        for m, f in zip(names, parts):
            c.execute("INSERT INTO candidate_runs(id, scope_key, forecast_date, data_as_of, model, train_run_id, status, "
                      "n_series, flags, created_at, job_id, detail_json) VALUES (?,?,?,?,?,?, 'SUCCEEDED', ?,?,?,?,?)",
                      (db.new_id("CR"), scope_key, ds, str(data_as_of), m, train_ids.get(m),
                       int(f[["sku_code", "fc_code"]].drop_duplicates().shape[0]), ",".join(flags.get(m, [])) or None,
                       at, job_id, json.dumps((detail or {}).get(m, {}), default=str)))
        n = c.executemany("INSERT INTO candidate_forecasts(forecast_date, sku_code, fc_code, model, horizon, target_date, "
                          "value) VALUES (?,?,?,?,?,?,?)",
                          ((ds, s, f, m, int(h), tds[int(h)], float(v)) for s, f, m, h, v in
                           zip(rows["sku_code"], rows["fc_code"], rows["model"], rows["horizon"], rows["value"]))).rowcount
    return n


def read_day(conn, scope_key: str, d) -> dict:
    """model -> frame (sku_code, fc_code, horizon, value) of the day's SUCCEEDED candidate runs of the scope."""
    out = {}
    for r in day_runs(conn, scope_key, d):
        out[r["model"]] = pd.DataFrame(conn.execute(
            "SELECT sku_code, fc_code, horizon, value FROM candidate_forecasts WHERE forecast_date=? AND model=?",
            (str(d), r["model"])).fetchall(), columns=["sku_code", "fc_code", "horizon", "value"])
    return out


class History:
    """Reader of the stored candidate forecasts of forecast days D-(window+6) .. D-1 of the scope for select_day, one
    candidate at a time, with integer key ids (no frame of strings for the whole history)."""

    def __init__(self, conn, scope_key: str, d: date, window_days: int = 28, horizons: int = 7):
        self.conn, self.scope_key, self.d = conn, scope_key, d
        self.lo = d - timedelta(days=window_days + horizons - 1)
        self.kid: dict = {}
        self.key_list: list = []

    def keys(self) -> pd.DataFrame:
        return pd.DataFrame(self.key_list or np.empty((0, 2), dtype=object), columns=["sku_code", "fc_code"])

    def __call__(self, model: str):
        days = [r[0] for r in self.conn.execute(
            "SELECT DISTINCT forecast_date FROM candidate_runs WHERE scope_key=? AND model=? AND status='SUCCEEDED' "
            "AND forecast_date BETWEEN ? AND ? ORDER BY forecast_date", (self.scope_key, model, str(self.lo),
                                                                         str(self.d - timedelta(days=1))))]
        kid, f, hz, val = [], [], [], []
        for ds in days:
            off = (date.fromisoformat(ds) - self.d).days
            cur = self.conn.execute("SELECT sku_code, fc_code, horizon, value FROM candidate_forecasts WHERE "
                                    "forecast_date=? AND model=? AND horizon BETWEEN 1 AND 7", (ds, model))
            while True:
                part = cur.fetchmany(HIST_ROWS)
                if not part:
                    break
                ids = np.empty(len(part), dtype=np.int32)
                for i, (s, fc, _, _) in enumerate(part):
                    k = self.kid.get((s, fc))
                    if k is None:
                        k = self.kid[(s, fc)] = len(self.key_list)
                        self.key_list.append((s, fc))
                    ids[i] = k
                kid.append(ids)
                f.append(np.full(len(part), off, dtype=np.int16))
                hz.append(np.fromiter((r[2] for r in part), dtype=np.int8, count=len(part)))
                val.append(np.fromiter((r[3] for r in part), dtype=np.float64, count=len(part)))
        cat = (lambda xs, t: np.concatenate(xs) if xs else np.zeros(0, dtype=t))
        return self.keys(), {"kid": cat(kid, np.int32), "f": cat(f, np.int16), "horizon": cat(hz, np.int8),
                             "value": cat(val, np.float64)}


def apply_retention(d: date, retention_days: int) -> dict:
    """candidate_forecasts of forecast days before d - retention_days deleted, one forecast day per transaction (the
    run records are kept; day_complete of a purged day is False, so a later request computes it again)."""
    cutoff = str(d - timedelta(days=int(retention_days)))
    with db.read() as c:
        days = [r[0] for r in c.execute("SELECT DISTINCT forecast_date FROM candidate_runs WHERE forecast_date < ? "
                                        "ORDER BY forecast_date", (cutoff,))]
    n = 0
    for ds in days:
        with db.tx() as c:
            n += c.execute("DELETE FROM candidate_forecasts WHERE forecast_date=?", (ds,)).rowcount
    return {"cutoff": cutoff, "days": len(days), "rows": n}


# ------------------------------------------------------------------ publication (1.3.1 refresh tables)
def config_version(sel2_cfg) -> str:
    """'SEL2:' + 12 hex of the selection settings (the marking of a SEL2 run in forecast_refresh_runs)."""
    keys = ("p_threshold", "window_days", "min_days", "fallback_model", "group_mode", "group_fixed_start",
            "group_fixed_end", "open_hours_lag_days", "tsb_alpha", "tsb_beta", "tsb_start")
    dump = {k: getattr(sel2_cfg, k) for k in keys}
    if getattr(sel2_cfg, "spike_cleaning", False):      # 1.4.8: only when ON, so OFF keeps the 1.4.6 value
        dump.update(spike_cleaning=True, spike_e4_n=int(sel2_cfg.spike_e4_n))
    return CONFIG_PREFIX + hashlib.sha256(json.dumps(dump, sort_keys=True, default=str).encode()).hexdigest()[:12]


def published_run(conn, scope_key: str, d) -> dict | None:
    return db.one(conn, "SELECT * FROM forecast_refresh_runs WHERE scope_key=? AND forecast_date=? AND "
                        "config_version LIKE 'SEL2:%' ORDER BY created_at DESC, rowid DESC LIMIT 1", (scope_key, str(d)))


def publish(scope_key: str, d: date, sel: pd.DataFrame, groups: pd.Series, flags: list, model_version: str, cv: str,
            trigger: str, job_id=None, detail: dict | None = None) -> tuple[str, int]:
    """ONE PUBLISHED forecast_refresh_runs record + its values (never updated): lgb_raw = SEL2 raw value, final_qty =
    published, method = model_used, group_code, flags = the run's flags. Returns (run id, values written)."""
    trial = bool(ss.get("daily_forecast").trial_mode)
    run_id = db.new_id("FRR")
    fl = ",".join(flags) or None
    gk = pd.MultiIndex.from_arrays([sel["sku_code"].to_numpy(), sel["fc_code"].to_numpy()])
    grp = groups.reindex(gk).to_numpy(dtype=object) if len(groups) else np.full(len(sel), None, dtype=object)
    td = pd.to_datetime(sel["target_date"]).dt.strftime("%Y-%m-%d").to_numpy()
    series = sel.drop_duplicates(["sku_code", "fc_code"])
    n_fb = int(series["model_used"].astype(str).str.startswith("FALLBACK:").sum())
    with db.tx() as c:
        c.execute("INSERT INTO forecast_refresh_runs(id, scope_key, forecast_date, data_as_of, status, trigger, "
                  "training_run_id, model_version, model_fingerprint, config_version, trial_mode, horizon, n_series, "
                  "n_lightgbm, n_fallback, group_computed_for, job_id, created_at, detail_json) "
                  "VALUES (?,?,?,?, 'PUBLISHED', ?, NULL, ?, NULL, ?,?,?,?,?,?,?,?,?,?)",
                  (run_id, scope_key, str(d), str(d - timedelta(days=1)), trigger, model_version, cv, int(trial),
                   int(sel["horizon"].max()), len(series), len(series) - n_fb, n_fb, str(d), job_id, now_iso(),
                   json.dumps(detail or {}, default=str)))
        n = c.executemany("INSERT INTO forecast_refresh_values(run_id, horizon, target_date, fc_code, sku_code, lgb_raw, "
                          "final_qty, method, group_code, flags) VALUES (?,?,?,?,?,?,?,?,?,?)",
                          ((run_id, int(h), t, f, s, float(r), int(q), str(m), None if g is None or g != g else g, fl)
                           for h, t, f, s, r, q, m, g in zip(sel["horizon"], td, sel["fc_code"], sel["sku_code"],
                                                              sel["raw_value"], sel["published"], sel["model_used"],
                                                              grp))).rowcount
        db.audit(c, "DAILY_FORECAST_PUBLISHED", "forecast_refresh_run", run_id,
                 {"forecast_date": str(d), "model_version": model_version, "rows": n, "config_version": cv,
                  "trial_mode": trial, "trigger": trigger, "pipeline": "SEL2"})
    return run_id, n
