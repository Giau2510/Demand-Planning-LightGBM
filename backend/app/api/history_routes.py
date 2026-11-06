"""Forecast & actual history (1.2.5): read-only views of the stored D+1 forecasts (see forecast_history.py).

GET only. Opening the page never starts a job, a training or a forecast and never writes the database: the history is
recorded when a forecast is published, the actual is read from the D-1 / D0 data at request time. 1.2.6: fields are
only added (forecast source / backup snapshot per day and row, the 23:59 close of the actual, filter `forecast_source`).

1.4.4: from SEL2_FROM (04/11/2026, the first SEL2 run date) a run date shows the PUBLISHED SEL2 number of that day:
forecast_used of the target day run date + 1 (horizon 2) as written in the newest daily Excel of that forecast day
(sidecar file of ml/sel2/published.py) - never recomputed, so a later change of the forecast source configuration or of
the AVG_DEMAND read never changes the history - compared with the actual of the same rule as before (D-1 / D0 / frozen
copy, an SKU x FC without a row on a read day = 0); source label SEL2. The only file a request may write is a missing /
stale sidecar of a published export, rebuilt from its recorded xlsx (one rebuild per export at a time). A run date
without a SEL2 publication keeps its 1.3.x day (label LIGHTGBM_CU; e.g. after the emergency switch-off), the run dates
before SEL2_FROM are unchanged. The SEL2 days are read day by day (per-day aggregates; a page of rows reads only the
days that hold it); the Excel export streams the days one by one for the sort `date` and, for the other sorts, merges
the per-day sorted rows of the range in memory (at most fh.MAX_EXPORT_ROWS rows, refused above). Rows and the Excel
export: the SEL2 rows first, then the 1.3.x rows (each part sorted on its own)."""
from __future__ import annotations

import heapq
from datetime import date, timedelta

from fastapi import APIRouter
from fastapi.responses import Response

from .. import db
from .. import forecast_history as fh
from .. import settings_service as ss
from ..data.demand import resolve_scope
from ..messages import AppError
from ..ml.sel2 import published
from . import sel2_view

router = APIRouter(prefix="/api/history")


def _scope(c, scope_key: str | None) -> tuple[str | None, str | None, list[dict], dict | None]:
    """(scope, data source, scopes with history, active scope). Default = the ACTIVE source's scope, even when it has
    no history yet (another source's history is never shown silently in its place)."""
    scopes = fh.scopes(c)
    try:
        active = resolve_scope(c)
    except AppError:
        active = None
    if scope_key:
        sc = next((s for s in scopes if s["scope_key"] == scope_key), None)
        if sc:
            return scope_key, sc["data_source"], scopes, active
        if active and active["scope_key"] == scope_key:
            return scope_key, active["data_source"], scopes, active
        raise AppError("VALIDATION_ERROR", 422, detail="unknown scope_key")
    if active:
        return active["scope_key"], active["data_source"], scopes, active
    return (scopes[0]["scope_key"], scopes[0]["data_source"], scopes, None) if scopes else (None, None, scopes, None)


SEL2_FROM = "2026-11-04"                 # 1.4.4: first run date of the SEL2 publication (owner 06/11/2026)
SRC_SEL2, SRC_OLD = "SEL2", "LIGHTGBM_CU"
SEL2_HORIZON = 2                         # target = run date + 1 = horizon 2 of the file of that day
# sort (as fh.SORTS) -> length of the group prefix of _key: one day each (its last item is -day), "sku": one SKU
SEL2_SORTS = {"date": 1, "forecast": 2, "abs_error": 3, "actual": 3, "sku": 1}


