"""1.2.0: separate BigQuery tables for the D-1 (history) and D-0 (today) feeds, metadata checks, job isolation, and
the scheduler tick that a long write transaction can no longer turn into an ERROR."""
import logging
import sqlite3

import pytest

from app import db, timeutil
from app import settings_service as ss
from app.bq import connector, source_tables, sql_sources
from app.jobs import flows

from fake_bq import FakeBQ
from test_v116 import D0_OUT, LAYOUT, _bq_ready, _d0_rows

D1 = "lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm"
D0 = "lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm_D0"


# the real D-1 table has refresh_time as STRING (not mappable to source_updated_at) - verified 16/10/2026
REAL_D1 = [(n, "STRING" if n == "refresh_time" else t) for n, t in LAYOUT]


def _fake(**kw):
    # the real layouts: the D-0 table has no open_date / total_open_* / refresh_time columns (verified 16/10/2026)
    tables = kw.pop("tables", {D1: REAL_D1, D0: D0_OUT})
    return FakeBQ(schema=REAL_D1, tables=tables, **kw)


def test_default_d0_table_and_status():
    st = source_tables.status()
    assert st["d0"]["table_id"] == D0 and st["d0"]["last_check"] is None and not st["d0"]["ok"]
    assert st["d1"]["table_id"] == ""                       # not configured on a fresh installation


def test_d0_check_uses_only_the_fields_the_d0_feed_reads(client):
    fake = _bq_ready(_fake())
    d0 = client.post("/api/bigquery/source-tables/d0/check", json={"table_id": D0}).json()
    assert d0["status"] == "PASSED", d0
    # the same D-0 layout as the D-1 table would miss the mapped reference columns
    bad = client.post("/api/bigquery/source-tables/d1/check", json={"table_id": D0}).json()
    assert bad["status"] == "FAILED" and {e.get("column") for e in bad["errors"]} >= {"open_date", "total_open_hours"}
    st = client.get("/api/bigquery/source-tables").json()
    assert st["d0"]["ok"] and st["d0"]["last_check"]["checked_at"]
    # 1.2.1: the D-0 check reads the D-0 mapping only - a D-1 column the D-0 table lacks does not matter to D-0
    m = ss.get("bigquery").field_mapping
    ss.update("bigquery", {"field_mapping": {**{k: v.model_dump() for k, v in m.items()},
                                             "source_updated_at": {"column": "refresh_time", "usage": "OPTIONAL"}}})
    same = client.post("/api/bigquery/source-tables/d0/check", json={"table_id": D0}).json()
    assert same["status"] == "PASSED", same
    # ... while a D-0 mapping naming a column the D-0 table lacks fails the D-0 check (the query would fail)
    d0m = ss.get("bigquery").d0_mapping
    ss.update("bigquery", {"d0_mapping": {**{k: v.model_dump() for k, v in d0m.items()},
                                          "source_updated_at": {"column": "refresh_time", "usage": "OPTIONAL"}}})
    miss = client.post("/api/bigquery/source-tables/d0/check", json={"table_id": D0}).json()
    assert miss["status"] == "FAILED" and miss["errors"][0]["column"] == "refresh_time"
    ss.update("bigquery", {"field_mapping": {k: v.model_dump() for k, v in m.items()},
                           "d0_mapping": {k: v.model_dump() for k, v in d0m.items()}})
    assert not st["d1"]["ok"]                       # the last D-1 check was for another table id and failed
    assert fake.queries == []                       # metadata only: no query, no cost


@pytest.mark.parametrize("table_id,code", [("not-a-table", "BQ_TABLE_ID_INVALID"),
                                           ("lakehouse-prod-394907.gold_buymed_vn2.x;DROP", "BQ_TABLE_ID_INVALID")])
def test_invalid_table_ids_are_refused(client, table_id, code):
    _bq_ready(_fake())
    r = client.put("/api/bigquery/source-tables/d0", json={"table_id": table_id})
    assert r.status_code == 422 and r.json()["code"] == code
    assert ss.get("bigquery").d0_table_id == D0


@pytest.mark.parametrize("err,code", [(type("NotFound", (Exception,), {})("Not found: Table x"), "BQ_NOT_FOUND"),
                                      (type("Forbidden", (Exception,), {})("Access Denied: Table x"), "BQ_PERMISSION_DENIED")])
