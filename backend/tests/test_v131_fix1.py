"""1.3.1 review fix loop 1 (C4-FIX1): no second scheduled refresh of a published day (F1), the open-hours read before
the panel and in sub-ranges (F2), a training retry waits for today's refresh (F3), actual_daily never turns a data gap
into 0 and replaces its range (F4 + F9), and the small fixes F5 / F6 / F7. Fakes only (no BigQuery, no live data)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app import db
from app import settings_service as ss
from app import timeutil
from app.bq import aux_sources
from app.jobs.scheduler import Scheduler, plan
from app.messages import CATALOG, category
from app.ml import daily_refresh as dr
from app.timeutil import VN_TZ
from test_v131_refresh import (BQ_SCOPE, D, NOW, OH_TABLE, OhBQ, _count, _counts, _d1_ok, _demand_row, _enable,
                               _fake_oh, _freeze, _no_real_bigquery, _oh_row, _real, bq_model)  # noqa: F401 (fixtures)
from test_v131_refresh_jobs import _bq_scope, _fake_refresh, _jobs, _of, _patched_get, _plan, _published, _sched

T0 = datetime(2026, 10, 28, 5, 10, tzinfo=VN_TZ)
T1 = datetime(2026, 10, 28, 5, 25, tzinfo=VN_TZ)          # after the training slot (05:20), before the deadline (12:00)
# FULL range 27/07..27/10 (93 days) in sub-ranges of at most 15 days, aligned on D-1 (the oldest one is the short one)
SUB_RANGES = [("2026-07-27", "2026-07-29"), ("2026-07-30", "2026-08-13"), ("2026-08-14", "2026-08-28"),
              ("2026-08-29", "2026-09-12"), ("2026-09-13", "2026-09-27"), ("2026-09-28", "2026-10-12"),
              ("2026-10-13", "2026-10-27")]


def _job(key, status, job_type=None):
    with db.tx() as c:
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, status, attempt, max_attempts, "
                  "created_at) VALUES (?, ?, ?, 'SCHEDULE', ?, 1, 4, ?)",
                  (db.new_id("JOB"), job_type or key.split(":", 1)[0], key, status, timeutil.now_iso()))


def _reads():
    with db.read() as c:
        return db.rows(c, "SELECT range_start, range_end, n_rows, last_day, source_modified FROM aux_source_reads "
                          "WHERE source_table=? ORDER BY completed_at, rowid", (OH_TABLE,))


# ================================================================== F1: one scheduled run per published day
def test_a_scheduled_attempt_of_a_published_day_is_skipped_without_writing_and_a_manual_run_is_not():
    _freeze(NOW)
    _bq_scope()
    _enable()
    _published("S-OTHER", scope="BIGQUERY:p.d.other")             # another scope / another day: never count
    _published("S-YDAY", fdate="2026-10-27")
    assert dr.run(D)["reason_code"] == "REFRESH_WAITS_FOR_D1"
    _published("S-OWN")
    before = _counts()
    for trigger in ("SCHEDULE", "RETRY", "CATCH_UP"):
        assert dr.run(D, trigger=trigger) == {"status": "SKIPPED", "reason_code": "ALREADY_PUBLISHED",
                                              "business_date": "2026-10-28", "refresh_run_id": "S-OWN"}
    assert _counts() == before                                    # nothing written
    manual = dr.run(D, trigger="MANUAL")                          # the owner's explicit run goes on (here: no D-1)
    assert (manual["status"], manual["reason_code"]) == ("NOT_READY", "REFRESH_WAITS_FOR_D1")
    assert CATALOG["ALREADY_PUBLISHED"][0] and CATALOG["ALREADY_PUBLISHED"][1]
    assert category("ALREADY_PUBLISHED") == "MODEL"


def test_no_new_refresh_attempt_is_planned_while_one_of_today_is_in_the_scheduler_workers(monkeypatch):
    _bq_scope()
    _enable()
    sched = _sched(refresh_enabled=True, train_enabled=False, d1_enabled=False, refresh_deadline="06:00")
    _freeze(T0)
    _d1_ok()
    with db.read() as c:
        assert [a["key"] for a in _of(plan(T0, sched, "BIGQUERY", None, c))] == ["FORECAST_REFRESH:2026-10-28:05:10"]
        assert not _of(plan(T0, sched, "BIGQUERY", None, c, None, {"FORECAST_REFRESH:2026-10-28:04:55"}))
        other = {"FORECAST_REFRESH:2026-10-27:05:10", "TRAIN_PUBLISH:2026-10-28", "D1_SYNC:2026-10-28"}
        assert [a["key"] for a in _of(plan(T0, sched, "BIGQUERY", None, c, None, other))] == \
            ["FORECAST_REFRESH:2026-10-28:05:10"]
        late = datetime(2026, 10, 28, 6, 1, tzinfo=VN_TZ)        # the stale verdict also waits for its end
        assert not _of(plan(late, sched, "BIGQUERY", None, c, None, {"FORECAST_REFRESH:2026-10-28:05:50"}))
    # the running scheduler passes its workers' keys: a queued attempt (no job row yet) is never doubled
    calls = []
    monkeypatch.setattr(dr, "run", _fake_refresh(calls, {"status": "PUBLISHED", "reason_code": "DAILY_FORECAST_PUBLISHED"}))
    monkeypatch.setattr(ss, "get", _patched_get(sched))
    s = Scheduler()
    s._inflight.add("FORECAST_REFRESH:2026-10-28:04:55")
    assert not [a for a in _of(s.tick(T0, wait=True)) if a["action"] == "run"]
    assert calls == [] and _jobs() == []
    s._inflight.clear()
    s.tick(T0, wait=True)
    assert calls == [("2026-10-28", "SCHEDULE")] and len(_jobs()) == 1


# ================================================================== F2: open hours before the panel, in sub-ranges
def test_open_hours_are_read_before_the_panel_in_sub_ranges_and_a_second_scheduled_run_is_skipped(bq_model, monkeypatch):
    _enable()
    fake = _fake_oh()
    _d1_ok()
    stages, reads_at_panel = [], []
    real_panel = dr.build_refresh_panel

    def panel(*a, **k):
        reads_at_panel.append(len(_reads()))
        return real_panel(*a, **k)
    monkeypatch.setattr(dr, "build_refresh_panel", panel)
    res = dr.run(D, progress=lambda st, *a, **k: stages.append(st))
    assert res["status"] == "PUBLISHED", res
    assert stages == ["VALIDATING_DATA", "VERIFYING_MODEL", "SYNCING", "PREPARING_DATA", "FORECASTING", "PUBLISHING"]
    assert reads_at_panel == [len(SUB_RANGES)]                    # the whole read completed before the panel
    assert [(str(p["start"]), str(p["end"])) for p in _real(fake)] == SUB_RANGES
    assert (res["open_hours"]["mode"], res["open_hours"]["start"], res["open_hours"]["end"]) == \
        ("FULL", "2026-07-27", "2026-10-27")
    with db.read() as c:
        assert res["open_hours"]["rows"] == _count(c, "open_hours_daily") and res["open_hours"]["last_day"] == "2026-10-27"
    # F1 on a real run: the second scheduled run of the day is skipped (nothing read or written), a MANUAL one publishes
    before, n = _counts(), len(fake.queries)
    again = dr.run(D)
    assert (again["status"], again["reason_code"], again["refresh_run_id"]) == \
        ("SKIPPED", "ALREADY_PUBLISHED", res["refresh_run_id"])
    assert _counts() == before and len(fake.queries) == n
    manual = dr.run(D, trigger="MANUAL")
    assert manual["status"] == "PUBLISHED" and manual["refresh_run_id"] != res["refresh_run_id"]


def test_a_full_open_hours_read_is_recorded_per_sub_range_and_an_interrupted_one_resumes_incrementally():
    _freeze(NOW)
    keys = [("HN", "A"), ("HCM", "B")]
    modified = datetime(2026, 10, 28, 4, 10, tzinfo=VN_TZ)

    class FailingOhBQ(OhBQ):
        """Fails the real query of its `fail_at`-th sub-range (1-based)."""
        fail_at, n = None, 0

        def _rows(self, cfg):
            self.n += 1
            if self.n == self.fail_at:
                raise RuntimeError("quota")
            return super()._rows(cfg)
    fake = FailingOhBQ(keys=keys, modified=modified)
    fake.fail_at = 3
    aux_sources.connector.set_client_factory(fake)
    out = dr.sync_open_hours(D, "2026-01-01")
    assert "quota" in out["error"] and out["mode"] == "FULL" and out["rows"] == (3 + 15) * 2 and out["reads"] == 2
    assert out["last_day"] == "2026-08-13"
    # the two completed sub-ranges stay recorded, each with the source's last-modified time
    assert [(r["range_start"], r["range_end"], r["n_rows"], r["last_day"]) for r in _reads()] == \
        [("2026-07-27", "2026-07-29", 6, "2026-07-29"), ("2026-07-30", "2026-08-13", 30, "2026-08-13")]
    assert {r["source_modified"] for r in _reads()} == {"2026-10-27T21:10:00+00:00"}
    # the next attempt resumes INCREMENTALLY from the last completed sub-range (- 3 days), again in sub-ranges, also
    # with the source unchanged (the interrupted read is not "unchanged")
    fake.fail_at, fake.queries = None, []
    nxt = dr.sync_open_hours(D, "2026-01-01")
    assert (nxt["mode"], nxt["start"], nxt["end"], nxt["last_day"]) == ("INCREMENTAL", "2026-08-10", "2026-10-27",
                                                                       "2026-10-27")
    assert "error" not in nxt and nxt["reads"] == 6 and nxt["rows"] == 79 * 2 and nxt["kept_on_conflict"] == 0
    assert [(str(p["start"]), str(p["end"])) for p in _real(fake)] == [("2026-08-10", "2026-08-13")] + SUB_RANGES[2:]
    assert len(fake.queries) == 2 * 6                             # each sub-range: its own dry run + its read
    with db.read() as c:
        assert _count(c, "open_hours_daily") == 93 * 2
    # the source is unchanged since the last completed sub-range, which reaches D-1: skipped, nothing read
    n = len(fake.queries)
    assert dr.sync_open_hours(D, "2026-01-01")["skipped"] == dr.SOURCE_NOT_REFRESHED and len(fake.queries) == n


def test_an_empty_last_sub_range_keeps_the_last_day_read_as_watermark():
    _freeze(NOW)
    fake = _fake_oh(keys=[("HN", "A")], oh_end=date(2026, 10, 12))  # the source has not loaded 13..27/10 yet
    out = dr.sync_open_hours(D, "2026-01-01")
    assert out["reads"] == len(SUB_RANGES) and out["rows"] == 93 - 15 and out["last_day"] == "2026-10-12"
    assert _reads()[-1]["range_start"] == "2026-10-13" and _reads()[-1]["n_rows"] == 0
    assert _reads()[-1]["last_day"] == "2026-10-12"
    assert dr.open_hours_range(D, "2026-01-01") == (date(2026, 10, 9), date(2026, 10, 27), "INCREMENTAL")
    assert len(_real(fake)) == len(SUB_RANGES)


# ================================================================== F3: a training retry waits for today's refresh
def _train_retry(acts):
    return [a for a in acts if a["job_type"] == "TRAIN_PUBLISH" and a["action"] == "run"]


def test_a_due_training_retry_waits_while_todays_refresh_is_due_or_under_way():
    _bq_scope()
    _enable()
    _freeze(T1)
    _d1_ok()
    _job("TRAIN_PUBLISH:2026-10-28", "RETRY_WAIT")
    on = _sched(refresh_enabled=True)
    expected = [{"action": "run", "job_type": "TRAIN_PUBLISH", "key": "TRAIN_PUBLISH:2026-10-28", "trigger": "RETRY",
                 "scheduled_for": None, "params": {}}]
    assert _train_retry(_plan(T1, _sched())) == expected                  # refresh switched OFF: 1.2.14
    acts = _plan(T1, on)                                                  # a refresh attempt is due in this tick
    assert [a["action"] for a in _of(acts)] == ["run"] and not _train_retry(acts)
    with db.read() as c:                                                  # in the scheduler's workers
        assert not _train_retry(plan(T1, on, "BIGQUERY", None, c, None, {"FORECAST_REFRESH:2026-10-28:05:20"}))
    for status in ("PENDING", "RUNNING", "RETRY_WAIT"):
        with db.tx() as c:
            c.execute("DELETE FROM job_runs WHERE job_type='FORECAST_REFRESH'")
        _job("FORECAST_REFRESH:2026-10-28:05:20", status)
        acts = _plan(T1, on)
        assert not _train_retry(acts), status
        assert [a["trigger"] for a in _of(acts) if a["action"] == "run"] == (["RETRY"] if status == "RETRY_WAIT" else [])
    ss.update("daily_forecast", {"enabled": False})                       # daily_forecast OFF: not held
    assert _train_retry(_plan(T1, on)) == expected
    _enable()
    noon = datetime(2026, 10, 28, 12, 30, tzinfo=VN_TZ)                   # after the deadline: not held
    assert _train_retry(_plan(noon, on)) == expected
    with db.tx() as c:                                                    # yesterday's waiting refresh: not held
        c.execute("UPDATE job_runs SET idempotency_key='FORECAST_REFRESH:2026-10-27:05:20' "
                  "WHERE job_type='FORECAST_REFRESH'")
    assert _train_retry(_plan(T1, on)) == expected
    with db.tx() as c:
        c.execute("DELETE FROM job_runs WHERE job_type='FORECAST_REFRESH'")
    _published("S-OWN")
    assert _train_retry(_plan(T1, on)) == expected                        # today's refresh published: not held


# ================================================================== F4 + F9: actual_daily
def _actual():
    with db.read() as c:
        return [tuple(r) for r in c.execute("SELECT scope_key, date, fc_code, sku_code, demand, total_open_hours "
                                            "FROM actual_daily ORDER BY scope_key, date, fc_code, sku_code")]


def test_actual_daily_never_writes_zero_on_a_day_without_any_demand_row_and_replaces_its_range():
    _freeze(NOW)
    with db.tx() as c:
        for day in ("2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23"):
            _oh_row(c, "HN", "A", day, 10)
            _oh_row(c, "HN", "B", day, 8)
        _demand_row(c, "2026-10-20", "A", "HN", 5)
        _demand_row(c, "2026-10-22", "B", "HN", 2)                        # 21/10: no demand row at all = data gap
        _demand_row(c, "2026-10-21", "A", "HN", 9, scope="BIGQUERY:p.d.other")   # another scope never counts
        c.execute("INSERT INTO actual_daily VALUES (?, '2026-10-21', 'HN', 'A', 0, 10, 'x')", (BQ_SCOPE,))  # an old 0
        c.execute("INSERT INTO actual_daily VALUES (?, '2026-10-19', 'HN', 'A', 4, 10, 'x')", (BQ_SCOPE,))  # outside
        c.execute("INSERT INTO actual_daily VALUES ('BIGQUERY:p.d.other', '2026-10-21', 'HN', 'A', 9, 10, 'x')")
    n = dr.refresh_actual_daily(BQ_SCOPE, date(2026, 10, 20), date(2026, 10, 23))
    rows = [(BQ_SCOPE, "2026-10-19", "HN", "A", 4.0, 10.0),              # outside the range: kept as it is
            (BQ_SCOPE, "2026-10-20", "HN", "A", 5.0, 10.0), (BQ_SCOPE, "2026-10-20", "HN", "B", 0.0, 8.0),
            (BQ_SCOPE, "2026-10-22", "HN", "A", 0.0, 10.0), (BQ_SCOPE, "2026-10-22", "HN", "B", 2.0, 8.0),
            ("BIGQUERY:p.d.other", "2026-10-21", "HN", "A", 9.0, 10.0)]
    # 21/10 (gap, its old 0 removed) and 23/10 (gap) get no row; 20 and 22 get the open-day 0
    assert _actual() == rows and n == 4
    with db.tx() as c:                                                    # open hours corrected to 0 (closed)
        c.execute("UPDATE open_hours_daily SET total_open_hours=0 WHERE sku_code='B' AND open_date='2026-10-20'")
    assert dr.refresh_actual_daily(BQ_SCOPE, date(2026, 10, 20), date(2026, 10, 23)) == 3
    assert _actual() == [r for r in rows if r[1:4] != ("2026-10-20", "HN", "B")]
    with db.tx() as c:                                                    # the gap day is loaded later: written
        _demand_row(c, "2026-10-21", "A", "HN", 1)
    assert dr.refresh_actual_daily(BQ_SCOPE, date(2026, 10, 20), date(2026, 10, 23)) == 5
    assert (BQ_SCOPE, "2026-10-21", "HN", "B", 0.0, 8.0) in _actual()
    assert (BQ_SCOPE, "2026-10-23", "HN", "A", 0.0, 10.0) not in _actual()


# ================================================================== F5 / F6 / F7
def test_feature_name_mismatch_raises_a_value_error_and_the_short_horizon_weight_is_bounded(monkeypatch):
    import numpy as np
    from app.ml import features
    from test_ml import _demand
    rng = np.random.default_rng(1)
    p = features.build_panel(_demand({("A", "F"): list(rng.poisson(5, 60)), ("B", "F"): list(rng.poisson(2, 60))}))
    cfg = ss.get("model").model_copy(update={"feature_sku_code": False})
    sc, fc = features.static_codes(p)
    assert features.features_at(p, p.Y, p.price, p.disc, p.promo, p.dates, 40, cfg, sc, fc).shape[0] == 2
    real = features._all_names
    monkeypatch.setattr(features, "_all_names", lambda c: real(c)[:-1])        # one name short
    with pytest.raises(ValueError, match="feature columns"):
        features.features_at(p, p.Y, p.price, p.disc, p.promo, p.dates, 40, cfg, sc, fc)
    ss.ModelSettings(forecast_strategy="DIRECT", horizon_weight_short=100, horizon_weight_cutoff=7)
    with pytest.raises(ValueError):
        ss.ModelSettings(forecast_strategy="DIRECT", horizon_weight_short=100.5, horizon_weight_cutoff=7)
    assert "not yet used" not in CATALOG["TRIAL_MODE_CHANGED"][1]
    assert "('Trial run – not used for purchasing')" in CATALOG["TRIAL_MODE_CHANGED"][1]
