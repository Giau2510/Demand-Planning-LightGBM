"""1.4.0 T5: AVG_DEMAND read from BigQuery (fake client only, read-only SELECT) into avg_demand_daily, the completed
reads (avg_demand_reads), the seller rule of avg_value(), the CLI sel2-avg-read and GET /api/sel2/avg-demand.
Integration with fakes (isolated temporary database, FakeBQ)."""
import json
import re
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from app import cli, db
from app import settings_service as ss
from app.bq import connector
from app.messages import AppError
from app.ml.sel2 import avg_demand
from fake_bq import FakeBQ

CUR = "lakehouse-prod-394907.gold_buymed_vn2.fact_avg_demand_sku"
HIST = "lakehouse-prod-394907.gold_buymed_vn2.fact_avg_demand_sku_historical"
MODIFIED = datetime(2026, 11, 2, 3, 15, 2, tzinfo=timezone.utc)


class AvgFake(FakeBQ):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.modified = MODIFIED

    def get_table(self, name):
        if name in self.errors:
            raise self.errors[name]
        return SimpleNamespace(schema=[], num_rows=1, modified=self.modified, location=self.location)


def _row(sku, fc, seller, v, name="P"):
    return {"fc_code": fc, "sku_code": sku, "seller_code": seller, "avg_demand": v, "product_name": name,
            "ingest_time": "10:15:02 02/11/2026"}


CURRENT_ROWS = [_row("S1", "F1", "MEDX", 2.5), _row("S2", "F1", "MEDX", 1.0), _row("S2", "F1", "MEDX_E", 3.0),
                _row("S3", "F2", "MEDX", None)]


@pytest.fixture
def fake(sel2_on, monkeypatch):
    # the current snapshot is today's table: read_current(D) needs D = today (Vietnam)
    monkeypatch.setattr(avg_demand, "today_vn", lambda: date(2026, 11, 2))
    f = AvgFake(responses={"sel2_avg_demand_current": CURRENT_ROWS})
    connector.set_client_factory(f)
    return f


def _assert_read_only(f):
    assert f.queries
    for sql, _ in f.queries:
        body = sql.split("\n", 1)[1].lstrip().upper()
        assert body.startswith("SELECT")
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|MERGE|CREATE|DROP|ALTER|TRUNCATE)\b", body)
    # every query is dry-run first, then run with a billing cap of at most 5 GB
    dry = [cfg for _, cfg in f.queries if cfg["dry_run"]]
    real = [cfg for _, cfg in f.queries if not cfg["dry_run"]]
    assert len(dry) == len(real)
    assert all(cfg["maximum_bytes_billed"] <= 5 * 1024 ** 3 for cfg in real)


def _stored(day, table=CUR):
    with db.read() as c:
        return db.rows(c, "SELECT sku_code, fc_code, seller_code, avg_demand, source_modified FROM avg_demand_daily "
                          "WHERE business_date=? AND source_table=? ORDER BY sku_code, seller_code", (day, table))


def _reads():
    with db.read() as c:
        return db.rows(c, "SELECT * FROM avg_demand_reads ORDER BY completed_at, rowid")


def test_read_current_stores_raw_rows_and_records_the_read_after_commit(fake):
    out = avg_demand.read_current("2026-11-02")
    assert out["rows"] == 4 and out["kind"] == "CURRENT" and out["source_table"] == CUR
    assert out["source_modified"] == "2026-11-02T03:15:02+00:00"                 # UTC ISO from the table metadata
    rows = _stored("2026-11-02")
    assert [(r["sku_code"], r["seller_code"], r["avg_demand"]) for r in rows] == [
        ("S1", "MEDX", 2.5), ("S2", "MEDX", 1.0), ("S2", "MEDX_E", 3.0), ("S3", "MEDX", None)]   # NULL kept as NULL
    rd = _reads()
    assert len(rd) == 1 and rd[0]["kind"] == "CURRENT" and rd[0]["n_rows"] == 4 and rd[0]["business_date"] == "2026-11-02"
    assert rd[0]["source_modified"] == out["source_modified"]
    sql = fake.queries[0][0]
    assert f"`{CUR}`" in sql and "*" not in sql
    _assert_read_only(fake)


