"""1.4.6 C4: the forecast pages show the 20 days of the daily Excel (horizon 1..7 SEL2, 8..20 weekly estimate with
cach_tinh UOC_TINH_THEO_TUAN) with exactly the numbers of the file, and a target-date filter FROM - TO (api/sel2_view.py,
api/daily_routes.py). Integration with fakes (isolated temporary database and data folder, rows inserted directly,
TestClient)."""
import random
from datetime import date, timedelta

from openpyxl import load_workbook

from app import paths
from app.api import daily_routes, sel2_view
from app.ml.sel2 import export
from test_v144_ui_data import D, SC, SCOPE, _big_scenario, _same, scenario  # noqa: F401  (fixture)

COLS = ("sku_code", "ten_san_pham", "seller_code", "product_code", "fc_code", "nhom", "target_date", "horizon",
        "lightgbm_forecast", "avg_demand", "forecast_source", "forecast_used", "fallback_reason", "model_used",
        "raw_value", "model_version", "is_stale", "flags", "cach_tinh")


def _excel20(d: date) -> dict:
    """{(sku, fc, horizon): row} of every DU_BAO_* sheet of the daily Excel of d (horizon 1..20)."""
    res = export.write_daily_export(d, scope_key=SCOPE)
    wb = load_workbook(paths.data_dir() / res["path"], read_only=True)
    out = {}
    for name in wb.sheetnames:
        if name.startswith("DU_BAO_"):
            rows = list(wb[name].iter_rows(values_only=True))
            for r in rows[1:]:
                x = dict(zip(rows[0], r))
                out[(x["sku_code"], x["fc_code"], x["horizon"])] = x
    wb.close()
    return out


def _want(x: dict, c: str):
    v = x[c]
    return v.date().isoformat() if c == "target_date" and v is not None else v


def _daily_all(client, run_id: str, extra: str = "") -> dict:
    got, page = {}, 0
    while True:
        r = client.get(f"/api/daily-forecast/values?run_id={run_id}&page={page}{extra}").json()
        for x in r["rows"]:
            got[(x["sku_code"], x["fc_code"], x["horizon"])] = x
        page += 1
        if page * r["page_size"] >= r["total"]:
            return got


def _totals(xl: dict, h_max: int = 20, lo: str | None = None, hi: str | None = None) -> dict:
    out: dict = {}
    for x in xl.values():
        d = x["target_date"].date().isoformat()
        if x["horizon"] <= h_max and (not lo or d >= lo) and (not hi or d <= hi):
            out[d] = out.get(d, 0) + x["forecast_used"]
    return out


def test_daily_page_shows_20_days_equal_excel(scenario, client):
    xl = _excel20(D)
    assert {k[2] for k in xl} == set(range(1, 21))
    r = client.get("/api/daily-forecast/values?run_id=R1").json()
    assert r["horizons"] == list(range(1, 21)) and r["estimate_from"] == 8 and r["total"] == len(xl) == 6 * 20
    got = _daily_all(client, "R1")
    assert set(got) == set(xl)
    for k, x in xl.items():
        for c in COLS:
            assert _same(got[k][c], _want(x, c)), (k, c, got[k][c], x[c])
        assert got[k]["final_qty"] == x["forecast_used"]
        assert got[k]["cach_tinh"] == (export.CACH_SEL2 if k[2] <= 7 else export.CACH_WEEK)
    # one horizon of the estimate
    r = client.get("/api/daily-forecast/values?run_id=R1&horizon=15").json()
    assert r["total"] == 6 and all(x["horizon"] == 15 and x["cach_tinh"] == export.CACH_WEEK for x in r["rows"])


def test_daily_page_date_filter(scenario, client):
    xl = _excel20(D)
    lo, hi = (D + timedelta(days=5)).isoformat(), (D + timedelta(days=9)).isoformat()   # horizon 6..10
    got = _daily_all(client, "R1", f"&date_from={lo}&date_to={hi}")
    want = {k for k, x in xl.items() if lo <= x["target_date"].date().isoformat() <= hi}
    assert set(got) == want and {k[2] for k in got} == {6, 7, 8, 9, 10}
    for k in want:
        assert got[k]["forecast_used"] == xl[k]["forecast_used"]
    only_from = _daily_all(client, "R1", f"&date_from={(D + timedelta(days=19)).isoformat()}")
    assert {k[2] for k in only_from} == {20}
    assert client.get(f"/api/daily-forecast/values?run_id=R1&date_to={(D - timedelta(days=1)).isoformat()}").json()["total"] == 0
    assert client.get("/api/daily-forecast/values?run_id=R1&date_from=05-11-2026").status_code == 422


