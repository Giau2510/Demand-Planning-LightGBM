"""1.4.10: product names come from the Avg Demand tables first; the dim_sku table (bigquery.product_names_table) is an
OPTIONAL last fallback (empty = never read). Resolution per SKU: (1) newest non-empty name in avg_demand_daily, (2) the
historical Avg Demand table for SKUs still without a name (last 60 days, swallowed on error), (3) the name stored by the
previous refresh is never blanked, (4) dim_sku only for SKUs still missing (>1 distinct names = none). The Excel export
takes the Avg name of the day first and the stored mapping only fills gaps. source_tables: product_names optional.

Kind of evidence: integration with fakes (isolated temporary database, fake BigQuery client, TestClient). Synthetic
data only."""
import json
from datetime import date, datetime, timedelta, timezone

import pytest

from app import db
from app import settings_service as ss
from app.bq import connector, product_names, source_tables
from app.messages import AppError
from app.ml.sel2 import avg_demand, export

from test_v116 import _bq_ready
from test_v140_t6_export import COLS20, D, SCOPE, _all_rows, _avg as _avg_export, _book, _config, _run

DIM = "lakehouse-prod-394907.gold_buymed_vn2.dim_sku"
HIST_KIND = "product_names_hist"


@pytest.fixture(autouse=True)
def _fresh_cache():
    product_names._cache.update(updated_at=None, names={})
    yield
    product_names._cache.update(updated_at=None, names={})


# ------------------------------------------------------------------ helpers
def _setup(**responses):
    """Fake BigQuery client (counted: how many clients were created) + the D-1 table configured."""
    fake = _bq_ready()
    fake.responses.update(responses)
    made = []

    def factory(settings):
        made.append(1)
        return fake(settings)

    connector.set_client_factory(factory)
    return fake, made


def _demand(*skus, fc="F1"):
    """BIGQUERY demand rows (the SKU universe of the refresh)."""
    with db.tx() as c:
        c.executemany("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, "
                      "loaded_at) VALUES ('BIGQUERY:t', 'BIGQUERY', '2026-11-01', ?, ?, 3, 1, '2026-11-02T01:00:00+00:00')",
                      [(s, fc) for s in skus])


def _avg(day: str, rows, loaded="2026-11-02T03:20:00+00:00"):
    """rows [(sku, fc, seller, name)] stored as the current Avg Demand read of `day`."""
    table = ss.get("sel2_pipeline").avg_demand_table
    with db.tx() as c:
        c.executemany("INSERT INTO avg_demand_daily(business_date, sku_code, fc_code, seller_code, avg_demand, "
                      "product_name, source_table, source_modified, loaded_at) VALUES (?,?,?,?,?,?,?,?,?)",
                      [(day, s, f, sel, 1.0, n, table, None, loaded) for s, f, sel, n in rows])


def _stored():
    """The mapping stored in sync_state (read directly: names() caches by a one-second updated_at)."""
    with db.read() as c:
        r = c.execute("SELECT value_json FROM sync_state WHERE name='product_names'").fetchone()
    return json.loads(r[0])["names"] if r else {}


def _dim_queries(fake):
    return [q for q in fake.queries if q[0].startswith("-- df:product_names\n")]


def _hist_real(fake):
    return [q for q in fake.queries if q[0].startswith(f"-- df:{HIST_KIND}\n") and not q[1].get("dry_run")]