def test_a_failing_table_is_never_saved_and_never_replaced_by_another(client, err, code):
    other = "lakehouse-prod-394907.gold_buymed_vn2.other_d0"
    _bq_ready(_fake(errors={other: err}))
    r = client.put("/api/bigquery/source-tables/d0", json={"table_id": other})
    assert r.status_code == 409 and r.json()["code"] == "BQ_TABLE_CHECK_FAILED" and code in r.json()["detail"]
    assert ss.get("bigquery").d0_table_id == D0                     # current source unchanged, no fallback
    assert source_tables.last_check("d0")["errors"][0]["code"] == code


def test_d1_table_change_needs_production_off_and_changes_the_scope(client):
    _bq_ready(_fake(tables={D1: REAL_D1, D0: D0_OUT, "lakehouse-prod-394907.gold_buymed_vn2.hist2": REAL_D1}))
    old_hash = connector.mapping_hash(ss.get("bigquery"))
    ss.update("bigquery", {"production_enabled": True})
    r = client.put("/api/bigquery/source-tables/d1", json={"table_id": "lakehouse-prod-394907.gold_buymed_vn2.hist2"})
    assert r.status_code == 409 and r.json()["code"] == "BQ_TABLE_CHANGE_NEEDS_PRODUCTION_OFF"
    assert ss.get("bigquery").source_table == "demand_planing_lightgbm"
    ss.update("bigquery", {"production_enabled": False})
    r = client.put("/api/bigquery/source-tables/d1", json={"table_id": "lakehouse-prod-394907.gold_buymed_vn2.hist2"})
    assert r.status_code == 200, r.text
    assert ss.get("bigquery").source_table == "hist2" and connector.mapping_hash(ss.get("bigquery")) != old_hash
    assert r.json()["d1"]["ok"]
    same = client.put("/api/bigquery/source-tables/d1", json={"table_id": "lakehouse-prod-394907.gold_buymed_vn2.hist2"})
    assert same.status_code == 200                          # re-saving the same table is allowed


def test_d0_job_reads_only_the_d0_table_and_needs_a_passed_check(client):
    from app.sync import run_d0_snapshot
    fake = _bq_ready(_fake())
    today = timeutil.today_vn()
    fake.responses["d0"] = _d0_rows(today)
    sql_sources.set_options("d0", mode="TABLE")
    ss.update("bigquery", {"production_enabled": True})
    ss.update("general", {"active_source": "BIGQUERY"})
    r = flows.readiness("d0")
    assert not r["ready"] and "D0_TABLE_NOT_CHECKED" in [x["code"] for x in r["reasons"]]
    assert source_tables.check("d0")["status"] == "PASSED"
    assert "D0_TABLE_NOT_CHECKED" not in [x["code"] for x in flows.readiness("d0")["reasons"]]
    res = run_d0_snapshot("JOB-D0", None, False)
    assert res["series"] == 2
    sql = [q[0] for q in fake.queries if q[0].startswith("-- df:d0")][-1]
    assert f"`{D0}`" in sql and f"`{D1}`" not in sql
    again = run_d0_snapshot("JOB-D0", None, False)                         # retry of the same job: no duplicate
    assert again["already_written"]
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM d0_snapshots").fetchone()[0] == 1
    assert ss.get("schedule").d0_enabled is False                         # nothing switched a schedule on
    assert today


def test_d1_queries_read_only_the_d1_table(client):
    fake = _bq_ready(_fake())
    connector.profile(30)
    sqls = [q[0] for q in fake.queries if not q[0].startswith("-- df:access")]
    assert sqls and all(f"`{D1}`" in s and D0 not in s for s in sqls)


def test_scheduler_defers_a_tick_when_the_database_is_busy(monkeypatch, caplog):
    from app.jobs.scheduler import Scheduler
    s = Scheduler.__new__(Scheduler)

    def locked():
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(s, "tick", locked, raising=False)
    with caplog.at_level(logging.WARNING, logger="df.scheduler"):
        assert s.safe_tick() == "DEFERRED"
    assert any("deferred" in r.getMessage() and r.levelno == logging.WARNING for r in caplog.records)
    assert not any(r.levelno >= logging.ERROR for r in caplog.records)

    def other():
        raise sqlite3.OperationalError("no such table: x")
    monkeypatch.setattr(s, "tick", other, raising=False)
    with caplog.at_level(logging.ERROR, logger="df.scheduler"):
        assert s.safe_tick() == "ERROR"