def test_results_summary_20_days_and_date_filter_equal_excel(scenario, client):
    xl = _excel20(D)
    s = client.get("/api/daily-forecast/sel2-summary?run_id=R1&horizon=20&limit=1000").json()
    assert s["run"]["horizons"] == list(range(1, 21)) and s["run"]["max_horizon"] == 20 and s["run"]["estimate_from"] == 8
    assert {d["target_date"]: d["total"] for d in s["daily"]} == _totals(xl)
    assert [d["cach_tinh"] for d in s["daily"]] == [export.CACH_SEL2] * 7 + [export.CACH_WEEK] * 13
    assert s["grand_total"] == sum(x["forecast_used"] for x in xl.values())
    assert (s["start_date"], s["end_date"]) == (D.isoformat(), (D + timedelta(days=19)).isoformat())
    for one in s["series"]:
        assert one["total"] == sum(xl[(one["sku_id"], one["fc_id"], h)]["forecast_used"] for h in range(1, 21))
    # default stays horizon 1..7 (the numbers of 1.4.5)
    s7 = client.get("/api/daily-forecast/sel2-summary?run_id=R1").json()
    assert s7["horizon"] == 7 and {d["target_date"]: d["total"] for d in s7["daily"]} == _totals(xl, 7)
    # date filter inside horizon 1..h
    lo, hi = (D + timedelta(days=3)).isoformat(), (D + timedelta(days=12)).isoformat()
    f = client.get(f"/api/daily-forecast/sel2-summary?run_id=R1&horizon=10&date_from={lo}&date_to={hi}&limit=1000").json()
    assert {d["target_date"]: d["total"] for d in f["daily"]} == _totals(xl, 10, lo, hi)
    assert (f["start_date"], f["end_date"]) == (lo, (D + timedelta(days=9)).isoformat())
    for one in f["series"]:
        assert one["total"] == sum(xl[(one["sku_id"], one["fc_id"], h)]["forecast_used"] for h in range(4, 11))
    # a range outside the horizons: nothing, no error
    e = client.get(f"/api/daily-forecast/sel2-summary?run_id=R1&horizon=3&date_from={hi}").json()
    assert e["daily"] == [] and e["grand_total"] == 0 and e["start_date"] is None
    assert e["actual"]["in_horizon"] is False
    assert client.get("/api/daily-forecast/sel2-summary?horizon=21").status_code == 422


def test_results_detail_20_days_and_date_filter_equal_excel(scenario, client):
    xl = _excel20(D)
    r = client.get("/api/daily-forecast/sel2-values?run_id=R1&horizon=20&sku_id=S1&fc_id=F1&limit=100").json()
    assert r["total"] == 20 and [x["horizon_day"] for x in r["rows"]] == list(range(1, 21))
    for x in r["rows"]:
        e = xl[("S1", "F1", x["horizon"])]
        for c in COLS:
            assert _same(x[c], _want(e, c)), (x["horizon"], c, x[c], e[c])
        assert x["forecast_qty"] == e["forecast_used"]
        assert x["weekday"] == date.fromisoformat(x["target_date"]).isoweekday()
    lo, hi = (D + timedelta(days=6)).isoformat(), (D + timedelta(days=8)).isoformat()
    r = client.get(f"/api/daily-forecast/sel2-values?run_id=R1&horizon=20&date_from={lo}&date_to={hi}&limit=1000").json()
    assert {x["horizon"] for x in r["rows"]} == {7, 8, 9} and r["total"] == 6 * 3
    assert {x["horizon"]: x["cach_tinh"] for x in r["rows"]} == {7: export.CACH_SEL2, 8: export.CACH_WEEK,
                                                                  9: export.CACH_WEEK}
    assert client.get("/api/daily-forecast/sel2-values?horizon=21").status_code == 422


def test_random_50_sku_fc_20_days_equal_excel(sel2_on, client, monkeypatch):
    """50 random SKU x FC of a mixed day (R1 / R2 / R3' / R3'' / R4 / NULL AVG / PENDING): horizon 1..20 of the Results
    detail, the Daily Forecast rows and the daily totals equal the daily Excel, column by column."""
    sel2_view.clear_cache()
    monkeypatch.setattr(daily_routes, "_scope", lambda c: dict(SC))
    monkeypatch.setattr(export, "_scope_key", lambda conn: (SCOPE, None))
    _big_scenario()
    xl = _excel20(D)
    xkeys = sorted({(k[0], k[1]) for k in xl})
    assert {export.REASON_OUT_ZERO, export.REASON_PREVIOUS, export.REASON_NO_NUMBER} <= \
        {x["fallback_reason"] for x in xl.values() if x["horizon"] > 7}          # the mix reaches the estimate days
    for k in random.Random(5).sample(xkeys, 50):
        r = client.get(f"/api/daily-forecast/sel2-values?run_id=RC&sku_id={k[0]}&fc_id={k[1]}&horizon=20&limit=20").json()
        assert r["total"] == 20
        for x in r["rows"]:
            e = xl[(k[0], k[1], x["horizon"])]
            for c in COLS:
                assert _same(x[c], _want(e, c)), (k, x["horizon"], c, x[c], e[c])
        d = client.get(f"/api/daily-forecast/values?run_id=RC&q={k[0]}").json()
        got = {(x["sku_code"], x["fc_code"], x["horizon"]): x for x in d["rows"]}
        for h in range(1, 21):
            assert got[(k[0], k[1], h)]["forecast_used"] == xl[(k[0], k[1], h)]["forecast_used"]
    s = client.get("/api/daily-forecast/sel2-summary?run_id=RC&horizon=20&limit=1000").json()
    assert {x["target_date"]: x["total"] for x in s["daily"]} == _totals(xl)
    assert s["grand_total"] == sum(x["forecast_used"] for x in xl.values())
    assert client.get("/api/daily-forecast/values?run_id=RC").json()["total"] == len(xl) == len(xkeys) * 20


def test_non_sel2_run_date_filter(sel2_on, client, monkeypatch):
    """A 1.3.1 refresh run (not SEL2): the date filter applies to its stored rows; no estimate days."""
    from test_v144_ui_data import _run
    monkeypatch.setattr(daily_routes, "_scope", lambda c: dict(SC))
    sel2_view.clear_cache()
    _run("OLD1", D, {("S1", "F1"): ("A", "LGBM", {h: (h, h - 0.4) for h in range(1, 8)})}, cv="v131:abc")
    r = client.get(f"/api/daily-forecast/values?run_id=OLD1&date_from={(D + timedelta(days=2)).isoformat()}"
                   f"&date_to={(D + timedelta(days=3)).isoformat()}").json()
    assert "sel2" not in r and "estimate_from" not in r and [x["horizon"] for x in r["rows"]] == [3, 4]