# ------------------------------------------------------------------ 1. empty setting + every SKU named by Avg: no call
def test_empty_dim_table_and_all_skus_named_by_avg_makes_no_bigquery_call():
    fake, made = _setup()
    assert ss.get("bigquery").product_names_table == ""
    _demand("S0", "S1", "S2")
    _avg("2026-11-02", [("S0", "F1", "SL", "Thuoc 0"), ("S1", "F1", "SL", "Thuoc 1"), ("S9", "F2", "SL", "Thuoc 9")])
    _avg("2026-11-01", [("S2", "F1", "SL", "Thuoc 2 (older day)")])     # named only on an older day: still a name
    st = product_names.refresh()
    assert fake.queries == [] and made == []                            # no client, no dry run, no query
    assert st["skus_by_source"] == {"avg": 4, "hist": 0, "stored": 0, "dim": 0}
    assert (st["skus_local"], st["skus_named"], st["skus_without_name"], st["skus_ambiguous"]) == (4, 4, 0, 0)
    assert st["rows_read"] == 0 and st["estimated_bytes"] == 0 and "names" not in st
    assert _stored() == {"S0": "Thuoc 0", "S1": "Thuoc 1", "S2": "Thuoc 2 (older day)", "S9": "Thuoc 9"}
    assert "dim_sku" not in st["source"] and "historical" not in st["source"]
    assert product_names.source_table(ss.get("bigquery")) == ""


def test_avg_name_is_the_newest_with_ties_by_loaded_at_then_rowid_and_is_trimmed():
    _setup()
    _demand("S0", "S1", "S2")
    _avg("2026-11-01", [("S0", "F1", "SL", "Old S0"), ("S1", "F1", "SL", "Old S1")])
    _avg("2026-11-02", [("S0", "F1", "SL", "  New S0  ")])                                  # newer day wins, stripped
    # same day, two rows (other fc): the later loaded_at wins; same loaded_at -> the later rowid wins
    _avg("2026-11-02", [("S1", "F1", "SL", "Early S1")], loaded="2026-11-02T03:00:00+00:00")
    _avg("2026-11-02", [("S1", "F2", "SL", "Late S1")], loaded="2026-11-02T04:00:00+00:00")
    _avg("2026-11-02", [("S2", "F1", "SL", "First S2")])
    _avg("2026-11-02", [("S2", "F2", "SL", "Second S2")])
    product_names.refresh()
    assert _stored() == {"S0": "New S0", "S1": "Late S1", "S2": "Second S2"}


def test_a_newer_empty_avg_name_does_not_hide_an_older_real_name():
    _setup()
    _demand("S0")
    _avg("2026-11-01", [("S0", "F1", "SL", "Real name")])
    _avg("2026-11-02", [("S0", "F1", "SL", "   ")])
    st = product_names.refresh()
    assert _stored() == {"S0": "Real name"} and st["skus_by_source"]["avg"] == 1


# ------------------------------------------------------------------ 2. precedence, Excel names
def test_avg_name_beats_dim_name_and_empty_avg_name_is_not_a_name():
    fake, _ = _setup(product_names=[{"sku": "S1", "name": "Dim S1"}, {"sku": "S2", "name": "Dim S2"}])
    ss.update("bigquery", {"product_names_table": DIM})
    _demand("S1", "S2", "S3")
    _avg("2026-11-02", [("S1", "F1", "SL", "Avg S1"), ("S2", "F1", "SL", "  "), ("S3", "F1", "SL", "")])
    st = product_names.refresh()
    assert _stored() == {"S1": "Avg S1", "S2": "Dim S2"}                # S1: Avg wins; S2: whitespace is no name
    assert st["skus_by_source"] == {"avg": 1, "hist": 0, "stored": 0, "dim": 1}
    assert st["skus_without_name"] == 1 and st["source"].endswith("+ dim_sku")
    assert len(_dim_queries(fake)) == 2                                 # dry run + run of the one dim read


def test_excel_names_avg_of_the_day_first_stored_mapping_only_fills_gaps_empty_is_no_name():
    _setup()
    day = "2026-11-02"
    table = ss.get("sel2_pipeline").avg_demand_table
    _demand("S4", "S5")
    _avg("2026-11-01", [("S4", "F1", "SL", "Avg A"), ("S5", "F1", "SL", "Avg five")])
    product_names.refresh()
    assert _stored() == {"S4": "Avg A", "S5": "Avg five"}
    # the export day: S4 has a different (padded) Avg name, S5 has no row, S6 only an empty name, S7 nothing anywhere
    _avg(day, [("S4", "F1", "SL", "  Avg B "), ("S6", "F1", "SL", "   "), ("S7", "F1", "SL", None)])
    with db.read() as c:
        out = export._names(c, day, table)
        assert out == {"S4": "  Avg B ", "S5": "Avg five"}              # Avg of the day first, exactly as read (as 1.4.9); stored only fills S5
        assert export._names(c, day, None) == {"S4": "Avg A", "S5": "Avg five"}      # no Avg table: the stored mapping
        assert "S6" not in out and "S7" not in out


