"""1.2.13: the owner's six-key open-hours MAX rule (1.2.12, data/open_hours_override.py) carries over to a later load of
a key only when that load verified, before writing, that the source still gives the recorded evidence (owner rule
restated 22/10/2026: "only if the source values still match the recorded evidence"). Needed so that a full reload -
e.g. after mapping the customer column - does not block the training while nothing in the evidence changed.
Synthetic versioned BigQuery source (tests/test_v1213_history_sync.py), not real integration evidence."""
from __future__ import annotations

import json
from datetime import date

import pytest

from app import db
from app import settings_service as ss
from app.bq import connector
from app.data import history_sync as hs
from app.data import open_hours
from app.data import open_hours_override as ovr
from test_v1213_history_sync import SCHEMA, Y, L, Source, _production, _stored

SCOPE = ovr.SCOPE_KEY


def _agg(rec, **change) -> dict:
    """The source aggregate of an approved key as connector._daily_sql returns it (the evidence values)."""
    vals = [x["total_open_hours"] for x in rec["listings"]]
    r = {"order_date": rec["business_date"], "sku_id": rec["sku_id"], "fc_id": rec["fc_id"], "qty": rec["approved_qty"],
         "n_orders": rec["approved_orders"], "open_hours_null_rows": 0, "open_hours_no_item_rows": 0,
         "open_hours_items": len(vals), "open_hours_item_values": len(vals), "open_hours_min": min(vals),
         "open_hours_max": max(vals)}
    r.update(change)
    return r


# ================================================================== verify_load: what a load records
def test_a_load_with_the_evidence_values_verifies_every_approved_key_in_its_window():
    rows = [_agg(r) for r in ovr.approved()] + [{"order_date": "2026-02-09", "sku_id": "X", "fc_id": "HN", "qty": 1}]
    v = ovr.verify_load(SCOPE, rows, "2026-01-01", "2026-10-21")
    assert v["verify_version"] == "1.2.13" and len(v["keys"]) == 6 and all(k["match"] for k in v["keys"])
    assert [k["key"] for k in v["keys"]] == [[r["business_date"], r["sku_id"], r["fc_id"]] for r in ovr.approved()]
    # a window without approved keys records nothing to check; another scope records nothing at all
    assert ovr.verify_load(SCOPE, rows, "2026-10-18", "2026-10-21")["keys"] == []
    assert ovr.verify_load("BIGQUERY:other.ds.t", rows, "2026-01-01", "2026-10-21") is None


@pytest.mark.parametrize("change,reason,differs", [
    ({"open_hours_max": 23.5}, "LISTING_VALUES_CHANGED", ["hours_max"]),
    ({"open_hours_min": 20.0}, "LISTING_VALUES_CHANGED", ["hours_min"]),
    ({"open_hours_items": 3, "open_hours_item_values": 3}, "LISTING_VALUES_CHANGED", ["hours_item_values", "hours_items"]),
    ({"open_hours_null_rows": 1}, "LISTING_VALUES_CHANGED", ["hours_null_rows"]),
    ({"open_hours_no_item_rows": 1}, "LISTING_VALUES_CHANGED", ["hours_no_item_rows"]),
    ({"open_hours_max": None}, "LISTING_VALUES_CHANGED", ["hours_max"]),
    ({"qty": 5.0}, "CONTENT_CHANGED", ["qty"]),
    ({"n_orders": 3}, "CONTENT_CHANGED", ["n_orders"])])
def test_any_difference_from_the_evidence_is_named_and_not_verified(change, reason, differs):
    recs = ovr.approved()
    rows = [_agg(recs[0])] + [_agg(r, **change) for r in recs[5:]]
    v = {tuple(k["key"]): k for k in ovr.verify_load(SCOPE, rows, "2026-01-01", "2026-10-21")["keys"]}
    k6 = v[(recs[5]["business_date"], recs[5]["sku_id"], recs[5]["fc_id"])]
    assert (k6["match"], k6["reason"], k6["differs"]) == (False, reason, differs)
    assert v[(recs[0]["business_date"], recs[0]["sku_id"], recs[0]["fc_id"])]["match"]
    # a key of the window the load did not return is not verified (no row: nothing to compare)
    assert {k["reason"] for kk, k in v.items() if not k["match"]} >= {"ROW_NOT_FOUND"}


