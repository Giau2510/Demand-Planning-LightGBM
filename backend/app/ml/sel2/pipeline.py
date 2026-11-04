"""1.4.0 SEL2 daily pipeline (settings section sel2_pipeline; enabled = False is the emergency switch: nothing here runs
or writes, every entry point raises / returns SEL2_DISABLED).

  train_week(origin)        the 3 LightGBM candidates (MOC -> V33_L112 -> V36_two_stage, sequential) of a weekly origin
                            (the retraining weekday, Monday by default): data < origin, scope of the origin; each finished
                            model is a SUCCEEDED candidate_train_runs record (checkpoint: a re-run skips it); free commit
                            checked before each model (SEL2_LOW_MEMORY, retryable); one training of a scope at a time
                            across processes (OS lock on <models>/sel2/<scope hash>/train.lock, else SEL2_TRAIN_BUSY,
                            retryable)
  candidates_for_day(D)     the 6 candidates of D for the series in scope(D): the 3 LightGBM with the models of D's week
                            (or the week before, flag MODEL_PREV_WEEK) + TSB / DOW4 / AVG7; one stored day
  select_and_publish(D)     SEL2 (select.select_day) on the stored candidates of D and of D-34 .. D-1; publication into
                            forecast_refresh_runs / values (config_version 'SEL2:...')
  run_day(D)                free commit >= DAY_MIN_COMMIT_MB (else SEL2_LOW_MEMORY, retryable) -> inputs (open-hours lag
                            rule, data.py) -> candidates -> selection -> publication -> retention
                            -> export hook (app.ml.sel2.export.write_daily_export when that module exists)
  replay(...)               reproduction on a DB COPY: trains the needed origins, candidates + SEL2 of every day, parquet
                            files (candidates.parquet read and written in row groups), nothing published
  bootstrap(days)           first start: the training of today's origin, today's candidates and a TEMPORARY Excel
                            (V33_L112 for every SKU x FC, du_bao_YYYYMMDD_TAM.xlsx, not published), then the other
                            origins covering the last `days` days (28 by default), the candidates of every past day,
                            then run_day(today)
  openhours_backfill(...)   one-time read of the open-hours history (read-only BigQuery, dry run + byte cap)
Every step is resumable: a finished training or a stored day is skipped unless forced. run_day, select_and_publish and
replay log one line per step (seconds, private MB of the process now and its peak: _progress)."""
from __future__ import annotations

import gc
import json
import logging
import os
import time
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ... import db
from ... import settings_service as ss
from ...data.demand import resolve_scope
from ...jobs import resources
from ...timeutil import today_vn
from . import data, lgbm, select, simple, store
from .errors import (DISABLED, EMPTY_SCOPE, HISTORY_INVALID, LOW_MEMORY, MISSING_FORECAST, NO_MODEL, ORIGIN_INVALID,
                     TRAIN_FAILED, Sel2Error, mapped)

log = logging.getLogger("df.sel2")
TRAIN_ORDER = ("MOC", "V33_L112", "V36_two_stage")
NAME = {"MOC": "MOC", "V33_L112": "V33_L112", "V36_two_stage": "V36_two_stage@0.6"}
MODELS = select.CANDIDATES
FLAG_MODEL_PREV_WEEK = "MODEL_PREV_WEEK"
MIN_COMMIT_MB = 3072            # free commit (RAM + page file) needed before each training
DAY_MIN_COMMIT_MB = 1500        # free commit needed to start a day's run (candidates + SEL2 + publication)
TRAIN_BUSY = "SEL2_TRAIN_BUSY"  # another process trains the same scope (retryable; = jobs.TRAIN_BUSY)
OPEN_HOURS_READ_DAYS = 15
BACKTEST_HISTORY_FLOOR = date(2026, 6, 1)
# candidates.parquet of replay: row groups of CANDIDATE_EXPORT_ROWS rows (= pyarrow's default row group of the former
# one-frame DataFrame.to_parquet), read CANDIDATE_READ_ROWS at a time (a multiple of 1024, pyarrow's write batch)
CANDIDATE_EXPORT_ROWS = 1 << 20
CANDIDATE_READ_ROWS = 1 << 18
CANDIDATE_COLUMNS = ["forecast_date", "sku_code", "fc_code", "model", "horizon", "target_date", "value"]