def test_excel_stored_empty_or_blank_names_never_fill():
    _setup()
    with db.tx() as c:
        c.execute("INSERT INTO sync_state(name, value_json, updated_at) VALUES ('product_names', ?, '2026-11-02T00:00:00+00:00')",
                  (json.dumps({"names": {"A": "  ", "B": "", "C": " Name C "}}),))
    with db.read() as c:
        assert export._names(c, "2026-11-02", ss.get("sel2_pipeline").avg_demand_table) == {"C": " Name C "}   # exactly as read


# ------------------------------------------------------------------ 3. historical Avg Demand table
def test_historical_read_names_the_skus_without_an_avg_name_with_a_bounded_chunked_query(monkeypatch):
    timeutil_now = datetime(2026, 11, 12, 17, 30, tzinfo=timezone.utc)      # 13/11/2026 00:30 in Vietnam (UTC is still 12/11)
    from app import timeutil
    timeutil.set_now_override(lambda: timeutil_now)
    seen = []

    def hist(cfg):
        seen.append(cfg["params"])
        want = dict((n, v) for n, _, v in cfg["params"])["skus"]
        names = {"S1": "Hist S1", "S2": "  Hist S2  ", "S3": "   ", "S5": "Hist S5"}
        return [{"sku": s, "name": names[s]} for s in want if s in names]

    fake, _ = _setup(**{HIST_KIND: hist})
    monkeypatch.setattr(product_names, "HIST_CHUNK", 2)
    _demand("S0", "S1", "S2", "S3", "S4", "S5")
    _avg("2026-11-02", [("S0", "F1", "SL", "Avg S0")])
    st = product_names.refresh()
    real = _hist_real(fake)
    assert len(real) == 3 and len(fake.queries) == 6                    # S0 has an Avg name: 5 SKUs -> chunks 2 + 2 + 1
    sql = real[0][0]
    assert "UNNEST(@skus)" in sql and "transformed_at >= TIMESTAMP(@since)" in sql and "QUALIFY" in sql
    assert ss.get("sel2_pipeline").avg_demand_hist_table in sql
    assert "CAST(sku_code AS STRING) IN UNNEST(@skus)" in sql
    chunks = [dict((n, v) for n, _, v in p)["skus"] for p in seen]
    assert chunks == [["S1", "S2"], ["S3", "S4"], ["S5"]]               # sorted, S0 (Avg name) never asked again
    assert {dict((n, v) for n, _, v in p)["since"] for p in seen} == {date(2026, 9, 14)}    # Vietnam today - 60 days
    assert [[(n, t) for n, t, _ in p] for p in seen][0] == [("since", "DATE"), ("skus", "STRING")]
    assert all(q[1]["maximum_bytes_billed"] <= avg_demand.MAX_BYTES for q in real)
    assert _stored() == {"S0": "Avg S0", "S1": "Hist S1", "S2": "Hist S2", "S5": "Hist S5"}
    assert st["skus_by_source"] == {"avg": 1, "hist": 3, "stored": 0, "dim": 0}
    assert st["rows_read"] == 4 and st["skus_without_name"] == 2 and "historical" in st["source"]
    assert _dim_queries(fake) == []                                     # empty setting: dim_sku never read