def test_read_current_replaces_only_its_day_and_is_idempotent(fake, monkeypatch):
    monkeypatch.setattr(avg_demand, "today_vn", lambda: date(2026, 11, 1))
    avg_demand.read_current("2026-11-01")
    monkeypatch.setattr(avg_demand, "today_vn", lambda: date(2026, 11, 2))
    avg_demand.read_current("2026-11-02")
    fake.responses["sel2_avg_demand_current"] = [_row("S1", "F1", "MEDX", 9.0)]
    avg_demand.read_current("2026-11-02")
    avg_demand.read_current("2026-11-02")
    assert [(r["sku_code"], r["avg_demand"]) for r in _stored("2026-11-02")] == [("S1", 9.0)]
    assert len(_stored("2026-11-01")) == 4                      # another day untouched
    assert len(_reads()) == 4


def test_a_failure_while_storing_keeps_the_old_rows_and_records_no_read(fake, monkeypatch):
    avg_demand.read_current("2026-11-02")
    fake.responses["sel2_avg_demand_current"] = [_row("S9", "F9", "MEDX", 1.0)]
    real = avg_demand._store_day

    def boom(*args, **kw):
        real(*args, **kw)                                       # rows deleted + inserted, then the failure
        raise RuntimeError("disk full")
    monkeypatch.setattr(avg_demand, "_store_day", boom)
    with pytest.raises(RuntimeError):
        avg_demand.read_current("2026-11-02")
    assert len(_stored("2026-11-02")) == 4                      # rolled back
    assert len(_reads()) == 1


