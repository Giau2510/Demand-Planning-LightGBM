"""1.2.12: the owner's ADHOC open-hours rule for six exact day x SKU x FC keys (data/open_hours_override.py).

Owner decision (21/10/2026): for exactly the six keys that stopped the BigQuery training with OPEN_HOURS_INVALID
(status MULTI_ITEM), the representative total_open_hours is the MAXIMUM of the valid listing-level values. Proven here:
* the list is exactly those six keys (scope x date x SKU x FC, never item_code) and the maximum is computed from validated
  listing values (present, numeric, finite, 0..24, at least two) - never typed in, never guessed;
* only the exact stored rows it was approved for are covered (still MULTI_ITEM, same qty and orders); any other key -
  another MULTI_ITEM / CONFLICT / MISSING row, a changed approved row, another scope or FC - keeps blocking;
* the stored data (demand_daily) and the D-1 classification are never changed; the run records the listing values, the
  maximum, rule, version, reason and time, and a rebuilt panel of that run uses the recorded values;
* the value really is the model input (open_hours_last of the next day), and the feature registry and data-check agree
  with the training gate.
Isolated databases (conftest), synthetic data; no BigQuery."""
import hashlib
import json
from datetime import datetime, timezone

import numpy as np
import pytest

from app import db, paths, timeutil
from app import settings_service as ss
from app.data import open_hours
from app.data import open_hours_override as ovr
from app.data.demand import bigquery_scope_key, panel_for_run
from app.messages import AppError
from app.ml.features import feature_names, features_at, static_codes

SCOPE = ovr.SCOPE_KEY
SIX = [("2026-02-09", "MEDX.DMTS-HOA-BAO-002", "HN", 24.0), ("2026-02-10", "MEDX.2LJ61PGE", "HN", 24.0),
       ("2026-03-02", "MEDX.DMTS-STA-LOS-002", "BD", 24.0), ("2026-03-02", "MEDX.SOP-NEO-001", "BD", 24.0),
       ("2026-08-26", "MEDX.COU-STR-001", "BD", 24.0), ("2026-08-26", "MEDX.D6TABCV8", "BD", 22.85)]
FM = {"order_id": {"column": "so_code", "usage": "OPTIONAL"}, "order_date": {"column": "created_date", "usage": "REQUIRED"},
      "created_at": {"column": None, "usage": "UNUSED"},
      "sku_id": {"column": "sku_code", "usage": "REQUIRED"}, "fc_id": {"column": "fc_code", "usage": "REQUIRED"},
      "order_qty": {"column": "demand_quantity", "usage": "REQUIRED"},
      "unit_price": {"column": "sales_price", "usage": "OPTIONAL"}}
REF = {"item_code": {"column": "item_code", "usage": "OPTIONAL"},
       "open_hours": {"column": "total_open_hours", "usage": "OPTIONAL"}}


# ================================================================== A. the approved list and the rule itself
def test_the_list_is_exactly_the_six_blocked_keys_and_the_maximum_is_computed_from_valid_listing_values():
    recs = ovr.approved()
    assert [(r["business_date"], r["sku_id"], r["fc_id"], r["selected_hours"]) for r in recs] == SIX
    assert all(r["invalid_reason"] is None and len(r["listings"]) == 2 for r in recs)
    for r in recs:      # the maximum of the listing values, recomputed here (not trusted from the list)
        assert r["selected_hours"] == max(x["total_open_hours"] for x in r["listings"])
        # the key is scope x date x SKU x FC; the item codes only label the evidence values (all of the same SKU)
        assert all(x["item_code"].startswith(r["sku_id"] + ".") for x in r["listings"])
        assert set(r) >= {"business_date", "sku_id", "fc_id"} and "item_code" not in r
    # the six keys of the source (read-only evidence of 21/10/2026): qty / orders of the stored rows
    assert [(r["approved_qty"], r["approved_orders"]) for r in recs] == [(8, 4), (11, 2), (88, 18), (3, 3), (42, 8), (4, 4)]
    assert SCOPE == "BIGQUERY:lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm"
    assert (ovr.RULE_ID, ovr.RULE_VERSION) == ("OWNER_ADHOC_MAX_LISTING_OPEN_HOURS", "1.2.12")