def test_historical_read_cost_cap_is_the_lower_of_the_setting_and_the_avg_cap():
    fake, _ = _setup(**{HIST_KIND: [{"sku": "S0", "name": "H"}]})
    ss.update("bigquery", {"maximum_bytes_billed": 2 * 1024 ** 3})
    _demand("S0")
    product_names.refresh()
    assert [q[1]["maximum_bytes_billed"] for q in _hist_real(fake)] == [2 * 1024 ** 3]
    assert [q[1].get("dry_run") for q in fake.queries] == [True, False]  # dry run first


def test_historical_read_is_skipped_when_no_sku_is_missing_and_for_skus_named_by_avg():
    fake, _ = _setup(**{HIST_KIND: [{"sku": "S0", "name": "Hist"}]})
    _demand("S0")
    _avg("2026-11-02", [("S0", "F1", "SL", "Avg S0")])
    product_names.refresh()
    assert fake.queries == [] and _stored() == {"S0": "Avg S0"}


# ------------------------------------------------------------------ 4. historical read fails: refresh goes on
def test_a_failing_historical_read_never_fails_the_refresh_and_stored_and_dim_names_still_apply(caplog):
    fake, _ = _setup(product_names=[{"sku": "S2", "name": "Dim S2"}])
    ss.update("bigquery", {"product_names_table": DIM})
    _demand("S0", "S1", "S2", "S3")
    _avg("2026-11-01", [("S0", "F1", "SL", "Avg S0"), ("S1", "F1", "SL", "Avg S1")])
    product_names.refresh()                                              # first refresh: stored = S0, S1, S2
    assert _stored() == {"S0": "Avg S0", "S1": "Avg S1", "S2": "Dim S2"}
    with db.tx() as c:
        c.execute("DELETE FROM avg_demand_daily")                        # S0 / S1 now only in the stored mapping
    fake.errors[HIST_KIND] = RuntimeError("historical table unavailable")
    fake.responses["product_names"] = [{"sku": "S3", "name": "Dim S3"}]
    with caplog.at_level("WARNING"):
        st = product_names.refresh()                                     # does not raise
    assert _stored() == {"S0": "Avg S0", "S1": "Avg S1", "S2": "Dim S2", "S3": "Dim S3"}
    assert st["skus_by_source"] == {"avg": 0, "hist": 0, "stored": 3, "dim": 1}
    assert any("historical Avg Demand read failed" in r.getMessage() for r in caplog.records)


def test_historical_read_without_a_configured_dataset_is_swallowed_too():
    fake, _ = _setup()
    ss.update("bigquery", {"dataset_id": ""})
    _demand("S0")
    st = product_names.refresh()                                         # BQ_NOT_CONFIGURED inside the swallowed read
    assert st["skus_named"] == 0 and st["skus_by_source"]["hist"] == 0
    product_names.refresh_quietly("test")                                # never raises


# ------------------------------------------------------------------ 5. stored name never blanked
def test_a_stored_name_is_never_blanked_when_every_source_loses_the_sku():
    _setup()
    _demand("S0", "S1")
    _avg("2026-11-02", [("S0", "F1", "SL", "Avg S0"), ("S1", "F1", "SL", "Avg S1")])
    product_names.refresh()
    with db.tx() as c:
        c.execute("DELETE FROM avg_demand_daily WHERE sku_code='S0'")    # S0 absent from Avg now; S1 gets a new name
        c.execute("UPDATE avg_demand_daily SET product_name='Avg S1 v2' WHERE sku_code='S1'")
    st = product_names.refresh()
    assert _stored() == {"S0": "Avg S0", "S1": "Avg S1 v2"}              # Avg of today replaces, the stored fills S0
    assert st["skus_by_source"] == {"avg": 1, "hist": 0, "stored": 1, "dim": 0}
    assert st["skus_named"] == 2 and st["skus_without_name"] == 0
    st = product_names.refresh()                                         # and again: still there
    assert _stored()["S0"] == "Avg S0" and st["skus_by_source"]["stored"] == 1


