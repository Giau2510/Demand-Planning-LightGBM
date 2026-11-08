"""1.4.8 C-2 (tester): gaps of the SO-line step tests (app/spike_lines.py, data_checks so_lines_cache_matches_demand,
jobs/scheduler.py with spike cleaning OFF). Isolated test DB (conftest), fake BigQuery client, synthetic lines, fixed
Vietnam dates: unit / integration with fakes (no BigQuery, no live data)."""
import contextlib
import io
import json
import logging
from datetime import date, timedelta

import pandas as pd
import pytest

from app import cli, db, spike_lines
from app.bq import connector
from app.ml.sel2 import spike
from fake_bq import FakeBQ

from test_v148_spike_lines import D, KEYS, SPIKE, _configure, _count, _fake, _seed_db, _stored_flag

# distinctive customer ids (never a substring of a SKU / FC / day / code of these tests)
CUSTS = ("KHZQ7001", "KHZQ7002", "KHZQ7003")
VOLATILE = ("next_day", "computed_for", "computed_at")


def _flag_rows(where="", p=()):
    with db.read() as c:
        return {(r["d"], r["fc_code"], r["sku_code"], r["so_code"], r["customer_id"]): r
                for r in db.rows(c, "SELECT * FROM spike_flag_lines" + where, p)}


def _strip(rows):
    return {k: {c: v for c, v in r.items() if c not in VOLATILE} for k, r in rows.items()}


def _excess_rows():
    with db.read() as c:
        return db.rows(c, "SELECT * FROM demand_excess_daily ORDER BY scope_key, d, fc_code, sku_code, level, e4_n")


# ------------------------------------------------------------------ later nights: rows before D-30 kept
@pytest.mark.parametrize("gap", [1, 3])
def test_later_night_keeps_rows_before_d30_except_next_day_and_computed_for(sel2_on, gap):
    """Every stored row of a day < d2-30 keeps every column but next_day / computed_for / computed_at (also after
    skipped nights), and Excess on the refreshed rows as of d2 no longer raises (it did before the run)."""
    scope = _configure()
    _seed_db(scope, end=D + timedelta(days=gap))
    _fake()
    spike_lines.run(D)
    d2 = D + timedelta(days=gap)
    w0 = d2 - timedelta(days=30)
    old = d2 - timedelta(days=40)
    _stored_flag(scope, old, "S00", "C1")                         # T7 pending, next purchase in the cache
    _stored_flag(scope, old, "S01", "C9")                         # T7 pending, customer without any later purchase
    _stored_flag(scope, old - timedelta(days=1), "S03", "C2", next_day=str(old), computed_for=old)
    _stored_flag(scope, D - timedelta(days=300), "S02", "")       # older than the cache: never touched
    before = _flag_rows(" WHERE d < ?", (str(w0),))
    with db.read() as c:
        stale = spike.read_flags(c, scope)
    with pytest.raises(ValueError, match="too old"):              # the scenario: the pending T7 needs the refresh
        spike.Excess(stale).cells_frame(d2, 1, 4)

    r = spike_lines.run(d2)
    assert r["status"] == "DONE" and not r["flags"]["full"] and r["flags"]["written_from"] == str(w0)
    after = _flag_rows(" WHERE d < ?", (str(w0),))
    assert set(after) == set(before)                              # no row of those days added or removed
    assert _strip(after) == _strip(before)                        # every non-volatile column as stored
    changed = {k for k in before if any(before[k][c] != after[k][c] for c in ("next_day", "computed_for"))}
    assert changed == {(str(old), "FC1", "S00", "SOX", "C1"), (str(old), "FC1", "S01", "SOX", "C9")}
    c9 = after[(str(old), "FC1", "S01", "SOX", "C9")]
    assert c9["next_day"] is None and c9["computed_for"] == str(d2)
    old_row = after[(str(D - timedelta(days=300)), "FC1", "S02", "SOX", "")]
    assert old_row == before[(str(D - timedelta(days=300)), "FC1", "S02", "SOX", "")]
    # Excess on the refreshed rows: no exception, and the stored excess is exactly its result as of d2
    with db.read() as c:
        stored = spike.read_flags(c, scope)
    cells = spike.Excess(stored).cells_frame(d2, 1, 4)
    got = {(x["d"], x["sku_code"], x["fc_code"]): x["excess"] for x in _excess_rows()}
    assert got == {(str(pd.Timestamp(x.d).date()), x.sku_code, x.fc_code): x.excess for x in cells.itertuples()}
    assert {x["asof"] for x in _excess_rows()} == {str(d2)}
    # C9: no later purchase, 39+ days >= 2 x the 7-day median gap -> T7 adds a signal; the line counts as of d2
    assert got[(str(old), "S01", "FC1")] == 48.0