def settings():
    s = ss.get("sel2_pipeline")
    if not s.enabled:
        raise Sel2Error(DISABLED)
    return s


def _scope(scope_key):
    if scope_key:
        return scope_key
    with db.read() as c:
        return resolve_scope(c)["scope_key"]


def origin_of(d: date, weekday: int = 1) -> date:
    """The training origin of forecast day d: the latest retraining weekday (ISO, 1 = Monday) on or before d."""
    return d - timedelta(days=(d.isoweekday() - weekday) % 7)


def backtest_history_start(d: date) -> date:
    """History start of the backtest's FINAL2 runs (ct_step5.py): max(2026-06-01, first day of d's month - 35 days)."""
    return max(BACKTEST_HISTORY_FLOOR, d.replace(day=1) - timedelta(days=35))


def load(scope_key: str, d: date, s=None) -> data.Inputs:
    s = s or settings()
    with db.read() as c:
        return data.load_inputs(c, scope_key, d, s.open_hours_lag_days)


def _memory_gate(min_mb: int | None = None) -> None:
    need = MIN_COMMIT_MB if min_mb is None else min_mb
    avail = resources.snapshot().get("commit_avail")
    if avail is not None and avail / resources.MB < need:
        raise Sel2Error(LOW_MEMORY, detail=f"free commit {avail / resources.MB:.0f} MB < {need} MB")


def _memory_mb() -> dict:
    """Private MB of this process now and its peak since it started (Windows: PeakPagefileUsage of the counters
    resources reads; elsewhere the peak working set). None when the platform gives no reading; never raises."""
    s = resources.snapshot()
    peak = s.get("ws_peak_lifetime")
    pmc = getattr(resources, "_PMC", None)          # Windows only
    if pmc is not None:
        try:
            import ctypes
            p = pmc()
            p.cb = ctypes.sizeof(p)
            if resources._psapi.GetProcessMemoryInfo(resources._k32.GetCurrentProcess(), ctypes.byref(p), p.cb):
                peak = p.PeakPagefileUsage
        except Exception:  # noqa: BLE001 - a reading never fails a run
            pass
    mb = (lambda v: None if v is None else round(v / resources.MB))
    return {"private_mb": mb(s.get("private")), "peak_private_mb": mb(peak)}


def _progress(run: str, **ctx):
    """Step logger of a run: each call logs ONE line "sel2 <run> step" with the step name, its seconds (since the
    previous step or the start), the private MB of the process now and its peak, and the given counts."""
    t = [time.monotonic()]

    def step(name: str, **counts) -> None:
        now = time.monotonic()
        log.info(f"sel2 {run} step", extra={"ctx": {**ctx, "step": name, "seconds": round(now - t[0], 1),
                                                     **_memory_mb(), **counts}})
        t[0] = now
    return step


@contextmanager
def train_lock(scope_key: str):
    """Exclusive OS lock (msvcrt / fcntl, released by the OS when the process ends: no stale lock) on
    <models>/sel2/<scope hash>/train.lock while a process trains the scope; held elsewhere -> SEL2_TRAIN_BUSY (retryable)."""
    p = store.scope_dir(scope_key) / "train.lock"
    p.parent.mkdir(parents=True, exist_ok=True)
    f = open(p, "a+b")
    try:
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            e = Sel2Error(TRAIN_BUSY, detail=f"another process trains scope {scope_key}")
            e.retryable = True
            raise e from None
        try:
            yield
        finally:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
    finally:
        f.close()


def _tuples(keys: pd.DataFrame) -> list:
    return list(zip(keys["sku_code"], keys["fc_code"]))


# ------------------------------------------------------------------ training
def train_week(origin: date, models=None, cancel=None, inputs: data.Inputs | None = None, scope_key=None,
               job_id=None) -> dict:
    s = settings()
    scope_key = _scope(scope_key)
    if origin.isoweekday() != s.retrain_weekday:
        raise Sel2Error(ORIGIN_INVALID, detail=f"{origin} is not ISO weekday {s.retrain_weekday}")
    with train_lock(scope_key):
        return _train_week(s, origin, models, cancel, inputs, scope_key, job_id)


