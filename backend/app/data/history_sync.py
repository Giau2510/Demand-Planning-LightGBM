"""History sync of the BigQuery D-1 demand (1.2.13, owner rule of 22/10/2026).

The source table is rebuilt every morning and returns only the orders that are NOT cancelled at that moment: when an
order is cancelled (fact_order status CANCEL), every line of it leaves the source; an unconfirmed WAIT_TO_CONFIRM line
leaves it too; a change of the source's product scope adds or removes the whole history of some SKUs (read-only
evidence of 22/10/2026, docs/BIGQUERY.md section 11g). The target is the order quantity of the orders placed (gross
demand), so a stored day must not be reduced only because the source dropped a line, while late lines and real
re-attributions must be taken - on every day, not only on the few days the D-1 load re-reads.

Policy (data_policy.history_change_policy):
  KEEP_OBSERVED_LINES (default)  stored row = what the source returns now + the order lines the app has seen in the
                                 source and that later left it without a proven move ("held lines"). Additions,
                                 attribute changes and moves are taken as the source has them; nothing is reduced
                                 because a line disappeared.
  FOLLOW_SOURCE                  stored row = the source (the behaviour before 1.2.13); every held line of a written
                                 key is released (OWNER_DECISION).

Line evidence (bq/source_lines.py, BigQuery time travel, read-only): for a key the source now returns less than what
the stored row holds without its held lines, the lines of the version the row was written from ("base") are compared
with the lines now:
  same line (order, product, item, quantity)   unchanged (a status change has no quantity effect)
  same line, smaller quantity                  QTY_REDUCED held (the difference)
  line now under another SKU / FC / day        MOVED: no hold - the new key gets it from the source
  WAIT_TO_CONFIRM line replaced by a coded     PENDING_CONFIRMED: no hold (the order replaced the request)
  line of the same product in the key
  every line of the order gone                 ORDER_GONE held (a cancelled order: fact_order says CANCEL)
  the order still has other lines              LINE_GONE held (removed by the source logic, not cancelled)
  WAIT_TO_CONFIRM line gone                    PENDING_GONE held
  no usable base version (> time travel        NO_EVIDENCE held: the decrease is kept, at key level
  window, SQL source, DROP_EXACT, lines that
  do not add up to the aggregates)
A move needs the same order line (product, quantity) proven NEW in another key of the same run; otherwise the leaving
line is held. A held line that comes back is released (REAPPEARED) so it is never counted twice: a whole line by its
order / product / item in the key (back with fewer units: the difference stays QTY_REDUCED), a pending request as a new
pending line of the same product / item / quantity, a QTY_REDUCED difference when the same line grows again, a
NO_EVIDENCE hold when the key's source units are back to the level before the drop. Holds are released otherwise only
by a rollback or an explicit owner decision (release_holds). A failed evidence read (BigQuery error, cost cap, timeout)
stops the run before anything is written (fail-closed: the job retries or fails with the BigQuery error); more than
MAX_EVIDENCE_KEYS changed keys in one run stops it too (HISTORY_CHANGE_TOO_LARGE).

Every write goes through ONE transaction (sync.run_d1_sync): rows of the window replaced by the target rows, held
lines recorded / released, every changed row logged with its full before / after (demand_change_log, append-only), a
run record (demand_sync_runs) and its per-key decisions; the stored data the plan was computed on is re-checked inside
the transaction (a concurrent change -> nothing written, the job retries). A day with a FINALIZED actual is never
frozen for the demand itself: its changes are written and marked `finalized` in the log (the frozen actual - the KPI
snapshot - is never changed). rollback() restores the rows of one run exactly (loaded_at included) when nothing
changed them since. day_check() compares the stored history outside the D-1 window with the source every day.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from .. import db
from .. import settings_service as ss
from ..messages import AppError
from ..timeutil import now_iso, now_utc
from . import customers, open_hours

log = logging.getLogger("df.history_sync")

KEEP, FOLLOW = "KEEP_OBSERVED_LINES", "FOLLOW_SOURCE"
COLS = ("qty", "n_orders", "avg_unit_price", "avg_discount_rate", "promo_share", "voucher_share", "open_hours",
        "open_hours_status", "customer_count", "repeat_customer_count", "repeat_interval_days_sum")
HOLD_CAUSES = ("ORDER_GONE", "LINE_GONE", "PENDING_GONE", "QTY_REDUCED", "NO_EVIDENCE")
EPS = 1e-9
# more stored keys changed in one run than this is not reconciled automatically (memory of the PC, a partial source or a
# redefinition): the run stops before writing (HISTORY_CHANGE_TOO_LARGE)
MAX_EVIDENCE_KEYS = 50000


class StaleBase(Exception):
    """The stored data changed between the plan and the write (the caller retries; nothing was written)."""


class SourceChanged(Exception):
    """The source table got a new version while the run read it (the caller retries; nothing was written)."""


def policy() -> str:
    return ss.get("data_policy").history_change_policy


# ------------------------------------------------------------------ rows
def _f(v):
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def src_content(r: dict) -> tuple:
    """The stored content of one aggregated source row (connector._daily_sql), as the D-1 load writes it."""
    oh = open_hours.row_cell(r)
    return (float(r["qty"]), int(r["n_orders"] or 0), _f(r.get("avg_unit_price")), _f(r.get("avg_discount_rate")),
            _f(r.get("promo_share")), _f(r.get("voucher_share")), oh[0], oh[1], *customers.stored(r))


def _key(r: dict) -> tuple:
    return str(r["order_date"])[:10], r["sku_id"], r["fc_id"]


def _same(a: tuple | None, b: tuple | None) -> bool:
    """Equal contents (floats within a relative 1e-9: an average computed again by BigQuery may differ in the last bit)."""
    if a is None or b is None:
        return a is b
    for x, y in zip(a, b):
        if isinstance(x, float) or isinstance(y, float):
            if x is None or y is None:
                if x is not y:
                    return False
            elif abs(float(x) - float(y)) > 1e-9 * max(1.0, abs(float(x)), abs(float(y))):
                return False
        elif x != y:
            return False
    return True


def _row_json(key: tuple, content: tuple, loaded_at: str | None) -> str:
    return json.dumps({"order_date": key[0], "sku_id": key[1], "fc_id": key[2], **dict(zip(COLS, content)),
                       "loaded_at": loaded_at}, default=str)


def _stored_iter(c, scope_key: str, start: str, end: str | None):
    q = (f"SELECT order_date, sku_id, fc_id, {', '.join(COLS)}, loaded_at FROM demand_daily WHERE scope_key=? "
         "AND order_date >= ?" + (" AND order_date <= ?" if end else "") + " ORDER BY order_date, sku_id, fc_id")
    for r in c.execute(q, (scope_key, start, end) if end else (scope_key, start)):
        yield (r[0], r[1], r[2]), tuple(r[3:3 + len(COLS)]), r[3 + len(COLS)]


def active_holds(c, scope_key: str, start: str, end: str | None) -> dict[tuple, list[dict]]:
    q = ("SELECT * FROM demand_held_lines WHERE scope_key=? AND status='ACTIVE' AND order_date >= ?"
         + (" AND order_date <= ?" if end else ""))
    out: dict[tuple, list[dict]] = defaultdict(list)
    for h in db.rows(c, q, (scope_key, start, end) if end else (scope_key, start)):
        out[(h["order_date"], h["sku_id"], h["fc_id"])].append(h)
    return out


def _marker(c, scope_key: str, start: str, end: str | None) -> tuple:
    """Identity of the stored state of a range, cheap enough to be read again under the write lock: every write of a
    BIGQUERY scope goes through this module and leaves a run record (demand_sync_runs) and, for a changed row, a log
    entry; the row count (key index only) and the held lines of the range are checked too."""
    w = " AND order_date <= ?" if end else ""
    p = (scope_key, start, end) if end else (scope_key, start)
    n = c.execute(f"SELECT COUNT(*) FROM demand_daily WHERE scope_key=? AND order_date >= ?{w}", p).fetchone()[0]
    run = c.execute("SELECT MAX(rowid) FROM demand_sync_runs WHERE scope_key=? AND kind != 'PREVIEW'",
                    (scope_key,)).fetchone()[0]
    h = c.execute(f"SELECT COUNT(*), TOTAL(qty), MAX(detected_at), MAX(released_at) FROM demand_held_lines WHERE "
                  f"scope_key=? AND order_date >= ?{w}", p).fetchone()
    log_id = c.execute("SELECT MAX(id) FROM demand_change_log WHERE scope_key=?", (scope_key,)).fetchone()[0]
    return (n, run) + tuple(h) + (log_id,)


# ------------------------------------------------------------------ base versions (line evidence)
def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(ts)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _base_lookup(c, scope_key: str) -> tuple[dict, dict]:
    """(loaded_at -> source version of the load that wrote it, day -> version of the last matching day check)."""
    loads = {}
    for fin, ver in c.execute("SELECT finished_at, source_version FROM demand_sync_runs WHERE scope_key=? AND kind IN "
                              "('D1_SYNC','BACKFILL','HOLD_RELEASE','ROLLBACK') AND finished_at IS NOT NULL", (scope_key,)):
        loads[fin] = ver
    days = {d: (ver or vat) for d, ver, vat in c.execute(
        "SELECT order_date, source_version, verified_at FROM source_day_checks WHERE scope_key=? AND verified_at IS NOT NULL",
        (scope_key,))}
    return loads, days


def _asof(version: str | None, fallback: str | None) -> str | None:
    """Time travel timestamp of a source version: one second after its modified time (the version is current from then
    until the next rebuild); without a recorded version the time the row was written (read just before)."""
    v = _parse(version)
    if v:
        return (v + timedelta(seconds=1)).isoformat()
    f = _parse(fallback)
    return f.isoformat() if f else None


def _base_for(key: tuple, loaded_at: str | None, loads: dict, days: dict) -> str | None:
    """The source version a stored row was written from / last verified against. Every write (load, backfill) and
    every matching daily check records its day's version (source_day_checks) - that is the base. A day without such a
    record (data stored before 1.2.13, or reset by a rollback) falls back to the load that wrote the row (its
    loaded_at; one-second resolution: two loads in the same second cannot be told apart, so the day record wins)."""
    return _asof(days.get(key[0]), None) or _asof(loads.get(loaded_at), loaded_at)


# ------------------------------------------------------------------ classification (pure)
def _lid(x: dict) -> tuple:
    return x.get("order_id"), x.get("product_id"), x.get("item_code")


def _same_product(x: dict, y: dict) -> bool:
    if x.get("product_id") is not None and y.get("product_id") is not None:
        return x["product_id"] == y["product_id"]
    return x.get("sku_id") == y.get("sku_id")


def _hold(out: dict, line: dict, cause: str, qty: float) -> None:
    """Record a held line (a line of zero units holds nothing and is not recorded)."""
    if qty > EPS:
        out["new_holds"].append({**_hold_line({**line, "qty": qty}), "qty": float(qty), "cause": cause})
        out["causes"][cause] += qty


def _key_of(y: dict) -> tuple:
    return y["order_date"], y["sku_id"], y["fc_id"]


def classify_key(key: tuple, prev: list[dict] | None, now: list[dict] | None, orders_now: dict[str, list[dict]],
                 holds: list[dict], decrease: float, compare: bool = True, *, dest_new=None, src_increase: float = 0.0,
                 used_dest: set | None = None) -> dict:
    """Why the lines of one key changed: new holds, holds to release, units by cause. Pure function.
      prev        lines of the base version (None: none usable - a NO_EVIDENCE hold keeps the net decrease)
      now         lines now (None: not read)
      compare     False = only the held lines are checked (the key's units and order count did not change)
      dest_new    (key, line) -> True when that line is proven NEW in that other key of the same plan (a move needs it)
      src_increase  source units now minus the stored row without its held lines (a NO_EVIDENCE hold is released when
                    the source is back to the level it had before the drop)
      used_dest   destination lines already claimed by a move (one line is the target of one move only)"""
    out: dict = {"new_holds": [], "release": [], "causes": Counter(), "moves": []}
    dest_new = dest_new or (lambda k, y: False)
    used_dest = used_dest if used_dest is not None else set()
    now_left = list(now or [])
    whole = [h for h in holds if h.get("cause") in ("ORDER_GONE", "LINE_GONE") and h.get("order_id") is not None]
    # 0. a held whole line back in the source (same order, product, item in this key) is released - counted once; back
    #    with fewer units: the difference stays held (QTY_REDUCED); with more units: the excess is an increase
    if now is not None:
        for exact in (True, False):
            for h in list(whole):
                m = next((y for y in now_left if _lid(y) == _lid(h)
                          and (abs(y["qty"] - h["qty"]) < EPS or not exact)), None)
                if m is None:
                    continue
                now_left.remove(m)
                whole.remove(h)
                out["release"].append((h["id"], "REAPPEARED"))
                out["causes"]["REAPPEARED"] += min(h["qty"], m["qty"])
                if m["qty"] < h["qty"] - EPS:
                    _hold(out, {**h, "qty": h["qty"]}, "QTY_REDUCED", h["qty"] - m["qty"])
                elif m["qty"] > h["qty"] + EPS:
                    out["causes"]["QTY_INCREASED"] += m["qty"] - h["qty"]
    # 0b. a NO_EVIDENCE hold (key level, no line identity) is released when the source is back to its earlier level
    room = src_increase
    for h in sorted((h for h in holds if h.get("cause") == "NO_EVIDENCE"), key=lambda z: (z.get("detected_at") or "", z["id"])):
        if room > EPS and room >= h["qty"] - EPS:
            room -= h["qty"]
            out["release"].append((h["id"], "REAPPEARED"))
            out["causes"]["REAPPEARED_KEY_LEVEL"] += h["qty"]
    if not compare:
        return out
    if prev is None:
        _hold(out, {"order_id": None, "product_id": None, "item_code": None, "order_status": None}, "NO_EVIDENCE",
              decrease)
        return out
    # 1. the same line with the same quantity (its status may differ: no quantity effect)
    pool: dict[tuple, list[dict]] = defaultdict(list)
    for y in now_left:
        pool[(_lid(y), y["qty"])].append(y)
    prev_left = []
    for x in prev:
        lst = pool.get((_lid(x), x["qty"]))
        if lst:
            y = lst.pop()
            if y.get("order_status") != x.get("order_status"):
                out["causes"]["STATUS_ONLY"] += 0.0
        else:
            prev_left.append(x)
    now_left = [y for lst in pool.values() for y in lst]
    # 1b. a held pending request (no order code) back as a NEW pending line of the same product, item and quantity
    for h in [h for h in holds if h.get("cause") == "PENDING_GONE"]:
        m = next((y for y in now_left if y.get("order_id") is None and y.get("product_id") == h.get("product_id")
                  and y.get("item_code") == h.get("item_code") and abs(y["qty"] - h["qty"]) < EPS), None)
        if m:
            now_left.remove(m)
            out["release"].append((h["id"], "REAPPEARED"))
            out["causes"]["REAPPEARED"] += h["qty"]
    # 2. the same line with another quantity
    reduced = defaultdict(list)
    for h in holds:
        if h.get("cause") == "QTY_REDUCED" and h.get("order_id") is not None:
            reduced[_lid(h)].append(h)
    by_lid: dict[tuple, list[dict]] = defaultdict(list)
    for y in now_left:
        if y.get("order_id") is not None:
            by_lid[_lid(y)].append(y)
    rest = []
    for x in prev_left:
        lst = by_lid.get(_lid(x)) if x.get("order_id") is not None else None
        if not lst:
            rest.append(x)
            continue
        y = lst.pop()
        now_left.remove(y)
        if y["qty"] < x["qty"] - EPS:
            _hold(out, x, "QTY_REDUCED", x["qty"] - y["qty"])
            continue
        up = y["qty"] - x["qty"]
        # units held earlier for this line (QTY_REDUCED) come back first: released, a remainder stays held
        for h in sorted(reduced.get(_lid(x), []), key=lambda z: (z.get("detected_at") or "", z["id"])):
            if up <= EPS:
                break
            out["release"].append((h["id"], "REAPPEARED"))
            back = min(up, h["qty"])
            out["causes"]["REAPPEARED"] += back
            if h["qty"] > up + EPS:
                _hold(out, h, "QTY_REDUCED", h["qty"] - up)
            up -= back
        if up > EPS:
            out["causes"]["QTY_INCREASED"] += up
    # 3. lines that left this key
    for x in rest:
        if x.get("order_id") is None:
            y = next((y for y in now_left if y.get("order_id") is not None and _same_product(x, y)
                      and y.get("item_code") == x.get("item_code")), None)
            if y:
                now_left.remove(y)
                out["causes"]["PENDING_CONFIRMED"] += y["qty"] - x["qty"]
                continue
            _hold(out, x, "PENDING_GONE", x["qty"])
            continue
        other = orders_now.get(x["order_id"], [])
        # a move is proven only by the same order line (product, quantity) that is NEW in another key of this plan
        cand = next((y for y in other if _same_product(x, y) and _key_of(y) != key and abs(y["qty"] - x["qty"]) < EPS
                     and (_key_of(y), _lid(y), y["qty"]) not in used_dest and dest_new(_key_of(y), y)), None)
        if cand is not None:
            used_dest.add((_key_of(cand), _lid(cand), cand["qty"]))
            out["causes"]["MOVED_OUT"] += x["qty"]
            out["moves"].append({"order_id": x["order_id"], "qty": x["qty"], "to": "|".join(_key_of(cand))})
            continue
        _hold(out, x, "ORDER_GONE" if not other else "LINE_GONE", x["qty"])
    # 4. lines new in this key (taken from the source as they are)
    prev_orders = {x.get("order_id") for x in prev}
    for y in now_left:
        c = "LINE_NEW" if y.get("order_id") in prev_orders and y.get("order_id") is not None else "ORDER_NEW"
        out["causes"][c] += y["qty"]
    return out


def _hold_line(x: dict) -> dict:
    return {"order_id": x.get("order_id"), "product_id": x.get("product_id"), "item_code": x.get("item_code"),
            "order_status": x.get("order_status"), "qty": float(x["qty"])}


# ------------------------------------------------------------------ plan
def prepare(scope_key: str, rows: list[dict], read_start: str, read_end: str, delete_start: str, delete_end: str | None,
            snap: dict | None, *, pol: str | None = None, lines_api=None) -> dict:
    """What a load of [read_start, read_end] writes under the policy, computed WITHOUT writing: target rows (source +
    held lines), holds to record / release, per-key causes, and the stored state it was computed on. BigQuery is read
    only for the keys that return less than stored (line evidence). `lines_api` (tests) replaces bq/source_lines."""
    pol = pol or policy()
    if lines_api is None:
        from ..bq import source_lines as lines_api
    by_day: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        by_day[str(r["order_date"])[:10]].append(i)
    keep: dict[tuple, dict] = {}      # only the keys that need a decision: content differs from the source, or held lines
    with db.read() as c:
        marker = _marker(c, scope_key, delete_start, delete_end)
        holds = active_holds(c, scope_key, delete_start, delete_end)
        loads, day_ver = _base_lookup(c, scope_key)
        finals = {r[0] for r in c.execute(
            "SELECT business_date FROM actual_finals WHERE scope_key=? AND status='FINALIZED' AND business_date >= ?"
            + (" AND business_date <= ?" if delete_end else ""),
            (scope_key, delete_start, delete_end) if delete_end else (scope_key, delete_start))} \
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='actual_finals'").fetchone() else set()
        stored_n, stored_q = 0, 0.0
        flushed: set[str] = set()

        def flush(day: str, stored_day: dict) -> None:
            # one day at a time: a backfill of the whole window never holds 1.3 M stored rows in memory
            src_day = {_key(rows[i]): i for i in by_day.get(day, ())}
            for k, (content, loaded) in stored_day.items():
                hk = holds.get(k, [])
                i = src_day.pop(k, None)
                sc = src_content(rows[i]) if i is not None else None
                if hk or not _same(sc, content):
                    keep[k] = {"stored": content, "loaded_at": loaded, "held_before": float(sum(h["qty"] for h in hk)),
                               "holds": hk, "src": sc}
            for k, i in src_day.items():
                keep[k] = {"stored": None, "loaded_at": None, "held_before": 0.0, "holds": holds.get(k, []),
                           "src": src_content(rows[i])}
            flushed.add(day)

        cur_day, buf = None, {}
        for k, content, loaded in _stored_iter(c, scope_key, delete_start, delete_end):
            stored_n += 1
            stored_q += content[0] or 0.0
            if k[0] != cur_day:
                if cur_day is not None:
                    flush(cur_day, buf)
                cur_day, buf = k[0], {}
            buf[k] = (content, loaded)
        if cur_day is not None:
            flush(cur_day, buf)
        for day in list(by_day):
            if day not in flushed:
                flush(day, {})
        for k, hk in holds.items():            # held lines without a stored row (cannot happen: data check FAILs it)
            if k not in keep:
                keep[k] = {"stored": None, "loaded_at": None, "held_before": float(sum(h["qty"] for h in hk)),
                           "holds": hk, "src": None}
        for k, x in keep.items():
            x["base"] = _base_for(k, x["loaded_at"], loads, day_ver) if x["stored"] is not None else None
    plan = {"scope_key": scope_key, "policy": pol, "read": [read_start, read_end], "delete": [delete_start, delete_end],
            "marker": marker, "finalized_days": finals, "keys": keep, "new_holds": [], "release": [],
            "evidence": {"available": None, "reason": None, "queries": 0, "keys_with_evidence": 0, "keys_no_evidence": 0,
                         "base_versions": []},
            "stored_rows": int(stored_n), "stored_qty": stored_q, "source_rows": len(rows),
            "source_qty": float(sum(float(r["qty"]) for r in rows))}
    if pol == FOLLOW:
        for k, x in keep.items():
            plan["release"] += [(h["id"], "OWNER_DECISION") for h in x["holds"]]
            x["target"] = x["src"]
            x["causes"] = {"FOLLOW_SOURCE": (x["src"][0] if x["src"] else 0.0) - (x["stored"][0] if x["stored"] else 0.0)}
        return _finish(plan)
    # KEEP_OBSERVED_LINES: line evidence for every stored key whose units / order count the source changed (a line that
    # left may be hidden by a bigger new one) and for every key holding lines (a held line may be back). A change that
    # keeps both the units and the order count of a key is not seen (no evidence is read for unchanged keys).
    suspects = {}
    for k, x in keep.items():
        if x["stored"] is None:
            x["decrease"], x["lines_changed"] = 0.0, False
            continue
        equiv = x["stored"][0] - x["held_before"]
        sq = x["src"][0] if x["src"] else 0.0
        so = x["src"][1] if x["src"] else 0
        x["decrease"] = equiv - sq if equiv - sq > EPS else 0.0
        x["lines_changed"] = abs(equiv - sq) > EPS or (not x["holds"] and so != int(x["stored"][1] or 0))
        if x["lines_changed"] or x["holds"]:
            suspects[k] = x
    if len(suspects) > MAX_EVIDENCE_KEYS:
        # fail-closed: a change this large (a partial source, a redefinition) is not reconciled automatically - nothing
        # is written; a smaller backfill window or an explicit owner decision (FOLLOW_SOURCE) is needed
        raise AppError("HISTORY_CHANGE_TOO_LARGE", 409, detail=f"{len(suspects)} stored keys changed in "
                                                               f"{read_start}..{read_end} (max {MAX_EVIDENCE_KEYS})")
    ok, why = lines_api.available(snap) if suspects else (True, None)
    plan["evidence"].update(available=ok, reason=why)
    now_lines: dict[tuple, list[dict]] = defaultdict(list)
    prev_lines: dict[tuple, list[dict]] = {}
    orders_now: dict[str, list[dict]] = defaultdict(list)
    if suspects and ok:
        limit = now_utc() - timedelta(hours=ss.get("data_policy").source_time_travel_hours)
        for y in lines_api.lines(set(suspects)):
            now_lines[(y["order_date"], y["sku_id"], y["fc_id"])].append(y)
        plan["evidence"]["queries"] += 1
        groups: dict[str, set] = defaultdict(set)
        for k, x in suspects.items():
            b = _parse(x.get("base"))
            if x["lines_changed"] and b is not None and limit <= b <= now_utc() + timedelta(minutes=5):
                groups[x["base"]].add(k)
        for asof, ks in sorted(groups.items()):
            got: dict[tuple, list[dict]] = defaultdict(list)
            for y in lines_api.lines(ks, asof=asof):
                got[(y["order_date"], y["sku_id"], y["fc_id"])].append(y)
            plan["evidence"]["queries"] += 1
            plan["evidence"]["base_versions"].append({"asof": asof, "keys": len(ks)})
            for k in ks:
                prev_lines[k] = got.get(k, [])
        gone_orders = set()
        for k, pl in prev_lines.items():
            ids_now = {_lid(y) for y in now_lines.get(k, [])}
            gone_orders |= {x["order_id"] for x in pl if x.get("order_id") and _lid(x) not in ids_now}
        if gone_orders:
            for y in lines_api.order_lines(gone_orders):
                orders_now[y["order_id"]].append(y)
            plan["evidence"]["queries"] += 1
    # fail-safe: lines must add up to the aggregates (now = the source row, base = the stored row without its held
    # lines); lines that do not (a wrong mapping, a query that returned nothing, a base version that is not the one the
    # row was written from) are no evidence - the decrease is then kept (NO_EVIDENCE)
    usable_now: dict[tuple, list[dict] | None] = {}
    usable_prev: dict[tuple, list[dict]] = {}
    for k, x in suspects.items():
        now = now_lines.get(k, []) if ok else None
        if now is not None and abs(sum(y["qty"] for y in now) - (x["src"][0] if x["src"] else 0.0)) > 1e-6:
            plan["evidence"]["inconsistent_now"] = plan["evidence"].get("inconsistent_now", 0) + 1
            now = None
        usable_now[k] = now
        if now is not None and k in prev_lines:
            if abs(sum(y["qty"] for y in prev_lines[k]) - (x["stored"][0] - x["held_before"])) <= 1e-6:
                usable_prev[k] = prev_lines[k]
            else:
                plan["evidence"]["inconsistent_base"] = plan["evidence"].get("inconsistent_base", 0) + 1

    def dest_new(k2: tuple, y: dict) -> bool:
        """A line is proven NEW in another key of this plan: a key the plan creates, or one whose usable base version
        holds fewer such lines than now. An unchanged key, a key outside this plan or one without usable evidence
        proves nothing (the leaving line is then held, never silently moved)."""
        x2 = keep.get(k2)
        if x2 is None:
            return False
        if x2["stored"] is None:
            return True
        if k2 not in usable_prev or usable_now.get(k2) is None:
            return False
        same = lambda z: _lid(z) == _lid(y) and abs(z["qty"] - y["qty"]) < EPS  # noqa: E731
        return sum(1 for z in usable_now[k2] if same(z)) > sum(1 for z in usable_prev[k2] if same(z))

    used_dest: set = set()
    for k, x in keep.items():
        now = None
        if k in suspects:
            now = usable_now.get(k)
            if not x["lines_changed"]:
                prev, compare = [], False          # only the held lines to check (one may be back)
            elif k in usable_prev:
                prev, compare = usable_prev[k], True
            else:
                prev, compare = None, True         # no usable base version: NO_EVIDENCE keeps the decrease
            equiv = x["stored"][0] - x["held_before"]
            res = classify_key(k, prev, now, orders_now, x["holds"], x["decrease"], compare, dest_new=dest_new,
                               src_increase=(x["src"][0] if x["src"] else 0.0) - equiv, used_dest=used_dest)
            if x["lines_changed"]:
                plan["evidence"]["keys_with_evidence" if prev is not None else "keys_no_evidence"] += 1
        else:
            res = {"new_holds": [], "release": [], "causes": Counter(), "moves": []}
        released = {hid for hid, _ in res["release"]}
        plan["release"] += res["release"]
        for h in res["new_holds"]:
            plan["new_holds"].append({**h, "key": k, "base_asof": x.get("base")})
        held_after = [h for h in x["holds"] if h["id"] not in released] + [{**h, "id": None} for h in res["new_holds"]]
        x["held_after"] = float(sum(h["qty"] for h in held_after))
        x["causes"] = dict(res["causes"])
        x["moves"] = res["moves"]
        x["target"] = _target(x, held_after, now)
    return _finish(plan)


def _target(x: dict, held_after: list[dict], now: list[dict] | None) -> tuple | None:
    """Stored content to write: the source row + held units (and orders that are no longer in the source)."""
    held = sum(h["qty"] for h in held_after)
    if held <= EPS:
        return x["src"]
    if now is not None:
        in_src = {y.get("order_id") for y in now if y.get("order_id")}
        extra_orders = len({h["order_id"] for h in held_after if h.get("order_id") and h["order_id"] not in in_src})
    else:
        extra_orders = None
    # a key-level hold (NO_EVIDENCE) knows no order: the order count of the stored row is kept when it was larger
    keep_orders = extra_orders is None or any(h.get("cause") == "NO_EVIDENCE" for h in held_after)
    if x["src"] is not None:
        t = list(x["src"])
        t[0] = t[0] + held
        t[1] = t[1] + (extra_orders or 0)
        if keep_orders:
            t[1] = max(t[1], int((x["stored"] or x["src"])[1] or 0))
        return tuple(t)
    base = list(x["stored"]) if x["stored"] is not None else [0.0, 0] + [None] * (len(COLS) - 2)
    base[0] = held
    if extra_orders is not None:
        base[1] = extra_orders
    return tuple(base)


def _finish(plan: dict) -> dict:
    keys = plan["keys"]
    changed = {k: x for k, x in keys.items() if not _same(x.get("target"), x["stored"]) or x.get("holds")
               or x.get("held_after")}
    plan["keys"] = changed
    h = hashlib.sha256()
    for k in sorted(changed):
        t = changed[k].get("target")
        h.update(repr((k, None if t is None else (round(t[0], 6), t[1]))).encode())
    for nh in sorted(plan["new_holds"], key=lambda z: (z["key"], str(z.get("order_id")), str(z.get("product_id")),
                                                        str(z.get("item_code")), z["qty"], z["cause"])):
        h.update(repr((nh["key"], nh.get("order_id"), nh.get("product_id"), nh.get("item_code"), round(nh["qty"], 6),
                       nh["cause"])).encode())
    h.update(repr(sorted(plan["release"])).encode())
    causes: Counter = Counter()
    for x in changed.values():
        for c, v in (x.get("causes") or {}).items():
            causes[c] += v
    kinds = Counter()
    for x in changed.values():
        s, t = x["stored"], x.get("target")
        kinds["NEW" if s is None and t is not None else "REMOVED" if t is None and s is not None
              else "UPDATED" if not _same(s, t) else "HELD_UNCHANGED"] += 1
    plan["digest"] = h.hexdigest()[:16]
    plan["summary"] = {
        "policy": plan["policy"], "keys_changed": dict(kinds),
        "units_by_cause": {c: round(v, 6) for c, v in sorted(causes.items())},
        "holds_new": len(plan["new_holds"]), "holds_new_units": round(sum(x["qty"] for x in plan["new_holds"]), 6),
        "holds_new_by_cause": dict(Counter(x["cause"] for x in plan["new_holds"])),
        "holds_released": len(plan["release"]), "holds_released_by_reason": dict(Counter(r for _, r in plan["release"])),
        "held_units_after": round(sum(x.get("held_after") or 0.0 for x in changed.values()), 6),
        "finalized_days_changed": sorted({k[0] for k, x in changed.items() if k[0] in plan["finalized_days"]
                                           and not _same(x.get("target"), x["stored"])}),
        "evidence": plan["evidence"], "digest": plan["digest"]}
    return plan


def target_rows(plan: dict, rows: list[dict]):
    """(key, content) of every row to write: the source rows with the plan's targets, then the keys kept only by held
    lines. A source row whose target is None (cannot happen: a source row always has a target) is skipped."""
    keys = plan["keys"]
    for r in rows:
        k = _key(r)
        x = keys.get(k)
        t = x["target"] if x is not None else src_content(r)
        if t is not None:
            yield k, t
    for k, x in keys.items():
        if x.get("src") is None and x.get("target") is not None:
            yield k, x["target"]


# ------------------------------------------------------------------ write (inside the caller's transaction)
def write(c, plan: dict, rows: list[dict], *, run_id: str, run_kind: str, loaded: str, data_source: str,
          source_version: str | None, job_id: str | None, backup: dict | None, preview_id: str | None,
          started: str, rewrite_all: bool = True) -> dict:
    """Write the plan's target rows, record held lines / releases, the change log, the run and its per-key decisions.
    rewrite_all (a regular D-1 load): every stored row of the delete range is replaced - one loaded_at per day, which
    the finalization of a completed day relies on. rewrite_all False (a backfill of the history): only the rows whose
    content changes are replaced - an unchanged row keeps its loaded_at (e.g. a row pinned by the owner's six-key open
    hours rule stays approved). Raises StaleBase (nothing written) when the stored data changed since the plan."""
    scope_key = plan["scope_key"]
    d0, d1 = plan["delete"]
    if _marker(c, scope_key, d0, d1) != plan["marker"]:
        raise StaleBase("the stored rows or held lines changed since the plan")
    n, q = 0, 0.0
    if rewrite_all:
        if d1:
            c.execute("DELETE FROM demand_daily WHERE scope_key=? AND order_date BETWEEN ? AND ?", (scope_key, d0, d1))
        else:
            c.execute("DELETE FROM demand_daily WHERE scope_key=? AND order_date >= ?", (scope_key, d0))
        batch = []
        for k, t in target_rows(plan, rows):
            batch.append((scope_key, data_source, k[0], k[1], k[2], t[0], t[1], t[2], t[3], t[4], t[5], loaded, *t[6:]))
            n += 1
            q += t[0]
            if len(batch) >= 20000:
                _insert(c, batch)
                batch = []
        if batch:
            _insert(c, batch)
    else:
        # a day not finalized yet is rewritten whole (one loaded_at per day: the finalization of a completed day needs
        # it); a finalized day gets only its changed rows (the frozen actual is its KPI snapshot)
        nonfinal = {d for d in _days(plan["read"]) if d not in plan["finalized_days"]}
        for d in sorted(nonfinal):
            c.execute("DELETE FROM demand_daily WHERE scope_key=? AND order_date=?", (scope_key, d))
        if nonfinal:
            _insert(c, [(scope_key, data_source, k[0], k[1], k[2], t[0], t[1], t[2], t[3], t[4], t[5], loaded, *t[6:])
                        for k, t in target_rows(plan, rows) if k[0] in nonfinal])
        for k, x in plan["keys"].items():
            t = x.get("target")
            if k[0] in nonfinal or _same(t, x["stored"]):
                continue
            c.execute("DELETE FROM demand_daily WHERE scope_key=? AND order_date=? AND sku_id=? AND fc_id=?", (scope_key, *k))
            if t is not None:
                _insert(c, [(scope_key, data_source, k[0], k[1], k[2], t[0], t[1], t[2], t[3], t[4], t[5], loaded, *t[6:])])
        w = " AND order_date <= ?" if d1 else ""
        n, q = c.execute(f"SELECT COUNT(*), TOTAL(qty) FROM demand_daily WHERE scope_key=? AND order_date >= ?{w}",
                         (scope_key, d0, d1) if d1 else (scope_key, d0)).fetchone()
    # held lines (ids: the run id + a counter - unique however many lines one run holds)
    for hid, reason in plan["release"]:
        c.execute("UPDATE demand_held_lines SET status='RELEASED', released_run=?, released_at=?, release_reason=? "
                  "WHERE id=? AND status='ACTIVE'", (run_id, loaded, reason, hid))
    for i, h in enumerate(plan["new_holds"], start=1):
        k = h["key"]
        c.execute("INSERT INTO demand_held_lines(id, scope_key, order_date, sku_id, fc_id, order_id, product_id, item_code, "
                  "order_status, qty, cause, status, detected_run, detected_at, base_asof, evidence_json) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?, 'ACTIVE', ?,?,?,?)",
                  (f"{run_id}-H{i:06d}", scope_key, k[0], k[1], k[2], h.get("order_id"), h.get("product_id"),
                   h.get("item_code"), h.get("order_status"), float(h["qty"]), h["cause"], run_id, loaded,
                   h.get("base_asof"), json.dumps({"key_causes": plan["keys"][k].get("causes"),
                                                   "moves": plan["keys"][k].get("moves")}, default=str)))
    # change log + per-key decisions
    finals = plan["finalized_days"]
    logged = 0
    for k, x in sorted(plan["keys"].items()):
        s, t = x["stored"], x.get("target")
        if not _same(s, t):
            action = "INSERT" if s is None else "DELETE" if t is None else "UPDATE"
            c.execute("INSERT INTO demand_change_log(run_id, run_kind, scope_key, order_date, sku_id, fc_id, action, "
                      "qty_before, qty_after, held_after, before_json, after_json, finalized, at) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (run_id, run_kind, scope_key, k[0], k[1], k[2], action, s[0] if s else None, t[0] if t else None,
                       float(x.get("held_after") or 0.0), _row_json(k, s, x["loaded_at"]) if s else None,
                       _row_json(k, t, loaded) if t else None, int(k[0] in finals), loaded))
            logged += 1
        kind = ("NEW" if s is None and t is not None else "REMOVED" if t is None and s is not None
                else "UPDATED" if not _same(s, t) else "HELD")
        c.execute("INSERT INTO demand_sync_run_keys(run_id, order_date, sku_id, fc_id, kind, stored_qty, source_qty, "
                  "target_qty, held_qty, causes_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (run_id, k[0], k[1], k[2], kind, s[0] if s else None, x["src"][0] if x.get("src") else None,
                   t[0] if t else None, float(x.get("held_after") or 0.0),
                   json.dumps({"causes": x.get("causes"), "moves": x.get("moves")}, default=str)))
    summary = {**plan["summary"], "rows_written": n, "qty_written": q, "rows_logged": logged,
               "read": plan["read"], "delete": plan["delete"], "loaded_at": loaded}
    c.execute("INSERT INTO demand_sync_runs(id, kind, status, scope_key, window_start, window_end, policy, source_version, "
              "started_at, finished_at, summary_json, backup, job_id, preview_id) VALUES (?,?, 'COMMITTED', ?,?,?,?,?,?,?,?,?,?,?)",
              (run_id, run_kind, scope_key, d0, d1 or plan["read"][1], plan["policy"], source_version, started, loaded,
               json.dumps(summary, default=str), json.dumps(backup) if backup else None, job_id, preview_id))
    # every day written now matches the source (+ held lines): the base of the next line evidence
    _mark_days(c, scope_key, plan, rows, loaded, source_version, run_id)
    return {"rows_written": n, "qty_written": q, "rows_logged": logged}


def _days(r: list) -> list[str]:
    """The calendar days of a [start, end] range (ISO strings)."""
    d, end = datetime.fromisoformat(r[0]).date(), datetime.fromisoformat(r[1]).date()
    out = []
    while d <= end:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _insert(c, batch: list[tuple]) -> None:
    c.executemany(
        "INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, avg_unit_price, "
        "avg_discount_rate, promo_share, voucher_share, loaded_at, open_hours, open_hours_status, customer_count, "
        "repeat_customer_count, repeat_interval_days_sum) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)


def _mark_days(c, scope_key: str, plan: dict, rows: list[dict], loaded: str, version: str | None, run_id: str) -> None:
    stats: dict[str, list] = defaultdict(lambda: [0, 0.0])
    for r in rows:
        s = stats[str(r["order_date"])[:10]]
        s[0] += 1
        s[1] += float(r["qty"])
    r0, r1 = plan["read"]
    d = datetime.fromisoformat(r0).date()
    end = datetime.fromisoformat(r1).date()
    while d <= end:
        day = d.isoformat()
        s = stats.get(day, [0, 0.0])
        c.execute("INSERT INTO source_day_checks(scope_key, order_date, status, checked_at, verified_at, source_version, "
                  "source_keys, source_qty, stored_keys, stored_qty, run_id) VALUES (?,?, 'MATCH', ?,?,?,?,?,?,?,?) "
                  "ON CONFLICT(scope_key, order_date) DO UPDATE SET status='MATCH', checked_at=excluded.checked_at, "
                  "verified_at=excluded.verified_at, source_version=excluded.source_version, source_keys=excluded.source_keys, "
                  "source_qty=excluded.source_qty, stored_keys=excluded.stored_keys, stored_qty=excluded.stored_qty, "
                  "run_id=excluded.run_id", (scope_key, day, loaded, loaded, version, s[0], s[1], s[0], s[1], run_id))
        d += timedelta(days=1)


def record_preview(plan: dict, preview_id: str, source_version: str | None, started: str) -> None:
    """A preview keeps its per-key decisions (report) - nothing of the demand is written."""
    with db.tx() as c:
        c.execute("INSERT INTO demand_sync_runs(id, kind, status, scope_key, window_start, window_end, policy, "
                  "source_version, started_at, finished_at, summary_json) VALUES (?, 'PREVIEW', 'PREVIEW', ?,?,?,?,?,?,?,?)",
                  (preview_id, plan["scope_key"], plan["read"][0], plan["read"][1], plan["policy"], source_version, started,
                   now_iso(), json.dumps(plan["summary"], default=str)))
        for k, x in sorted(plan["keys"].items()):
            s, t = x["stored"], x.get("target")
            kind = ("NEW" if s is None and t is not None else "REMOVED" if t is None and s is not None
                    else "UPDATED" if not _same(s, t) else "HELD")
            c.execute("INSERT INTO demand_sync_run_keys(run_id, order_date, sku_id, fc_id, kind, stored_qty, source_qty, "
                      "target_qty, held_qty, causes_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (preview_id, k[0], k[1], k[2], kind, s[0] if s else None, x["src"][0] if x.get("src") else None,
                       t[0] if t else None, float(x.get("held_after") or 0.0),
                       json.dumps({"causes": x.get("causes"), "moves": x.get("moves")}, default=str)))


# ------------------------------------------------------------------ rollback of one run
def _rollback_check(c, run_id: str):
    """(run, its change log entries, conflicts, its ACTIVE holds, its RELEASED holds, holds it released)."""
    run = db.one(c, "SELECT * FROM demand_sync_runs WHERE id=?", (run_id,))
    if not run:
        raise AppError("BATCH_NOT_FOUND", 404, detail=run_id)
    if run["status"] != "COMMITTED" or run["kind"] not in ("D1_SYNC", "BACKFILL", "HOLD_RELEASE"):
        raise AppError("SYNC_ROLLBACK_REFUSED", 409, detail=f"{run_id} is {run['kind']} {run['status']}")
    entries = db.rows(c, "SELECT * FROM demand_change_log WHERE run_id=? ORDER BY id", (run_id,))
    conflicts = []
    for e in entries:
        later = c.execute("SELECT id, run_id FROM demand_change_log WHERE scope_key=? AND order_date=? AND sku_id=? "
                          "AND fc_id=? AND id > ? LIMIT 1", (e["scope_key"], e["order_date"], e["sku_id"], e["fc_id"],
                                                             e["id"])).fetchone()
        cur = c.execute(f"SELECT {', '.join(COLS)} FROM demand_daily WHERE scope_key=? AND order_date=? AND sku_id=? "
                        "AND fc_id=?", (e["scope_key"], e["order_date"], e["sku_id"], e["fc_id"])).fetchone()
        want = json.loads(e["after_json"]) if e["after_json"] else None
        same = (cur is None and want is None) or (cur is not None and want is not None
                                                  and _same(tuple(cur), tuple(want[x] for x in COLS)))
        if later or not same:
            conflicts.append({"key": [e["order_date"], e["sku_id"], e["fc_id"]], "later_run": later[1] if later else None,
                              "current_differs": not same})
    # a later run may have released a hold of this run: that hold is then not ours to release any more
    new_holds = db.rows(c, "SELECT id FROM demand_held_lines WHERE detected_run=? AND status='ACTIVE'", (run_id,))
    gone_holds = db.rows(c, "SELECT * FROM demand_held_lines WHERE detected_run=? AND status='RELEASED'", (run_id,))
    released = db.rows(c, "SELECT * FROM demand_held_lines WHERE released_run=?", (run_id,))
    return run, entries, conflicts, new_holds, gone_holds, released


def rollback(run_id: str, apply: bool = False, by: str = "CLI") -> dict:
    """Restore the stored rows of one committed run exactly as they were before it (loaded_at included) and undo its
    held-line changes. Refused when a later write changed one of its keys. Dry run unless `apply` (then an online
    backup first). The rollback is itself a run (ROLLBACK) with its change log."""
    with db.read() as c:
        run, entries, conflicts, new_holds, gone_holds, released = _rollback_check(c, run_id)
    out = {"run_id": run_id, "kind": run["kind"], "entries": len(entries), "conflicts": conflicts[:50],
           "n_conflicts": len(conflicts), "holds_to_release": len(new_holds), "holds_to_restore": len(released),
           "holds_of_run_already_released": len(gone_holds), "applied": False}
    if conflicts:
        out["status"] = "REFUSED"
        if apply:
            raise AppError("SYNC_ROLLBACK_REFUSED", 409, detail=f"{len(conflicts)} keys changed since {run_id}",
                           conflicts=conflicts[:20])
        return out
    out["status"] = "READY"
    if not apply:
        return out
    from ..backup import backup_database
    bk = backup_database(reason="pre-rollback")
    rid = db.new_id("RBK")
    at = now_iso()
    with db.tx() as c:
        # checked again under the write lock: a load committed after the dry run makes the rollback refused
        run, entries, conflicts, new_holds, gone_holds, released = _rollback_check(c, run_id)
        if conflicts:
            raise AppError("SYNC_ROLLBACK_REFUSED", 409, detail=f"{len(conflicts)} keys changed since {run_id}",
                           conflicts=conflicts[:20])
        for e in reversed(entries):
            k = (e["scope_key"], e["order_date"], e["sku_id"], e["fc_id"])
            before = json.loads(e["before_json"]) if e["before_json"] else None
            after = json.loads(e["after_json"]) if e["after_json"] else None
            c.execute("DELETE FROM demand_daily WHERE scope_key=? AND order_date=? AND sku_id=? AND fc_id=?", k)
            if before:
                data_source = c.execute("SELECT data_source FROM demand_daily WHERE scope_key=? LIMIT 1",
                                        (k[0],)).fetchone()
                _insert(c, [(k[0], data_source[0] if data_source else "BIGQUERY", k[1], k[2], k[3],
                             *[before[x] for x in COLS[:6]], before["loaded_at"], *[before[x] for x in COLS[6:]])])
            c.execute("INSERT INTO demand_change_log(run_id, run_kind, scope_key, order_date, sku_id, fc_id, action, "
                      "qty_before, qty_after, held_after, before_json, after_json, finalized, at) "
                      "VALUES (?, 'ROLLBACK', ?,?,?,?,?,?,?,0,?,?,?,?)",
                      (rid, *k, "DELETE" if not before else "INSERT" if not after else "UPDATE",
                       after["qty"] if after else None, before["qty"] if before else None,
                       json.dumps(after) if after else None, json.dumps(before) if before else None, e["finalized"], at))
        for h in new_holds:
            c.execute("UPDATE demand_held_lines SET status='RELEASED', released_run=?, released_at=?, release_reason='ROLLBACK' "
                      "WHERE id=? AND status='ACTIVE'", (rid, at, h["id"]))
        for i, h in enumerate(released, start=1):
            c.execute("INSERT INTO demand_held_lines(id, scope_key, order_date, sku_id, fc_id, order_id, product_id, item_code, "
                      "order_status, qty, cause, status, detected_run, detected_at, base_asof, evidence_json, restored_from) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?, 'ACTIVE', ?,?,?,?,?)",
                      (f"{rid}-H{i:06d}", h["scope_key"], h["order_date"], h["sku_id"], h["fc_id"], h["order_id"],
                       h["product_id"], h["item_code"], h["order_status"], h["qty"], h["cause"], rid, at, h["base_asof"],
                       h["evidence_json"], h["id"]))
        # the restored days are no longer the source version the run verified: their next evidence base falls back to
        # the load that wrote each restored row (its loaded_at), never to the version of the rolled-back run
        for d in sorted({e["order_date"] for e in entries}):
            c.execute("UPDATE source_day_checks SET status='DIFF', verified_at=NULL, source_version=NULL, checked_at=?, "
                      "run_id=? WHERE scope_key=? AND order_date=?", (at, rid, run["scope_key"], d))
        c.execute("UPDATE demand_sync_runs SET status='ROLLED_BACK', rolled_back_by=?, rolled_back_at=? WHERE id=?",
                  (rid, at, run_id))
        summary = {"rolled_back_run": run_id, "entries": len(entries), "holds_released": len(new_holds),
                   "holds_restored": len(released), "by": by}
        c.execute("INSERT INTO demand_sync_runs(id, kind, status, scope_key, window_start, window_end, policy, started_at, "
                  "finished_at, summary_json, backup) VALUES (?, 'ROLLBACK', 'COMMITTED', ?,?,?,?,?,?,?,?)",
                  (rid, run["scope_key"], run["window_start"], run["window_end"], run["policy"], at, at,
                   json.dumps(summary), json.dumps({"file": bk.name})))
        db.audit(c, "DEMAND_SYNC_ROLLBACK", "scope", run["scope_key"], {**summary, "rollback_run": rid, "backup": bk.name})
    out.update(applied=True, rollback_run=rid, backup=bk.name)
    return out


# ------------------------------------------------------------------ owner decision: release held lines
def release_holds(scope_key: str, cause: str | None = None, sku_id: str | None = None, start: str | None = None,
                  end: str | None = None, apply: bool = False, by: str = "CLI") -> dict:
    """Explicit owner decision: stop keeping some held lines (e.g. accept that a product left the source scope). The
    stored rows lose the held units (a row kept only by them is removed). Dry run unless `apply` (online backup first);
    logged as a HOLD_RELEASE run, reversible with rollback()."""
    if cause and cause not in HOLD_CAUSES:
        raise AppError("VALIDATION_ERROR", 422, detail=f"cause must be one of {HOLD_CAUSES}")
    q = "SELECT * FROM demand_held_lines WHERE scope_key=? AND status='ACTIVE'"
    p: list = [scope_key]
    for col, v in (("cause", cause), ("sku_id", sku_id)):
        if v:
            q += f" AND {col}=?"
            p.append(v)
    if start:
        q += " AND order_date >= ?"
        p.append(start)
    if end:
        q += " AND order_date <= ?"
        p.append(end)
    with db.read() as c:
        hs = db.rows(c, q, p)
    by_key: dict[tuple, list[dict]] = defaultdict(list)
    for h in hs:
        by_key[(h["order_date"], h["sku_id"], h["fc_id"])].append(h)
    out = {"scope_key": scope_key, "filter": {"cause": cause, "sku_id": sku_id, "start": start, "end": end},
           "holds": len(hs), "units": round(sum(h["qty"] for h in hs), 6), "keys": len(by_key),
           "by_cause": dict(Counter(h["cause"] for h in hs)), "applied": False}
    if not apply or not hs:
        return out
    from ..backup import backup_database
    bk = backup_database(reason="pre-hold-release")
    rid = db.new_id("HRL")
    at = now_iso()
    with db.tx() as c:
        # under the write lock: only the holds of the dry run that are still ACTIVE are released
        ids = {h["id"] for h in hs}
        now_active = {h["id"] for h in db.rows(c, q, p)}
        if ids - now_active:
            raise AppError("VALIDATION_ERROR", 409, detail=f"{len(ids - now_active)} held lines changed since the dry run")
        logged = 0
        for k, lst in sorted(by_key.items()):
            row = c.execute(f"SELECT {', '.join(COLS)}, loaded_at, data_source FROM demand_daily WHERE scope_key=? AND "
                            "order_date=? AND sku_id=? AND fc_id=?", (scope_key, *k)).fetchone()
            if row is None:
                raise AppError("VALIDATION_ERROR", 409, detail=f"held lines of {k} have no stored row (data check)")
            before = tuple(row[:len(COLS)])
            units = sum(h["qty"] for h in lst)
            mine = {h["id"] for h in lst}
            still = [h for h in db.rows(c, "SELECT * FROM demand_held_lines WHERE scope_key=? AND order_date=? AND "
                                           "sku_id=? AND fc_id=? AND status='ACTIVE'", (scope_key, *k)) if h["id"] not in mine]
            # an order counted only because all its lines were held (ORDER_GONE) leaves the order count with them
            gone_orders = {h["order_id"] for h in lst if h["order_id"] and h["cause"] == "ORDER_GONE"} - \
                {h["order_id"] for h in still if h["order_id"]}
            after = list(before)
            after[0] = round(before[0] - units, 9)
            after[1] = max(0, int(before[1] or 0) - len(gone_orders))
            c.execute("DELETE FROM demand_daily WHERE scope_key=? AND order_date=? AND sku_id=? AND fc_id=?", (scope_key, *k))
            if after[0] > EPS:
                _insert(c, [(scope_key, row[len(COLS) + 1], k[0], k[1], k[2], *after[:6], at, *after[6:])])
            c.execute("INSERT INTO demand_change_log(run_id, run_kind, scope_key, order_date, sku_id, fc_id, action, "
                      "qty_before, qty_after, held_after, before_json, after_json, finalized, at) "
                      "VALUES (?, 'HOLD_RELEASE', ?,?,?,?,?,?,?,?,?,?,?,?)",
                      (rid, scope_key, *k, "UPDATE" if after[0] > EPS else "DELETE", before[0],
                       after[0] if after[0] > EPS else None, 0.0, _row_json(k, before, row[len(COLS)]),
                       _row_json(k, tuple(after), at) if after[0] > EPS else None,
                       int(bool(c.execute("SELECT 1 FROM actual_finals WHERE scope_key=? AND business_date=? AND "
                                          "status='FINALIZED'", (scope_key, k[0])).fetchone())), at))
            logged += 1
            for h in lst:
                c.execute("UPDATE demand_held_lines SET status='RELEASED', released_run=?, released_at=?, "
                          "release_reason='OWNER_DECISION' WHERE id=? AND status='ACTIVE'", (rid, at, h["id"]))
        summary = {**out, "rows_logged": logged, "by": by}
        c.execute("INSERT INTO demand_sync_runs(id, kind, status, scope_key, policy, started_at, finished_at, summary_json, "
                  "backup) VALUES (?, 'HOLD_RELEASE', 'COMMITTED', ?,?,?,?,?,?)",
                  (rid, scope_key, policy(), at, at, json.dumps(summary, default=str), json.dumps({"file": bk.name})))
        db.audit(c, "HELD_LINES_RELEASED", "scope", scope_key, {**summary, "run": rid, "backup": bk.name})
    out.update(applied=True, run_id=rid, backup=bk.name)
    return out


# ------------------------------------------------------------------ daily check of the history outside the window
def day_check(scope_key: str, start: str, end: str, snap: dict | None = None, run_id: str | None = None,
              lines_api=None) -> dict:
    """Compare every stored day of [start, end] (the history the regular D-1 load does not re-read) with the source:
    keys, units and a fingerprint of (SKU, FC, units) - stored rows minus held lines. One read-only BigQuery query.
    Writes only source_day_checks (MATCH keeps the day's evidence base fresh; DIFF = the source changed it: run a
    backfill preview of those days)."""
    if lines_api is None:
        from ..bq import source_lines as lines_api
    from datetime import date as _date
    if start > end:
        return {"status": "SKIPPED", "reason": "EMPTY_RANGE"}
    version = lines_api.table_version()
    src = lines_api.day_totals(_date.fromisoformat(start), _date.fromisoformat(end), snap)
    if lines_api.table_version() != version:
        raise SourceChanged("the source table changed during the history check")
    from ..bq.source_lines import fp_one
    with db.read() as c:
        holds = defaultdict(float)
        for d, s, f, q in c.execute("SELECT order_date, sku_id, fc_id, TOTAL(qty) FROM demand_held_lines WHERE scope_key=? "
                                    "AND status='ACTIVE' AND order_date BETWEEN ? AND ? GROUP BY 1, 2, 3", (scope_key, start, end)):
            holds[(d, s, f)] = q
        # streamed in key order: per day only (keys, units, fingerprint) - never the history rows themselves
        per_day: dict[str, list] = {}
        for d, s, f, q in c.execute("SELECT order_date, sku_id, fc_id, qty FROM demand_daily WHERE scope_key=? AND "
                                    "order_date BETWEEN ? AND ? ORDER BY order_date, sku_id, fc_id", (scope_key, start, end)):
            e = q - holds.get((d, s, f), 0.0)
            if e > EPS:
                acc = per_day.setdefault(d, [0, 0.0, 0])
                acc[0] += 1
                acc[1] += e
                acc[2] ^= fp_one(s, f, e)
    at = now_iso()
    diff = []
    days = sorted(set(per_day) | set(src))
    with db.tx() as c:
        for d in days:
            n_st, sq, fp = per_day.get(d, [0, 0.0, 0])
            sv = src.get(d, {"keys": 0, "qty": 0.0, "fp": 0})
            match = n_st == sv["keys"] and abs(sq - sv["qty"]) <= 1e-6 * max(1.0, abs(sq)) and fp == sv["fp"]
            if not match:
                diff.append({"day": d, "source_keys": sv["keys"], "stored_keys": n_st, "source_qty": sv["qty"],
                             "stored_qty": round(sq, 6)})
            c.execute("INSERT INTO source_day_checks(scope_key, order_date, status, checked_at, verified_at, source_version, "
                      "source_keys, source_qty, stored_keys, stored_qty, run_id) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                      "ON CONFLICT(scope_key, order_date) DO UPDATE SET status=excluded.status, checked_at=excluded.checked_at, "
                      "verified_at=COALESCE(excluded.verified_at, source_day_checks.verified_at), "
                      "source_version=CASE WHEN excluded.status='MATCH' THEN excluded.source_version "
                      "ELSE source_day_checks.source_version END, source_keys=excluded.source_keys, "
                      "source_qty=excluded.source_qty, stored_keys=excluded.stored_keys, stored_qty=excluded.stored_qty, "
                      "run_id=excluded.run_id",
                      (scope_key, d, "MATCH" if match else "DIFF", at, at if match else None, version, sv["keys"], sv["qty"],
                       n_st, sq, run_id))
        res = {"status": "DIFF" if diff else "MATCH", "range": [start, end], "days_checked": len(days),
               "days_diff": len(diff), "first_diff_day": diff[0]["day"] if diff else None,
               "last_diff_day": diff[-1]["day"] if diff else None,
               "keys_delta": sum(x["source_keys"] - x["stored_keys"] for x in diff),
               "qty_delta": round(sum(x["source_qty"] - x["stored_qty"] for x in diff), 6), "source_version": version,
               "sample": diff[:10]}
        if diff:
            db.alert(c, "WARNING", "HISTORY_SOURCE_CHANGED", {k: res[k] for k in ("days_diff", "first_diff_day",
                                                                                   "last_diff_day", "keys_delta", "qty_delta")},
                     "scope", scope_key)
        db.audit(c, "HISTORY_DAY_CHECK", "scope", scope_key, {k: v for k, v in res.items() if k != "sample"})
    return res


# ------------------------------------------------------------------ older states (training data reproduction)
def rows_as_of(c, scope_key: str, at: str, start: str, end: str) -> dict[tuple, tuple]:
    """The stored content of [start, end] as it was at `at` (UTC ISO): the current rows with every logged change made
    after `at` undone, newest first. Exact for changes made by 1.2.13+ (every write is logged); a change made before
    the log existed cannot be undone (the result is then the current row)."""
    cur = {k: content for k, content, _ in _stored_iter(c, scope_key, start, end)}
    for e in c.execute("SELECT order_date, sku_id, fc_id, action, before_json FROM demand_change_log WHERE scope_key=? "
                       "AND at > ? AND order_date BETWEEN ? AND ? ORDER BY id DESC", (scope_key, at, start, end)):
        k = (e[0], e[1], e[2])
        if e[3] == "INSERT":
            cur.pop(k, None)
        else:
            b = json.loads(e[4])
            cur[k] = tuple(b[x] for x in COLS)
    return cur


def window_identity_as_of(scope_key: str, start: str, end: str, at: str, columns) -> dict:
    """identity.window_identity of the data as it was at `at` (rows_as_of): a training run's stored identity can be
    reproduced after later history changes."""
    from .identity import ALGORITHM, _columns
    cols = _columns(columns)
    idx = {"order_date": None, "sku_id": None, "fc_id": None}
    with db.read() as c:
        rows = rows_as_of(c, scope_key, at, start, end)
    day_h: dict[str, list] = {}
    for k in sorted(rows):
        content = dict(zip(COLS, rows[k]))
        t = tuple(k[("order_date", "sku_id", "fc_id").index(col)] if col in idx else content[col] for col in cols)
        h = day_h.get(k[0])
        if h is None:
            h = day_h[k[0]] = [hashlib.sha256(), 0]
        h[0].update(repr(t).encode())
        h[0].update(b"\n")
        h[1] += 1
    sel = {d: (v[0].hexdigest(), v[1]) for d, v in day_h.items()}
    sha = hashlib.sha256("\n".join(f"{d}:{sel[d][0]}" for d in sorted(sel)).encode()).hexdigest()
    return {"algorithm": ALGORITHM, "columns": list(cols), "start": start, "end": end, "days": len(sel),
            "rows": sum(v[1] for v in sel.values()), "sha256": sha}