def test_a_stored_name_of_a_sku_that_left_the_local_data_is_dropped_not_kept_forever():
    _setup()
    _demand("S0", "S1")
    _avg("2026-11-02", [("S0", "F1", "SL", "Avg S0"), ("S1", "F1", "SL", "Avg S1")])
    product_names.refresh()
    with db.tx() as c:
        c.execute("DELETE FROM avg_demand_daily")
        c.execute("DELETE FROM demand_daily WHERE sku_id='S1'")
    st = product_names.refresh()
    assert _stored() == {"S0": "Avg S0"} and st["skus_local"] == 1 and st["skus_by_source"]["stored"] == 1


# ------------------------------------------------------------------ 6. dim_sku only fills what is still missing
def test_dim_table_is_not_read_when_every_sku_already_has_a_name():
    fake, made = _setup(product_names=[{"sku": "S0", "name": "Dim S0"}])
    ss.update("bigquery", {"product_names_table": DIM})
    _demand("S0", "S1")
    _avg("2026-11-02", [("S0", "F1", "SL", "Avg S0"), ("S1", "F1", "SL", "Avg S1")])
    st = product_names.refresh()
    assert fake.queries == [] and made == []
    assert _stored() == {"S0": "Avg S0", "S1": "Avg S1"} and st["skus_by_source"]["dim"] == 0


def test_dim_table_fills_only_the_missing_sku_and_an_ambiguous_one_gets_no_name():
    fake, _ = _setup(product_names=[
        {"sku": "S0", "name": "Dim S0 (must not replace Avg)"},
        {"sku": "S1", "name": "Name A"}, {"sku": "S1", "name": "Name B"},            # ambiguous: no name
        {"sku": "S2", "name": " Dim S2 "}, {"sku": "S2", "name": "Dim S2"},          # same name twice: one name
        {"sku": "S3", "name": "   "},                                                  # blank: not a name
        {"sku": "NOT_LOCAL", "name": "Elsewhere"}])
    ss.update("bigquery", {"product_names_table": DIM})
    _demand("S0", "S1", "S2", "S3", "S4")
    _avg("2026-11-02", [("S0", "F1", "SL", "Avg S0")])
    st = product_names.refresh()
    assert len(_dim_queries(fake)) == 2 and f"`{DIM}`" in _dim_queries(fake)[0][0]
    assert _stored() == {"S0": "Avg S0", "S2": "Dim S2"}
    assert st["skus_by_source"] == {"avg": 1, "hist": 0, "stored": 0, "dim": 1}
    assert st["skus_ambiguous"] == 1 and st["ambiguous_sample"] == ["S1"] and st["skus_without_name"] == 3
    assert st["source"].endswith("+ dim_sku")


def test_a_stored_name_prevents_the_dim_read_even_when_the_dim_table_is_configured_later():
    fake, _ = _setup()
    _demand("S0")
    _avg("2026-11-02", [("S0", "F1", "SL", "Avg S0")])
    product_names.refresh()
    with db.tx() as c:
        c.execute("DELETE FROM avg_demand_daily")
    ss.update("bigquery", {"product_names_table": DIM})
    fake.responses["product_names"] = [{"sku": "S0", "name": "Name A"}, {"sku": "S0", "name": "Name B"}]
    st = product_names.refresh()
    assert _dim_queries(fake) == [] and _stored() == {"S0": "Avg S0"} and st["skus_by_source"]["stored"] == 1


def test_a_dim_read_error_is_recorded_and_never_loses_the_other_names():
    # review 13/11: a failing OPTIONAL dim table must not stop the Avg / stored names from being saved
    fake, _ = _setup()
    ss.update("bigquery", {"product_names_table": DIM})
    fake.errors["product_names"] = RuntimeError("dim table unavailable")
    _demand("S0", "S1")                                                   # S0 has no name anywhere, S1 has an Avg name
    _avg("2026-11-02", [("S1", "F1", "x", "Avg one")])
    r = product_names.refresh()                                           # does not raise
    assert r["dim_error"] and r["skus_named"] == 1 and r["skus_without_name"] == 1
    assert r["skus_by_source"]["avg"] == 1 and r["skus_by_source"]["dim"] == 0
    assert _stored() == {"S1": "Avg one"}                                 # saved although the dim read failed
    product_names.refresh_quietly("test")                                 # never raises either
    with db.read() as c:
        assert product_names.status(c)["dim_error"]