# ================================================================== resolve: what the training gate accepts
def _six(loaded_at):
    with db.tx() as c:
        for r in ovr.approved():
            c.execute("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, loaded_at, "
                      "open_hours, open_hours_status) VALUES (?, 'BIGQUERY', ?,?,?,?,?,?, NULL, 'MULTI_ITEM')",
                      (SCOPE, r["business_date"], r["sku_id"], r["fc_id"], r["approved_qty"], r["approved_orders"], loaded_at))


def _run(run_id, finished, verification, status="COMMITTED", kind="D1_SYNC"):
    with db.tx() as c:
        c.execute("INSERT INTO demand_sync_runs(id, kind, status, scope_key, started_at, finished_at, summary_json) "
                  "VALUES (?,?,?,?,?,?,?)", (run_id, kind, status, SCOPE, finished, finished,
                                             json.dumps({"open_hours_override": verification})))


def _resolve():
    with db.read() as c:
        res = ovr.resolve(c, SCOPE, "2026-01-01", "2026-10-21")
        chk = open_hours.window_check(c, SCOPE, "2026-01-01", "2026-10-21", overrides=res["applied"])
    return res, chk


def test_a_reload_counts_only_through_the_verification_of_the_load_that_wrote_the_row():
    t = "2026-10-23T00:20:00+00:00"
    _six(t)
    res, chk = _resolve()                       # rewritten by a load that recorded nothing: still blocking
    assert {a["not_applied_reason"] for a in res["not_applied"]} == {"RELOADED_SINCE_APPROVAL"} and not chk["ok"]
    _run("D1L-OTHER", "2026-10-23T00:19:59+00:00", ovr.verify_load(SCOPE, [_agg(r) for r in ovr.approved()],
                                                                    "2026-01-01", "2026-10-21"))
    assert len(_resolve()[0]["not_applied"]) == 6           # another load's record never counts
    _run("D1L-NEW", t, ovr.verify_load(SCOPE, [_agg(r) for r in ovr.approved()], "2026-01-01", "2026-10-21"))
    res, chk = _resolve()
    assert len(res["applied"]) == 6 and not res["not_applied"] and chk["ok"] and chk["override_rows"] == 6
    assert {a["verified_by_load"]["run_id"] for a in res["applied"]} == {"D1L-NEW"}
    assert [a["selected_hours"] for a in res["applied"]] == [24.0, 24.0, 24.0, 24.0, 24.0, 22.85]


def test_a_reload_with_other_listing_values_keeps_blocking_with_its_reason():
    t = "2026-10-23T00:20:00+00:00"
    _six(t)
    recs = ovr.approved()
    rows = [_agg(r) for r in recs[:5]] + [_agg(recs[5], open_hours_min=20.0)]
    _run("D1L-NEW", t, ovr.verify_load(SCOPE, rows, "2026-01-01", "2026-10-21"))
    res, chk = _resolve()
    assert [(a["sku_id"], a["not_applied_reason"]) for a in res["not_applied"]] == [("MEDX.D6TABCV8", "LISTING_VALUES_CHANGED")]
    assert chk["not_ok"] == {"MULTI_ITEM": {"rows": 1, "first": "2026-08-26", "last": "2026-08-26"}} and not chk["ok"]


def test_a_rolled_back_load_still_counts_for_the_rows_that_carry_its_load_and_the_approved_load_too():
    # rows a rollback did not restore (identical content) still carry the load that verified them
    t = "2026-10-23T00:20:00+00:00"
    _six(t)
    _run("D1L-NEW", t, ovr.verify_load(SCOPE, [_agg(r) for r in ovr.approved()], "2026-01-01", "2026-10-21"),
         status="ROLLED_BACK")
    assert len(_resolve()[0]["applied"]) == 6
    with db.tx() as c:
        c.execute("UPDATE demand_daily SET loaded_at=? WHERE scope_key=?", (ovr.APPROVED_LOADED_AT, SCOPE))
    res, chk = _resolve()
    assert len(res["applied"]) == 6 and chk["ok"] and all("verified_by_load" not in a for a in res["applied"])


# ================================================================== end to end: a full reload after mapping the customer column
class CustomerSource(Source):
    """The source with a customer column: once it is mapped, the daily aggregate also carries the customer counts
    (connector._customer_ctes; here one customer per order, no repeat)."""

    def __init__(self):
        super().__init__()
        self.schema = SCHEMA + [("customer_id", "INT64")]

    def _daily(self, cfg):
        rows = super()._daily(cfg)
        if "cust_src" in self.queries[-1][0]:
            for r in rows:
                if r.get("_kind") is None:
                    r.update(customer_count=r["n_orders"], repeat_customer_count=0, repeat_interval_days_sum=0)
        return rows