def test_rows_without_a_completed_read_are_not_used(fake, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("crash before the read record")
    monkeypatch.setattr(avg_demand, "_record_read", boom)
    with pytest.raises(RuntimeError):
        avg_demand.read_current("2026-11-02")
    # 1.4.0 fix2: rows and read record are one transaction -> nothing stored, nothing recorded
    assert _stored("2026-11-02") == [] and _reads() == []
    res = avg_demand.avg_value("2026-11-02", rule="SUM")
    assert res["source_kind"] is None and res["values"] == {}


def test_null_keys_skipped_exact_repeats_kept_once_conflicts_refused(fake):
    fake.responses["sel2_avg_demand_current"] = [_row("S1", "F1", "MEDX", 1.0), _row("S1", "F1", "MEDX", 1.0),
                                                 _row(None, "F1", "MEDX", 1.0), _row("S2", "F1", None, 1.0)]
    out = avg_demand.read_current("2026-11-02")
    assert out["rows"] == 1 and out["skipped_null_keys"] == 2 and out["exact_duplicates"] == 1
    fake.responses["sel2_avg_demand_current"] = [_row("S1", "F1", "MEDX", 1.0), _row("S1", "F1", "MEDX", 2.0)]
    with pytest.raises(AppError) as e:
        avg_demand.read_current("2026-11-02")
    assert e.value.code == "AVG_DEMAND_CONFLICTING_ROWS"
    assert [r["avg_demand"] for r in _stored("2026-11-02")] == [1.0] and len(_reads()) == 1


def test_read_historical_per_day_latest_snapshot_partition_filter(fake):
    def hist(cfg):
        return [{**_row("S1", "F1", "MEDX", 1.0), "business_date": "2026-10-30", "transformed_at": "2026-10-30 08:10:00+00"},
                {**_row("S1", "F1", "MEDX", 5.0), "business_date": "2026-10-31", "transformed_at": "2026-10-31 07:00:00+00"},
                {**_row("S1", "F1", "MEDX", 6.0), "business_date": "2026-10-31", "transformed_at": "2026-10-31 08:10:00+00"}]
    fake.responses["sel2_avg_demand_hist"] = hist
    out = avg_demand.read_historical("2026-10-30", "2026-11-01")
    assert out["rows"] == 2 and out["superseded_rows"] == 1 and out["days_without_rows"] == ["2026-11-01"]
    assert [r["avg_demand"] for r in _stored("2026-10-31", HIST)] == [6.0]
    assert [(r["business_date"], r["kind"], r["source_table"]) for r in _reads()] == [
        ("2026-10-30", "HISTORICAL", HIST), ("2026-10-31", "HISTORICAL", HIST)]
    sql, cfg = fake.queries[-1]
    assert "transformed_at >= TIMESTAMP(@start)" in sql and f"`{HIST}`" in sql
    assert [(n, t, str(v)) for n, t, v in cfg["params"]] == [("start", "DATE", "2026-10-30"), ("end", "DATE", "2026-11-01")]
    _assert_read_only(fake)
    with pytest.raises(AppError):
        avg_demand.read_historical("2026-11-02", "2026-11-01")


def test_avg_value_prefers_the_current_read_of_the_day_else_the_historical(fake):
    fake.responses["sel2_avg_demand_hist"] = [{**_row("S1", "F1", "MEDX", 7.0), "business_date": "2026-11-02",
                                               "transformed_at": "2026-11-02 08:10:00+00"}]
    avg_demand.read_historical("2026-11-02", "2026-11-02")
    res = avg_demand.avg_value("2026-11-02")
    assert res["source_kind"] == "HISTORICAL" and res["source_table"] == HIST
    assert res["values"][("S1", "F1")]["value"] == 7.0
    avg_demand.read_current("2026-11-02")
    res = avg_demand.avg_value("2026-11-02")
    assert res["source_kind"] == "CURRENT" and res["values"][("S1", "F1")]["value"] == 2.5
    assert res["source_modified"].startswith("2026-11-02T03:15:02")


@pytest.mark.parametrize("rule, expected, reason", [
    ("PENDING", None, "SELLER_RULE_PENDING"), ("SUM", 4.0, None), ("MAX", 3.0, None),
    ("SELLER:MEDX_E", 3.0, None), ("SELLER:BML_E", None, "SELLER_NOT_FOUND")])
def test_seller_rule_with_several_sellers(fake, rule, expected, reason):
    avg_demand.read_current("2026-11-02")
    res = avg_demand.avg_value("2026-11-02", rule=rule)
    assert res["values"][("S2", "F1")] == {"value": expected, "reason": reason, "n_sellers": 2}
    # one seller row: its value whatever the rule; NULL stays no value
    assert res["values"][("S1", "F1")]["value"] == 2.5
    assert res["values"][("S3", "F2")] == {"value": None, "reason": "AVG_DEMAND_NULL", "n_sellers": 1}


def test_seller_rule_default_from_settings_and_requested_keys(fake):
    avg_demand.read_current("2026-11-02")
    res = avg_demand.avg_value("2026-11-02", keys=[("S2", "F1"), ("S404", "F1")])
    assert res["rule"] == "PENDING" and set(res["values"]) == {("S2", "F1"), ("S404", "F1")}
    assert res["values"][("S2", "F1")]["reason"] == "SELLER_RULE_PENDING"
    assert res["values"][("S404", "F1")]["reason"] == "NO_ROW"
    assert avg_demand.apply_rule([("A", None), ("B", 1.0)], "SUM") == (None, "AVG_DEMAND_NULL")


def test_disabled_pipeline_reads_nothing(sel2_off):
    f = AvgFake(responses={"sel2_avg_demand_current": CURRENT_ROWS})
    connector.set_client_factory(f)
    with pytest.raises(AppError) as e:
        avg_demand.read_current("2026-11-02")
    assert e.value.code == "SEL2_PIPELINE_DISABLED" and f.queries == []


def test_source_modified_now_metadata_only(fake):
    assert avg_demand.source_modified_now().startswith("2026-11-02T03:15:02")
    fake.errors[CUR] = RuntimeError("no access")
    assert avg_demand.source_modified_now() is None
    assert fake.queries == []


def test_cli_plan_without_yes_and_read_with_yes(fake, capsys):
    assert cli.main(["sel2-avg-read", "--date", "2026-11-02"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True and out["db"] and out["kind"] == "CURRENT" and fake.queries == []
    assert cli.main(["sel2-avg-read", "--date", "2026-11-02", "--hist-from", "2026-11-01"]) == 2
    capsys.readouterr()
    assert cli.main(["sel2-avg-read", "--date", "2026-11-02", "--yes"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["result"]["rows"] == 4 and len(_reads()) == 1


def test_api_avg_demand(fake, client):
    avg_demand.read_current("2026-11-02")
    r = client.get("/api/sel2/avg-demand", params={"date": "2026-11-02", "sku_code": "s2"})
    assert r.status_code == 200
    body = r.json()
    assert body["source_kind"] == "CURRENT" and body["total"] == 1
    assert body["items"][0] == {"sku_code": "S2", "fc_code": "F1", "value": None, "reason": "SELLER_RULE_PENDING",
                                "n_sellers": 2}
    assert client.get("/api/sel2/avg-demand", params={"date": "02/11/2026"}).status_code == 422
    empty = client.get("/api/sel2/avg-demand", params={"date": "2026-10-01"}).json()
    assert empty["source_kind"] is None and empty["items"] == []