def _train_week(s, origin, models, cancel, inputs, scope_key, job_id) -> dict:
    out = {"origin": str(origin), "trained": [], "skipped": []}
    for m in models or TRAIN_ORDER:
        with db.read() as c:
            if store.succeeded_train(c, scope_key, m, origin):
                out["skipped"].append(m)
                continue
        _memory_gate()
        if inputs is None:
            inputs = load(scope_key, origin, s)
        keys = _tuples(inputs.scope_keys(origin))
        rid = store.start_train(scope_key, m, origin, job_id)
        t = time.monotonic()
        try:
            with mapped(TRAIN_FAILED):
                trained, info = lgbm.train(inputs.frame, origin, keys, lgbm.CANDIDATE_SPECS[m], cancel)
            data_as_of = str(lgbm.rows_before(inputs.frame, origin)["od"].max().date())
            store.finish_train(rid, m, origin, trained, info, data_as_of, time.monotonic() - t)
        except BaseException as e:
            store.fail_train(rid, e)
            raise
        del trained
        resources.release_memory()
        out["trained"].append(m)
        log.info("sel2 candidate trained", extra={"ctx": {"model": m, "origin": str(origin), "run_id": rid}})
    return out


# ------------------------------------------------------------------ candidates of a day
def candidates_for_day(d: date, inputs: data.Inputs | None = None, scope_key=None, job_id=None,
                       force: bool = False) -> dict:
    s = settings()
    scope_key = _scope(scope_key)
    with db.read() as c:
        if not force and store.day_complete(c, scope_key, d, MODELS):
            return {"forecast_date": str(d), "status": "SKIPPED_DONE"}
    inputs = inputs or load(scope_key, d, s)
    sk = inputs.scope_keys(d)
    if sk.empty:
        raise Sel2Error(EMPTY_SCOPE, detail=str(d))
    keys = _tuples(sk)
    origin = origin_of(d, s.retrain_weekday)
    cands, train_ids, flags, detail = {}, {}, {}, {}
    for m in TRAIN_ORDER:
        fl = []
        with db.read() as c:
            run = store.succeeded_train(c, scope_key, m, origin)
            if run is None:
                run = store.succeeded_train(c, scope_key, m, origin - timedelta(days=7))
                fl = [FLAG_MODEL_PREV_WEEK]
        if run is None:
            raise Sel2Error(NO_MODEL, detail=f"{m}: no training of origin {origin} nor {origin - timedelta(days=7)}")
        models, trained = store.load_train(run)
        with mapped(MISSING_FORECAST):
            f = lgbm.forecast(inputs.frame, d, keys, models, lgbm.CANDIDATE_SPECS[m], trained)
        v = select.two_stage_value(f["prob"], f["qty"], s.p_threshold) if "prob" in f else f["value"]
        name = NAME[m]
        cands[name] = _long([k[0] for k in f["keys"]], [k[1] for k in f["keys"]], v)
        train_ids[name] = run["id"]
        run_flags = json.loads(run["detail_json"] or "{}").get("flags", [])
        flags[name] = fl + list(run_flags)
        detail[name] = {"origin": run["origin_date"]}
    g = inputs.g(d)
    m = inputs.scope_mask(d)
    daily, om = inputs.daily[m, :g], simple.open_mask(inputs.oh[m, :g])
    g_tsb = inputs.g(date.fromisoformat(s.tsb_start))
    with mapped(MISSING_FORECAST):
        tsb = simple.tsb(daily, om, g, g_tsb, s.tsb_alpha, s.tsb_beta)
        dow4 = simple.dow4(daily, om, g, data.DAY0)
        avg7 = simple.avg7(daily, g)
    H = simple.HORIZONS
    cands["TSB"] = _long(sk["sku_code"], sk["fc_code"], np.repeat(tsb[:, None], H, axis=1))
    cands["DOW4"] = _long(sk["sku_code"], sk["fc_code"], dow4)
    cands["AVG7"] = _long(sk["sku_code"], sk["fc_code"], np.repeat(avg7[:, None], H, axis=1))
    for nm in ("TSB", "DOW4", "AVG7"):
        flags[nm] = []
    n = store.write_day(scope_key, d, d - timedelta(days=1), cands, train_ids, flags, job_id, detail)
    return {"forecast_date": str(d), "status": "STORED", "rows": n, "series": len(sk),
            "flags": sorted({x for v in flags.values() for x in v})}