def test_a_stored_short_dim_name_is_still_joined_with_the_d1_project_and_dataset():
    ss.update("bigquery", {"dataset_id": "gold_buymed_vn2", "project_id": "company-prod-01",
                           "product_names_table": "dim_sku"})
    assert product_names.source_table(ss.get("bigquery")) == "company-prod-01.gold_buymed_vn2.dim_sku"
    ss.update("bigquery", {"product_names_table": "  "})
    assert product_names.source_table(ss.get("bigquery")) == ""


# ------------------------------------------------------------------ 7. source_tables: product_names is optional
def test_check_with_an_empty_id_passes_as_optional_without_any_client():
    fake, made = _setup()
    r = source_tables.check("product_names", "")
    assert r["status"] == "PASSED" and r["optional_empty"] is True and r["errors"] == [] and r["table_id"] == ""
    assert made == [] and fake.queries == []
    assert source_tables.check("product_names", "   ")["status"] == "PASSED"           # blank = empty
    assert source_tables.check("product_names")["status"] == "PASSED"                   # no id given = the empty setting
    lc = source_tables.last_check("product_names")
    assert lc["status"] == "PASSED" and lc["table_id"] == "" and made == []
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM audit_log WHERE action='BQ_TABLE_CHECKED'").fetchone()[0] == 3


def test_save_with_an_empty_id_stores_empty_with_a_settings_history_entry():
    from test_v149_source_tables import NAMES, _fake
    fake = _bq_ready(_fake())
    assert source_tables.save("product_names", NAMES)["product_names"]["table_id"] == NAMES
    n0 = len(ss.history("bigquery", 500))
    out = source_tables.save("product_names", "")
    assert ss.get("bigquery").product_names_table == ""
    h = ss.history("bigquery", 500)
    assert len(h) == n0 + 1 and h[0]["value"]["product_names_table"] == "" and "optional" in h[0]["note"]
    assert out["product_names"]["table_id"] == "" and out["product_names"]["ok"] is True
    assert source_tables.save("product_names", "")["product_names"]["ok"] and len(ss.history("bigquery", 500)) == n0 + 1
    n_queries = len(fake.queries)
    assert n_queries == 0                                                # metadata only, before and after


def test_status_of_the_optional_table_is_ok_when_empty_and_requires_a_check_when_set():
    from test_v149_source_tables import NAMES, _fake
    st = source_tables.status()
    assert st["product_names"]["optional"] is True and st["product_names"]["ok"] is True
    assert st["product_names"]["table_id"] == "" and st["product_names"]["last_check"] is None
    assert not any("optional" in st[k] for k in ("d1", "d0", "openhours", "avg_demand", "avg_demand_hist"))
    ss.update("bigquery", {"product_names_table": NAMES})
    st = source_tables.status()["product_names"]
    assert st["optional"] is True and st["ok"] is False and st["table_id"] == NAMES    # set but never checked
    _bq_ready(_fake())
    assert source_tables.check("product_names", NAMES)["status"] == "PASSED"
    assert source_tables.status()["product_names"]["ok"] is True
    ss.update("bigquery", {"product_names_table": "company-prod-01.ref.other"})
    assert source_tables.status()["product_names"]["ok"] is False                      # another id: not the checked one