def _lines(change=None):
    lines = [L(date(2026, 1, 5), "X1", "OTHER", 2, fc="HN"), L(Y, "O9", "C", 1)]
    for d, sku, fc, qty, n, items in ovr.APPROVED_KEYS:
        its = sorted(items.items())
        q = [int(qty) // n] * n
        q[0] += int(qty) - sum(q)
        for i in range(n):
            item, oh = its[i % 2]
            oh = (change or {}).get(item, oh)
            lines.append(L(date.fromisoformat(d), f"SO-{sku}-{i}", sku, q[i], fc=fc, item=item, oh=oh))
    return lines


def _remap(column):
    ss.update("bigquery", {"customer_id_column": column, "production_enabled": False})
    assert connector.validate_source()["passed"]
    ss.update("bigquery", {"production_enabled": True})


def test_a_full_reload_after_mapping_the_customer_column_keeps_the_six_key_rule_when_the_evidence_holds(client):
    from app import sync
    src = CustomerSource()
    src.publish(_lines())
    _production(src, dataset="gold_buymed_vn2", table="demand_planing_lightgbm")
    sync.run_d1_sync("J1")
    with db.tx() as c:          # the production state the owner approved: the six rows of the 21/10 load
        c.execute("UPDATE demand_daily SET loaded_at=? WHERE scope_key=? AND open_hours_status='MULTI_ITEM'",
                  (ovr.APPROVED_LOADED_AT, SCOPE))
    assert len(_resolve()[0]["applied"]) == 6
    _remap("customer_id")       # new mapping hash: the next D-1 reloads the whole range, every row gets a new loaded_at
    r = sync.run_d1_sync("J2")
    assert r["status"] == "SUCCEEDED" and r["full_reload"]
    st = _stored(SCOPE)
    six = [(d, sku, fc) for d, sku, fc, *_ in ovr.APPROVED_KEYS]
    assert all(st[k][4] == r["synced_at"] != ovr.APPROVED_LOADED_AT for k in six)        # really rewritten
    assert all(st[k][2] is None and st[k][3] == "MULTI_ITEM" for k in six)               # stored data never filled
    res, chk = _resolve()
    assert len(res["applied"]) == 6 and chk["ok"]
    assert {a["verified_by_load"]["run_id"] for a in res["applied"]} == {r["load_id"]}
    with db.read() as c:
        rec = json.loads(c.execute("SELECT summary_json FROM demand_sync_runs WHERE id=?", (r["load_id"],)).fetchone()[0])
    assert all(k["match"] for k in rec["open_hours_override"]["keys"]) and len(rec["open_hours_override"]["keys"]) == 6
    with db.read() as c:        # the customer counts are what changed every row (logged, so it can be rolled back)
        assert c.execute("SELECT COUNT(*) FROM demand_daily WHERE scope_key=? AND customer_count IS NULL",
                         (SCOPE,)).fetchone()[0] == 0
    # rolled back: every changed row returns to its earlier version - the six to the approved load, which still counts
    assert hs.rollback(r["load_id"], apply=True, by="TEST").get("applied") is True
    assert all(_stored(SCOPE)[k][4] == ovr.APPROVED_LOADED_AT for k in six)
    res, chk = _resolve()
    assert len(res["applied"]) == 6 and chk["ok"] and all("verified_by_load" not in a for a in res["applied"])


def test_a_full_reload_with_a_changed_listing_value_blocks_the_training(client):
    from app import sync
    src = CustomerSource()
    src.publish(_lines())
    _production(src, dataset="gold_buymed_vn2", table="demand_planing_lightgbm")
    sync.run_d1_sync("J1")
    src.publish(_lines({"MEDX.D6TABCV8.2": 19.5}))         # the source changed one listing value of one key
    _remap("customer_id")
    r = sync.run_d1_sync("J2")
    assert r["status"] == "SUCCEEDED" and r["full_reload"]
    res, chk = _resolve()
    why = {(a["sku_id"]): a["not_applied_reason"] for a in res["not_applied"]}
    assert why == {"MEDX.D6TABCV8": "LISTING_VALUES_CHANGED"} and len(res["applied"]) == 5 and not chk["ok"]