def _sel2_days(c, sk: str | None, run_from: str | None = None, run_to: str | None = None) -> list[dict]:
    """Run dates >= SEL2_FROM with a daily Excel of the scope (newest export of the day), newest first."""
    if sk is None:
        return []
    lo = max(SEL2_FROM, run_from or SEL2_FROM)
    return [{"run_date": e["forecast_date"],
             "target_date": str(date.fromisoformat(e["forecast_date"]) + timedelta(days=1)),
             "export_run_id": e["id"], "forecast_run_id": e["refresh_run_id"], "model_version": e["model_version"],
             "published_at": e["created_at"], "source": SRC_SEL2, "_export": e}
            for e in published.latest_exports(c, sk, lo, run_to or "9999-12-31")]


def _actuals(c, sk: str, x: dict | None) -> dict | None:
    """{(sku, fc): qty} of a target day by its actual source (as forecast_history.Query: D1 demand_daily, D0 the
    snapshot, FINAL the frozen copy); None = no actual (never 0)."""
    if not x or x["status"] == fh.NO_ACTUAL or not x.get("source"):
        return None
    if x["source"] == "D1":
        cur = c.execute("SELECT sku_id, fc_id, qty FROM demand_daily WHERE scope_key=? AND order_date=?", (sk, x["date"]))
    elif x["source"] == "D0":
        cur = c.execute("SELECT sku_id, fc_id, cumulative_qty FROM d0_snapshot_values WHERE snapshot_id=?",
                        (x["snapshot_id"],))
    elif x["source"] == "FINAL":
        cur = c.execute("SELECT sku_id, fc_id, qty FROM actual_final_values WHERE final_id=?", (x["snapshot_id"],))
    else:
        return None
    out: dict = {}
    for s, f, q in cur:
        out[(s, f)] = out.get((s, f), 0) + (q or 0)
    return out


def _key(sort: str, r: tuple, dord: int) -> tuple:
    """Full order of a SEL2 row (as the 1.3.x SORTS): r = (sku, fc, target, used, src, reason, actual, present)."""
    if sort == "forecast":
        return (-r[3], -dord, r[0], r[1])
    if sort == "abs_error":
        return (r[6] is None, -abs(r[3] - r[6]) if r[6] is not None else 0, -dord, r[0], r[1])
    if sort == "actual":                     # actual DESC NULLS LAST (an absent row on a read day is 0, not None)
        return (r[6] is None, -r[6] if r[6] is not None else 0, -dord, r[0], r[1])
    if sort == "sku":
        return (r[0], r[1], -dord)
    return (-dord, -r[3], r[0], r[1])