def test_a_non_empty_id_is_checked_exactly_as_before():
    from test_v149_source_tables import NAMES, NAMES_COLS, _fake
    fake = _bq_ready(_fake({"company-prod-01.ref.bad": [c for c in NAMES_COLS if c[0] != "product_name"]}))
    ok = source_tables.check("product_names", NAMES)
    assert ok["status"] == "PASSED" and "optional_empty" not in ok and ok["n_columns"] == len(NAMES_COLS)
    bad = source_tables.check("product_names", "company-prod-01.ref.bad")
    assert bad["status"] == "FAILED" and {"code": "COLUMN_NOT_FOUND", "field": "product_names", "column": "product_name"} in bad["errors"]
    assert source_tables.check("product_names", "dim_sku")["errors"][0]["code"] == "BQ_TABLE_ID_INVALID"   # short name: no
    with pytest.raises(AppError) as e:
        source_tables.save("product_names", "company-prod-01.ref.bad")
    assert e.value.code == "BQ_TABLE_CHECK_FAILED" and ss.get("bigquery").product_names_table == ""
    assert fake.queries == []


@pytest.mark.parametrize("kind", ["openhours", "avg_demand", "avg_demand_hist"])
def test_a_required_kind_with_an_empty_id_is_still_refused(kind):
    fake, made = _setup()
    section, key = source_tables.AUX[kind]
    before = getattr(ss.get(section), key)
    r = source_tables.check(kind, "")
    assert r["status"] == "FAILED" and r["errors"][0]["code"] == "BQ_TABLE_ID_INVALID" and "optional_empty" not in r
    with pytest.raises(AppError) as e:
        source_tables.save(kind, "  ")
    assert e.value.code == "BQ_TABLE_ID_INVALID" and e.value.status == 422
    assert getattr(ss.get(section), key) == before and made == []
    assert source_tables.OPTIONAL == ("product_names",)


def test_settings_validator_accepts_empty_and_still_rejects_garbage():
    assert ss.BigQuerySettings().product_names_table == ""
    assert ss.BigQuerySettings(product_names_table="").product_names_table == ""
    assert ss.BigQuerySettings(product_names_table="  ").product_names_table == ""
    assert ss.BigQuerySettings(product_names_table=" dim_sku ").product_names_table == "dim_sku"
    assert ss.BigQuerySettings(product_names_table=DIM).product_names_table == DIM
    for bad in ("a b c", "a;b", "p.d", "p.d.t.x", "dim sku"):
        with pytest.raises(ValueError):
            ss.BigQuerySettings(product_names_table=bad)
    with pytest.raises(Exception):
        ss.update("bigquery", {"product_names_table": "a b c"})
    assert ss.get("bigquery").product_names_table == ""


def test_an_installation_that_saved_its_own_value_keeps_it():
    ss.update("bigquery", {"product_names_table": DIM})
    assert ss.get("bigquery").product_names_table == DIM
    assert source_tables.current_id("product_names") == DIM


# ------------------------------------------------------------------ 8. API
def test_api_put_and_check_with_an_empty_id(client):
    from test_v149_source_tables import NAMES, _fake
    fake = _bq_ready(_fake())
    ss.update("bigquery", {"product_names_table": NAMES})
    r = client.post("/api/bigquery/source-tables/product_names/check", json={"table_id": ""})
    assert r.status_code == 200 and r.json()["status"] == "PASSED" and r.json()["optional_empty"] is True
    r = client.put("/api/bigquery/source-tables/product_names", json={"table_id": ""})
    assert r.status_code == 200, r.text
    pn = r.json()["product_names"]
    assert pn["table_id"] == "" and pn["ok"] is True and pn["optional"] is True
    assert ss.get("bigquery").product_names_table == ""
    g = client.get("/api/bigquery/source-tables").json()["product_names"]
    assert g["optional"] is True and g["ok"] is True and g["table_id"] == "" and g["setting"] == "bigquery.product_names_table"
    assert "not used" in g["used_by"]
    # a required table is still refused with an empty id
    r = client.put("/api/bigquery/source-tables/openhours", json={"table_id": ""})
    assert r.status_code == 422 and r.json()["code"] == "BQ_TABLE_ID_INVALID"
    assert client.post("/api/bigquery/source-tables/avg_demand/check", json={"table_id": ""}).json()["status"] == "FAILED"
    assert fake.queries == []


