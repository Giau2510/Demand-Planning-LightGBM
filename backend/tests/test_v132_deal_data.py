"""1.3.2 data layer (docs/hoc_lai_2025_deal_20261030.md 1.1-1.3), written BEFORE the implementation (task G3-T1a):
the extended-history backfill floor, the order-line deal codes (demand_deal_daily), the deal source (deals +
deal_snapshots), the read-only deal checks, the CLI commands and the preset option; plus the G3-T0 settings and
migration 0012. Temporary data only (conftest); BigQuery is a FakeBQ subclass, nothing real is read.

Section A (G3-T0 settings, migration 0012) and section B (defaults unchanged) pass on the code of 1.3.1 + G3-T0.
Sections C-G need the G3-T1 code (sync.backfill_floor, app.bq.deal_lines, app.bq.deal_source, the new CLI commands)
and FAIL until it exists.

Interface these tests fix where the contract leaves it open (the coder matches it):
* every deal query goes through connector._run with a kind containing "deal" (e.g. -- df:deal_lines / df:deal_source);
  the fake routes the query of the deal table by its table id in the SQL text, any other deal query to the lines;
* the deal-lines read returns rows {"_kind": "DEAL", order_date, sku_id, fc_id, deal_code, qty, n_rows} (lines with a
  deal code, summed per day x SKU x FC x code) and one {"_kind": "TOTAL", qty, n_rows} (valid lines of the window);
  params start / end (DATE) like the demand read;
* run_d1_sync returns "deal_lines" / "deal_refresh" dicts with a "status" (SUCCEEDED / FAILED);
* deal_source.checks(scope, start, end) -> {"deals": {n_rows, duplicate_keys, ready_after_end},
  "lines": {rows, qty, match_key: {rows_share, qty_share}, match_code: {rows_share, qty_share}},
  "per_deal": {deals_compared, share_equal, share_within_5pct, ratio}, "snapshot": {id, taken_at}};
* CLI deal-lines-load / open-hours-load / deal-refresh print one JSON object; the chunked commands list "chunks"
  [{start, end, estimated_bytes, ...}]; a refusal exits with a non-zero code and writes nothing.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from app import cli, db, timeutil
from app import settings_service as ss
from app.bq import connector
from app.messages import AppError
from fake_bq import FakeBQ, FakeJob

SCHEMA = [("so_code", "STRING"), ("created_date", "DATE"), ("sku_code", "STRING"), ("fc_code", "STRING"),
          ("demand_quantity", "INT64"), ("sales_price", "FLOAT64"), ("total_open_hours", "FLOAT64"),
          ("deal_code", "STRING")]
FM = {"order_id": {"column": "so_code", "usage": "OPTIONAL"}, "order_date": {"column": "created_date", "usage": "REQUIRED"},
      "created_at": {"column": None, "usage": "UNUSED"},
      "sku_id": {"column": "sku_code", "usage": "REQUIRED"}, "fc_id": {"column": "fc_code", "usage": "REQUIRED"},
      "order_qty": {"column": "demand_quantity", "usage": "REQUIRED"},
      "unit_price": {"column": "sales_price", "usage": "OPTIONAL"}}
REF = {"open_hours": {"column": "total_open_hours", "usage": "OPTIONAL"}}
SCOPE = "BIGQUERY:lakehouse-prod-394907.sales.orders"
DEAL_TABLE = "lakehouse-prod-394907.gold_buymed_vn2.demand_planing_deal"
WINDOW = "2026-01-01"            # data_policy.window_start_date (default)
EXT = "2025-11-01"               # data_policy.extended_history_start_date of the tests that set it
UTC = timezone.utc
# sha256 of the regular D-1 aggregation SQL ("-- df:daily") of this mapping (exact_duplicate_policy BLOCK), measured on
# the unchanged connector.py / sync.py of 1.3.1 (+ G3-T0) on 30/10/2026: the new optional parameters must leave it
# byte-identical
DAILY_SQL_SHA_131 = "6132f3f77a4409a3dcdbc819c8d0c0be1d2607ca7982632f99e5f811fdc0d708"


def _d(s) -> date:
    return date.fromisoformat(str(s)[:10])


def _days(a: date, b: date):
    while a <= b:
        yield a
        a += timedelta(days=1)


def _month_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """[start, end] cut at every calendar-month boundary (written independently of deal_lines.months)."""
    out, cur = [], [start, start]
    for d in _days(start, end):
        if (d.year, d.month) != (cur[0].year, cur[0].month):
            out.append(tuple(cur))
            cur = [d, d]
        cur[1] = d
    return out + [tuple(cur)] if start <= end else []


def _source(start: date, end: date) -> list[dict]:
    """Synthetic demand per day: A 5 every day; B 3 on even ordinal days only (absent = no row, never a zero)."""
    out = []
    for d in _days(start, end):
        for sku, q in (("A", 5.0), ("B", 3.0)):
            if sku == "B" and d.toordinal() % 2:
                continue
            out.append({"order_date": d, "sku_id": sku, "fc_id": "F1", "qty": q, "n_rows": 2, "n_orders": 2,
                        "avg_unit_price": 10.0, "avg_discount_rate": None, "promo_share": None, "voucher_share": None,
                        "max_source_updated_at": None, "max_batch_id": None, "open_hours_null_rows": 0,
                        "open_hours_min": 24.0, "open_hours_max": 24.0})
    return out


def _deal_lines(src: list[dict]) -> list[dict]:
    """A: deal D1 with 2 of its 5 units every day; B: deal D2 with all its 3 units."""
    return [{"order_date": r["order_date"], "sku_id": r["sku_id"], "fc_id": "F1",
             "deal_code": "D1" if r["sku_id"] == "A" else "D2", "qty": 2.0 if r["sku_id"] == "A" else 3.0, "n_rows": 1}
            for r in src]


class DealFake(FakeBQ):
    """FakeBQ that answers the daily read by its window and the deal queries (kind containing 'deal')."""

    def __init__(self, src: list[dict], **kw):
        super().__init__(**kw)
        self.src = src
        self.lines = _deal_lines(src)
        self.deal_rows: list[dict] = []
        self.deal_errors: dict = {}
        self.deal_modified = datetime(2026, 10, 1, 1, 2, 3, tzinfo=UTC)
        self.responses["daily"] = lambda cfg: [r for r in self.src if self._win(cfg)[0] <= r["order_date"] <= self._win(cfg)[1]]

    @staticmethod
    def _win(cfg) -> tuple[date, date]:
        p = {n: v for n, _, v in (cfg or {}).get("params") or []}
        return _d(p["start"]), _d(p["end"])

    def get_table(self, name):
        t = super().get_table(name)
        if name == DEAL_TABLE:
            t.modified = self.deal_modified
        return t

    def query(self, sql, job_config=None):
        kind = re.match(r"-- df:(\w+)", sql).group(1)
        if "deal" not in kind.lower():
            return super().query(sql, job_config)
        self.queries.append((sql, job_config))
        route = "deal_source" if DEAL_TABLE in sql else "deal_lines"
        if route in self.deal_errors:
            raise self.deal_errors[route]
        if job_config and job_config.get("dry_run"):
            return FakeJob([], self.bytes)
        if route == "deal_source":
            return FakeJob([dict(r) for r in self.deal_rows], self.bytes)
        s, e = self._win(job_config)
        rows = [{"_kind": "DEAL", **r} for r in self.lines if s <= r["order_date"] <= e]
        src = [r for r in self.src if s <= r["order_date"] <= e]
        rows.append({"_kind": "TOTAL", "order_date": None, "sku_id": None, "fc_id": None, "deal_code": None,
                     "qty": sum(r["qty"] for r in src), "n_rows": sum(r["n_rows"] for r in src)})
        return FakeJob(rows, self.bytes)

    # ---- what was sent
    def sent(self, pred) -> list[tuple[str, dict]]:
        return [(q, c) for q, c in self.queries if not (c or {}).get("dry_run") and pred(re.match(r"-- df:(\w+)", q).group(1))]

    def deal_sent(self, route=None):
        return [(q, c) for q, c in self.sent(lambda k: "deal" in k.lower())
                if route is None or (route == "deal_source") == (DEAL_TABLE in q)]

    def daily_sql(self) -> list[str]:
        return [q for q, _ in self.sent(lambda k: k == "daily")]


def _production(src_start: date | None = None, *, deal_col: str = "", deal_table: str = "", ext: str | None = None,
                policy: str | None = None) -> DealFake:
    from test_bigquery import PASSING_VALIDATION
    y = timeutil.today_vn() - timedelta(days=1)
    fake = DealFake(_source(src_start or _d(EXT), y), schema=SCHEMA,
                    responses={"completion": [{"n": 1}],
                               "profile": [{"n_rows": 100, "min_date": date(2026, 1, 1), "max_date": y}],
                               **PASSING_VALIDATION})
    connector.set_client_factory(fake)
    if ext:
        ss.update("data_policy", {"extended_history_start_date": ext})
    ss.update("bigquery", {"dataset_id": "sales", "source_table": "orders", "location": "asia-southeast1",
                           "partition_column": "", "field_mapping": FM, "reference_mapping": REF,
                           "completion_table": "done", "completion_date_column": "d",
                           **({"exact_duplicate_policy": policy} if policy else {})})
    connector.test_connection()
    ss.update("bigquery", {"schema_snapshot": connector.read_schema()["columns"]})
    connector.profile(7)
    assert connector.validate_source()["passed"]
    ss.update("bigquery", {"production_enabled": True, "deal_code_column": deal_col, "deal_table_id": deal_table})
    ss.update("general", {"active_source": "BIGQUERY"})
    return fake


def _q(sql, *a):
    with db.read() as c:
        return [tuple(r) for r in c.execute(sql, a)]


def _n(table: str) -> int:
    return _q(f"SELECT COUNT(*) FROM {table}")[0][0]


def _alerts(code: str) -> list[tuple]:
    return _q("SELECT level, params_json FROM alerts WHERE code=? ORDER BY rowid", code)


def _demand(start: str, end: str) -> list[tuple]:
    return _q("SELECT order_date, sku_id, fc_id, qty FROM demand_daily WHERE scope_key=? AND order_date BETWEEN ? AND ? "
              "ORDER BY 1, 2, 3", SCOPE, start, end)


def _lines(start: str = "0000", end: str = "9999") -> list[tuple]:
    return _q("SELECT order_date, sku_id, fc_id, deal_code, qty, n_rows, load_id FROM demand_deal_daily WHERE scope_key=? "
              "AND order_date BETWEEN ? AND ? ORDER BY 1, 2, 3, 4", SCOPE, start, end)


def _backfill(start: str, end: str, job: str = "JB") -> dict:
    from app import sync
    pv = sync.backfill_preview(start, end)
    assert pv["status"] == "READY", pv
    return sync.run_d1_sync(job, backfill_start=start, backfill_end=end, backfill_preview_id=pv["preview_id"])


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ================================================================== A. G3-T0 settings and migration 0012 (pass now)
def test_new_settings_default_to_the_behaviour_of_1_3_1():
    assert ss.DataPolicySettings().extended_history_start_date is None
    bq = ss.BigQuerySettings()
    assert (bq.deal_code_column, bq.deal_table_id) == ("", "")
    m = ss.ModelSettings()
    assert (m.feature_set, m.ly_history_start) == ("CHOT", None)
    assert ss.get("data_policy").extended_history_start_date is None and ss.get("bigquery").deal_code_column == ""


@pytest.mark.parametrize("fs", ["CHOT_LY", "CHOT_LY_DEAL"])
def test_the_extra_feature_sets_need_the_direct_strategy(fs):
    with pytest.raises(ValueError, match="FEATURE_SET_DIRECT_ONLY"):
        ss.ModelSettings(feature_set=fs, forecast_strategy="RECURSIVE")
    assert ss.ModelSettings(feature_set=fs, forecast_strategy="DIRECT").feature_set == fs
    assert ss.ModelSettings(feature_set="CHOT", forecast_strategy="RECURSIVE").feature_set == "CHOT"
    with pytest.raises(ValueError):
        ss.ModelSettings(feature_set="LY", forecast_strategy="DIRECT")


@pytest.mark.parametrize("ext, ok", [("2025-12-31", True), ("2025-01-01", True), ("2026-01-01", False),
                                     ("2026-02-01", False), ("2025-13-01", False), ("2025/11/01", False)])
def test_the_extended_history_start_must_be_a_date_before_the_window(ext, ok):
    if ok:
        assert ss.DataPolicySettings(extended_history_start_date=ext).extended_history_start_date == ext
        return
    with pytest.raises(ValueError) as e:
        ss.DataPolicySettings(extended_history_start_date=ext)
    if ext[:4].isdigit() and "-" in ext and not ext.startswith("2025-13"):
        assert "EXTENDED_HISTORY_AFTER_WINDOW" in str(e.value)
    with pytest.raises(ValueError):                                     # nothing saved through the service either
        ss.update("data_policy", {"extended_history_start_date": ext})
    assert ss.get("data_policy").extended_history_start_date is None


def test_moving_the_window_start_before_a_saved_extended_date_is_refused():
    ss.update("data_policy", {"extended_history_start_date": "2025-11-01"})
    with pytest.raises(ValueError, match="EXTENDED_HISTORY_AFTER_WINDOW"):
        ss.update("data_policy", {"window_start_date": "2025-10-01"})
    assert ss.get("data_policy").window_start_date == WINDOW


@pytest.mark.parametrize("col, ok", [("deal_code", True), (" deal_code ", True), ("_x9", True), ("", True),
                                     ("deal code", False), ("9deal", False), ("deal-code", False), ("a;DROP", False)])
def test_deal_code_column_validator(col, ok):
    if ok:
        assert ss.BigQuerySettings(deal_code_column=col).deal_code_column == col.strip()
    else:
        with pytest.raises(ValueError):
            ss.BigQuerySettings(deal_code_column=col)


@pytest.mark.parametrize("tid, ok", [(DEAL_TABLE, True), ("", True), ("dataset.table", False), ("a.b.c.d", False),
                                     ("p.d.t; DROP TABLE x", False)])
def test_deal_table_id_validator(tid, ok):
    if ok:
        assert ss.BigQuerySettings(deal_table_id=tid).deal_table_id == tid
    else:
        with pytest.raises(ValueError):
            ss.BigQuerySettings(deal_table_id=tid)


def test_put_model_refuses_ly_history_start_and_always_saves_it_empty(client):
    cur = client.get("/api/settings").json()["model"]
    r = client.put("/api/settings/model", json={**cur, "ly_history_start": "2025-01-01"})
    assert r.status_code == 409 and r.json()["code"] == "LY_HISTORY_SET_BY_TRAINING"
    assert ss.get("model").ly_history_start is None
    r = client.put("/api/settings/model", json={**cur, "ly_history_start": None, "num_boost_round": 77})
    assert r.status_code == 200 and r.json()["ly_history_start"] is None and r.json()["num_boost_round"] == 77
    r = client.put("/api/settings/model", json={**cur, "feature_set": "CHOT_LY", "forecast_strategy": "RECURSIVE"})
    assert r.status_code == 422 and ss.get("model").feature_set == "CHOT"


def test_mapping_hash_ignores_the_deal_keys_and_the_extended_date_and_production_stays_on(client):
    _production(_d(WINDOW))
    bq = ss.get("bigquery")
    h0 = connector.mapping_hash(bq)
    ss.update("data_policy", {"extended_history_start_date": EXT})
    assert connector.mapping_hash(ss.get("bigquery")) == h0
    r = client.put("/api/settings/bigquery", json={"deal_code_column": "deal_code", "deal_table_id": DEAL_TABLE})
    assert r.status_code == 200
    bq2 = ss.get("bigquery")
    assert (bq2.deal_code_column, bq2.deal_table_id, bq2.production_enabled) == ("deal_code", DEAL_TABLE, True)
    assert connector.mapping_hash(bq2) == h0 and connector.validation_ok_for_current()
    assert {k: v for k, v in bq2.model_dump().items() if k not in ("deal_code_column", "deal_table_id")} == \
        {k: v for k, v in bq.model_dump().items() if k not in ("deal_code_column", "deal_table_id")}


def test_migration_0012_on_a_v11_database_keeps_every_row_and_adds_the_tables(tmp_path):
    from test_v126_retention_defaults import _db_at
    target = tmp_path / "v11.db"
    _db_at(target, 11)
    c = sqlite3.connect(target)
    c.execute("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, loaded_at) "
              "VALUES ('S', 'BIGQUERY', '2026-01-02', 'A', 'F1', 5, 1, 'x'), ('S', 'BIGQUERY', '2026-01-03', 'A', 'F1', 0, 0, 'x')")
    c.commit()
    tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    rows_of = lambda cn, t: sorted(cn.execute(f"SELECT * FROM {t}").fetchall(), key=repr)   # noqa: E731
    before = {t: rows_of(c, t) for t in tabs if t not in ("sqlite_sequence",)}
    frv0 = [r[1] for r in c.execute("PRAGMA table_info(forecast_refresh_values)")]
    c.close()
    res = db.migrate(target)
    assert (res["from"], res["to"], res["applied"]) == (11, 12, ["0012_ly_deal.sql"])
    assert db.migrate(target)["applied"] == []
    c = sqlite3.connect(target)
    for t, rows in before.items():
        if t == "schema_migrations":
            continue
        assert rows_of(c, t) == rows, t
    new = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"demand_deal_daily", "deal_line_loads", "deal_snapshots", "deals"} <= new
    assert [r[1] for r in c.execute("PRAGMA table_info(forecast_refresh_values)")] == frv0 + ["deal_active"]
    assert all(c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0
               for t in ("demand_deal_daily", "deal_line_loads", "deal_snapshots", "deals"))
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    # a snapshot holds either its rows or a pointer to the earlier snapshot with the same content, never both / none
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO deal_snapshots(id, source_table, taken_at, n_rows, content_sha256) VALUES "
                  "('X', 'p.d.t', 'x', 0, 'h')")
    c.close()


# ================================================================== B. defaults: the behaviour of 1.3.1 (pass now)
def test_defaults_refuse_a_backfill_before_the_window_and_send_no_deal_query(client):
    from app import sync
    fake = _production()
    out = sync.run_d1_sync("J1")
    assert out["status"] == "SUCCEEDED" and out["full_reload"] and out["window_start"] == WINDOW
    sql = fake.daily_sql()
    assert len(sql) == 1
    assert _sha(sql[0]) == DAILY_SQL_SHA_131                               # the 1.3.1 text, byte for byte
    assert _q("SELECT MIN(order_date) FROM demand_daily WHERE scope_key=?", SCOPE)[0][0] == WINDOW
    # a window entirely before window_start_date: clipped to the floor -> empty -> refused, by the preview and the job
    for call in (lambda: sync.backfill_preview("2025-11-10", "2025-11-20"),
                 lambda: sync.run_d1_sync("J2", backfill_start="2025-11-10", backfill_end="2025-11-20")):
        with pytest.raises(AppError) as e:
            call()
        assert e.value.code == "VALIDATION_ERROR"
    # a window spanning it: clipped to the window start
    pv = sync.backfill_preview("2025-12-25", "2026-01-05")
    assert pv["window"] == {"start": WINDOW, "end": "2026-01-05", "days": 5}
    assert all(_d(c["params"][0][2]) >= _d(WINDOW) for q, c in fake.sent(lambda k: k == "daily"))
    assert fake.deal_sent() == []                                          # no deal query, ever
    assert [_n(t) for t in ("demand_deal_daily", "deal_line_loads", "deal_snapshots", "deals")] == [0, 0, 0, 0]
    assert out.get("deal_lines") is None and out.get("deal_refresh") is None
    # the same settings saved explicitly at their defaults: the same SQL text and the same stored result
    rows0 = _demand(WINDOW, "9999")
    ss.update("bigquery", {"deal_code_column": "", "deal_table_id": ""})
    ss.update("data_policy", {"extended_history_start_date": None})
    out2 = sync.run_d1_sync("J3")
    assert fake.daily_sql()[-1] == sql[0] and not out2["full_reload"]
    assert _demand(WINDOW, "9999") == rows0 and fake.deal_sent() == []


# ================================================================== C. extended floor (needs G3-T1)
def test_backfill_floor_is_the_extended_date_only_when_set():
    from app import sync
    _production(_d(WINDOW))
    bq, y = ss.get("bigquery"), timeutil.today_vn() - timedelta(days=1)
    assert sync.backfill_floor(bq, y) == connector.read_range(bq, y)[0] == _d(WINDOW)
    ss.update("data_policy", {"extended_history_start_date": EXT})
    assert sync.backfill_floor(ss.get("bigquery"), y) == _d(EXT)
    assert connector.read_range(ss.get("bigquery"), y)[0] == _d(WINDOW)       # the regular read floor is unchanged


def test_a_backfill_before_the_window_reads_from_the_extended_floor_and_keeps_the_regular_d1(client):
    from app import sync
    fake = _production()
    first = sync.run_d1_sync("J1")
    sql0 = fake.daily_sql()[0]
    h0 = connector.mapping_hash(ss.get("bigquery"))
    with db.read() as c:
        st0 = sync._state_get(c, f"last_d1_sync:{SCOPE}")
    ss.update("data_policy", {"extended_history_start_date": EXT})
    assert connector.mapping_hash(ss.get("bigquery")) == h0                 # validation / D-1 state not reset
    # entirely before the window (API preview + API backfill: the route uses the same floor)
    pv = client.post("/api/sync/backfill/preview", json={"start": "2025-11-10", "end": "2025-11-20"}).json()
    assert pv["status"] == "READY" and pv["window"] == {"start": "2025-11-10", "end": "2025-11-20", "days": 11}
    q, c = fake.sent(lambda k: k == "daily")[-1]
    assert (_d(c["params"][0][2]), _d(c["params"][1][2])) == (date(2025, 11, 10), date(2025, 11, 20))  # not clamped
    assert q == sql0                                                        # the same SQL text, other dates
    r = client.post("/api/sync/backfill", json={"start": "2025-11-10", "end": "2025-11-20", "preview_id": pv["preview_id"]})
    assert r.status_code == 200
    with db.read() as cn:
        job = db.one(cn, "SELECT status, result_json FROM job_runs WHERE job_type='D1_SYNC' ORDER BY created_at DESC, "
                         "rowid DESC LIMIT 1")
    assert job["status"] == "SUCCEEDED", job["result_json"]
    want = [(str(r["order_date"]), r["sku_id"], "F1", r["qty"]) for r in fake.src
            if date(2025, 11, 10) <= r["order_date"] <= date(2025, 11, 20)]
    assert _demand("2025-11-10", "2025-11-20") == want and _demand(EXT, "2025-11-09") == []
    # spanning the window start, and one starting before the extended floor (clipped to it)
    out = _backfill("2025-12-25", "2026-01-05")
    assert out["window_start"] == "2025-12-25" and out["backfill"]
    pv2 = sync.backfill_preview("2025-10-01", "2025-11-03")
    assert pv2["window"]["start"] == EXT
    assert len(_demand("2025-12-25", "2025-12-31")) == len([r for r in fake.src if date(2025, 12, 25) <= r["order_date"]
                                                             <= date(2025, 12, 31)])
    # the regular D-1 is untouched: same state, not a full reload, same SQL, its window starts inside the data window
    with db.read() as c:
        st1 = sync._state_get(c, f"last_d1_sync:{SCOPE}")
    assert (st1["load_id"], st1["mapping_hash"], st1["watermark"]) == (st0["load_id"], st0["mapping_hash"], st0["watermark"])
    nxt = sync.run_d1_sync("J9")
    assert nxt["full_reload"] is False and _d(nxt["window_start"]) >= _d(WINDOW) and fake.daily_sql()[-1] == sql0
    assert nxt["mapping_hash"] == first["mapping_hash"] == h0
    assert len(_demand("2025-11-10", "2025-11-20")) == len(want)              # pre-window days kept by the regular D-1


# ================================================================== D. deal lines (needs G3-T1)
def test_d1_and_backfill_load_the_deal_lines_of_exactly_their_window(client):
    from app import sync
    y = timeutil.today_vn() - timedelta(days=1)
    fake = _production(deal_col="deal_code", ext=EXT)
    with db.tx() as c:                                                      # a stored line outside every window
        c.execute("INSERT INTO demand_deal_daily(scope_key, order_date, sku_id, fc_id, deal_code, qty, n_rows, load_id, "
                  "loaded_at) VALUES (?, '2025-11-02', 'A', 'F1', 'OLD', 1, 1, 'X', 'x')", (SCOPE,))
    out = sync.run_d1_sync("J1")                                            # full reload: window start .. y
    assert out["status"] == "SUCCEEDED" and out["deal_lines"]["status"] == "SUCCEEDED"
    # review fix round: one query and one deal_line_loads row per calendar month of the window, oldest first
    chunks = _month_chunks(_d(WINDOW), y)
    assert fake.daily_sql()[0] is not None and len(fake.deal_sent("deal_lines")) == len(chunks)
    assert [(_d(c["params"][0][2]), _d(c["params"][1][2])) for _, c in fake.deal_sent("deal_lines")] == chunks
    loads = _q("SELECT trigger, range_start, range_end, rows_written, deal_code_column, job_id FROM deal_line_loads "
               "ORDER BY rowid")
    want = [(str(r["order_date"]), r["sku_id"], "F1", r["deal_code"], r["qty"], 1) for r in fake.lines
            if _d(WINDOW) <= r["order_date"] <= y]
    assert loads == [("D1_SYNC", str(s), str(e), len([w for w in want if str(s) <= w[0] <= str(e)]), "deal_code", "J1")
                     for s, e in chunks]
    assert [(c["window"]["start"], c["window"]["end"]) for c in out["deal_lines"]["chunks"]] == [
        (str(s), str(e)) for s, e in chunks]
    assert out["deal_lines"]["rows_written"] == len(want)
    assert [r[:6] for r in _lines(WINDOW, str(y))] == want
    assert _lines("2025-11-02", "2025-11-02")[0][3] == "OLD"                  # outside: untouched
    # incremental D-1: the lines of its window are replaced (D1 -> D9 on y), the earlier days keep their load
    first_load = _lines(WINDOW, WINDOW)[0][6]
    fake.lines = [{**r, "deal_code": "D9", "qty": 1.0} if (r["order_date"] == y and r["sku_id"] == "A") else r
                  for r in fake.lines]
    out2 = sync.run_d1_sync("J2")
    w0 = out2["window_start"]
    assert not out2["full_reload"] and out2["deal_lines"]["status"] == "SUCCEEDED"
    n2 = len(_month_chunks(_d(w0), y))                                     # the incremental window, month by month
    assert _q("SELECT trigger, range_start, range_end FROM deal_line_loads ORDER BY rowid")[-n2:] == [
        ("D1_SYNC", str(s), str(e)) for s, e in _month_chunks(_d(w0), y)]
    assert {r[3] for r in _lines(str(y), str(y)) if r[1] == "A"} == {"D9"}
    assert _lines(WINDOW, WINDOW)[0][6] == first_load                         # before the window: not rewritten
    # a backfill (pre-window days) loads its own window with trigger BACKFILL
    _backfill("2025-11-10", "2025-11-12")
    assert _q("SELECT trigger, range_start, range_end, job_id FROM deal_line_loads ORDER BY rowid")[-1] == (
        "BACKFILL", "2025-11-10", "2025-11-12", "JB")
    assert len(_lines("2025-11-10", "2025-11-12")) == len([r for r in fake.lines if date(2025, 11, 10) <= r["order_date"]
                                                           <= date(2025, 11, 12)])
    assert _lines("2025-11-02", "2025-11-02")[0][3] == "OLD"
    # the deal SQL reads the same source, dates and validity rule as the demand, plus the trimmed deal code
    bq = ss.get("bigquery")
    q, c = fake.deal_sent("deal_lines")[-1]
    assert connector._table_ref(bq) in q and connector._order_date_expr(bq) in q and "TRIM(" in q and "deal_code" in q
    assert {n for n, _, _ in c["params"]} >= {"start", "end"}
    assert "NEGATIVE_TARGET" in q or "order_qty >= 0" in q.replace("  ", " ") or "_reason IS NULL" in q
    assert fake.daily_sql()[-1] == fake.daily_sql()[0]                      # the demand SQL itself is unchanged


@pytest.mark.parametrize("policy, dropped", [("DROP_EXACT", True), ("KEEP", False), ("BLOCK", False)])
def test_the_deal_read_applies_the_same_exact_duplicate_rule_as_the_demand_read(client, policy, dropped):
    from app.bq import deal_lines
    fake = _production(_d(WINDOW), deal_col="deal_code", policy=policy)
    from app import sync
    sync.run_d1_sync("J1")
    bq = ss.get("bigquery")
    q, _ = fake.deal_sent("deal_lines")[-1]
    daily = fake.daily_sql()[-1]
    rn = "ROW_NUMBER() OVER (PARTITION BY TO_JSON_STRING(STRUCT("
    cmp = ", ".join(x["alias"] for x in connector.dup_columns(bq))
    assert (rn in q) is dropped and (rn in daily) is dropped
    if dropped:
        assert f"STRUCT({cmp})" in q                                        # the same compared columns
    assert "_pend" in q                                                     # pending orders exempt, as for demand
    assert callable(deal_lines.load_window)


def test_blank_deal_codes_are_ignored(client):
    from app import sync
    y = timeutil.today_vn() - timedelta(days=1)
    fake = _production(_d(WINDOW), deal_col="deal_code")
    fake.lines = [r for r in fake.lines if r["order_date"] == y] + [
        {"order_date": y, "sku_id": "A", "fc_id": "F1", "deal_code": code, "qty": 1.0, "n_rows": 1} for code in ("", "   ", None)]
    out = sync.run_d1_sync("J1")
    assert out["deal_lines"]["status"] == "SUCCEEDED"
    assert {r[3] for r in _lines()} <= {"D1", "D2"} and all(r[3].strip() for r in _lines())


@pytest.mark.parametrize("bad", ["above", "no_demand"])
def test_deal_lines_above_the_stored_demand_are_not_written_and_never_fail_the_d1(client, bad):
    from app import sync
    y = timeutil.today_vn() - timedelta(days=1)
    fake = _production(_d(WINDOW), deal_col="deal_code")
    if bad == "above":                                                     # A has 5 units on y: 7 of a deal cannot be
        fake.lines = [{**r, "qty": 7.0} if (r["order_date"] == y and r["sku_id"] == "A") else r for r in fake.lines]
    else:                                                                  # a key without any demand row
        fake.lines = fake.lines + [{"order_date": y, "sku_id": "ZZ", "fc_id": "F1", "deal_code": "D1", "qty": 1.0,
                                    "n_rows": 1}]
    out = sync.run_d1_sync("J1")
    assert out["status"] == "SUCCEEDED" and out["deal_lines"]["status"] == "FAILED"
    assert _demand(str(y), str(y))                                          # the demand is written
    # review fix round (month chunks): the month of y is the last chunk - nothing of it is written; the earlier months
    # (each its own transaction) are kept
    m0 = y.replace(day=1)
    chunks = _month_chunks(_d(WINDOW), y)
    assert _lines(str(m0), str(y)) == []                                    # nothing of the refused month
    assert _q("SELECT range_start, range_end FROM deal_line_loads ORDER BY rowid") == [
        (str(s), str(e)) for s, e in chunks[:-1]]
    assert len(_lines()) == len([r for r in fake.lines if _d(WINDOW) <= r["order_date"] < m0])
    assert out["deal_lines"]["failed_chunk"] == {"start": str(m0), "end": str(y)}
    al = _alerts("DEAL_LINES_EXCEED_DEMAND")
    assert len(al) == 1 and al[0][0] == "WARNING"
    p = json.loads(al[0][1])
    assert p["failed_chunk"] == {"start": str(m0), "end": str(y)}
    assert p["chunks_done"] == [{"start": str(s), "end": str(e)} for s, e in chunks[:-1]]
    # the same rule when called directly: AppError, nothing written
    from app.bq import deal_lines
    n0 = (_n("demand_deal_daily"), _n("deal_line_loads"))
    with pytest.raises(AppError) as e:
        deal_lines.load_window(SCOPE, y, y, "MANUAL")
    assert e.value.code == "DEAL_LINES_EXCEED_DEMAND" and (_n("demand_deal_daily"), _n("deal_line_loads")) == n0


def test_a_failing_deal_query_never_fails_the_d1(client):
    from app import sync
    fake = _production(_d(WINDOW), deal_col="deal_code")
    fake.deal_errors["deal_lines"] = RuntimeError("boom")
    out = sync.run_d1_sync("J1")
    assert out["status"] == "SUCCEEDED" and out["deal_lines"]["status"] == "FAILED"
    assert _demand(WINDOW, "9999") and _n("demand_deal_daily") == 0 and _n("deal_line_loads") == 0
    al = _alerts("DEAL_LINES_LOAD_FAILED")
    assert len(al) == 1 and al[0][0] == "WARNING" and WINDOW in al[0][1]   # with the window
    # recovers on the next run
    fake.deal_errors.clear()
    assert sync.run_d1_sync("J2")["deal_lines"]["status"] == "SUCCEEDED" and _n("deal_line_loads") == 1


def test_load_window_refuses_above_max_bytes_before_running(client):
    from app import sync
    from app.bq import deal_lines
    y = timeutil.today_vn() - timedelta(days=1)
    fake = _production(_d(WINDOW))
    sync.run_d1_sync("J1")
    ss.update("bigquery", {"deal_code_column": "deal_code"})
    n0 = len(fake.deal_sent())
    with pytest.raises(AppError):
        deal_lines.load_window(SCOPE, y, y, "MANUAL", max_bytes=fake.bytes - 1)
    assert len(fake.deal_sent()) == n0 and _n("deal_line_loads") == 0      # only the dry run, nothing written
    res = deal_lines.load_window(SCOPE, y, y, "MANUAL", job_id="JM", max_bytes=fake.bytes)
    assert _q("SELECT load_id, trigger, job_id, estimated_bytes FROM deal_line_loads") == [
        (res["load_id"], "MANUAL", "JM", fake.bytes)]


# ================================================================== E. deal source (needs G3-T1)
def _deal(code, sku, fc="F1", ready=(2025, 11, 11, 0, 0, 0), end=(2025, 11, 11, 23, 59, 59), status="ACTIVE",
          used=10.0, mx=100.0, reason=None):
    return {"deal_code": code, "sku_code": sku, "fc_code": fc, "ready_time": datetime(*ready, tzinfo=UTC),
            "end_time": datetime(*end, tzinfo=UTC), "status": status, "quantity_used": used, "max_quantity": mx,
            "reason": reason}


DEALS = [_deal("D2", "B", used=3.0), _deal("D1", "A", ready=(2025, 11, 10, 17, 0, 0), end=(2025, 11, 12, 16, 59, 59)),
         _deal("D1", "A", fc="F2", used=None, mx=None), _deal("D3", "C", status="EXPIRED", reason="sold out")]


def _snaps():
    return _q("SELECT id, source_table, n_rows, content_sha256, rows_gz IS NULL, same_as, trigger FROM deal_snapshots "
              "ORDER BY taken_at, rowid")


def test_refresh_stores_a_snapshot_and_the_rows_as_the_vietnam_wall_clock(client):
    from app.bq import deal_source
    fake = _production(_d(WINDOW), deal_table=DEAL_TABLE)
    fake.deal_rows = DEALS
    deal_source.refresh("MANUAL", job_id="JR")
    (sid, tab, n, sha, no_blob, same_as, trig), = _snaps()
    assert (tab, n, no_blob, same_as, trig) == (DEAL_TABLE, 4, 0, None, "MANUAL")
    rows = _q("SELECT row_no, deal_code, sku_code, fc_code, ready_time, end_time, status, quantity_used, max_quantity, "
              "reason, snapshot_id FROM deals WHERE source_table=? ORDER BY row_no", DEAL_TABLE)
    assert [r[1:4] for r in rows] == [("D1", "A", "F1"), ("D1", "A", "F2"), ("D2", "B", "F1"), ("D3", "C", "F1")]
    assert [r[0] for r in rows] == sorted(r[0] for r in rows) and len({r[0] for r in rows}) == 4
    a = rows[0]
    assert (a[4], a[5]) == ("2025-11-10 17:00:00", "2025-11-12 16:59:59")    # UTC components, never +7 h
    assert rows[1][7] is None and rows[1][8] is None and rows[3][9] == "sold out"   # NULL stays NULL
    assert {r[10] for r in rows} == {sid}
    snap = _q("SELECT rows_gz, checks_json, source_modified, estimated_bytes FROM deal_snapshots")[0]
    raw = gzip.decompress(snap[0])
    assert hashlib.sha256(raw).hexdigest() == sha
    body = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    assert len(body) == 4 and [b["deal_code"] for b in body] == ["D1", "D1", "D2", "D3"]
    assert {"deal_code", "sku_code", "fc_code", "ready_time", "end_time", "status", "quantity_used", "max_quantity",
            "reason"} <= set(body[0]) and body[1]["quantity_used"] == ""
    chk = json.loads(snap[1])
    assert chk["n_rows"] == 4 and chk["duplicate_keys"] == 0
    assert snap[2] is not None and snap[2].startswith("2026-10-01") and snap[3] == fake.bytes
    assert _alerts("DEAL_DUPLICATE_KEYS") == []


def test_same_content_is_stored_once_and_changed_content_replaces_the_deals(client):
    from app.bq import deal_source
    fake = _production(_d(WINDOW), deal_table=DEAL_TABLE)
    fake.deal_rows = DEALS
    deal_source.refresh("MANUAL")
    fake.deal_rows = list(reversed(DEALS))                                  # the same content in another order
    deal_source.refresh("MANUAL")
    deal_source.refresh("MANUAL")
    s = _snaps()
    assert len(s) == 3 and s[0][3] == s[1][3] == s[2][3]                    # content hash independent of the order
    assert s[0][4] == 0 and s[1][4] == 1 and s[2][4] == 1                   # one blob
    assert s[1][5] == s[0][0] and s[2][5] == s[0][0]                         # pointing at the snapshot with the rows
    assert {r[0] for r in _q("SELECT snapshot_id FROM deals")} <= {x[0] for x in s} and _n("deals") == 4
    fake.deal_rows = DEALS[:2] + [_deal("D4", "A")]
    deal_source.refresh("MANUAL")
    s = _snaps()
    assert len(s) == 4 and s[3][4] == 0 and s[3][5] is None and s[3][3] != s[0][3]
    assert _q("SELECT DISTINCT snapshot_id FROM deals") == [(s[3][0],)] and _n("deals") == 3
    assert sorted(r[0] for r in _q("SELECT deal_code FROM deals")) == ["D1", "D2", "D4"]


def test_duplicate_deal_keys_are_stored_with_a_warning(client):
    from app.bq import deal_source
    fake = _production(_d(WINDOW), deal_table=DEAL_TABLE)
    fake.deal_rows = DEALS + [_deal("D2", "B", used=1.0)]
    deal_source.refresh("MANUAL")
    assert _n("deals") == 5
    assert json.loads(_q("SELECT checks_json FROM deal_snapshots")[0][0])["duplicate_keys"] == 1
    al = _alerts("DEAL_DUPLICATE_KEYS")
    assert len(al) == 1 and al[0][0] == "WARNING"


def test_refresh_runs_after_a_successful_regular_d1_only_and_never_fails_it(client):
    from app import sync
    fake = _production(deal_table=DEAL_TABLE, ext=EXT)
    fake.deal_rows = DEALS
    out = sync.run_d1_sync("J1")
    assert out["deal_refresh"]["status"] == "SUCCEEDED" and len(_snaps()) == 1 and _snaps()[0][6] == "D1_SYNC"
    assert not out.get("deal_lines")                                        # deal_code_column "": key absent or None
    assert fake.deal_sent("deal_lines") == [] and _n("deal_line_loads") == 0   # no deal column: no line read
    _backfill("2025-11-10", "2025-11-12")
    assert len(_snaps()) == 1                                                # not after a backfill
    fake.errors["daily"] = RuntimeError("source read failed")               # a D-1 that fails
    with pytest.raises(Exception):
        sync.run_d1_sync("J2")
    assert len(_snaps()) == 1 and len(fake.deal_sent("deal_source")) == 1
    del fake.errors["daily"]
    fake.deal_errors["deal_source"] = RuntimeError("deal table gone")
    out = sync.run_d1_sync("J3")
    assert out["status"] == "SUCCEEDED" and out["deal_refresh"]["status"] == "FAILED" and len(_snaps()) == 1
    al = _alerts("DEAL_REFRESH_FAILED")
    assert len(al) == 1 and al[0][0] == "WARNING" and _n("deals") == 4      # stored deals unchanged


# ================================================================== F. checks (needs G3-T1)
def test_checks_on_a_hand_made_fixture(client):
    from app.bq import deal_source
    _production(_d(WINDOW), deal_table=DEAL_TABLE, deal_col="deal_code")
    with db.tx() as c:
        c.execute("INSERT INTO deal_snapshots(id, source_table, taken_at, n_rows, content_sha256, rows_gz) VALUES "
                  "('DS-1', ?, '2026-10-30T01:00:00+00:00', 5, 'h', x'00')", (DEAL_TABLE,))
        for i, (code, sku, fc, ready, end, used) in enumerate([
                ("K1", "A", "F1", "2026-02-01 00:00:00", "2026-02-02 00:00:00", 10.0),   # lines 10: equal
                ("K2", "B", "F1", "2026-02-01 00:00:00", "2026-02-02 00:00:00", 20.0),   # lines 19.5: within 5 %
                ("K3", "C", "F1", "2026-02-03 00:00:00", "2026-02-02 00:00:00", 10.0),   # lines 5; ready after end
                ("K4", "D", "F1", "2026-02-01 00:00:00", "2026-02-02 00:00:00", 7.0),    # duplicate key, no line
                ("K4", "D", "F1", "2026-02-01 00:00:00", "2026-02-02 00:00:00", 7.0)]):
            c.execute("INSERT INTO deals(source_table, row_no, deal_code, sku_code, fc_code, ready_time, end_time, status, "
                      "quantity_used, max_quantity, reason, snapshot_id) VALUES (?,?,?,?,?,?,?,'A',?,100,NULL,'DS-1')",
                      (DEAL_TABLE, i, code, sku, fc, ready, end, used))
        for d, sku, code, q in [("2026-02-01", "A", "K1", 6.0), ("2026-02-02", "A", "K1", 4.0), ("2026-02-01", "B", "K2", 19.5),
                                ("2026-02-01", "C", "K3", 5.0),
                                ("2026-02-01", "Z", "K1", 2.0),        # code known, key (K1, Z, F1) unknown
                                ("2026-02-01", "A", "NOPE", 3.0),      # code unknown
                                ("2026-03-01", "A", "K1", 50.0)]:      # outside [start, end]
            c.execute("INSERT INTO demand_deal_daily(scope_key, order_date, sku_id, fc_id, deal_code, qty, n_rows, load_id, "
                      "loaded_at) VALUES (?,?,?,'F1',?,?,1,'L','x')", (SCOPE, d, sku, code, q))
    chk = deal_source.checks(SCOPE, "2026-02-01", "2026-02-28")
    assert (chk["deals"]["n_rows"], chk["deals"]["duplicate_keys"], chk["deals"]["ready_after_end"]) == (5, 1, 1)
    li = chk["lines"]
    assert (li["rows"], li["qty"]) == (6, 39.5)
    assert li["match_key"]["rows_share"] == pytest.approx(4 / 6) and li["match_key"]["qty_share"] == pytest.approx(34.5 / 39.5)
    assert li["match_code"]["rows_share"] == pytest.approx(5 / 6) and li["match_code"]["qty_share"] == pytest.approx(36.5 / 39.5)
    pdl = chk["per_deal"]                     # K1 10 vs 10, K2 19.5 vs 20, K3 5 vs 10; K4 has no line: not compared
    assert pdl["deals_compared"] == 3
    assert pdl["share_equal"] == pytest.approx(1 / 3) and pdl["share_within_5pct"] == pytest.approx(2 / 3)
    assert pdl["ratio"] == pytest.approx(34.5 / 40.0)
    assert chk["snapshot"]["id"] == "DS-1" and chk["snapshot"]["taken_at"] == "2026-10-30T01:00:00+00:00"
    # read-only
    before = [_n(t) for t in ("deals", "deal_snapshots", "demand_deal_daily", "alerts")]
    deal_source.checks(SCOPE)
    assert [_n(t) for t in ("deals", "deal_snapshots", "demand_deal_daily", "alerts")] == before
    assert deal_source.checks(SCOPE)["lines"]["rows"] == 7                  # no window: every line


# ================================================================== G. CLI (needs G3-T1)
def _values(obj, key) -> list:
    """Every value of `key` anywhere in a nested JSON object."""
    if isinstance(obj, dict):
        return [v for k, v in obj.items() if k == key] + [x for v in obj.values() for x in _values(v, key)]
    if isinstance(obj, list):
        return [x for v in obj for x in _values(v, key)]
    return []


def _cli(capsys, *argv) -> tuple[int, dict]:
    rc = cli.main(list(argv))
    return rc, json.loads(capsys.readouterr().out)


def test_cli_deal_lines_load_in_month_chunks(client, capsys):
    from app import sync
    y = timeutil.today_vn() - timedelta(days=1)
    fake = _production(ext=EXT)
    sync.run_d1_sync("J1")
    _backfill(EXT, "2025-12-31")
    ss.update("bigquery", {"deal_code_column": "deal_code"})
    rc, out = _cli(capsys, "deal-lines-load", "--start", "2025-10-01", "--end", "2026-01-10")
    assert rc == 0 and [(c["start"], c["end"]) for c in out["chunks"]] == [
        ("2025-11-01", "2025-11-30"), ("2025-12-01", "2025-12-31"), ("2026-01-01", "2026-01-10")]   # floor = EXT
    assert all(c["estimated_bytes"] == fake.bytes for c in out["chunks"])
    assert _n("deal_line_loads") == 0 and _n("demand_deal_daily") == 0 and fake.deal_sent() == []   # dry run only
    rc, out = _cli(capsys, "deal-lines-load", "--start", "2025-11-01", "--end", "2026-01-10", "--max-bytes",
                   str(fake.bytes - 1), "--apply")
    assert rc != 0 and _n("deal_line_loads") == 0
    rc, out = _cli(capsys, "deal-lines-load", "--start", "2025-11-01", "--end", "2026-01-10", "--apply")
    assert rc == 0 and len(out["chunks"]) == 3
    assert _q("SELECT trigger, range_start, range_end FROM deal_line_loads ORDER BY range_start") == [
        ("MANUAL", "2025-11-01", "2025-11-30"), ("MANUAL", "2025-12-01", "2025-12-31"), ("MANUAL", "2026-01-01", "2026-01-10")]
    assert len(_lines(EXT, "2026-01-10")) == len([r for r in fake.lines if _d(EXT) <= r["order_date"] <= date(2026, 1, 10)])
    # above: never today (Vietnam)
    rc, out = _cli(capsys, "deal-lines-load", "--start", str(y.replace(day=1)), "--end", str(y + timedelta(days=5)))
    assert out["chunks"][-1]["end"] == str(y)


def test_cli_deal_lines_load_bounds_yesterday_on_the_vietnam_calendar(client, capsys):
    """00:30 in Vietnam = 17:30 UTC of the day before: yesterday is the Vietnam yesterday, not the UTC one."""
    _production(_d(WINDOW), deal_col="deal_code")
    timeutil.set_now_override(lambda: datetime(2026, 3, 9, 17, 30, tzinfo=UTC))       # 10/03/2026 00:30 VN
    rc, out = _cli(capsys, "deal-lines-load", "--start", "2026-03-01", "--end", "2026-03-31")
    assert rc == 0 and out["chunks"][-1]["end"] == "2026-03-09"


def test_cli_deal_refresh_and_deal_check(client, capsys):
    fake = _production(_d(WINDOW), deal_table=DEAL_TABLE)
    fake.deal_rows = DEALS
    rc, out = _cli(capsys, "deal-refresh")
    assert rc == 0 and fake.bytes in _values(out, "estimated_bytes")
    assert _n("deal_snapshots") == 0 and fake.deal_sent() == []
    rc, out = _cli(capsys, "deal-refresh", "--apply")
    assert rc == 0 and _n("deal_snapshots") == 1 and _snaps()[0][6] == "MANUAL" and _n("deals") == 4
    rc, out = _cli(capsys, "deal-check")
    from app.bq import deal_source
    assert rc == 0 and out == json.loads(json.dumps(deal_source.checks(SCOPE), default=str))


def test_cli_open_hours_load_in_15_day_chunks_never_moves_the_watermark_back(client, capsys):
    from app.bq import aux_sources
    fake = _production(_d(WINDOW))
    fake.responses["daily_open_hours"] = lambda cfg: [
        {"fc_code": "F1", "sku_code": "A", "open_date": str(DealFake._win(cfg)[0]), "total_open_hours": 12.0, "n_items": 1}]
    table, seller = aux_sources.open_hours_source()
    with db.tx() as c:
        aux_sources._record_read(c, aux_sources.KIND_OPEN_HOURS, table, seller, "2026-10-01", "2026-10-20", 5, "2026-10-20")
    rc, out = _cli(capsys, "open-hours-load", "--start", "2026-01-01", "--end", "2026-01-31")
    assert rc == 0 and all(c["estimated_bytes"] == fake.bytes for c in out["chunks"])
    assert fake.sent(lambda k: k == "daily_open_hours") == [] and _n("open_hours_daily") == 0
    reads0 = _n("aux_source_reads")
    assert reads0 == 1
    rc, out = _cli(capsys, "open-hours-load", "--start", "2026-01-01", "--end", "2026-01-31", "--apply")
    assert rc == 0
    wins = [DealFake._win(c) for _, c in fake.sent(lambda k: k == "daily_open_hours")]
    assert wins[0][0] == date(2026, 1, 1) and wins[-1][1] == date(2026, 1, 31)
    assert all((e - s).days + 1 <= 15 for s, e in wins)                     # at most 15 days per read
    assert all(wins[i + 1][0] == wins[i][1] + timedelta(days=1) for i in range(len(wins) - 1))   # oldest first, contiguous
    assert _n("open_hours_daily") == len(wins)
    with db.read() as c:
        last = aux_sources.last_completed_read(c, aux_sources.KIND_OPEN_HOURS, table, seller)
    assert last["last_day"] >= "2026-10-20"                                 # the daily refresh's watermark not moved back
    assert all(r[0] >= "2026-10-20" for r in _q("SELECT last_day FROM aux_source_reads WHERE rowid > 1"))


@pytest.fixture
def ready_flows(monkeypatch):
    from app.jobs import flows
    monkeypatch.setattr(flows, "readiness", lambda flow, conn=None: {"flow": flow, "ready": True, "reasons": [],
                                                                      "notes": []})
    ss.update("model", {"forecast_strategy": "DIRECT"})


def test_apply_preset_feature_set_chot_is_the_1_3_1_preset(ready_flows, capsys):
    rc, plain = _cli(capsys, "apply-preset", "lgbm-chot")
    rc2, chot = _cli(capsys, "apply-preset", "lgbm-chot", "--feature-set", "CHOT")
    assert rc == rc2 == 0 and chot["changes"] == plain["changes"]
    assert "feature_set" not in {x["key"] for x in chot["changes"]}
    assert cli.main(["apply-preset", "lgbm-chot", "--feature-set", "CHOT", "--apply"]) == 0
    capsys.readouterr()
    assert ss.get("model").feature_set == "CHOT" and ss.get("bigquery").deal_code_column == ""


def test_apply_preset_chot_ly_needs_the_extended_history(ready_flows, capsys):
    with db.read() as c:
        hist0 = c.execute("SELECT COUNT(*) FROM settings_history").fetchone()[0]
    rc, out = _cli(capsys, "apply-preset", "lgbm-chot", "--feature-set", "CHOT_LY", "--apply")
    assert rc == 2 and out["ok"] is False and ss.get("model").feature_set == "CHOT"
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM settings_history").fetchone()[0] == hist0
    ss.update("data_policy", {"extended_history_start_date": EXT})
    rc, out = _cli(capsys, "apply-preset", "lgbm-chot", "--feature-set", "CHOT_LY")
    assert rc == 0 and ("model", "feature_set", "CHOT", "CHOT_LY") in {
        (x["section"], x["key"], x["from"], x["to"]) for x in out["changes"]}
    assert ss.get("model").feature_set == "CHOT"                             # dry run
    rc, out = _cli(capsys, "apply-preset", "lgbm-chot", "--feature-set", "CHOT_LY", "--apply")
    assert rc == 0 and ss.get("model").feature_set == "CHOT_LY" and ss.get("bigquery").deal_table_id == ""
    rc, again = _cli(capsys, "apply-preset", "lgbm-chot", "--feature-set", "CHOT_LY", "--apply")
    assert again["changes"] == []                                            # idempotent


def test_apply_preset_chot_ly_deal_sets_the_deal_keys_and_keeps_the_bigquery_settings(ready_flows, capsys):
    ss.update("data_policy", {"extended_history_start_date": EXT})
    ss.update("bigquery", {"dataset_id": "sales", "source_table": "orders", "field_mapping": FM, "reference_mapping": REF,
                           "exact_duplicate_policy": "DROP_EXACT", "production_enabled": True})
    bq0 = ss.get("bigquery").model_dump()
    keep = lambda d: {k: v for k, v in d.items() if k not in ("deal_code_column", "deal_table_id")}   # noqa: E731
    # orchestrator decision (G3-T1a follow-up): an empty deals table is not a refusal - the keys are set and the JSON
    # carries the warning DEAL_SOURCE_EMPTY (the first refresh after the next D-1 fills it)
    rc, out = _cli(capsys, "apply-preset", "lgbm-chot", "--feature-set", "CHOT_LY_DEAL", "--apply")
    assert rc == 0, out
    assert out["ok"] is True and "DEAL_SOURCE_EMPTY" in _values(out, "code")
    bq = ss.get("bigquery").model_dump()
    assert (bq["deal_code_column"], bq["deal_table_id"]) == ("deal_code", DEAL_TABLE)
    assert keep(bq) == keep(bq0)                                             # production stays on, other keys kept
    assert ss.get("model").feature_set == "CHOT_LY_DEAL"
    # with deals stored: no such warning (and nothing left to change)
    with db.tx() as c:
        c.execute("INSERT INTO deal_snapshots(id, source_table, taken_at, n_rows, content_sha256, rows_gz) VALUES "
                  "('DS-1', ?, 'x', 1, 'h', x'00')", (DEAL_TABLE,))
        c.execute("INSERT INTO deals(source_table, row_no, deal_code, snapshot_id) VALUES (?, 0, 'D1', 'DS-1')", (DEAL_TABLE,))
    rc, out = _cli(capsys, "apply-preset", "lgbm-chot", "--feature-set", "CHOT_LY_DEAL", "--apply")
    assert rc == 0, out
    assert "DEAL_SOURCE_EMPTY" not in _values(out, "code") and out["changes"] == []
    bq = ss.get("bigquery").model_dump()
    assert (bq["deal_code_column"], bq["deal_table_id"]) == ("deal_code", DEAL_TABLE)
    assert keep(bq) == keep(bq0)
    assert ss.get("model").feature_set == "CHOT_LY_DEAL"