class Sel2Part:
    """The SEL2 run dates of a request: the rows of the newest daily Excel of each day (sidecar files,
    ml/sel2/published.py) read day by day - per-day aggregates, one page of rows - never every row of the range in
    memory for the page (the Excel export: see rows()). sort given: the row-group counts of that sort are taken in the
    same pass (rows())."""

    def __init__(self, c, qy, sk: str, data_source: str | None, fc_id: str | None, q: str | None,
                 actual_status: str | None, sort: str | None = None):
        if sort is not None and sort not in SEL2_SORTS:
            raise AppError("VALIDATION_ERROR", 422, detail=f"sort must be one of {', '.join(SEL2_SORTS)}")
        self.c, self.qy, self.sk, self.fc = c, qy, sk, fc_id or None
        self.days = _sel2_days(c, sk, qy.run_from, qy.run_to)
        self.ctx = fh.actual_context(c, sk, data_source, [d["target_date"] for d in self.days], qy.today) \
            if self.days else {}
        statuses = [s for s in (actual_status or "").split(",") if s]
        self.active = [d for d in self.days
                       if not statuses or (self.ctx.get(d["target_date"]) or {}).get("status") in statuses]
        self.skus = self._search(q)
        self.by_day = {d["run_date"]: d for d in self.days}
        self.sort, self.groups = sort, ({} if sort else None)
        self.daily: dict[str, dict] = {}
        self.n_rows = 0
        act_days = {d["run_date"] for d in self.active}
        for d in self.days:
            n = fsum = asum = n_act = fcmp = err = zero = 0
            if d["run_date"] in act_days:
                dord = date.fromisoformat(d["run_date"]).toordinal()
                g = SEL2_SORTS.get(sort or "", 0)
                for r in self._recs(d):
                    n += 1
                    fsum += r[3]
                    if r[6] is not None:
                        n_act += 1
                        asum += r[6]
                        fcmp += r[3]
                        err += abs(r[3] - r[6])
                        zero += 0 if r[7] else 1
                    if g:
                        k = _key(sort, r, dord)[:g]
                        self.groups[k] = self.groups.get(k, 0) + 1
            self.n_rows += n
            x = self.ctx.get(d["target_date"])
            item = {"run_date": d["run_date"], "target_date": d["target_date"], "has_history": True,
                    "forecast_source": SRC_SEL2, "source_label": SRC_SEL2, "forecast_run_id": d["forecast_run_id"],
                    "export_run_id": d["export_run_id"], "snapshot": None, "n_rows": n,
                    "forecast": fsum if n else None, "actual": asum if n_act else None,
                    "forecast_compared": fcmp if n_act else None, "abs_error": err if n_act else None,
                    "actual_status": x["status"] if x else None, "actual_reason": x["reason"] if x else None,
                    "actual_as_of": x["as_of"] if x else None, "actual_source": x.get("source") if x else None,
                    "actual_close": x.get("close") if x else None, "actual_final": x.get("final") if x else None,
                    "actual_finalization": x.get("finalization") if x else None,
                    "n_zero_absent": zero if n_act else 0}
            item["deviation"] = (item["forecast_compared"] - item["actual"]) if item["actual"] is not None else None
            item["wape"] = (item["abs_error"] / item["actual"]) if item["actual"] else None
            self.daily[d["run_date"]] = item

    def _search(self, q: str | None) -> set | None:
        """SKUs of the stored rows whose SKU or product name contains every word of q (as forecast_history)."""
        if not q or not q.strip():
            return None
        from ..bq.product_names import matching_skus
        skus: set = set()
        for d in self.active:
            skus.update(r[0] for r in (published.load(d["_export"]) or ()))
        return set(matching_skus(sorted(skus), q, {s: self.qy.name_of(s, None) or "" for s in skus}))

    def _recs(self, d: dict):
        """(sku, fc, target, used, source, reason, actual, actual_present) of one day, filtered."""
        rows = published.load(d["_export"]) or ()
        act = _actuals(self.c, self.sk, self.ctx.get(d["target_date"]))
        fc, skus = self.fc, self.skus
        for r in rows:
            if (fc and r[1] != fc) or (skus is not None and r[0] not in skus):
                continue
            if act is None:
                yield (*r, None, None)
            else:
                a = act.get((r[0], r[1]))
                yield (*r, 0 if a is None else a, a is not None)

    def count(self) -> int:
        return self.n_rows

    def _row(self, r: tuple, d: dict) -> dict:
        x = self.ctx.get(d["target_date"]) or {}
        a = r[6]
        return {"run_date": d["run_date"], "target_date": r[2], "sku_id": r[0], "fc_id": r[1], "yhat": None,
                "forecast_qty": r[3], "method": None, "product_name": self.qy.name_of(r[0], None),
                "forecast_run_id": d["forecast_run_id"], "export_run_id": d["export_run_id"],
                "model_version": d["model_version"], "session_started_at": None, "published_at": d["published_at"],
                "sel2_source": r[4], "fallback_reason": r[5], "actual_status": x.get("status"),
                "actual_reason": x.get("reason"), "actual_source": x.get("source"), "actual": a,
                "actual_present": None if a is None else int(bool(r[7])), "actual_as_of": x.get("as_of"),
                "forecast_source": SRC_SEL2, "source_label": SRC_SEL2, "snapshot_id": None,
                "snapshot_business_date": None, "snapshot_created_at": None,
                "deviation": None if a is None else r[3] - a, "row_wape": abs(r[3] - a) / a if a else None}

    def rows(self, sort: str = "date", limit: int | None = 100, offset: int = 0):
        """Rows in the order of `sort`. A page: the row groups that hold it, from the group counts (taken in __init__
        for this sort, else here), then ONE pass over the days of those groups (the actuals of a day read once).
        limit None (Excel export, at most MAX_EXPORT_ROWS rows): sort date streams the days one by one (newest first);
        the other sorts merge the per-day sorted rows of the range in memory."""
        if sort not in SEL2_SORTS:
            raise AppError("VALIDATION_ERROR", 422, detail=f"sort must be one of {', '.join(SEL2_SORTS)}")
        ords = {d["run_date"]: date.fromisoformat(d["run_date"]).toordinal() for d in self.active}
        if limit is None:
            yield from self._all(sort, ords, offset)
            return
        g = SEL2_SORTS[sort]
        groups = self.groups if self.sort == sort else None
        if groups is None:
            groups = {}
            for d in self.active:
                for r in self._recs(d):
                    k = _key(sort, r, ords[d["run_date"]])[:g]
                    groups[k] = groups.get(k, 0) + 1
        need, pos, first = set(), 0, None
        for k in sorted(groups):
            n = groups[k]
            if pos + n > offset:
                if first is None:
                    first = pos
                need.add(k)
            pos += n
            if pos >= offset + limit:
                break
        if not need:
            return
        days = None if sort == "sku" else {-k[g - 1] for k in need}     # "sku": a group spans every day
        picked = []
        for d in self.active:
            o = ords[d["run_date"]]
            if days is not None and o not in days:
                continue
            for r in self._recs(d):
                k = _key(sort, r, o)
                if k[:g] in need:
                    picked.append((k, r, d))
        picked.sort(key=lambda t: t[0])
        start = offset - first
        for _k, r, d in picked[start:start + limit]:
            yield self._row(r, d)

    def _all(self, sort: str, ords: dict, offset: int):
        """Every row in the order of `sort` (the Excel export)."""
        n = 0
        if sort == "date":                   # the days in order, one day in memory at a time
            for d in sorted(self.active, key=lambda d: d["run_date"], reverse=True):
                o = ords[d["run_date"]]
                for r in sorted(self._recs(d), key=lambda r: _key(sort, r, o)):
                    if n >= offset:
                        yield self._row(r, d)
                    n += 1
            return
        its = [sorted(((_key(sort, r, ords[d["run_date"]]), r, d) for r in self._recs(d)), key=lambda t: t[0])
               for d in self.active]
        for _k, r, d in heapq.merge(*its, key=lambda t: t[0]):
            if n >= offset:
                yield self._row(r, d)
            n += 1