@pytest.mark.parametrize("values,reason", [
    ({"a.1": 23.0}, "FEWER_THAN_TWO_LISTINGS"), ({}, "FEWER_THAN_TWO_LISTINGS"),
    ({"a.1": None, "a.2": 24.0}, "LISTING_VALUE_MISSING"), ({"a.1": "24", "a.2": 1.0}, "LISTING_VALUE_NOT_NUMERIC"),
    ({"a.1": True, "a.2": 1.0}, "LISTING_VALUE_NOT_NUMERIC"), ({"a.1": float("nan"), "a.2": 1.0}, "LISTING_VALUE_NOT_FINITE"),
    ({"a.1": float("inf"), "a.2": 1.0}, "LISTING_VALUE_NOT_FINITE"), ({"a.1": -0.01, "a.2": 1.0}, "LISTING_VALUE_OUT_OF_RANGE"),
    ({"a.1": 24.01, "a.2": 1.0}, "LISTING_VALUE_OUT_OF_RANGE")])
def test_an_invalid_listing_value_gives_no_value_and_a_reason(values, reason):
    assert ovr.listing_max(values) == (None, reason)


def test_valid_listing_values_give_their_maximum_bounds_included():
    assert ovr.listing_max({"a.1": 0, "a.2": 24}) == (24.0, None)
    assert ovr.listing_max({"a.1": 22.85, "a.2": 18.22}) == (22.85, None)
    assert ovr.listing_max([0.0, 0.0]) == (0.0, None)


def test_the_d1_classification_is_unchanged_a_multi_listing_key_is_still_multi_item_at_load():
    # the six keys' own aggregates (2 items, 2 values, every line with a value) and any NEW multi-listing key: the load
    # never applies the rule - a new case blocks the training until the owner decides it
    for lo, hi in ((23.92, 24.0), (21.16, 24.0), (5.0, 24.0), (1.7, 24.0), (23.72, 24.0), (18.22, 22.85), (3.0, 9.5)):
        assert open_hours.cell(0, lo, hi, 2, 2, 0) == (None, "MULTI_ITEM")


# ================================================================== B. which stored rows are covered
def _row(day, sku, fc, qty=5.0, n=2, hours=12.0, status="OK", scope=SCOPE):
    return (scope, "BIGQUERY", day, sku, fc, qty, n, "2026-10-21T05:36:47+00:00", hours, status)