def _long(sku, fc, values) -> pd.DataFrame:
    v = np.asarray(values, dtype=float)
    S, H = v.shape
    return pd.DataFrame({"sku_code": np.repeat(np.asarray(sku, dtype=object), H),
                         "fc_code": np.repeat(np.asarray(fc, dtype=object), H),
                         "horizon": np.tile(np.arange(1, H + 1), S), "value": v.reshape(-1)})


# ------------------------------------------------------------------ selection + publication
def select_and_publish(d: date, publish: bool = True, history_start: date | None = None, group_mode: str | None = None,
                       group_start=None, group_end=None, inputs: data.Inputs | None = None, scope_key=None,
                       flags=(), trigger: str = "manual", job_id=None, fixed_groups: pd.Series | None = None) -> dict:
    s = settings()
    scope_key = _scope(scope_key)
    step = _progress("select", forecast_date=str(d), publish=publish)
    if inputs is None:
        inputs = load(scope_key, d, s)
        step("load", rows=len(inputs.frame), keys=len(inputs.keys))
    sk = inputs.scope_keys(d)
    if sk.empty:
        raise Sel2Error(EMPTY_SCOPE, detail=str(d))
    mode = group_mode or s.group_mode
    # fixed_groups: replay only (FIXED groups computed beforehand when their window ends after the day's inputs)
    groups = fixed_groups if fixed_groups is not None else inputs.groups(d, mode, group_start or s.group_fixed_start,
                                                                         group_end or s.group_fixed_end)
    step("groups", series=len(sk), groups=len(groups), fixed=fixed_groups is not None)
    with db.read() as c:
        runs = store.day_runs(c, scope_key, d)
        missing = set(MODELS) - {r["model"] for r in runs}
        if missing:
            raise Sel2Error(MISSING_FORECAST, detail=f"{d}: {', '.join(sorted(missing))}")
        today = store.read_day(c, scope_key, d)
        hist = store.History(c, scope_key, d, s.window_days)
        with mapped(HISTORY_INVALID):
            sel = select.select_day(d, sk, today, hist, inputs.actuals(d, s.window_days),
                                    inputs.open_days(d, s.window_days), groups, history_start=history_start,
                                    best=s.fallback_model, window_days=s.window_days, min_days=s.min_days)
    step("select", rows=len(sel))
    run_flags = sorted(set(flags) | set(inputs.flags) | {x for r in runs for x in (r["flags"] or "").split(",") if x})
    out = {"forecast_date": str(d), "series": len(sk), "rows": len(sel), "flags": run_flags,
           "methods": sel.drop_duplicates(["sku_code", "fc_code"])["model_used"].value_counts().to_dict(),
           "ok": int(sel.drop_duplicates(["sku_code", "fc_code"])["ok"].sum()), "selection": sel}
    if publish:
        tr = {r["model"]: r["train_run_id"] for r in runs if r["train_run_id"]}
        mv = "SEL2 " + " ".join(f"{m}={tr.get(NAME[m])}" for m in TRAIN_ORDER)
        detail = {"pipeline": "SEL2", "flags": run_flags, "methods": out["methods"], "ok_series": out["ok"],
                  "group_mode": mode, "history_start": str(history_start) if history_start else None,
                  "inputs": inputs.detail, "candidate_runs": {r["model"]: r["id"] for r in runs}}
        out["run_id"], out["values"] = store.publish(scope_key, d, sel, groups, run_flags, mv,
                                                     store.config_version(s), trigger, job_id, detail)
        out["model_version"] = mv
        step("publish", values=out["values"])
    return out


def _export_hook(d: date, trigger: str, job_id) -> dict | None:
    try:
        from . import export
    except ImportError:
        return None
    try:
        return {"ok": True, "result": export.write_daily_export(d, trigger=trigger, job_id=job_id)}
    except Exception as e:  # noqa: BLE001 - the export never fails the published run
        log.warning("sel2 export failed", exc_info=True, extra={"ctx": {"forecast_date": str(d)}})
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}