@router.get("/overview")
def overview(scope_key: str | None = None):
    """Scopes with history, the run dates of the chosen scope with their official session, FC list, today's state."""
    with db.read() as c:
        sk, src, scopes, active = _scope(c, scope_key)
        dl = fh.days(c, sk) if sk else []
        backup = fh.fallback_days(c, sk) if dl else []
        fcs = fh.Query(c, sk).fcs() if dl else []
        bq = ss.get("bigquery", c)
        today = str(fh.today_vn())
        from .. import actual_final
        final_summary = actual_final.summary(c, sk)
        sel2_days = _sel2_days(c, sk)
        forecast_info = sel2_view.info(c, (active or {}).get("scope_key"))   # the info line of the page
    return {"scope_key": sk, "data_source": src, "active_scope_key": (active or {}).get("scope_key"),
            "active_data_source": (active or {}).get("data_source"),
            "scopes": [{**s, "active": s["scope_key"] == (active or {}).get("scope_key")} for s in scopes],
            "days": dl, "backup_days": backup, "fcs": fcs, "today": today,
            "today_session": next((d for d in dl if d["run_date"] == today), None),
            "today_backup": next((d for d in backup if d["run_date"] == today), None),
            "completion_signal_configured": bool(bq.completion_table and bq.completion_date_column)
            if src == "BIGQUERY" else False,
            # 1.2.9 (seventh batch): finalized (frozen) actual days of the scope; only the D-1 source finalizes
            "finalization": {**final_summary, "applicable": src == "BIGQUERY"},
            # 1.4.4: run dates with a published SEL2 run (>= sel2_from); the run dates before keep their 1.3.x source
            "sel2_days": sel2_days, "sel2_from": SEL2_FROM, "forecast_info": forecast_info}