def test_api_refresh_with_the_empty_default_needs_no_bigquery_and_reports_the_sources(client):
    fake, made = _setup()
    _demand("S0")
    _avg("2026-11-02", [("S0", "F1", "SL", "Avg S0")])
    r = client.post("/api/bigquery/product-names/refresh")
    assert r.status_code == 200 and r.json()["skus_by_source"] == {"avg": 1, "hist": 0, "stored": 0, "dim": 0}
    assert made == [] and fake.queries == []
    v = client.get("/api/bigquery/product-names").json()
    assert v["skus_named"] == 1 and "names" not in v


# ------------------------------------------------------------------ 9. numbers untouched: only the name column differs
def test_excel_built_with_the_old_and_the_new_names_differs_only_in_the_name_column(sel2_on, monkeypatch):
    full = {h: (h, h - 0.4) for h in range(1, 8)}
    _run("R1", D, {("S1", "F1"): ("A", "MOC+DOW4", full), ("S2", "F1"): ("B", "FALLBACK:V33_L112", full),
                   ("S3", "F1"): ("C", "V36_two_stage@0.6+TSB", {h: (0, 0.1) for h in range(1, 6)})},
         created="2026-11-01T23:30:00+00:00")
    _avg_export(D, [("S1", "F1", "SL1", 2.5, "Thuoc A"), ("S2", "F1", "SL1", 4.0, "Thuoc B"), ("S4", "F1", "SL1", 3.0, "")])
    _config([("S1", "F1", "LIGHTGBM", None), ("S3", "F1", "LIGHTGBM", None), ("S4", "F1", "LIGHTGBM", None)])
    with db.tx() as c:                       # the stored mapping (dim_sku names) disagrees with Avg for S1 and S2
        c.execute("INSERT INTO sync_state(name, value_json, updated_at) VALUES ('product_names', ?, '2026-11-01T00:00:00+00:00')",
                  (json.dumps({"names": {"S1": "Dim S1", "S2": "Dim S2", "S3": "Dim S3", "S4": "Dim S4"}}),))

    def old_names(conn, d, avg_table):       # 1.4.9: the stored mapping overrode the Avg name
        out = {}
        if avg_table:
            out = {r[0]: r[1] for r in conn.execute(
                "SELECT sku_code, MAX(product_name) FROM avg_demand_daily WHERE business_date=? AND source_table=? "
                "AND product_name IS NOT NULL GROUP BY sku_code", (d, avg_table))}
        out.update({k: v for k, v in (product_names.names(conn) or {}).items() if v})
        return out

    new_res = export.write_daily_export(D, scope_key=SCOPE)
    new_rows = _all_rows(_book(new_res))                                  # read now: a newer version moves this file
    with monkeypatch.context() as m:
        m.setattr(export, "_names", old_names)
        old_res = export.write_daily_export(D, scope_key=SCOPE)
    old_rows = _all_rows(_book(old_res))
    assert new_res["n_rows"] == old_res["n_rows"] == len(new_rows) == len(old_rows) == 4 * 20
    key = lambda r: (r["sku_code"], r["fc_code"], r["horizon"])        # noqa: E731
    assert [key(r) for r in new_rows] == [key(r) for r in old_rows]
    diff_cols = {c for a, b in zip(new_rows, old_rows) for c in COLS20 if a[c] != b[c]}
    assert diff_cols == {"ten_san_pham"}                                  # quantities, sources, reasons all identical
    new_by = {r["sku_code"]: r["ten_san_pham"] for r in new_rows}
    old_by = {r["sku_code"]: r["ten_san_pham"] for r in old_rows}
    assert new_by == {"S1": "Thuoc A", "S2": "Thuoc B", "S3": "Dim S3", "S4": "Dim S4"}   # Avg first; stored fills gaps
    assert old_by == {"S1": "Dim S1", "S2": "Dim S2", "S3": "Dim S3", "S4": "Dim S4"}