def run_day(d: date | None = None, trigger: str = "manual", job_id=None, scope_key=None, force: bool = False,
            inputs: data.Inputs | None = None) -> dict:
    s = ss.get("sel2_pipeline")
    if not s.enabled:
        return {"status": "SKIPPED", "reason_code": DISABLED}
    d = d or today_vn()
    scope_key = _scope(scope_key)
    with db.read() as c:
        done = store.published_run(c, scope_key, d)
    if done and not force:
        return {"status": "ALREADY_PUBLISHED", "forecast_date": str(d), "run_id": done["id"]}
    step = _progress("day", forecast_date=str(d), trigger=trigger)
    if inputs is None:
        _memory_gate(DAY_MIN_COMMIT_MB)
        inputs = load(scope_key, d, s)
        step("load", rows=len(inputs.frame), keys=len(inputs.keys))
    cand = candidates_for_day(d, inputs=inputs, scope_key=scope_key, job_id=job_id, force=force)
    step("candidates", status=cand["status"], rows=cand.get("rows"))
    res = select_and_publish(d, inputs=inputs, scope_key=scope_key, trigger=trigger, job_id=job_id)
    res.pop("selection")
    step("select_and_publish", rows=res["rows"], values=res.get("values"))
    inputs = None               # not needed by retention / export: freed here when this run loaded it
    resources.release_memory()
    out = {"status": "PUBLISHED", **res, "candidates": cand}
    try:
        out["retention"] = store.apply_retention(d, s.retention_days)
    except Exception as e:  # noqa: BLE001 - the run stays published; the next run deletes again
        out["retention_error"] = f"{type(e).__name__}: {e}"[:300]
    step("retention", rows=(out.get("retention") or {}).get("rows"))
    out["export"] = _export_hook(d, trigger, job_id)
    step("export", ok=(out["export"] or {}).get("ok"))
    return out


# ------------------------------------------------------------------ reproduction, first start, open-hours history
def replay(start: date, end: date, out_dir, group_mode: str | None = None, history_start_rule: str | None = None,
           group_start=None, group_end=None, scope_key=None) -> dict:
    """On a DB COPY: candidates of every day needed by SEL2 of [start, end] (trains the origins), SEL2 of every day,
    parquet files candidates.parquet + selected.parquet in out_dir. Nothing is published."""
    s = settings()
    scope_key = _scope(scope_key)
    step = _progress("replay", start=str(start), end=str(end))
    hs = backtest_history_start if history_start_rule == "BACKTEST" else (lambda d: None)
    first = backtest_history_start(start) if history_start_rule == "BACKTEST" else start - timedelta(days=s.window_days + 6)
    # FIXED groups (reproduction of the backtest) do not depend on the day; when their window ends after `end` they are
    # computed first from a separate read up to the window end, which is released before the day's inputs are read
    fixed_groups = None
    if (group_mode or s.group_mode) == "FIXED":
        gs_, ge = group_start or s.group_fixed_start, date.fromisoformat(str(group_end or s.group_fixed_end))
        if ge > end:
            ginputs = load(scope_key, ge + timedelta(days=1), s)
            step("load_fixed_groups", rows=len(ginputs.frame), keys=len(ginputs.keys))
            fixed_groups = ginputs.groups(start, "FIXED", gs_, ge)
            del ginputs
            gc.collect()
            step("fixed_groups", groups=len(fixed_groups))
    inputs = load(scope_key, end + timedelta(days=1), s)
    step("load", rows=len(inputs.frame), keys=len(inputs.keys))
    days = [first + timedelta(days=i) for i in range((end - first).days + 1)]
    for o in sorted({origin_of(d, s.retrain_weekday) for d in days}):
        r = train_week(o, inputs=inputs, scope_key=scope_key)
        step("train", origin=str(o), trained=len(r["trained"]), skipped=len(r["skipped"]))
    for d in days:
        r = candidates_for_day(d, inputs=inputs, scope_key=scope_key)
        step("candidates", forecast_date=str(d), status=r["status"], rows=r.get("rows"))
    sels = []
    for i in range((end - start).days + 1):
        d = start + timedelta(days=i)
        r = select_and_publish(d, publish=False, history_start=hs(d), group_mode=group_mode, group_start=group_start,
                               group_end=group_end, inputs=inputs, scope_key=scope_key, fixed_groups=fixed_groups)
        sels.append(r["selection"].assign(forecast_date=str(d)))
        step("select", forecast_date=str(d), rows=len(r["selection"]))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    sel = pd.concat(sels, ignore_index=True)
    sel["target_date"] = pd.to_datetime(sel["target_date"]).dt.strftime("%Y-%m-%d")
    sel.to_parquet(out / "selected.parquet", index=False)
    n_sel = len(sel)
    # the inputs and selections are not needed by the candidate export: freed before it
    del sel, sels, inputs, fixed_groups
    resources.release_memory()
    step("selected_parquet", rows=n_sel)
    with db.read() as c:
        n_cand, n_groups = _write_candidates(c, first, end, out / "candidates.parquet")
    step("candidates_parquet", rows=n_cand, row_groups=n_groups)
    return {"from": str(start), "to": str(end), "candidates_from": str(first), "selected_rows": n_sel,
            "candidate_rows": n_cand, "out": str(out)}