def _query(c, scope_key, run_from, run_to, fc_id, q, actual_status, forecast_source=None):
    sk, _src, _s, _a = _scope(c, scope_key)
    return fh.Query(c, sk, run_from, run_to, fc_id, q, actual_status, forecast_source=forecast_source) if sk else None


def _label(items: list[dict], sp: Sel2Part | None) -> list[dict]:
    """Source label of each run date: SEL2 for a day with a SEL2 publication; any other day keeps its 1.3.x item
    (LIGHTGBM_CU when it has a forecast, e.g. a day >= SEL2_FROM after the emergency switch-off; else a gap)."""
    out = []
    for x in items:
        if sp is not None and x["run_date"] in sp.daily:
            x = sp.daily[x["run_date"]]
        else:
            x = {**x, "source_label": SRC_OLD if x["has_history"] else None}
        out.append(x)
    return out


class Merged:
    """The page's row set as one query for the summary, the rows and the Excel export: the SEL2 days (Sel2Part) first,
    then the 1.3.x rows of the other run dates of the range (one fh.Query per stretch of run dates without a SEL2 day,
    newest first); daily() / kpi() of the whole range. Every other attribute is the 1.3.x query's (filters, scope,
    range, connection)."""

    def __init__(self, c, qy, sp: Sel2Part | None, fc_id, q, actual_status):
        self._qy, self._sp = qy, sp
        if sp is None or not sp.daily:
            self._old = [qy]
            return
        old_dates = sorted({d["run_date"] for d in qy.in_range + qy.backup_in_range} - set(sp.daily), reverse=True)
        sel2 = sorted(sp.daily, reverse=True)
        segs: list[list[str]] = []
        for d in old_dates:                     # stretches of 1.3.x run dates without a SEL2 day in between
            if segs and not any(d < x < segs[-1][-1] for x in sel2):
                segs[-1].append(d)
            else:
                segs.append([d])
        self._old = [fh.Query(c, qy.scope_key, g[-1], g[0], fc_id, q, actual_status) for g in segs]

    def __getattr__(self, name):
        return getattr(self._qy, name)

    def daily(self) -> list[dict]:
        return _label(self._qy.daily(), self._sp)

    def kpi(self, daily: list[dict]) -> dict:
        k = self._qy.kpi(daily)
        k["days_sel2"] = sum(1 for x in daily if x["forecast_source"] == SRC_SEL2)
        return k

    def _parts(self) -> list:
        return ([self._sp] if self._sp is not None and self._sp.daily else []) + self._old

    def count(self) -> int:
        return sum(p.count() for p in self._parts())

    def rows(self, sort: str = "date", limit: int | None = 100, offset: int = 0):
        """Rows of every part in turn (a generator: the Excel export streams them)."""
        out = 0
        for p in self._parts():
            if limit is not None and out >= limit:
                return
            n = p.count()
            if offset >= n:
                offset -= n
                continue
            want = None if limit is None else limit - out
            label = {} if p is self._sp else {"source_label": SRC_OLD}
            for r in p.rows(sort, want, offset):
                out += 1
                yield {**r, **label}
            offset = 0