# ------------------------------------------------------------------ the cache prune
def _old_cache_line(scope, day):
    with db.tx() as c:
        c.execute("INSERT INTO so_lines_cache(scope_key, order_date, fc_code, sku_code, so_code, customer_id, qty, "
                  "n_rows, loaded_at) VALUES (?, ?, 'FC1', 'S00', 'SOOLD', 'C1', 2, 1, 'x')", (scope, str(day)))


def _excess_row(scope, day, level, e4_n, asof):
    with db.tx() as c:
        c.execute("INSERT INTO demand_excess_daily(scope_key, d, fc_code, sku_code, level, e4_n, excess, asof, "
                  "computed_at) VALUES (?, ?, 'FC1', 'S00', ?, ?, 7.5, ?, 'x')", (scope, str(day), level, e4_n, str(asof)))


def test_cache_prune_never_touches_flags_or_excess(sel2_on):
    scope = _configure()
    first = D - timedelta(days=210)
    for k in (250, 211):
        _old_cache_line(scope, D - timedelta(days=k))
    _old_cache_line(scope, first)                                 # the first cache day itself is kept
    _stored_flag(scope, D - timedelta(days=250), "S00", "C1", next_day=str(D - timedelta(days=249)),
                 computed_for=D - timedelta(days=248))
    _stored_flag(scope, D - timedelta(days=211), "S02", "")
    _excess_row(scope, D - timedelta(days=250), 1, 4, D - timedelta(days=200))
    _excess_row(scope, D - timedelta(days=250), 2, 4, D - timedelta(days=200))
    flags0, ex0 = _flag_rows(), _excess_rows()
    _fake()
    res = spike_lines.load_lines(scope, D - timedelta(days=2), D - timedelta(days=1), first)
    assert res["cache_rows_pruned"] == 2
    assert _count("SELECT MIN(order_date) FROM so_lines_cache") == str(first)
    assert _flag_rows() == flags0 and _excess_rows() == ex0       # byte-for-byte untouched
    # the whole step: rows older than the cache stay in spike_flag_lines; demand_excess_daily of another level kept
    _seed_db(scope, end=D)
    spike_lines.run(D)
    after = _flag_rows(" WHERE d < ?", (str(first),))
    assert after == {k: v for k, v in flags0.items() if k[0] < str(first)} and len(after) == 2
    lvl2 = [x for x in _excess_rows() if x["level"] == 2]
    assert lvl2 == [x for x in ex0 if x["level"] == 2]


# ------------------------------------------------------------------ data check so_lines_cache_matches_demand
def _chk():
    from app import data_checks, paths
    res = data_checks.run(paths.db_path())
    return next(x for x in res["checks"] if x["check"] == "so_lines_cache_matches_demand"), res


def _fake_named():
    """the lines of test_v148_spike_lines with the customer ids C1..C3 renamed to CUSTS."""
    from test_v148_spike_lines import _lines
    ren = dict(zip(("C1", "C2", "C3"), CUSTS))

    def resp(cfg):
        p = {n: v for n, _t, v in cfg["params"]}
        return [{**x, "customer_id": ren[x["customer_id"]], "so_code": x["so_code"][:-2] + str(i % 97)}
                for i, x in enumerate(_lines(p["start"], p["end"]))]
    f = FakeBQ(responses={"so_lines": resp})
    connector.set_client_factory(f)
    return f


def test_data_check_ok_on_empty_cache_and_equal_then_warn_without_customer_id(sel2_on):
    scope = _configure()
    _seed_db(scope, end=D)
    assert _chk()[0]["status"] == "OK" and _chk()[0]["count"] == 0          # no cache yet: nothing compared
    _fake_named()
    spike_lines.run(D)
    chk, full = _chk()
    assert chk["status"] == "OK" and chk["count"] == 0
    with db.tx() as c:                                                      # a missing line (lines < demand)
        c.execute("DELETE FROM so_lines_cache WHERE order_date=? AND sku_code='S00' AND customer_id=?",
                  (str(D - timedelta(days=4)), CUSTS[0]))
    chk, full = _chk()
    assert chk["status"] == "WARN" and chk["count"] == 1
    assert chk["examples"] == [[scope, str(D - timedelta(days=4)), "S00", "FC1", 4.0, 6.0]]
    text = json.dumps(full, default=str)
    assert not any(cu in text for cu in CUSTS)                              # no customer id in any check output


