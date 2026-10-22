"""1.2.13 history sync (owner rule of 22/10/2026, app/data/history_sync.py): the stored BigQuery demand keeps every
order line the source has shown, takes late lines / real re-attributions, never reduces a day only because the source
dropped a line (cancellation, unconfirmed WAIT_TO_CONFIRM, scope change), checks the history outside the D-1 window,
logs every change, and can roll a run back. The BigQuery source is a VERSIONED fake (time travel) whose aggregates
and line evidence come from the same order lines - synthetic data, not real integration evidence."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import db, timeutil
from app import settings_service as ss
from app.bq import connector, source_lines
from app.data import history_sync as hs
from app.messages import AppError
from fake_bq import FakeBQ
from test_bigquery import PASSING_VALIDATION

SCHEMA = [("so_code", "STRING"), ("created_date", "DATE"), ("sku_code", "STRING"), ("fc_code", "STRING"),
          ("demand_quantity", "INT64"), ("sales_price", "FLOAT64"), ("total_open_hours", "FLOAT64"),
          ("product_id", "INT64"), ("item_code", "STRING"), ("order_status", "STRING")]
FM = {"order_id": {"column": "so_code", "usage": "OPTIONAL"}, "order_date": {"column": "created_date", "usage": "REQUIRED"},
      "created_at": {"column": None, "usage": "UNUSED"},
      "sku_id": {"column": "sku_code", "usage": "REQUIRED"}, "fc_id": {"column": "fc_code", "usage": "REQUIRED"},
      "order_qty": {"column": "demand_quantity", "usage": "REQUIRED"},
      "unit_price": {"column": "sales_price", "usage": "OPTIONAL"}}
REF = {"open_hours": {"column": "total_open_hours", "usage": "OPTIONAL"},
       "product_id": {"column": "product_id", "usage": "OPTIONAL"},
       "item_code": {"column": "item_code", "usage": "OPTIONAL"},
       "order_status": {"column": "order_status", "usage": "OPTIONAL"}}
SCOPE = "BIGQUERY:lakehouse-prod-394907.sales.orders"
Y = timeutil.today_vn() - timedelta(days=1)          # yesterday: the last day a D-1 load reads
OLD = Y - timedelta(days=20)                         # a history day the regular D-1 window never re-reads


def L(d, so, sku, qty, fc="F1", pid=None, item=None, st="COMPLETED", oh=24.0):
    """One source order line."""
    return {"d": d, "so": so, "sku": sku, "fc": fc, "qty": qty, "pid": pid or f"P-{sku}", "item": item or f"{sku}.1",
            "st": st, "oh": oh}


class Source(FakeBQ):
    """Versioned D-1 source: every version is a list of order lines with its modified time (BigQuery time travel:
    FOR SYSTEM_TIME AS OF returns the latest version modified at or before the timestamp)."""

    def __init__(self):
        super().__init__(schema=SCHEMA, responses={})
        self.versions: list[tuple[datetime, list[dict]]] = []
        self.clock = timeutil.now_utc().replace(microsecond=0) - timedelta(hours=10)
        self.exact_dups = 0
        self.flip_on_get_table = None          # publish this version at the next get_table (source rebuilt mid-run)
        self.responses.update({"daily": self._daily, "hr_lines": self._lines, "hr_order_lines": self._orders,
                               "hr_day_totals": self._totals, "completion": [{"n": 1}],
                               "profile": [{"n_rows": 100, "min_date": date(2026, 1, 1), "max_date": Y}],
                               **PASSING_VALIDATION})

    def publish(self, lines):
        self.clock += timedelta(minutes=10)
        self.versions.append((self.clock, [dict(x) for x in lines]))

    def get_table(self, name):
        if self.flip_on_get_table is not None and self.versions:
            nxt, self.flip_on_get_table = self.flip_on_get_table, None
            t = super().get_table(name)
            t.modified = self.versions[-1][0]
            self.publish(nxt)
            return t
        t = super().get_table(name)
        t.modified = self.versions[-1][0] if self.versions else None
        return t

    @staticmethod
    def _p(cfg) -> dict:
        return {n: v for n, _, v in (cfg.get("params") or [])}

    def _version(self, p) -> list[dict]:
        asof = p.get("asof")
        if asof is None:
            return self.versions[-1][1] if self.versions else []
        got = [lines for ts, lines in self.versions if ts <= asof]
        return got[-1] if got else []

    @staticmethod
    def _valid(x) -> bool:
        return x["sku"] is not None and x["fc"] is not None and x["qty"] is not None and x["qty"] >= 0

    def _daily(self, cfg):
        p = self._p(cfg)
        agg: dict = {}
        for x in self._version({}):
            if not (p["start"] <= x["d"] <= p["end"]) or not self._valid(x):
                continue
            agg.setdefault((x["d"], x["sku"], x["fc"]), []).append(x)
        out = []
        for (d, s, f), xs in sorted(agg.items()):
            withv = [x for x in xs if x["oh"] is not None]
            out.append({"order_date": d, "sku_id": s, "fc_id": f, "qty": sum(x["qty"] for x in xs),
                        "n_orders": len({x["so"] for x in xs if x["so"]}), "avg_unit_price": 10.0, "avg_discount_rate": None,
                        "promo_share": None, "voucher_share": None, "max_source_updated_at": None, "max_batch_id": None,
                        "n_rows": len(xs), "open_hours_null_rows": len(xs) - len(withv),
                        "open_hours_min": min((x["oh"] for x in withv), default=None),
                        "open_hours_max": max((x["oh"] for x in withv), default=None),
                        "open_hours_items": len({x["item"] for x in withv}),
                        "open_hours_item_values": len({(x["item"], x["oh"]) for x in withv if x["item"]}),
                        "open_hours_no_item_rows": sum(1 for x in withv if not x["item"])})
        if self.exact_dups:
            out.append({"_kind": "TOTAL_READ", "_reason": str(self.exact_dups), "qty": sum(r["qty"] for r in out),
                        "n_rows": sum(r["n_rows"] for r in out)})
        return out

    @staticmethod
    def _line(x) -> dict:
        return {"order_date": x["d"], "order_id": x["so"], "sku_id": x["sku"], "fc_id": x["fc"], "qty": x["qty"],
                "product_id": x["pid"], "item_code": x["item"], "order_status": x["st"]}

    def _lines(self, cfg):
        p = self._p(cfg)
        keys = set(p["keys"])
        return [self._line(x) for x in self._version(p) if f'{x["d"]}|{x["sku"]}|{x["fc"]}' in keys and self._valid(x)]

    def _orders(self, cfg):
        p = self._p(cfg)
        return [self._line(x) for x in self._version(p) if x["so"] in p["ids"] and self._valid(x)]

    def _totals(self, cfg):
        p = self._p(cfg)
        agg: dict = {}
        for x in self._version({}):
            if p["start"] <= x["d"] <= p["end"] and self._valid(x):
                agg[(x["d"], x["sku"], x["fc"])] = agg.get((x["d"], x["sku"], x["fc"]), 0) + x["qty"]
        days: dict = {}
        for (d, s, f), q in agg.items():
            days.setdefault(d, []).append((s, f, q))
        return [{"d": d, "keys": len(v), "qty": sum(q for _, _, q in v), "fp": source_lines.day_fp_python(v)}
                for d, v in sorted(days.items())]


def _production(src, dataset="sales", table="orders"):
    connector.set_client_factory(src)
    ss.update("bigquery", {"dataset_id": dataset, "source_table": table, "location": "asia-southeast1",
                           "partition_column": "", "field_mapping": FM, "reference_mapping": REF,
                           "completion_table": "done", "completion_date_column": "d"})
    connector.test_connection()
    ss.update("bigquery", {"schema_snapshot": connector.read_schema()["columns"]})
    connector.profile(7)
    assert connector.validate_source()["passed"]
    ss.update("bigquery", {"production_enabled": True})
    ss.update("general", {"active_source": "BIGQUERY"})


def _stored(scope=SCOPE) -> dict:
    with db.read() as c:
        return {(r[0], r[1], r[2]): (r[3], r[4], r[5], r[6], r[7]) for r in c.execute(
            "SELECT order_date, sku_id, fc_id, qty, n_orders, open_hours, open_hours_status, loaded_at FROM demand_daily "
            "WHERE scope_key=?", (scope,))}


def _values(scope=SCOPE) -> dict:
    return {k: v[:4] for k, v in _stored(scope).items()}


def _holds(status=None) -> list[dict]:
    with db.read() as c:
        q = "SELECT * FROM demand_held_lines" + (" WHERE status=?" if status else "") + " ORDER BY detected_at, rowid"
        return db.rows(c, q, (status,) if status else ())


def _count(t) -> int:
    with db.read() as c:
        return c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]


def _k(d, sku, fc="F1"):
    return str(d), sku, fc


def _backfill(start, end):
    from app import sync
    pv = sync.backfill_preview(str(start), str(end))
    assert pv["status"] == "READY", pv
    return pv, sync.run_d1_sync("BF", backfill_start=str(start), backfill_end=str(end), backfill_preview_id=pv["preview_id"])


D = Y - timedelta(days=1)            # a day inside the next regular D-1 window


@pytest.fixture
def src(client):
    s = Source()
    _production(s)
    return s


# ============================================================ 1, 2, 4: a cancellation never reduces the stored demand
def test_a_cancelled_order_keeps_the_gross_demand_in_the_window_and_is_logged(src):
    from app import sync
    src.publish([L(D, "O1", "A", 5), L(D, "O2", "A", 3), L(Y, "O9", "B", 1)])
    sync.run_d1_sync("J1")                                                       # full first load
    assert _values()[_k(D, "A")][:2] == (8.0, 2)
    src.publish([L(D, "O1", "A", 5), L(Y, "O9", "B", 1)])                        # O2 cancelled: all its lines leave
    res = sync.run_d1_sync("J2")
    assert _values()[_k(D, "A")][:2] == (8.0, 2)                                # gross demand kept (8, both orders)
    h = _holds("ACTIVE")
    assert [(x["order_date"], x["sku_id"], x["order_id"], x["qty"], x["cause"]) for x in h] == [(str(D), "A", "O2", 3.0, "ORDER_GONE")]
    s = res["history_sync"]
    assert s["holds_new"] == 1 and s["units_by_cause"]["ORDER_GONE"] == 3.0 and s["evidence"]["keys_with_evidence"] == 1
    # the source returns 5 + the held 3 = the stored 8: the write reconciles exactly
    assert res["series_days_written"] == 2


def test_a_key_the_source_dropped_entirely_is_kept_not_deleted(src):
    from app import sync
    src.publish([L(D, "O1", "GONE", 4), L(D, "O2", "GONE", 2, item="GONE.2"), L(Y, "O9", "B", 1)])
    sync.run_d1_sync("J1")
    src.publish([L(Y, "O9", "B", 1)])
    sync.run_d1_sync("J2")
    assert _values()[_k(D, "GONE")][:2] == (6.0, 2)                              # kept with both orders
    assert sorted((x["order_id"], x["qty"]) for x in _holds("ACTIVE")) == [("O1", 4.0), ("O2", 2.0)]
    with db.read() as c:   # nothing deleted: no DELETE in the change log of this run
        assert not c.execute("SELECT 1 FROM demand_change_log WHERE action='DELETE'").fetchone()


# ============================================================ 3: quantity changes of the same line
def test_a_bigger_quantity_is_taken_a_smaller_one_is_held_for_review(src):
    from app import sync
    src.publish([L(D, "O1", "A", 5), L(D, "O2", "B", 5), L(Y, "O9", "C", 1)])
    sync.run_d1_sync("J1")
    src.publish([L(D, "O1", "A", 7), L(D, "O2", "B", 4), L(Y, "O9", "C", 1)])
    res = sync.run_d1_sync("J2")
    v = _values()
    assert v[_k(D, "A")][0] == 7.0                                               # increase applied as the source has it
    assert v[_k(D, "B")][0] == 5.0                                               # decrease of the same line held
    assert [(x["sku_id"], x["qty"], x["cause"]) for x in _holds("ACTIVE")] == [("B", 1.0, "QTY_REDUCED")]
    assert res["history_sync"]["units_by_cause"]["QTY_INCREASED"] == 2.0


# ============================================================ 5, 18: incomplete or moving source - nothing written
def test_an_empty_read_or_a_source_rebuilt_during_the_read_writes_nothing(src):
    from app import sync
    src.publish([L(D, "O1", "A", 5), L(Y, "O9", "B", 1)])
    sync.run_d1_sync("J1")
    before, runs, logs = _stored(), _count("demand_sync_runs"), _count("demand_change_log")
    src.publish([])                                                              # table being rebuilt: nothing read
    with pytest.raises(sync.Retryable) as e:
        sync.run_d1_sync("J2")
    assert e.value.code == "SOURCE_INCOMPLETE"
    src.publish([L(D, "O1", "A", 5), L(Y, "O9", "B", 2)])
    src.flip_on_get_table = [L(D, "O1", "A", 6), L(Y, "O9", "B", 2)]             # rebuilt between two reads of one run
    with pytest.raises(sync.Retryable) as e:
        sync.run_d1_sync("J3")
    assert e.value.code == "SOURCE_INCOMPLETE" and "SOURCE_CHANGED_DURING_READ" in str(e.value)
    assert _stored() == before and _count("demand_sync_runs") == runs and _count("demand_change_log") == logs
    res = sync.run_d1_sync("J4")                                                 # a stable version: written
    assert res["status"] == "SUCCEEDED" and _values()[_k(D, "A")][0] == 6.0


def test_a_day_missing_from_an_incomplete_source_is_kept_and_heals_when_it_comes_back(src):
    from app import sync
    src.publish([L(D, "O1", "A", 5), L(D, "O2", "A", 1), L(Y, "O9", "B", 1)])
    sync.run_d1_sync("J1")
    src.publish([L(Y, "O9", "B", 1)])                                            # day D missing (incomplete source)
    sync.run_d1_sync("J2")
    assert _values()[_k(D, "A")][0] == 6.0 and len(_holds("ACTIVE")) == 2       # not deleted
    src.publish([L(D, "O1", "A", 5), L(D, "O2", "A", 1), L(Y, "O9", "B", 1)])    # the day is back
    res = sync.run_d1_sync("J3")
    assert _values()[_k(D, "A")][0] == 6.0                                      # counted once
    assert not _holds("ACTIVE") and {x["release_reason"] for x in _holds("RELEASED")} == {"REAPPEARED"}
    assert res["history_sync"]["holds_released_by_reason"] == {"REAPPEARED": 2}


# ============================================================ 6, 7, 8: kinds, idempotency, repeated updates
def test_new_updated_and_held_keys_are_told_apart_and_a_second_run_changes_nothing(src):
    from app import sync
    src.publish([L(D, "O1", "A", 5), L(D, "O2", "B", 2), L(Y, "O9", "C", 1)])
    sync.run_d1_sync("J1")
    src.publish([L(D, "O1", "A", 7), L(D, "O3", "N", 4), L(Y, "O9", "C", 1)])    # A up, B gone, N new
    res = sync.run_d1_sync("J2")
    run = res["load_id"]
    with db.read() as c:
        kinds = {(r[0], r[1]): r[2] for r in c.execute("SELECT order_date, sku_id, kind FROM demand_sync_run_keys WHERE run_id=?",
                                                       (run,))}
        actions = {(r[0], r[1]): r[2] for r in c.execute("SELECT order_date, sku_id, action FROM demand_change_log WHERE run_id=?",
                                                         (run,))}
    assert kinds == {(str(D), "A"): "UPDATED", (str(D), "B"): "HELD", (str(D), "N"): "NEW"}
    assert actions == {(str(D), "A"): "UPDATE", (str(D), "N"): "INSERT"}         # B unchanged: kept, nothing logged
    values, logs, holds = _values(), _count("demand_change_log"), _count("demand_held_lines")
    again = sync.run_d1_sync("J3")                                               # same source version
    assert _values() == values and _count("demand_change_log") == logs and _count("demand_held_lines") == holds
    assert again["history_sync"]["holds_new"] == 0 and again["history_sync"]["keys_changed"] == {"HELD_UNCHANGED": 1}


def test_the_same_key_updated_over_several_runs_never_double_counts(src):
    from app import sync
    src.publish([L(D, "O1", "A", 5), L(D, "O2", "A", 3), L(Y, "O9", "C", 1)])
    sync.run_d1_sync("J1")
    src.publish([L(D, "O1", "A", 5), L(Y, "O9", "C", 1)])                        # O2 cancelled
    sync.run_d1_sync("J2")
    src.publish([L(D, "O1", "A", 5), L(D, "O3", "A", 2), L(Y, "O9", "C", 1)])    # O3 late
    sync.run_d1_sync("J3")
    assert _values()[_k(D, "A")][:2] == (10.0, 3)
    src.publish([L(D, "O1", "A", 5), L(D, "O2", "A", 3), L(D, "O3", "A", 2), L(Y, "O9", "C", 1)])   # O2 back
    sync.run_d1_sync("J4")
    assert _values()[_k(D, "A")][:2] == (10.0, 3) and not _holds("ACTIVE")       # = the source, nothing twice


# ============================================================ 9: re-attribution (FC / SKU) - never from the SKU suffix
def test_a_line_moved_to_another_fc_or_sku_is_a_move_not_a_hold(src):
    from app import sync
    src.publish([L(D, "O1", "A", 5, item="A.2"), L(D, "O2", "A", 3), L(Y, "O9", "C", 1)])
    sync.run_d1_sync("J1")
    # O1 now ships from F2 (its item code still ends with .2: the FC comes from fc_code only); O2 re-coded to SKU B
    src.publish([L(D, "O1", "A", 5, fc="F2", item="A.2"), L(D, "O2", "B", 3, pid="P-A"), L(Y, "O9", "C", 1)])
    res = sync.run_d1_sync("J2")
    v = _values()
    assert _k(D, "A") not in v and v[_k(D, "A", "F2")][0] == 5.0 and v[_k(D, "B")][0] == 3.0
    assert not _holds("ACTIVE") and res["history_sync"]["units_by_cause"]["MOVED_OUT"] == 8.0
    assert all(fc in ("F1", "F2") for _, _, fc in v)                             # never a suffix-derived FC


# ============================================================ 10, 11, 12: pending orders, item code, duplicates
def test_wait_to_confirm_without_code_loads_is_confirmed_or_kept(src):
    from app import sync
    src.publish([L(D, None, "W", 4, st="WAIT_TO_CONFIRM"), L(D, None, "W", 4, st="WAIT_TO_CONFIRM", item="W.2"),
                 L(D, None, "V", 2, st="WAIT_TO_CONFIRM"), L(Y, "O9", "C", 1)])
    res = sync.run_d1_sync("J1")
    assert res["status"] == "SUCCEEDED" and _values()[_k(D, "W")][:2] == (8.0, 0)   # no code: valid, 0 coded orders
    # W: one request confirmed (a coded order of the same product / item), one still pending; V: rejected (gone)
    src.publish([L(D, "SO1", "W", 4, st="CONFIRMED"), L(D, None, "W", 4, st="WAIT_TO_CONFIRM", item="W.2"),
                 L(Y, "O9", "C", 1)])
    res = sync.run_d1_sync("J2")
    v = _values()
    assert v[_k(D, "W")][:2] == (8.0, 1) and v[_k(D, "V")][0] == 2.0
    assert [(x["sku_id"], x["cause"], x["order_id"]) for x in _holds("ACTIVE")] == [("V", "PENDING_GONE", None)]
    assert "PENDING_CONFIRMED" in res["history_sync"]["units_by_cause"]


def test_item_code_is_neither_grain_nor_duplicate_criterion_and_exact_duplicates_still_block(src):
    from app import sync
    assert connector.DUP_NOT_COMPARED_FIELDS == ("item_code",) and connector.PENDING_STATUSES == ("WAIT_TO_CONFIRM",)
    src.publish([L(D, "O1", "A", 5, item="A.1"), L(D, "O1", "A", 2, item="A.3"), L(Y, "O9", "C", 1)])
    sync.run_d1_sync("J1")
    assert _values()[_k(D, "A")][:2] == (7.0, 1)                                # one SKU x FC x day row, one order
    src.publish([L(D, "O1", "A", 5, item="A.1"), L(Y, "O9", "C", 1)])            # the A.3 line left
    sync.run_d1_sync("J2")
    h = _holds("ACTIVE")
    assert [(x["order_date"], x["sku_id"], x["fc_id"], x["item_code"], x["cause"]) for x in h] == [(str(D), "A", "F1", "A.3", "LINE_GONE")]
    before = _stored()
    src.exact_dups = 2                                                           # non-pending exact duplicates
    with pytest.raises(AppError) as e:
        sync.run_d1_sync("J3")
    assert e.value.code == "BQ_DATA_DUPLICATES" and _stored() == before         # BLOCK: nothing written


# ============================================================ 13: open hours are never invented
def test_missing_open_hours_stay_missing_and_a_held_row_keeps_its_stored_hours(src):
    from app import sync
    src.publish([L(D, "O1", "A", 5, oh=None), L(D, "O2", "H", 3, oh=12.5), L(Y, "O9", "C", 1)])
    sync.run_d1_sync("J1")
    v = _stored()
    assert v[_k(D, "A")][2:4] == (None, "MISSING") and v[_k(D, "H")][2:4] == (12.5, "OK")
    src.publish([L(D, "O1", "A", 5, oh=None), L(Y, "O9", "C", 1)])               # H dropped by the source
    sync.run_d1_sync("J2")
    v = _stored()
    assert v[_k(D, "A")][2:4] == (None, "MISSING") and v[_k(D, "H")][:4] == (3.0, 1, 12.5, "OK")


# ============================================================ 14: the owner's six-key MAX rule keeps applying
def test_a_history_backfill_rewrites_only_changed_rows_so_the_six_key_rule_still_applies(client):
    from app import sync
    from app.data import open_hours_override as ovr
    s = Source()
    lines = [L(OLD, "X1", "OTHER", 2, fc="HN")]
    for d, sku, fc, qty, n, items in ovr.APPROVED_KEYS:
        its = sorted(items.items())
        q = [int(qty) // n] * n
        q[0] += int(qty) - sum(q)
        lines += [L(date.fromisoformat(d), f"SO-{sku}-{i}", sku, q[i], fc=fc, item=its[i % 2][0], oh=its[i % 2][1])
                  for i in range(n)]
    lines += [L(date(2026, 2, 9), "Z1", "MEDX.OTHER", 2, fc="HN"), L(Y, "O9", "C", 1)]
    s.publish(lines)
    _production(s, dataset="gold_buymed_vn2", table="demand_planing_lightgbm")
    sync.run_d1_sync("J1")
    with db.tx() as c:   # the production state the owner approved: the six rows written by the 21/10 backfill
        for d, sku, fc, *_ in ovr.APPROVED_KEYS:
            c.execute("UPDATE demand_daily SET loaded_at=? WHERE scope_key=? AND order_date=? AND sku_id=? AND fc_id=?",
                      (ovr.APPROVED_LOADED_AT, ovr.SCOPE_KEY, d, sku, fc))
    with db.read() as c:
        assert len(ovr.resolve(c, ovr.SCOPE_KEY, "2026-01-01", str(Y))["applied"]) == 6
    s.publish([x if (x["d"], x["sku"]) != (date(2026, 2, 9), "MEDX.OTHER") else {**x, "qty": 7} for x in lines])
    pv, res = _backfill(date(2026, 2, 9), date(2026, 2, 9))
    assert res["status"] == "SUCCEEDED" and _values(ovr.SCOPE_KEY)[("2026-02-09", "MEDX.OTHER", "HN")][0] == 7.0
    with db.read() as c:
        r = ovr.resolve(c, ovr.SCOPE_KEY, "2026-01-01", str(Y))
    assert len(r["applied"]) == 6 and not r["not_applied"]                       # unchanged rows were not rewritten
    st = _stored(ovr.SCOPE_KEY)
    assert all(st[(d, sku, fc)][3:] == ("MULTI_ITEM", ovr.APPROVED_LOADED_AT) for d, sku, fc, *_ in ovr.APPROVED_KEYS)
    assert all(st[(d, sku, fc)][2] is None for d, sku, fc, *_ in ovr.APPROVED_KEYS)   # never a filled value


# ============================================================ 15, 20: other data, training and forecasts untouched
def test_other_scopes_training_runs_and_forecasts_are_never_touched(src):
    from app import sync
    from app.data.demo import create_demo_batch
    b = create_demo_batch(days=40, n_skus=3, seed=1)
    with db.read() as c:
        demo = c.execute("SELECT COUNT(*), TOTAL(qty), MAX(loaded_at) FROM demand_daily WHERE scope_key=?",
                         (b["batch_id"],)).fetchone()
    counts = {t: _count(t) for t in ("training_runs", "forecast_runs", "forecast_values", "actual_finals", "d0_snapshots")}
    src.publish([L(D, "O1", "A", 5), L(D, "O2", "A", 3), L(OLD, "O5", "A", 2), L(Y, "O9", "C", 1)])
    sync.run_d1_sync("J1")
    src.publish([L(D, "O1", "A", 5), L(OLD, "O5", "A", 4), L(Y, "O9", "C", 1)])
    sync.run_d1_sync("J2")
    pv, res = _backfill(OLD, OLD)
    hs.rollback(res["load_id"], apply=True)
    with db.read() as c:
        assert c.execute("SELECT COUNT(*), TOTAL(qty), MAX(loaded_at) FROM demand_daily WHERE scope_key=?",
                         (b["batch_id"],)).fetchone() == demo
        assert not c.execute("SELECT 1 FROM job_runs WHERE job_type='TRAIN_PUBLISH'").fetchone()
    counts.pop("actual_finals")
    assert {t: _count(t) for t in counts} == counts                               # no training, no forecast, no D0


# ============================================================ 16: rollback restores exactly
def test_rollback_restores_the_rows_exactly_and_refuses_after_a_later_change(src):
    from app import sync
    src.publish([L(OLD, "O1", "A", 5), L(OLD, "O2", "A", 3), L(OLD, "O3", "B", 1), L(Y, "O9", "C", 1)])
    sync.run_d1_sync("J1")
    before = _stored()
    src.publish([L(OLD, "O1", "A", 9), L(OLD, "O3", "B", 1), L(OLD, "O4", "N", 2), L(Y, "O9", "C", 1)])
    pv, res = _backfill(OLD, OLD)
    run = res["load_id"]
    assert _values()[_k(OLD, "A")][0] == 12.0 and _values()[_k(OLD, "N")][0] == 2.0   # 9 + O2 held 3; N new
    dry = hs.rollback(run)
    assert dry["status"] == "READY" and dry["applied"] is False and dry["entries"] == 2 and dry["holds_to_release"] == 1
    out = hs.rollback(run, apply=True)
    assert out["applied"] and out["backup"].startswith("backup-") and _stored() == before   # loaded_at included
    assert {x["release_reason"] for x in _holds("RELEASED")} == {"ROLLBACK"} and not _holds("ACTIVE")
    with pytest.raises(AppError) as e:                                             # a run is rolled back once
        hs.rollback(run, apply=True)
    assert e.value.code == "SYNC_ROLLBACK_REFUSED"
    pv, res2 = _backfill(OLD, OLD)                                                 # apply again, then change a key later
    src.publish([L(OLD, "O1", "A", 9), L(OLD, "O3", "B", 1), L(OLD, "O4", "N", 5), L(Y, "O9", "C", 1)])
    _backfill(OLD, OLD)
    assert hs.rollback(res2["load_id"])["status"] == "REFUSED"


# ============================================================ 17: an older training snapshot can be reproduced
def test_the_data_of_an_older_training_can_be_rebuilt_after_history_changes(src):
    from app import sync
    from app.data import identity
    src.publish([L(OLD, "O1", "A", 5), L(D, "O2", "B", 3), L(Y, "O9", "C", 1)])
    sync.run_d1_sync("J1")
    cols = identity.CONTENT_COLUMNS
    with db.read() as c:
        then = identity.window_identity(SCOPE, str(OLD), str(Y), c, columns=cols)
    t0 = timeutil.now_iso()
    later = datetime.fromisoformat(t0) + timedelta(seconds=5)          # every later write is strictly after t0
    timeutil.set_now_override(lambda: later)
    src.publish([L(OLD, "O1", "A", 8), L(D, "O2", "B", 3), L(D, "O3", "B", 1), L(Y, "O9", "C", 1)])
    sync.run_d1_sync("J2")
    _backfill(OLD, OLD)
    timeutil.set_now_override(None)
    with db.read() as c:
        now_ident = identity.window_identity(SCOPE, str(OLD), str(Y), c, columns=cols, days=identity.day_hashes(SCOPE, c, cache=False))
    assert now_ident["sha256"] != then["sha256"]                                   # a new training sees the reconciled data
    assert hs.window_identity_as_of(SCOPE, str(OLD), str(Y), t0, cols)["sha256"] == then["sha256"]   # the old one is rebuilt


# ============================================================ 19: a failure in the middle of the write leaves nothing
def test_a_failure_inside_the_write_leaves_no_half_written_data(src, monkeypatch):
    from app import sync
    src.publish([L(D, "O1", "A", 5), L(D, "O2", "A", 3), L(Y, "O9", "C", 1)])
    sync.run_d1_sync("J1")
    before = _stored()
    counts = {t: _count(t) for t in ("demand_held_lines", "demand_change_log", "demand_sync_runs", "demand_sync_run_keys")}
    src.publish([L(D, "O1", "A", 5), L(D, "O4", "N", 2), L(Y, "O9", "C", 1)])
    real = hs._insert

    def boom(c, batch):
        real(c, batch[:1])
        raise RuntimeError("disk full")
    monkeypatch.setattr(hs, "_insert", boom)
    with pytest.raises(RuntimeError):
        sync.run_d1_sync("J2")
    assert _stored() == before and {t: _count(t) for t in counts} == counts


# ============================================================ history outside the window: detected, then reconciled
def test_the_daily_check_detects_a_change_of_an_old_day_and_a_backfill_reconciles_it(src):
    from app import sync
    src.publish([L(OLD, "O1", "A", 5), L(OLD, "O2", "A", 3), L(OLD, "O7", "K", 1), L(Y, "O9", "C", 1)])
    sync.run_d1_sync("J1")
    src.publish([L(OLD, "O1", "A", 5), L(OLD, "O7", "K", 1), L(OLD, "O8", "L", 6), L(Y, "O9", "C", 1)])  # O2 cancelled, O8 late
    res = sync.run_d1_sync("J2")
    hc = res["history_check"]
    assert hc["status"] == "DIFF" and hc["days_diff"] == 1 and hc["first_diff_day"] == str(OLD)
    assert _values()[_k(OLD, "A")][0] == 8.0 and _k(OLD, "L") not in _values()   # the regular load never touches it
    with db.read() as c:
        assert c.execute("SELECT status FROM source_day_checks WHERE order_date=?", (str(OLD),)).fetchone()[0] == "DIFF"
        assert c.execute("SELECT 1 FROM alerts WHERE code='HISTORY_SOURCE_CHANGED'").fetchone()
    loaded_k = _stored()[_k(OLD, "K")][4]
    pv, out = _backfill(OLD, OLD)
    assert pv["history_sync"]["holds_new_by_cause"] == {"ORDER_GONE": 1} and pv["history_sync"]["keys_changed"]["NEW"] == 1
    v = _values()
    assert v[_k(OLD, "A")][0] == 8.0 and v[_k(OLD, "L")][0] == 6.0                # cancellation kept, late order taken
    assert _stored()[_k(OLD, "K")][4] == loaded_k                                 # unchanged row not rewritten
    res3 = sync.run_d1_sync("J3")
    assert res3["history_check"]["status"] == "MATCH"


def test_the_backfill_refuses_a_plan_that_changed_after_its_preview(src):
    from app import sync
    src.publish([L(OLD, "O1", "A", 5), L(OLD, "O2", "A", 3), L(Y, "O9", "C", 1)])
    sync.run_d1_sync("J1")
    src.publish([L(OLD, "O1", "A", 5), L(Y, "O9", "C", 1)])
    pv = sync.backfill_preview(str(OLD), str(OLD))
    src.publish([L(OLD, "O1", "A", 5), L(OLD, "O2", "A", 2), L(Y, "O9", "C", 1)])  # same totals per key? no: 7 vs 5
    with pytest.raises(AppError) as e:
        sync.run_d1_sync("BF", backfill_start=str(OLD), backfill_end=str(OLD), backfill_preview_id=pv["preview_id"])
    assert e.value.code == "BACKFILL_PREVIEW_REQUIRED"
    assert _values()[_k(OLD, "A")][0] == 8.0 and not _holds()


# ============================================================ finalized days are marked, the frozen actual is kept
def test_a_change_of_a_finalized_day_is_written_marked_and_the_frozen_actual_stays(src):
    from app import actual_final, data_checks, paths, sync
    src.publish([L(OLD, "O1", "A", 5), L(Y, "O9", "C", 1)])
    sync.run_d1_sync("J1")
    with db.read() as c:
        assert actual_final.finals(c, SCOPE, [str(OLD)])[str(OLD)]["status"] == "FINALIZED"
        frozen = c.execute("SELECT total_qty, values_sha256 FROM actual_finals WHERE business_date=?", (str(OLD),)).fetchone()
    src.publish([L(OLD, "O1", "A", 5), L(OLD, "O2", "A", 4), L(Y, "O9", "C", 1)])  # a late order of a finalized day
    pv, res = _backfill(OLD, OLD)
    assert pv["history_sync"]["finalized_days_changed"] == [str(OLD)] and _values()[_k(OLD, "A")][0] == 9.0
    with db.read() as c:
        assert c.execute("SELECT finalized FROM demand_change_log WHERE run_id=?", (res["load_id"],)).fetchone()[0] == 1
        assert c.execute("SELECT total_qty, values_sha256 FROM actual_finals WHERE business_date=?", (str(OLD),)).fetchone() == frozen
    chk = {x["check"]: x for x in data_checks.run(paths.db_path())["checks"]}
    assert chk["finalized_days_changed"]["status"] == "WARN" and chk["finalized_days_changed"]["count"] == 1
    assert chk["held_lines_in_demand"]["status"] == "OK" and chk["history_sync_protection_triggers"]["status"] == "OK"


# ============================================================ owner decisions: release, FOLLOW_SOURCE
def test_an_owner_release_reduces_the_rows_is_logged_and_reversible(src):
    from app import sync
    src.publish([L(D, "O1", "A", 5), L(D, "O2", "A", 3), L(D, "O5", "G", 2), L(Y, "O9", "C", 1)])
    sync.run_d1_sync("J1")
    src.publish([L(D, "O1", "A", 5), L(Y, "O9", "C", 1)])
    sync.run_d1_sync("J2")
    before = _stored()
    dry = hs.release_holds(SCOPE, cause="ORDER_GONE")
    assert dry["applied"] is False and dry["holds"] == 2 and dry["units"] == 5.0 and _stored() == before
    out = hs.release_holds(SCOPE, cause="ORDER_GONE", sku_id="A", apply=True)
    v = _values()
    assert out["applied"] and v[_k(D, "A")][:2] == (5.0, 1) and v[_k(D, "G")][0] == 2.0
    hs.rollback(out["run_id"], apply=True)
    assert _values() == {k: x[:4] for k, x in before.items()} and len(_holds("ACTIVE")) == 2


def test_follow_source_releases_the_held_lines_of_the_keys_it_writes(src):
    from app import sync
    src.publish([L(D, "O1", "A", 5), L(D, "O2", "A", 3), L(Y, "O9", "C", 1)])
    sync.run_d1_sync("J1")
    src.publish([L(D, "O1", "A", 5), L(Y, "O9", "C", 1)])
    sync.run_d1_sync("J2")
    assert _values()[_k(D, "A")][0] == 8.0
    ss.update("data_policy", {"history_change_policy": "FOLLOW_SOURCE"})
    sync.run_d1_sync("J3")
    assert _values()[_k(D, "A")][0] == 5.0 and not _holds("ACTIVE")
    assert {x["release_reason"] for x in _holds("RELEASED")} == {"OWNER_DECISION"}


def test_the_new_tables_are_append_only():
    import sqlite3
    with db.tx() as c:
        c.execute("INSERT INTO demand_change_log(run_id, run_kind, scope_key, order_date, sku_id, fc_id, action, qty_after, "
                  "after_json, at) VALUES ('R', 'D1_SYNC', 'S', '2026-01-01', 'A', 'F', 'INSERT', 1, '{}', 'x')")
        c.execute("INSERT INTO demand_held_lines(id, scope_key, order_date, sku_id, fc_id, qty, cause, status, detected_run, "
                  "detected_at) VALUES ('H', 'S', '2026-01-01', 'A', 'F', 1, 'ORDER_GONE', 'ACTIVE', 'R', 'x')")
    for sql in ("UPDATE demand_change_log SET qty_after = 2", "DELETE FROM demand_change_log",
                "DELETE FROM demand_held_lines", "UPDATE demand_held_lines SET qty = 5",
                "UPDATE demand_held_lines SET status='RELEASED', released_run='R2', released_at='y', release_reason='BAD'"):
        with pytest.raises(sqlite3.IntegrityError):
            with db.tx() as c:
                c.execute(sql)
    with db.tx() as c:   # the one allowed change: ACTIVE -> RELEASED, once
        c.execute("UPDATE demand_held_lines SET status='RELEASED', released_run='R2', released_at='y', "
                  "release_reason='OWNER_DECISION' WHERE id='H'")
    with pytest.raises(sqlite3.IntegrityError):
        with db.tx() as c:
            c.execute("UPDATE demand_held_lines SET status='ACTIVE', released_run=NULL, released_at=NULL, release_reason=NULL")


# ============================================================ the classification itself (pure function)
def _ln(so, qty, sku="A", fc="F1", d="2026-10-01", pid="P1", item="A.1", st="COMPLETED"):
    return {"order_date": d, "order_id": so, "sku_id": sku, "fc_id": fc, "qty": qty, "product_id": pid, "item_code": item,
            "order_status": st}


K = ("2026-10-01", "A", "F1")


def test_classify_status_change_is_no_quantity_effect_and_no_hold():
    r = hs.classify_key(K, [_ln("O1", 5, st="DELIVERING")], [_ln("O1", 5, st="COMPLETED")], {}, [], 0.0)
    assert r["new_holds"] == [] and "STATUS_ONLY" in r["causes"]


def test_classify_without_base_version_keeps_the_net_decrease():
    r = hs.classify_key(K, None, [_ln("O1", 5)], {}, [], 3.0)
    assert [(h["cause"], h["qty"], h["order_id"]) for h in r["new_holds"]] == [("NO_EVIDENCE", 3.0, None)]


def test_classify_order_gone_line_gone_and_move():
    prev = [_ln("O1", 5), _ln("O2", 3, pid="P2", item="A.2"), _ln("O3", 1, pid="P3")]
    now = []
    orders_now = {"O2": [_ln("O2", 4, pid="P9", sku="Z")],                        # the order lives on, not this product
                  "O3": [_ln("O3", 1, pid="P3", fc="F2")]}                       # same product, other FC: moved
    r = hs.classify_key(K, prev, now, orders_now, [], 9.0, dest_new=lambda k, y: k == ("2026-10-01", "A", "F2"))
    assert sorted((h["order_id"], h["cause"], h["qty"]) for h in r["new_holds"]) == [("O1", "ORDER_GONE", 5.0),
                                                                                      ("O2", "LINE_GONE", 3.0)]
    assert r["causes"]["MOVED_OUT"] == 1.0 and r["moves"][0]["to"] == "2026-10-01|A|F2"
    # the same situation without a proven NEW destination line: held, never silently moved
    r = hs.classify_key(K, prev, now, orders_now, [], 9.0)
    assert sorted((h["order_id"], h["cause"]) for h in r["new_holds"]) == [("O1", "ORDER_GONE"), ("O2", "LINE_GONE"),
                                                                          ("O3", "LINE_GONE")]


def test_classify_releases_a_held_line_that_came_back_once():
    held = [{"id": "H1", "order_id": "O2", "product_id": "P1", "item_code": "A.1", "qty": 3.0, "cause": "ORDER_GONE"}]
    r = hs.classify_key(K, [], [_ln("O1", 5), _ln("O2", 3)], {}, held, 0.0, compare=False)
    assert r["release"] == [("H1", "REAPPEARED")] and r["new_holds"] == []


# ============================================================ independent data review of 22/10 (B1, S2-S5, S7, S8)
def test_thousands_of_held_lines_in_one_run_get_unique_ids(src):
    from app import sync
    src.publish([L(D, f"O{i}", f"S{i % 400}", 1, item=f"S{i % 400}.{i}") for i in range(2500)] + [L(Y, "O9", "C", 1)])
    sync.run_d1_sync("J1")
    src.publish([L(Y, "O9", "C", 1)])                                              # every line of day D leaves
    res = sync.run_d1_sync("J2")
    hl = _holds("ACTIVE")
    assert res["history_sync"]["holds_new"] == 2500 and len({h["id"] for h in hl}) == 2500
    assert all(h["id"].startswith(res["load_id"] + "-H") for h in hl)


def test_a_no_evidence_hold_is_released_when_the_source_is_back_to_its_level(src, monkeypatch):
    from app import sync
    src.publish([L(D, "O1", "A", 5), L(D, "O2", "A", 3), L(Y, "O9", "C", 1)])
    sync.run_d1_sync("J1")
    src.publish([L(D, "O1", "A", 5), L(Y, "O9", "C", 1)])
    with monkeypatch.context() as m:                                               # no line evidence for this run
        m.setattr(source_lines, "available", lambda snap: (False, "TEST"))
        sync.run_d1_sync("J2")
    assert [(h["cause"], h["qty"], h["order_id"]) for h in _holds("ACTIVE")] == [("NO_EVIDENCE", 3.0, None)]
    assert _values()[_k(D, "A")][:2] == (8.0, 2)                                   # order count kept with the units
    src.publish([L(D, "O1", "A", 5), L(D, "O2", "A", 3), L(Y, "O9", "C", 1)])      # the source is back
    res = sync.run_d1_sync("J3")
    assert _values()[_k(D, "A")][0] == 8.0 and not _holds("ACTIVE")               # not 11: counted once
    assert res["history_sync"]["units_by_cause"]["REAPPEARED_KEY_LEVEL"] == 3.0


def test_a_pending_request_that_comes_back_is_released_not_doubled(src):
    from app import sync
    src.publish([L(D, None, "W", 4, st="WAIT_TO_CONFIRM"), L(D, "O1", "W", 2), L(Y, "O9", "C", 1)])
    sync.run_d1_sync("J1")
    src.publish([L(D, "O1", "W", 2), L(Y, "O9", "C", 1)])                          # the request leaves
    sync.run_d1_sync("J2")
    assert _values()[_k(D, "W")][0] == 6.0 and len(_holds("ACTIVE")) == 1
    src.publish([L(D, None, "W", 4, st="WAIT_TO_CONFIRM"), L(D, "O1", "W", 2), L(Y, "O9", "C", 1)])   # and is back
    sync.run_d1_sync("J3")
    assert _values()[_k(D, "W")][0] == 6.0 and not _holds("ACTIVE")


def test_a_reduced_quantity_that_grows_again_releases_its_hold(src):
    from app import sync
    src.publish([L(D, "O1", "A", 5), L(Y, "O9", "C", 1)])
    sync.run_d1_sync("J1")
    src.publish([L(D, "O1", "A", 4), L(Y, "O9", "C", 1)])
    sync.run_d1_sync("J2")
    assert _values()[_k(D, "A")][0] == 5.0 and [h["cause"] for h in _holds("ACTIVE")] == ["QTY_REDUCED"]
    src.publish([L(D, "O1", "A", 5), L(Y, "O9", "C", 1)])
    sync.run_d1_sync("J3")
    assert _values()[_k(D, "A")][0] == 5.0 and not _holds("ACTIVE")               # 5, not 6
    src.publish([L(D, "O1", "A", 7), L(Y, "O9", "C", 1)])                         # a real increase is taken
    sync.run_d1_sync("J4")
    assert _values()[_k(D, "A")][0] == 7.0


def test_a_split_order_with_one_part_cancelled_is_held_not_moved(src):
    from app import sync
    src.publish([L(D, "O1", "A", 3, fc="F1"), L(D, "O1", "A", 2, fc="F2"), L(Y, "O9", "C", 1)])
    sync.run_d1_sync("J1")
    src.publish([L(D, "O1", "A", 2, fc="F2"), L(Y, "O9", "C", 1)])                # the F1 part is cancelled
    res = sync.run_d1_sync("J2")
    v = _values()
    assert v[_k(D, "A", "F1")][0] == 3.0 and v[_k(D, "A", "F2")][0] == 2.0        # kept: F2 did not gain a new line
    assert [(h["fc_id"], h["cause"]) for h in _holds("ACTIVE")] == [("F1", "LINE_GONE")]
    assert "MOVED_OUT" not in res["history_sync"]["units_by_cause"]


def test_a_zero_unit_line_that_leaves_holds_nothing(src):
    from app import sync
    src.publish([L(D, "O1", "A", 5), L(D, "O2", "A", 0), L(Y, "O9", "C", 1)])
    sync.run_d1_sync("J1")
    src.publish([L(D, "O1", "A", 5), L(Y, "O9", "C", 1)])                         # only the zero line left
    res = sync.run_d1_sync("J2")
    assert res["status"] == "SUCCEEDED" and not _holds() and _values()[_k(D, "A")][0] == 5.0


def test_the_history_cli_refuses_an_older_database_and_never_migrates(tmp_path, monkeypatch, capsys):
    import sqlite3
    from app import cli
    d = tmp_path / "old"
    (d / "db").mkdir(parents=True)
    c = sqlite3.connect(d / "db" / "app.db")
    c.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)")
    c.executemany("INSERT INTO schema_migrations VALUES (?,?,?)", [(v, f"{v:04d}.sql", "x") for v in range(1, 10)])
    c.commit()
    c.close()
    monkeypatch.setenv("DF_DATA_DIR", str(d))
    for cmd in (["held-lines"], ["sync-runs"], ["sync-rollback", "--run", "X"], ["history-check"]):
        assert cli.main(cmd) == 2
        assert "schema 9" in capsys.readouterr().out
    c = sqlite3.connect(d / "db" / "app.db")
    assert c.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 9           # not migrated
    assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='demand_held_lines'").fetchone()
    c.close()


def test_a_backfill_rewrites_every_row_of_a_day_that_is_not_finalized(src, monkeypatch):
    from app import actual_final, sync
    src.publish([L(OLD, "O1", "A", 5), L(OLD, "O2", "B", 2), L(Y, "O9", "C", 1)])
    with monkeypatch.context() as m:                                               # OLD stays not finalized
        m.setattr(actual_final, "finalize_quietly", lambda *a, **k: None)
        sync.run_d1_sync("J1")
    src.publish([L(OLD, "O1", "A", 6), L(OLD, "O2", "B", 2), L(Y, "O9", "C", 1)])
    pv, res = _backfill(OLD, OLD)
    st = _stored()
    assert st[_k(OLD, "A")][0] == 6.0
    assert {st[_k(OLD, "A")][4], st[_k(OLD, "B")][4]} == {res["synced_at"]}        # one loaded_at for the day


def test_a_full_reload_that_holds_lines_raises_an_alert(src):
    from app import sync
    src.publish([L(OLD, "O1", "A", 5), L(OLD, "O2", "A", 3), L(Y, "O9", "C", 1)])
    sync.run_d1_sync("J1")
    with db.tx() as c:                         # what a mapping / range / SQL change does: the next load is a full reload
        st = json.loads(c.execute("SELECT value_json FROM sync_state WHERE name=?", (f"last_d1_sync:{SCOPE}",)).fetchone()[0])
        c.execute("UPDATE sync_state SET value_json=? WHERE name=?", (json.dumps({**st, "mapping_hash": "old"}),
                                                                       f"last_d1_sync:{SCOPE}"))
    src.publish([L(OLD, "O1", "A", 5), L(Y, "O9", "C", 1)])
    res = sync.run_d1_sync("J2")
    assert res["full_reload"] and _values()[_k(OLD, "A")][0] == 8.0
    with db.read() as c:
        assert c.execute("SELECT 1 FROM alerts WHERE code='FULL_RELOAD_HELD_LINES'").fetchone()