def _merged(c, scope_key, run_from, run_to, fc_id, q, actual_status, forecast_source, sort=None) -> Merged | None:
    qy = _query(c, scope_key, run_from, run_to, fc_id, q, actual_status, forecast_source)
    if qy is None:
        return None
    sp = None
    if not forecast_source and qy.run_to >= SEL2_FROM:      # a PRIMARY / SNAPSHOT filter: the 1.3.x days only
        _sk, src, _s, _a = _scope(c, scope_key)
        sp = Sel2Part(c, qy, qy.scope_key, src, fc_id, q, actual_status, sort)
    return Merged(c, qy, sp, fc_id, q, actual_status)


@router.get("/summary")
def summary(scope_key: str | None = None, run_from: str | None = None, run_to: str | None = None,
            fc_id: str | None = None, q: str | None = None, actual_status: str | None = None,
            forecast_source: str | None = None):
    """KPI, one chart point per run date of the range (gaps stay gaps), the sessions of those run dates and the
    end-of-day backups used for run dates without a session of their own. 1.4.4: SEL2 days (Merged)."""
    with db.read() as c:
        m = _merged(c, scope_key, run_from, run_to, fc_id, q, actual_status, forecast_source)
        if m is None:
            return {"scope_key": None, "kpi": None, "daily": [], "sessions": [], "backup_days": [],
                    "actual_context": [], "filters": {}}
        daily = m.daily()
        sp = m._sp
        return {"scope_key": m.scope_key, "data_source": m.data_source, "filters": m.filters, "today": str(m.today),
                "kpi": m.kpi(daily), "daily": daily, "sessions": fh.sessions(c, m.scope_key, m.run_from, m.run_to),
                "backup_days": m.backup_in_range,
                "actual_context": list(m.ctx.values()) + (list(sp.ctx.values()) if sp else []),
                "matching_skus": len(m.skus) if m.skus is not None else None, "sel2_from": SEL2_FROM}


@router.get("/rows")
def rows(scope_key: str | None = None, run_from: str | None = None, run_to: str | None = None,
         fc_id: str | None = None, q: str | None = None, actual_status: str | None = None, sort: str = "date",
         limit: int = 100, offset: int = 0, forecast_source: str | None = None):
    """SKU x FC detail of the same filter, one page (limit <= 1000). 1.4.4: the SEL2 rows (run dates >= SEL2_FROM)
    first, then the 1.3.x rows of the run dates before SEL2_FROM (source_label LIGHTGBM_CU)."""
    limit, offset = max(1, min(int(limit), 1000)), max(0, int(offset))
    with db.read() as c:
        m = _merged(c, scope_key, run_from, run_to, fc_id, q, actual_status, forecast_source, sort)
        if m is None:
            return {"total": 0, "rows": [], "filters": {}}
        return {"total": m.count(), "rows": list(m.rows(sort, limit, offset)), "filters": m.filters, "sort": sort}


@router.get("/export.xlsx")
def export(scope_key: str | None = None, run_from: str | None = None, run_to: str | None = None,
           fc_id: str | None = None, q: str | None = None, actual_status: str | None = None, sort: str = "date",
           lang: str = "vi", forecast_source: str | None = None):
    """Excel of ALL rows of the current filter (Info, sessions, per day, SKU x FC detail) in the UI language. 1.4.4:
    the same rows, days and KPI as the page (SEL2 from SEL2_FROM, Merged)."""
    from ..export_i18n import history_labels
    lang, L = history_labels(lang)
    with db.read() as c:
        qy = _merged(c, scope_key, run_from, run_to, fc_id, q, actual_status, forecast_source)
        if qy is None:
            raise AppError("NO_ACTIVE_DATASET", 409)
        # fh.export_xlsx refuses more than MAX_EXPORT_ROWS on qy.count() (SEL2: the counts of the streamed days)
        # before any row is built
        content = fh.export_xlsx(qy, L, sort)
    name = f"forecast-history-{qy.data_source or 'NA'}-{qy.run_from}-{qy.run_to}-{lang}.xlsx"
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