# ------------------------------------------------------------------ OFF: a failed step changes no refresh decision
def test_off_failed_step_changes_no_refresh_decision(sel2_on):
    from test_v131_refresh import _d1_ok, _freeze
    from test_v131_refresh_jobs import _bq_scope, _of, _sched
    from test_v140_t4b_planning import TUE, _at, _job, _sel2_run
    from test_v148_spike_schedule import _both, _ref_scheduler, _strip as _no_spike
    connector.set_client_factory(FakeBQ())
    _bq_scope()
    ref = _ref_scheduler()
    sched = _sched(refresh_enabled=True)
    # a manual SPIKE_LINES of today failed before D-1 (row + its WARNING alert): the refresh is planned as in 1.4.7
    _freeze(_at(TUE, "04:30"))
    _job("SPIKE_LINES", f"SPIKE_LINES:{TUE}", "FAILED")
    with db.tx() as c:
        db.alert(c, "WARNING", spike_lines.ALERT, {"business_date": str(TUE), "cause": "X"}, "job", "J1")
    new, old = _both(ref, TUE, "05:05", sched)
    assert _no_spike(new) == old and new == old
    _d1_ok(day=TUE)
    new, old = _both(ref, TUE, "05:10", sched)
    assert new == old and len(_of(new)) == 1                                # the refresh, exactly as 1.4.7
    _job("FORECAST_REFRESH", f"FORECAST_REFRESH:{TUE}:05:10", "SUCCEEDED")
    _sel2_run(TUE)
    for hhmm in ("05:40", "09:00", "18:00", "23:00"):                       # published: no re-run, no new step
        new, old = _both(ref, TUE, hhmm, sched)
        assert new == old, hhmm


def test_off_running_step_never_holds_the_refresh(sel2_on):
    """a SPIKE_LINES row RUNNING (e.g. started by hand) with the switch OFF: the refresh after D-1 as in 1.4.7."""
    from test_v131_refresh import _d1_ok, _freeze
    from test_v131_refresh_jobs import _bq_scope, _of, _sched
    from test_v140_t4b_planning import TUE, _at, _job
    from test_v148_spike_schedule import _both, _ref_scheduler
    connector.set_client_factory(FakeBQ())
    _bq_scope()
    ref = _ref_scheduler()
    _freeze(_at(TUE, "05:00"))
    _job("SPIKE_LINES", f"SPIKE_LINES:{TUE}", "RUNNING")
    _d1_ok(day=TUE)
    new, old = _both(ref, TUE, "05:10", _sched(refresh_enabled=True))
    assert new == old and len(_of(new)) == 1


# ------------------------------------------------------------------ no customer id in logs / alerts / job rows
class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        from app.logging_setup import JsonFormatter
        self.setFormatter(JsonFormatter())
        self.lines = []

    def emit(self, record):
        self.lines.append(self.format(record) + " " + repr(getattr(record, "ctx", "")))


@contextlib.contextmanager
def _df_logs():
    lg = logging.getLogger("df")
    h, lvl = _Capture(), lg.level
    lg.addHandler(h)
    lg.setLevel(logging.DEBUG)
    try:
        yield h.lines
    finally:
        lg.removeHandler(h)
        if lg.level == logging.DEBUG:       # (cli setup_logging may have set its own level meanwhile: keep that one)
            lg.setLevel(lvl)


def _child_in_process(args, timeout):
    """the child's contract (jobs.run_child): `python -m app.cli <args>` JSON stdout + exit_code, run in-process."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(args)
    return {**json.loads(buf.getvalue()), "exit_code": rc}


def _all_text(c, table):
    return json.dumps(db.rows(c, f"SELECT * FROM {table}"), default=str)


def _run_job(monkeypatch, day):
    from app.jobs import resources, runner
    real = resources.snapshot
    monkeypatch.setattr(resources, "snapshot", lambda: {**real(), "commit_avail": 1 << 50})
    spike_lines.set_child_runner(_child_in_process)
    try:
        return runner.execute("SPIKE_LINES", spike_lines.job_key(day), "MANUAL", None, {"business_date": str(day)})
    finally:
        spike_lines.set_child_runner(None)


def test_no_customer_id_in_logs_alerts_or_job_rows(sel2_on, monkeypatch):
    scope = _configure()
    _seed_db(scope, end=D + timedelta(days=1))
    _fake_named()
    with _df_logs() as lines:
        ok = _run_job(monkeypatch, D)                                       # success: cache + flags written
        assert ok["status"] == "SUCCEEDED"
        assert _count("SELECT COUNT(*) FROM so_lines_cache WHERE customer_id=?", (CUSTS[0],)) > 0
        assert _count("SELECT COUNT(*) FROM spike_flag_lines WHERE customer_id=?", (CUSTS[0],)) > 0
        # failure after the lines were cached (the excess write breaks): FAILED + one WARNING alert
        monkeypatch.setattr(spike, "write_excess_daily",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("excess write failed")))
        bad = _run_job(monkeypatch, D + timedelta(days=1))
        assert bad["status"] == "FAILED" and bad["reason_code"] == spike_lines.ALERT
    assert lines and any("spike lines step failed" in x for x in lines)
    with db.read() as c:
        al = db.rows(c, "SELECT level, code FROM alerts")
        texts = [_all_text(c, t) for t in ("alerts", "job_runs", "job_events")
                 if c.execute("SELECT 1 FROM sqlite_master WHERE name=?", (t,)).fetchone()]
    assert al == [{"level": "WARNING", "code": spike_lines.ALERT}]
    for cu in CUSTS:
        assert not any(cu in x for x in lines), cu
        assert not any(cu in t for t in texts), cu