def _write_candidates(conn, first: date, end: date, path: Path) -> tuple[int, int]:
    """candidates.parquet of the stored candidates of forecast days [first, end] -> (rows, row groups). Read
    CANDIDATE_READ_ROWS rows at a time and written in row groups of CANDIDATE_EXPORT_ROWS rows: the columns, dtypes,
    row order and values of the former one-frame DataFrame(fetchall()).to_parquet, without holding every row (27.6 M
    rows of 45 days of the production scope took ~20 GB as Python tuples). Each part goes through the same
    DataFrame -> pa.Table.from_pandas conversion as DataFrame.to_parquet; no row at all -> the former empty frame."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    cur = conn.execute("SELECT forecast_date, sku_code, fc_code, model, horizon, target_date, value FROM "
                       "candidate_forecasts WHERE forecast_date BETWEEN ? AND ? ORDER BY forecast_date, sku_code, "
                       "fc_code, model, horizon", (str(first), str(end)))
    part = path.with_name(path.name + ".part")   # written whole, then renamed: never a truncated candidates.parquet
    writer, schema, parts, held, n, groups = None, None, [], 0, 0, 0
    try:
        while True:
            rows = cur.fetchmany(CANDIDATE_READ_ROWS)
            if rows:
                t = pa.Table.from_pandas(pd.DataFrame(rows, columns=CANDIDATE_COLUMNS), preserve_index=False)
                del rows
                if schema is None:
                    schema = t.schema
                    writer = pq.ParquetWriter(str(part), schema, compression="snappy")
                elif not t.schema.equals(schema):
                    t = t.cast(schema)
                parts.append(t)
                held += t.num_rows
                n += t.num_rows
                last = False
            else:
                last = True
            while held >= CANDIDATE_EXPORT_ROWS or (last and held):
                tab = pa.concat_tables(parts)
                g = min(CANDIDATE_EXPORT_ROWS, held)
                writer.write_table(tab.slice(0, g), row_group_size=CANDIDATE_EXPORT_ROWS)
                groups += 1
                rest = tab.slice(g)
                parts, held = ([rest] if rest.num_rows else []), rest.num_rows
                del tab, rest
            if last:
                break
        if writer is not None:
            writer.close()
        else:
            pd.DataFrame([], columns=CANDIDATE_COLUMNS).to_parquet(part, index=False)
    except BaseException:
        if writer is not None:
            try:
                writer.close()
            except Exception:  # noqa: BLE001 - never mask the original error
                pass
        try:
            part.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    os.replace(part, path)
    return n, groups


def _temp_export_hook(d: date, inputs: data.Inputs, s, scope_key: str, job_id) -> dict | None:
    """Temporary Excel of the first start (export.write_temp_export): today's candidates (models of origin_of(d)), then
    the V33_L112 numbers for every SKU x FC. Skipped when d is already published (the official file exists or comes
    from that run); a failure never fails the bootstrap (run_day computes the candidates again)."""
    try:
        from . import export
    except ImportError:
        return None
    with db.read() as c:
        if store.published_run(c, scope_key, d):
            return {"ok": True, "skipped": "ALREADY_PUBLISHED"}
    try:
        cand = candidates_for_day(d, inputs=inputs, scope_key=scope_key, job_id=job_id)
        groups = inputs.groups(d, s.group_mode, s.group_fixed_start, s.group_fixed_end)
        res = export.write_temp_export(d, groups=groups.to_dict(), job_id=job_id, scope_key=scope_key)
        return {"ok": True, "candidates": cand["status"], "result": res}
    except Exception as e:  # noqa: BLE001 - the temporary file never fails the first start
        log.warning("sel2 temporary export failed", exc_info=True, extra={"ctx": {"forecast_date": str(d)}})
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}


def bootstrap(days: int = 28, scope_key=None, job_id=None, today: date | None = None) -> dict:
    """First start: the trainings of the origin of TODAY first, then the temporary Excel (V33_L112 for every SKU x FC,
    du_bao_YYYYMMDD_TAM.xlsx, not published), then the other origins of [today - days, today], the candidates of the
    past days and run_day(today) (SEL2, publication, official export)."""
    s = settings()
    scope_key = _scope(scope_key)
    today = today or today_vn()
    step = _progress("bootstrap", today=str(today), days=days)
    t0 = time.monotonic()
    timings = {}
    first = today - timedelta(days=days)
    inputs = load(scope_key, today, s)
    step("load", rows=len(inputs.frame), keys=len(inputs.keys))
    span = [first + timedelta(days=i) for i in range(days + 1)]
    # each training reads only the rows before its own origin and is independent of the other trainings: training
    # the origin of today first changes no model, it only brings the temporary file forward
    o_today = origin_of(today, s.retrain_weekday)
    trained = [train_week(o_today, inputs=inputs, scope_key=scope_key, job_id=job_id)]
    step("train_today", origin=str(o_today), trained=len(trained[0]["trained"]), skipped=len(trained[0]["skipped"]))
    temp = _temp_export_hook(today, inputs, s, scope_key, job_id)
    timings["temp_export_after_s"] = round(time.monotonic() - t0, 1)
    step("temp_export", ok=(temp or {}).get("ok"), rows=((temp or {}).get("result") or {}).get("n_rows"))
    for o in sorted({origin_of(d, s.retrain_weekday) for d in span} - {o_today}):
        r = train_week(o, inputs=inputs, scope_key=scope_key, job_id=job_id)
        trained.append(r)
        step("train", origin=str(o), trained=len(r["trained"]), skipped=len(r["skipped"]))
    timings["trainings_done_after_s"] = round(time.monotonic() - t0, 1)
    past = []
    for d in span[:-1]:
        past.append(candidates_for_day(d, inputs=inputs, scope_key=scope_key, job_id=job_id))
        step("candidates", forecast_date=str(d), status=past[-1]["status"], rows=past[-1].get("rows"))
    timings["past_days_done_after_s"] = round(time.monotonic() - t0, 1)
    # today's run reads its own inputs (same day, same data): this frame is freed first, so the publication and the
    # official export never run with a second, unused copy of the inputs held here
    del inputs
    resources.release_memory()
    res = run_day(today, trigger="bootstrap", job_id=job_id, scope_key=scope_key)
    timings["total_s"] = round(time.monotonic() - t0, 1)
    step("today", status=res.get("status"))
    tr = (temp or {}).get("result") or {}
    return {"trainings": trained, "past_days": [p["status"] for p in past], "today": res,
            "temp_export": temp and {**temp, "path": tr.get("path"), "n_rows": tr.get("n_rows")}, "timings": timings}


def openhours_backfill(start: date | None = None, end: date | None = None) -> dict:
    """Open-hours history of the configured source from sel2_pipeline.open_hours_history_start to yesterday: read-only
    BigQuery (aux_sources.fetch_open_hours: dry run + byte cap, idempotent upsert), consecutive ranges of at most
    OPEN_HOURS_READ_DAYS days, oldest first, each one recorded as a completed read."""
    from ...bq import aux_sources
    s = settings()
    start = start or date.fromisoformat(s.open_hours_history_start)
    end = end or today_vn() - timedelta(days=1)
    cfg = ss.get("daily_forecast")
    modified = aux_sources.source_modified(cfg)
    out = {"start": str(start), "end": str(end), "reads": 0, "rows": 0, "last_day": None}
    a = start
    while a <= end:
        b = min(a + timedelta(days=OPEN_HOURS_READ_DAYS - 1), end)
        r = aux_sources.fetch_open_hours(a, b, cfg, source_modified=modified, last_day=out["last_day"])
        out.update(reads=out["reads"] + 1, rows=out["rows"] + r["rows"], last_day=r["last_day"])
        a = b + timedelta(days=1)
    return out