def _insert(rows):
    with db.tx() as c:
        c.executemany("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, loaded_at, "
                      "open_hours, open_hours_status) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)


def _six_rows(change=None):
    out = []
    for r in ovr.approved():
        k = (r["business_date"], r["sku_id"], r["fc_id"])
        q, n = (change or {}).get(k, (r["approved_qty"], r["approved_orders"]))
        out.append(_row(*k, qty=q, n=n, hours=None, status="MULTI_ITEM"))
    return out


def test_exactly_the_six_stored_rows_are_covered_and_every_other_row_still_blocks():
    _insert(_six_rows() + [_row("2026-05-05", "S1", "HN"), _row("2026-05-05", "S1", "BD"),
                           _row("2026-06-01", "MEDX.NEW-MULTI", "HN", hours=None, status="MULTI_ITEM"),      # not approved
                           # same day and SKU as an approved key, another FC: never matched (FC is part of the key)
                           _row("2026-08-26", "MEDX.D6TABCV8", "HN", qty=1, n=1, hours=None, status="MULTI_ITEM")])
    with db.read() as c:
        res = ovr.resolve(c, SCOPE, "2026-01-01", "2026-10-20")
        chk = open_hours.window_check(c, SCOPE, "2026-01-01", "2026-10-20", overrides=res["applied"])
    assert [(a["business_date"], a["sku_id"], a["fc_id"], a["selected_hours"]) for a in res["applied"]] == SIX
    assert res["not_applied"] == []
    assert chk["override_rows"] == 6 and chk["ok_rows"] == 2 and not chk["ok"]
    assert chk["not_ok"] == {"MULTI_ITEM": {"rows": 2, "first": "2026-06-01", "last": "2026-08-26"}}
    with db.tx() as c:
        c.execute("DELETE FROM demand_daily WHERE sku_id IN ('MEDX.NEW-MULTI') OR (sku_id='MEDX.D6TABCV8' AND fc_id='HN')")
    with db.read() as c:
        chk = open_hours.window_check(c, SCOPE, "2026-01-01", "2026-10-20", overrides=ovr.resolve(c, SCOPE, "2026-01-01",
                                                                                                    "2026-10-20")["applied"])
        plain = open_hours.window_check(c, SCOPE, "2026-01-01", "2026-10-20")
    assert chk["ok"] and chk["override_rows"] == 6 and chk["not_ok"] == {}
    # without the rule (1.2.11 behaviour, or the rule removed) the six rows block exactly as before
    assert plain["not_ok"] == {"MULTI_ITEM": {"rows": 6, "first": "2026-02-09", "last": "2026-08-26"}} and not plain["ok"]


def test_a_changed_fixed_or_missing_approved_row_is_not_covered_and_says_why():
    k_changed, k_fixed, k_gone = (("2026-03-02", "MEDX.DMTS-STA-LOS-002", "BD"), ("2026-02-10", "MEDX.2LJ61PGE", "HN"),
                                  ("2026-08-26", "MEDX.COU-STR-001", "BD"))
    rows = [r for r in _six_rows({k_changed: (89.0, 18)}) if (r[2], r[3], r[4]) not in (k_fixed, k_gone)]
    rows.append(_row(*k_fixed, qty=11, n=2, hours=24.0, status="OK"))         # the source now gives one value
    _insert(rows)
    with db.read() as c:
        res = ovr.resolve(c, SCOPE, "2026-01-01", "2026-10-20")
        chk = open_hours.window_check(c, SCOPE, "2026-01-01", "2026-10-20", overrides=res["applied"])
        late = ovr.resolve(c, SCOPE, "2026-03-01", "2026-10-20")              # a later window start
    why = {(a["business_date"], a["sku_id"], a["fc_id"]): a["not_applied_reason"] for a in res["not_applied"]}
    assert why == {k_changed: "CONTENT_CHANGED", k_fixed: "STORED_STATUS_OK", k_gone: "ROW_NOT_FOUND"}
    assert len(res["applied"]) == 3
    assert chk["not_ok"] == {"MULTI_ITEM": {"rows": 1, "first": "2026-03-02", "last": "2026-03-02"}}   # the changed row
    assert chk["override_rows"] == 3 and chk["ok_rows"] == 1
    # the key whose row is gone gets nothing (no row to give a value: nothing guessed) and is reported, not counted
    assert ovr.summary(res)["not_applied"][-1] == ["2026-08-26", "MEDX.COU-STR-001", "BD", "ROW_NOT_FOUND"]
    assert {a["not_applied_reason"] for a in late["not_applied"] if a["business_date"] < "2026-03-01"} == {"NOT_IN_WINDOW"}


def test_a_reloaded_approved_row_is_not_covered_the_listing_values_were_verified_for_the_earlier_load_only():
    rows = _six_rows()
    rows[5] = rows[5][:7] + ("2026-10-25T23:30:00+00:00",) + rows[5][8:]       # K6 rewritten by a later load, same content
    _insert(rows)
    with db.read() as c:
        res = ovr.resolve(c, SCOPE, "2026-01-01", "2026-10-20")
        chk = open_hours.window_check(c, SCOPE, "2026-01-01", "2026-10-20", overrides=res["applied"])
    assert [(a["sku_id"], a["not_applied_reason"]) for a in res["not_applied"]] == [("MEDX.D6TABCV8", "RELOADED_SINCE_APPROVAL")]
    assert chk["not_ok"] == {"MULTI_ITEM": {"rows": 1, "first": "2026-08-26", "last": "2026-08-26"}} and chk["override_rows"] == 5
    assert not chk["ok"]                                                       # the reloaded key keeps blocking


def test_fill_checks_the_loaded_frame_again_and_never_writes_an_unchecked_value():
    import pandas as pd
    _insert(_six_rows())
    with db.read() as c:
        res = ovr.resolve(c, SCOPE, "2026-01-01", "2026-10-20")
    frame = lambda: pd.DataFrame([{"order_date": r[2], "sku_id": r[3], "fc_id": r[4], "qty": r[5], "n_orders": r[6],  # noqa: E731
                                   "open_hours": np.nan} for r in _six_rows()])
    d, probs = ovr.fill(frame(), res["applied"])
    assert probs == [] and d["open_hours"].tolist() == [s[3] for s in SIX]
    d = frame()
    d.loc[0, "qty"] = 9.0                                                      # a load between resolve and the read
    d.loc[1, "open_hours"] = 21.16
    d = pd.concat([d, d.iloc[[2]]], ignore_index=True)                         # the same key twice
    bad = [dict(res["applied"][3], selected_hours=23.0),                       # not the maximum of its listings
           dict(res["applied"][4], listings=[{"item_code": "x.1", "total_open_hours": float("nan")},
                                             {"item_code": "x.2", "total_open_hours": 24.0}])]
    d, probs = ovr.fill(d, res["applied"][:3] + bad)
    assert [p["reason"] for p in probs] == ["CONTENT_CHANGED_AT_LOAD", "VALUE_ALREADY_PRESENT", "ROWS_FOUND_2",
                                            "SELECTED_VALUE_NOT_THE_MAXIMUM", "LISTING_VALUE_NOT_FINITE"]
    assert d["open_hours"].isna().sum() == 6 and d.loc[1, "open_hours"] == 21.16     # nothing written for a problem key


def test_no_other_scope_is_ever_covered():
    other = "BIGQUERY:lakehouse-prod-394907.sales.orders"
    _insert([(other, *r[1:]) for r in _six_rows()])
    with db.read() as c:
        res = ovr.resolve(c, other, "2026-01-01", "2026-10-20")
        chk = open_hours.window_check(c, other, "2026-01-01", "2026-10-20", overrides=res["applied"])
    assert not res["applies_to_scope"] and res["applied"] == [] and res["not_applied"] == []
    assert chk["not_ok"]["MULTI_ITEM"]["rows"] == 6 and "override_rows" not in chk


# ================================================================== C. training, recording, stored data, model input
def _scope_with_six(monkeypatch, extra=()):
    """BIGQUERY scope with the production scope key: demo demand (every row OK) + the six approved MULTI_ITEM rows."""
    from app.data.demo import create_demo_batch
    from app.jobs import flows
    timeutil.set_now_override(lambda: datetime(2026, 10, 21, 3, 0, tzinfo=timezone.utc))      # 10:00 VN, 21/10/2026
    demo = create_demo_batch(days=150, n_skus=6, seed=5)
    ss.update("bigquery", {"dataset_id": "gold_buymed_vn2", "source_table": "demand_planing_lightgbm",
                           "location": "asia-southeast1", "partition_column": "", "field_mapping": FM,
                           "reference_mapping": REF})
    assert bigquery_scope_key(ss.get("bigquery")) == SCOPE
    with db.tx() as c:
        c.execute("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, avg_unit_price, "
                  "avg_discount_rate, promo_share, voucher_share, loaded_at, open_hours, open_hours_status) SELECT ?, "
                  "'BIGQUERY', order_date, sku_id, fc_id, qty, n_orders, avg_unit_price, avg_discount_rate, promo_share, "
                  "voucher_share, loaded_at, 8 + (julianday(order_date) % 17), 'OK' FROM demand_daily WHERE scope_key=?",
                  (SCOPE, demo["batch_id"]))
        # the day after K6 for its series (so the value is visible as open_hours_last of a real row)
        c.execute("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, loaded_at, "
                  "open_hours, open_hours_status) VALUES (?, 'BIGQUERY', '2026-08-27', 'MEDX.D6TABCV8', 'BD', 2, 2, 'x', 20, 'OK')",
                  (SCOPE,))
    _insert(_six_rows() + list(extra))
    monkeypatch.setattr(flows, "_bq_ready", lambda c, blockers: None)      # production state is not under test here
    ss.update("model", {"forecast_strategy": "DIRECT"})                     # the production strategy
    ss.update("horizons", {"enabled": [7]})                                 # within the fast model's 7 trained days


def _stored_hash():
    with db.read() as c:
        rows = c.execute("SELECT order_date, sku_id, fc_id, qty, n_orders, open_hours, open_hours_status, loaded_at FROM "
                         "demand_daily WHERE scope_key=? ORDER BY 1, 2, 3", (SCOPE,)).fetchall()
    return hashlib.sha256(repr([tuple(r) for r in rows]).encode()).hexdigest(), len(rows)


def test_training_runs_records_the_override_and_never_changes_the_stored_rows(client, fast_model, monkeypatch):
    from app.ml import pipeline
    with monkeypatch.context() as m:
        _scope_with_six(m)
        before = _stored_hash()
        res = pipeline.train_and_publish(force=True, source="BIGQUERY")
        assert res["status"] == "PUBLISHED", res
        assert _stored_hash() == before                                       # demand_daily untouched
        with db.read() as c:
            tr = db.one(c, "SELECT * FROM training_runs WHERE id=?", (res["training_run_id"],))
            six = c.execute("SELECT open_hours, open_hours_status FROM demand_daily WHERE scope_key=? AND "
                            "open_hours_status='MULTI_ITEM'", (SCOPE,)).fetchall()
            aud = c.execute("SELECT details_json FROM audit_log WHERE action='OPEN_HOURS_OVERRIDE_APPLIED' AND entity_id=?",
                            (res["training_run_id"],)).fetchall()
        assert [tuple(r) for r in six] == [(None, "MULTI_ITEM")] * 6          # still as the D-1 loaded them
        fc = json.loads(tr["feature_config_json"])
        oh = fc["feature_decisions"]["open_hours"]
        assert oh["window_check"]["ok"] and oh["window_check"]["override_rows"] == 6
        rec = oh["override"]
        assert (rec["rule"], rec["version"], rec["approved_on"]) == (ovr.RULE_ID, "1.2.12", "2026-10-21") and rec["reason"]
        assert rec["checked_at"] and rec["source_snapshot"] == ovr.SOURCE_SNAPSHOT
        assert [(a["business_date"], a["sku_id"], a["fc_id"], a["selected_hours"]) for a in rec["applied"]] == SIX
        assert all(len(a["listings"]) == 2 and a["stored"]["open_hours_status"] == "MULTI_ITEM" for a in rec["applied"])
        assert len(aud) == 1
        a = json.loads(aud[0][0])
        assert [k["selected_hours"] for k in a["keys"]] == [s[3] for s in SIX] and a["applied_at"] and a["rule"] == ovr.RULE_ID
        # the value is the model input: the rebuilt panel of the run carries it and open_hours_last of the next day is it
        panel = panel_for_run(tr)
        cfg = ss.ModelSettings.model_validate(fc["config"])
        s = panel.keys.index(("MEDX.D6TABCV8", "BD"))
        t = int(np.nonzero(panel.dates == np.datetime64("2026-08-26"))[0][0])
        assert panel.hours[s, t] == 22.85
        sc, fcc = static_codes(panel)
        cols = feature_names(ss.ModelSettings.model_validate({**fc["config"], "forecast_strategy": "RECURSIVE"}))
        x = features_at(panel, panel.Y, panel.price, panel.disc, panel.promo, panel.dates, t + 1, cfg, sc, fcc)
        assert x[s, cols.index("open_hours_last")] == np.float32(22.85)
        import lightgbm as lgb
        booster = lgb.Booster(model_file=str(paths.models_dir() / tr["model_path"]))
        assert booster.feature_name() == fc["features"] and "open_hours_last" in booster.feature_name()
        # reversible: with the rule removed the next training blocks again, the run keeps its recorded values
        m.setattr(ovr, "APPROVED_KEYS", ())
        with pytest.raises(AppError) as e:
            pipeline.train_and_publish(force=True, source="BIGQUERY")
        assert e.value.code == "OPEN_HOURS_INVALID"
        assert json.loads(e.value.detail)["not_ok"] == {"MULTI_ITEM": {"rows": 6, "first": "2026-02-09", "last": "2026-08-26"}}
        assert panel_for_run(tr).hours[s, t] == 22.85                          # recorded with the run, not the list


def test_an_unrelated_blocker_is_never_hidden_by_the_override(client, fast_model, monkeypatch):
    from app.ml import pipeline
    with monkeypatch.context() as m:
        _scope_with_six(m, extra=[_row("2026-07-07", "MEDX.OTHER", "HN", hours=None, status="MISSING"),
                                  _row("2026-07-08", "MEDX.OTHER2", "BD", hours=None, status="MULTI_ITEM")])
        with pytest.raises(AppError) as e:
            pipeline.train_and_publish(force=True, source="BIGQUERY")
        assert e.value.code == "OPEN_HOURS_INVALID"
        det = json.loads(e.value.detail)
        assert det["not_ok"] == {"MISSING": {"rows": 1, "first": "2026-07-07", "last": "2026-07-07"},
                                 "MULTI_ITEM": {"rows": 1, "first": "2026-07-08", "last": "2026-07-08"}}
        assert det["override_rows"] == 6 and det["override"]["applied"] == 6
        with db.read() as c:
            assert c.execute("SELECT COUNT(*) FROM training_runs WHERE scope_key=?", (SCOPE,)).fetchone()[0] == 0


def test_a_changed_approved_row_blocks_the_training_with_its_reason(client, fast_model, monkeypatch):
    from app.ml import pipeline
    with monkeypatch.context() as m:
        _scope_with_six(m)
        with db.tx() as c:
            c.execute("UPDATE demand_daily SET qty = 43 WHERE scope_key=? AND order_date='2026-08-26' AND "
                      "sku_id='MEDX.COU-STR-001'", (SCOPE,))
        with pytest.raises(AppError) as e:
            pipeline.train_and_publish(force=True, source="BIGQUERY")
        det = json.loads(e.value.detail)
        assert det["not_ok"] == {"MULTI_ITEM": {"rows": 1, "first": "2026-08-26", "last": "2026-08-26"}}
        assert det["override"]["not_applied"] == [["2026-08-26", "MEDX.COU-STR-001", "BD", "CONTENT_CHANGED"]]


def test_an_approved_key_without_a_row_gets_nothing_and_is_reported_with_the_run(client, fast_model, monkeypatch):
    # no stored row = no model-input row for that key: nothing to give a value, nothing guessed; the other five apply.
    # (A BIGQUERY scope with this key whose data never had the six rows - e.g. the default test settings - trains.)
    from app import data_checks
    from app.ml import pipeline
    with monkeypatch.context() as m:
        _scope_with_six(m)
        with db.tx() as c:
            c.execute("DELETE FROM demand_daily WHERE scope_key=? AND sku_id='MEDX.SOP-NEO-001'", (SCOPE,))
        res = pipeline.train_and_publish(force=True, source="BIGQUERY")
        assert res["status"] == "PUBLISHED", res
        with db.read() as c:
            tr = db.one(c, "SELECT feature_config_json FROM training_runs WHERE id=?", (res["training_run_id"],))
        rec = json.loads(tr["feature_config_json"])["feature_decisions"]["open_hours"]["override"]
        assert len(rec["applied"]) == 5
        assert [(a["sku_id"], a["not_applied_reason"]) for a in rec["not_applied"]] == [("MEDX.SOP-NEO-001", "ROW_NOT_FOUND")]
        chk = {x["check"]: x for x in data_checks.run(paths.db_path())["checks"]}
        assert chk["open_hours_window_ready"]["status"] == "OK" and chk["open_hours_owner_override"]["status"] == "OK"


def test_feature_registry_and_data_check_agree_with_the_training_gate(client, fast_model, monkeypatch):
    from app import data_checks
    with monkeypatch.context() as m:
        _scope_with_six(m)
        v = client.get("/api/features/registry", params={"source": "BIGQUERY"}).json()
        assert v["next_training"]["blocked_by"] is None
        assert v["decisions"]["open_hours"]["window_check"]["override"]["applied"] == 6
        chk = {x["check"]: x for x in data_checks.run(paths.db_path())["checks"]}
        assert chk["open_hours_window_ready"]["status"] == "OK", chk["open_hours_window_ready"]
        assert chk["open_hours_owner_override"]["status"] == "OK" and chk["open_hours_owner_override"]["count"] == 0
        _insert([_row("2026-07-08", "MEDX.OTHER2", "BD", hours=None, status="MULTI_ITEM")])
        v = client.get("/api/features/registry", params={"source": "BIGQUERY"}).json()
        assert v["next_training"]["blocked_by"] == "OPEN_HOURS_INVALID"
        chk = {x["check"]: x for x in data_checks.run(paths.db_path())["checks"]}
        assert chk["open_hours_window_ready"]["status"] == "WARN" and chk["open_hours_window_ready"]["count"] == 1
        with db.tx() as c:
            c.execute("UPDATE demand_daily SET n_orders = 5 WHERE scope_key=? AND sku_id='MEDX.SOP-NEO-001'", (SCOPE,))
        chk = {x["check"]: x for x in data_checks.run(paths.db_path())["checks"]}
        assert chk["open_hours_owner_override"]["status"] == "WARN"
        assert chk["open_hours_owner_override"]["examples"] == [["2026-03-02", "MEDX.SOP-NEO-001", "BD", "CONTENT_CHANGED"]]
        assert chk["open_hours_window_ready"]["count"] == 2
