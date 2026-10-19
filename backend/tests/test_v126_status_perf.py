"""1.2.7 (dashboard load hotfix on top of 1.2.6): the system status (every page, and the dashboard) no longer reads demand_daily row by row.

The freshness aggregate of system_status() went through the primary-key index, which does not hold loaded_at, so
SQLite fetched every row of the scope again for MAX(loaded_at): 1.35 M random lookups, 7.5 s on a warm copy of the
production database and 45-66 s on the production PC. It is now one sequential scan with the same values. The dashboard
page loads its forecast card from /api/forecast-runs/{id}/summary, which must give exactly what /api/dashboard gives."""
from app import db
from app.api.ops_routes import system_status
from app.data.demand import resolve_scope
from app.timeutil import today_vn

# the two statements before the hotfix, kept here as the reference for the values
OLD = ("SELECT MAX(order_date) AS max_date, MIN(order_date) AS min_date, COUNT(*) AS n, MAX(loaded_at) AS loaded_at "
       "FROM demand_daily WHERE scope_key=?")
OLD_WINDOW = ("SELECT COUNT(*) AS n, MIN(order_date) AS min_date, MAX(order_date) AS max_date FROM demand_daily "
              "WHERE scope_key=? AND order_date BETWEEN ? AND ?")


def _reference(scope_key: str) -> dict:
    with db.read() as c:
        return db.one(c, OLD, (scope_key,))


def _reference_window(scope_key: str, start, end) -> dict:
    with db.read() as c:
        return db.one(c, OLD_WINDOW, (scope_key, start, end))


def _traced(monkeypatch) -> list[str]:
    seen: list[str] = []
    real = db.connect

    def connect(*a, **k):
        c = real(*a, **k)
        c.set_trace_callback(seen.append)
        return c
    monkeypatch.setattr(db, "connect", connect)
    return seen


def test_freshness_values_equal_the_old_statement(small_demo):
    sk = resolve_scope()["scope_key"]
    with db.tx() as c:
        # another scope with later loads must not count, and the newest load of this scope sits in the middle of the key
        # order (MAX(loaded_at) is not the last row's)
        c.execute("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, loaded_at) "
                  "SELECT 'OTHER-SCOPE', 'MANUAL_IMPORT', order_date, sku_id, fc_id, qty, '2099-01-01T00:00:00+00:00' "
                  "FROM demand_daily WHERE scope_key=? LIMIT 50", (sk,))
        mid = c.execute("SELECT order_date, sku_id, fc_id FROM demand_daily WHERE scope_key=? ORDER BY order_date "
                        "LIMIT 1 OFFSET 100", (sk,)).fetchone()
        c.execute("UPDATE demand_daily SET loaded_at='2030-05-05T05:05:05+00:00' WHERE scope_key=? AND order_date=? "
                  "AND sku_id=? AND fc_id=?", (sk, *mid))
        # one day before the model-input window and one after it (today): in the scope's totals, not in the window's
        for day in ("2020-01-01", str(today_vn())):
            c.execute("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, loaded_at) "
                      "VALUES (?, 'DEMO', ?, 'SKU-OUT', 'FC-OUT', 1, '2026-01-01T00:00:00+00:00')", (sk, day))
    st = system_status()
    fresh, win = st["freshness"], st["data_window"]
    ref = _reference(sk)
    assert ref["n"] > 1000 and ref["loaded_at"] == "2030-05-05T05:05:05+00:00"
    assert (fresh["max_date"], fresh["min_date"], fresh["rows"], fresh["loaded_at"]) == (
        ref["max_date"], ref["min_date"], ref["n"], ref["loaded_at"])
    rw = _reference_window(sk, win["start"], win["end"])
    assert 0 < rw["n"] == ref["n"] - 2 and fresh["min_date"] == "2020-01-01" < rw["min_date"]
    assert (fresh["window_rows"], fresh["window_min_date"], fresh["window_max_date"]) == (
        rw["n"], rw["min_date"], rw["max_date"])
    assert fresh["lag_days"] >= 0


def test_freshness_of_a_scope_without_rows_is_unchanged(small_demo):
    sk = resolve_scope()["scope_key"]
    with db.tx() as c:
        c.execute("DELETE FROM demand_daily WHERE scope_key=?", (sk,))
    fresh = system_status()["freshness"]
    ref = _reference(sk)
    assert ref == {"max_date": None, "min_date": None, "n": 0, "loaded_at": None}
    assert (fresh["max_date"], fresh["min_date"], fresh["rows"], fresh["loaded_at"]) == (None, None, 0, None)
    assert (fresh["window_rows"], fresh["window_min_date"], fresh["window_max_date"]) == (0, None, None)
    assert "lag_days" not in fresh and "stale" not in fresh


def test_the_status_reads_demand_daily_once_and_never_row_by_row(small_demo, monkeypatch):
    """Regression guard: one plain scan of demand_daily per status, never a per-row lookup through the index (and no
    second pass over the index for the window)."""
    seen = _traced(monkeypatch)
    system_status()
    reads = [s for s in seen if "FROM demand_daily" in s]
    assert len(reads) == 1, reads
    with db.read() as c:   # the trace gives the statement with its values filled in
        plan = [r[3] for r in c.execute("EXPLAIN QUERY PLAN " + reads[0]).fetchall()]
    assert plan == ["SCAN demand_daily"], plan


def test_dashboard_card_from_the_summary_endpoint_equals_api_dashboard(client, fast_model):
    """The page now asks /api/forecast-runs/{id}/summary?horizon=min(h, max)&limit=10 itself: same figures."""
    assert client.post("/api/demo/generate", json={"days": 150, "n_skus": 8, "seed": 3}).status_code == 200
    j = client.post("/api/training/run", json={}).json()
    assert j["status"] == "SUCCEEDED" and j["reason_code"] == "FORECAST_PUBLISHED", j
    st = client.get("/api/system/status").json()
    run = st["latest_forecast_run"]
    for h in (7, 15, run["max_horizon"], run["max_horizon"] + 30):
        dash = client.get(f"/api/dashboard?horizon={h}").json()
        hr = min(h, run["max_horizon"])
        card = client.get(f"/api/forecast-runs/{run['id']}/summary?horizon={hr}&limit=10").json()
        assert card == dash["forecast"], h
        assert dash["system"]["freshness"] == st["freshness"]
