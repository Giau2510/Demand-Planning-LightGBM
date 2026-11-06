"""1.4.4 T2: the forecast pages read the published SEL2 run with the numbers of the daily Excel (api/sel2_view.py),
the history page uses SEL2 from 04/11/2026 (api/history_routes.py), the SEL2 refresh job refreshes actual_daily
(ml/sel2/jobs.actual_refresh) and the info line (/api/forecast-info). Integration with fakes (isolated temporary
database, rows inserted directly, TestClient)."""
from datetime import date, timedelta

import pytest
from openpyxl import load_workbook

from app import db, paths
from app import settings_service as ss
from app.api import daily_routes, history_routes, sel2_view
from app.ml.sel2 import export, jobs

D = date(2026, 11, 5)
SCOPE = "SC-V144"
SC = {"scope_key": SCOPE, "data_source": "BIGQUERY"}
KEYS = ("forecast_used", "lightgbm_forecast", "avg_demand", "forecast_source", "fallback_reason", "model_used",
        "raw_value", "nhom", "flags", "model_version")


def _run(run_id, fdate: date, series: dict, created="2026-11-04T23:30:00+00:00", cv="SEL2:abcdef012345"):
    """series {(sku, fc): (group, method, {horizon: (qty, raw)})}: one run published for fdate."""
    with db.tx() as c:
        c.execute("INSERT INTO forecast_refresh_runs(id, scope_key, forecast_date, data_as_of, status, trigger, "
                  "model_version, config_version, trial_mode, horizon, n_series, n_lightgbm, n_fallback, created_at, "
                  "detail_json) VALUES (?,?,?,?, 'PUBLISHED', 'test', ?, ?, 0, 7, ?, ?, 0, ?, '{}')",
                  (run_id, SCOPE, fdate.isoformat(), (fdate - timedelta(days=1)).isoformat(), f"MV-{run_id}", cv,
                   len(series), len(series), created))
        for (sku, fc), (grp, method, hs) in series.items():
            for h, (qty, raw) in hs.items():
                c.execute("INSERT INTO forecast_refresh_values(run_id, horizon, target_date, fc_code, sku_code, lgb_raw, "
                          "final_qty, method, group_code, flags) VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (run_id, h, (fdate + timedelta(days=h - 1)).isoformat(), fc, sku, raw, qty, method, grp,
                           None))


def _avg(day: date, rows):
    """rows [(sku, fc, seller, value, name)] stored as the CURRENT read of day."""
    table = ss.get("sel2_pipeline").avg_demand_table
    with db.tx() as c:
        c.executemany("INSERT INTO avg_demand_daily(business_date, sku_code, fc_code, seller_code, avg_demand, "
                      "product_name, source_table, source_modified, loaded_at) VALUES (?,?,?,?,?,?,?,?,?)",
                      [(day.isoformat(), s, f, sel, v, n, table, "2026-11-05T03:15:00+00:00",
                        "2026-11-05T03:20:00+00:00") for s, f, sel, v, n in rows])
        c.execute("INSERT INTO avg_demand_reads(id, source_table, business_date, kind, n_rows, source_modified, "
                  "completed_at) VALUES (?,?,?, 'CURRENT', ?, ?, ?)",
                  (db.new_id("ADR"), table, day.isoformat(), len(rows), "2026-11-05T03:15:00+00:00",
                   "2026-11-05T03:20:00+00:00"))


def _config(rows):
    with db.tx() as c:
        c.executemany("INSERT INTO forecast_source_config(sku_code, fc_code, forecast_source, ghi_chu, updated_by, "
                      "updated_at) VALUES (?,?,?,?, 'tester', '2026-11-01T01:00:00+00:00')", rows)


def _demand(rows):
    """rows [(day, sku, fc, qty)] of the scope (D-1 data)."""
    with db.tx() as c:
        c.executemany("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, loaded_at) "
                      "VALUES (?, 'BIGQUERY', ?, ?, ?, ?, '2026-11-05T01:00:00+00:00')",
                      [(SCOPE, d.isoformat(), s, f, q) for d, s, f, q in rows])


@pytest.fixture
def scenario(sel2_on, monkeypatch):
    """Run R1 of D (S1 LIGHTGBM full, S2 AVG default full, S3 LIGHTGBM horizons 1-5 with zeros, S6 in BD), a previous
    run R0 of D-1 (S3 horizons 6-8 -> R3' numbers), AVG of D (S1, S2, S4 LIGHTGBM outside the run, S5 two sellers)."""
    sel2_view.clear_cache()
    monkeypatch.setattr(daily_routes, "_scope", lambda c: dict(SC))
    monkeypatch.setattr(history_routes, "resolve_scope", lambda c: dict(SC))
    monkeypatch.setattr(export, "_scope_key", lambda conn: (SCOPE, None))
    full = {h: (h, h - 0.4) for h in range(1, 8)}
    _run("R0", D - timedelta(days=1), {("S3", "F1"): ("C", "OLDM", {h: (10 + h, 10 + h - 0.5) for h in range(1, 9)}),
                                       ("S7", "F1"): ("B", "OLDM", {h: (1, 0.9) for h in range(1, 9)})},
         created="2026-11-03T23:30:00+00:00")
    _run("R1", D, {("S1", "F1"): ("A", "MOC+DOW4", full), ("S2", "F1"): ("B", "FALLBACK:V33_L112", full),
                   ("S3", "F1"): ("C", "V36_two_stage@0.6+TSB", {h: (0, 0.1) for h in range(1, 6)}),
                   ("S6", "BD"): ("A", "MOC", {h: (2, 1.7) for h in range(1, 8)})})
    _avg(D, [("S1", "F1", "SL1", 2.5, "Thuoc A"), ("S2", "F1", "SL1", 4.0, "Thuoc B"),
             ("S4", "F1", "SL1", 3.0, "Thuoc D"), ("S5", "F1", "SL1", 1.0, "Thuoc E"),
             ("S5", "F1", "SL2", 2.0, "Thuoc E"), ("S6", "BD", "SL1", 0.1, "Thuoc F")])
    _config([("S1", "F1", "LIGHTGBM", None), ("S3", "F1", "LIGHTGBM", None), ("S4", "F1", "LIGHTGBM", None),
             ("S6", "BD", "LIGHTGBM", None)])
    yield
    sel2_view.clear_cache()


def _excel_rows(d: date) -> dict:
    """{(sku, fc, horizon): row} of horizon 1..7 of the daily Excel of d (1.4.4: sheets DU_BAO_<fc_code>)."""
    res = export.write_daily_export(d, scope_key=SCOPE)
    wb = load_workbook(paths.data_dir() / res["path"], read_only=True)
    out = {}
    for name in wb.sheetnames:
        if name.startswith("DU_BAO_"):
            rows = list(wb[name].iter_rows(values_only=True))
            cols = list(rows[0])
            for r in rows[1:]:
                x = dict(zip(cols, r))
                if x["horizon"] <= 7:
                    out[(x["sku_code"], x["fc_code"], x["horizon"])] = x
    return out


def _publish(*days):
    """1.4.4: the daily Excel of each day (the publication the history page reads: its horizon-2 sidecar file,
    ml/sel2/published.py)."""
    for d in days:
        export.write_daily_export(d, scope_key=SCOPE)


def _same(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        return a is not None and b is not None and abs(float(a) - float(b)) < 1e-9
    return a == b


def test_daily_values_equal_excel(scenario, client):
    xl = _excel_rows(D)
    got, page = {}, 0
    while True:
        r = client.get(f"/api/daily-forecast/values?run_id=R1&page={page}").json()
        assert r["sel2"] is True and r["horizons"] == list(range(1, 8))
        for x in r["rows"]:
            got[(x["sku_code"], x["fc_code"], x["horizon"])] = x
        page += 1
        if page * r["page_size"] >= r["total"]:
            break
    assert set(got) == set(xl) and len(got) == 6 * 7          # union of the run and the AVG rows (S1..S6)
    for k, x in xl.items():
        for c in KEYS:
            assert _same(got[k][c], x[c]), (k, c, got[k][c], x[c])
        assert got[k]["final_qty"] == x["forecast_used"] and got[k]["method"] == x["model_used"]
    # the fixed rule really ran: R2 outside the scope, R3' previous run, AVG default
    assert got[("S4", "F1", 1)]["fallback_reason"] == export.REASON_OUT_ZERO
    assert got[("S3", "F1", 6)]["fallback_reason"] == export.REASON_PREVIOUS
    assert got[("S2", "F1", 1)]["forecast_source"] == "AVG_DEMAND" and got[("S2", "F1", 1)]["forecast_used"] == 4
    # filters: one horizon, a group, a search
    r = client.get("/api/daily-forecast/values?run_id=R1&horizon=3&group=A").json()
    assert {(x["sku_code"], x["horizon"]) for x in r["rows"]} == {("S1", 3), ("S6", 3)}
    r = client.get("/api/daily-forecast/values?q=thuoc%20b").json()      # latest run, product name search
    assert r["run"]["id"] == "R1" and {x["sku_code"] for x in r["rows"]} == {"S2"} and r["total"] == 7


def test_results_summary_totals_equal_excel(scenario, client):
    xl = _excel_rows(D)
    s = client.get("/api/daily-forecast/sel2-summary?horizon=7").json()
    assert s["run"]["id"] == "R1" and s["run"]["sel2"] is True and s["n_series"] == 6
    for d in s["daily"]:
        assert d["total"] == sum(x["forecast_used"] for x in xl.values()
                                 if x["target_date"].date().isoformat() == d["target_date"])
    assert s["grand_total"] == sum(x["forecast_used"] for x in xl.values())
    one = next(x for x in s["series"] if (x["sku_id"], x["fc_id"]) == ("S1", "F1"))
    assert one["total"] == sum(xl[("S1", "F1", h)]["forecast_used"] for h in range(1, 8))
    s3 = client.get("/api/daily-forecast/sel2-summary?horizon=3&fc_id=BD").json()
    assert s3["n_series"] == 1 and s3["grand_total"] == sum(xl[("S6", "BD", h)]["forecast_used"] for h in (1, 2, 3))
    v = client.get("/api/daily-forecast/sel2-values?horizon=2&sku_id=S1&limit=10").json()
    assert v["total"] == 2 and [x["forecast_qty"] for x in v["rows"]] == \
        [xl[("S1", "F1", h)]["forecast_used"] for h in (1, 2)]
    assert v["rows"][0]["weekday"] == date.fromisoformat(v["rows"][0]["target_date"]).isoweekday()


def test_non_sel2_run_keeps_1_3_1_rows(sel2_on, client, monkeypatch):
    """A 1.3.1 refresh run (config_version not SEL2) is shown as stored, without the export columns."""
    monkeypatch.setattr(daily_routes, "_scope", lambda c: dict(SC))
    sel2_view.clear_cache()
    _run("OLD1", D, {("S1", "F1"): ("A", "LGBM", {1: (5, 4.6)})}, cv="v131:abc")
    r = client.get("/api/daily-forecast/values?run_id=OLD1").json()
    assert "sel2" not in r and r["rows"][0]["final_qty"] == 5 and "forecast_used" not in r["rows"][0]
    assert client.get("/api/daily-forecast/sel2-summary").json()["run"] is None


def test_forecast_info_line(scenario, client):
    r = client.get("/api/forecast-info").json()
    assert r == {"source": "SEL2", "run_id": "R1", "refreshed_at": "2026-11-05 06:30:00",
                 "data_cutoff_date": "2026-11-04", "forecast_date": "2026-11-05"}


def test_forecast_info_without_sel2(sel2_on, client, monkeypatch):
    monkeypatch.setattr(daily_routes, "_scope", lambda c: dict(SC))
    assert client.get("/api/forecast-info").json()["source"] is None
    _avg(D, [("S1", "F1", "SL1", 2.5, "Thuoc A")])
    r = client.get("/api/forecast-info").json()
    assert r["source"] == "AVG" and r["refreshed_at"] == "2026-11-05 10:20:00" and r["forecast_date"] == "2026-11-05"


def test_history_uses_sel2_from_0411(scenario, client):
    """Run dates >= 04/11: forecast_used of horizon 2 (target run date + 1) of that day's SEL2 run vs the D-1 actual
    (an SKU x FC without a row on a read day = 0); before 04/11: no SEL2 (1.3.x source unchanged)."""
    _run("R03", date(2026, 11, 3), {("S1", "F1"): ("A", "M", {h: (50, 50.0) for h in range(1, 8)})},
         created="2026-11-02T23:30:00+00:00")             # before SEL2_FROM: never a SEL2 day
    _demand([(D, "S3", "F1", 3.0), (D, "S9", "F1", 1.0), (D + timedelta(days=1), "S2", "F1", 7.0)])
    _publish(date(2026, 11, 3), D - timedelta(days=1), D)   # 03/11 is exported too: before SEL2_FROM, never SEL2
    ov = client.get("/api/history/overview").json()
    assert ov["sel2_from"] == "2026-11-04" and [d["run_date"] for d in ov["sel2_days"]] == ["2026-11-05", "2026-11-04"]
    s = client.get("/api/history/summary?run_from=2026-11-01&run_to=2026-11-05").json()
    by = {x["run_date"]: x for x in s["daily"]}
    assert by["2026-11-03"]["source_label"] is None and by["2026-11-03"]["has_history"] is False
    d4, d5 = by["2026-11-04"], by["2026-11-05"]
    assert d4["source_label"] == "SEL2" and d4["forecast_run_id"] == "R0" and d4["target_date"] == "2026-11-05"
    assert d5["forecast_run_id"] == "R1" and d5["target_date"] == "2026-11-06"
    xl5 = _excel_rows(D)                                   # the expected values come from the Excel of the day
    assert d5["forecast"] == sum(x["forecast_used"] for k, x in xl5.items() if k[2] == 2)
    rows = client.get("/api/history/rows?run_from=2026-11-04&run_to=2026-11-05&limit=1000").json()
    r4 = {(x["sku_id"], x["fc_id"]): x for x in rows["rows"] if x["run_date"] == "2026-11-04"}
    assert all(x["source_label"] == "SEL2" for x in rows["rows"])
    assert set(r4) == {("S3", "F1"), ("S7", "F1")}         # the run of 04/11 (no AVG read that day)
    assert r4[("S3", "F1")]["forecast_qty"] == 12              # horizon 2 of R0, LIGHTGBM (R1)
    assert r4[("S3", "F1")]["actual"] == 3.0 and r4[("S3", "F1")]["actual_present"] == 1
    assert r4[("S7", "F1")]["actual"] == 0 and r4[("S7", "F1")]["actual_present"] == 0   # read day, no row -> 0
    assert d4["actual"] == sum(x["actual"] for x in r4.values()) and d4["n_rows"] == len(r4)
    r5 = [x for x in rows["rows"] if x["run_date"] == "2026-11-05"]
    assert {x["actual"] for x in r5 if x["sku_id"] == "S2"} == {7.0}
    assert rows["total"] == len(rows["rows"])
    # a PRIMARY / SNAPSHOT filter keeps the 1.3.x days only
    s = client.get("/api/history/summary?run_from=2026-11-04&run_to=2026-11-05&forecast_source=PRIMARY").json()
    assert all(x["forecast_source"] != "SEL2" for x in s["daily"])


def test_actual_daily_refreshed_by_sel2_refresh(sel2_on, monkeypatch):
    """jobs.refresh (SEL2 mode) writes actual_daily D-14 .. D-1 from demand_daily; a second refresh gives the same
    rows (idempotent) and a day outside the range is never touched."""
    with db.tx() as c:
        c.execute("INSERT INTO actual_daily(scope_key, date, fc_code, sku_code, demand, total_open_hours, updated_at) "
                  "VALUES (?, '2026-10-01', 'F1', 'S1', 9, NULL, '2026-10-02T00:00:00+00:00')", (SCOPE,))
    _demand([(D - timedelta(days=1), "S1", "F1", 3.0), (D - timedelta(days=2), "S2", "F1", 0.0),
             (D - timedelta(days=20), "S1", "F1", 8.0), (D, "S1", "F1", 4.0)])
    import app.data.demand as demand_mod
    monkeypatch.setattr(demand_mod, "resolve_scope", lambda c: dict(SC))
    monkeypatch.setattr(jobs, "call_cli", lambda args, cancel=None, timeout=None:
                        {"ok": True, "result": {"status": "PUBLISHED", "run_id": "RX"}, "exit_code": 0})
    out = jobs.refresh("J1", {"business_date": D.isoformat()}, trigger="MANUAL")
    assert out["status"] == "PUBLISHED" and out["actual_daily"]["rows"] == 2
    assert (out["actual_daily"]["start"], out["actual_daily"]["end"]) == ("2026-10-22", "2026-11-04")

    def rows():
        with db.read() as c:
            return [tuple(r) for r in c.execute("SELECT date, fc_code, sku_code, demand FROM actual_daily "
                                                "WHERE scope_key=? ORDER BY date, sku_code", (SCOPE,))]
    first = rows()
    assert first == [("2026-10-01", "F1", "S1", 9.0), ("2026-11-03", "F1", "S2", 0.0), ("2026-11-04", "F1", "S1", 3.0)]
    jobs.refresh("J2", {"business_date": D.isoformat()}, trigger="MANUAL")
    assert rows() == first


def test_actual_refresh_failure_never_blocks(sel2_on, monkeypatch):
    from app.ml import daily_refresh

    def boom(*a, **k):
        raise RuntimeError("disk")
    monkeypatch.setattr(daily_refresh, "refresh_actual_daily", boom)
    out = jobs.actual_refresh(D, dict(SC))
    assert out["rows"] is None and "RuntimeError" in out["error"]


# ---------------------------------------------------------------------------------------------------------- tester T2
# Independent tests (tester 144-T2-test). Integration with fakes: isolated temporary database, synthetic rows only.
import io  # noqa: E402
import random  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

from app import timeutil  # noqa: E402
from app.ml import daily_refresh  # noqa: E402
from app.ml.sel2 import source_config  # noqa: E402

SEL2_COLS = KEYS + ("lightgbm_forecast", "ten_san_pham", "seller_code", "product_code", "data_cutoff_date", "is_stale")


def _big_scenario(seed: int = 7, n: int = 240):
    """Random synthetic day D: run RA of D-4 (outside D-3 .. D-1: never used), RB of D-2 (horizons 1..9), RC of D with
    missing horizons, zeros and missing raw values; AVG rows with NULL values and two sellers (rule PENDING); a
    LIGHTGBM / AVG_DEMAND configuration that also names SKU x FC outside the run (R2). Returns the SKU x FC list."""
    rng = random.Random(seed)
    fcs = ("F1", "F2", "HN")
    keys = [(f"SL{i % 5}.P{i:04d}", fcs[i % 3]) for i in range(n)]
    ra = {k: ("A", "OLDM", {h: (rng.randint(0, 9), rng.random() * 9) for h in range(1, 12)}) for k in keys[:60]}
    rb = {k: ("B", "MOC", {h: (rng.randint(0, 20), round(rng.random() * 20, 3)) for h in range(1, 10)})
          for k in keys[20:150]}
    rc = {}
    for k in keys[40:200]:
        hs = {}
        for h in range(1, 8):
            if rng.random() < 0.2:
                continue                                    # missing horizon -> R3' from RB, else R3'' / R4
            q = rng.choice((0, 0, rng.randint(1, 30)))
            hs[h] = (q, None if rng.random() < 0.1 else round(q - rng.random(), 3))
        if hs:
            rc[k] = (rng.choice("ABC"), rng.choice(("MOC+DOW4", "V36_two_stage@0.6+TSB", "FALLBACK:V33_L112")), hs)
    _run("RA", D - timedelta(days=4), ra, created="2026-11-01T00:10:00+00:00")
    _run("RB", D - timedelta(days=2), rb, created="2026-11-03T00:10:00+00:00")
    _run("RC", D, rc, created="2026-11-05T00:10:00+00:00")
    avg = []
    for i, (s, f) in enumerate(keys[100:]):
        r = rng.random()
        if r < 0.1:
            avg.append((s, f, "SL1", None, f"Thuoc {i}"))                     # NULL value
        elif r < 0.2:
            avg += [(s, f, "SL1", 1.5, f"Thuoc {i}"), (s, f, "SL2", 2.5, f"Thuoc {i}")]   # two sellers, PENDING
        else:
            avg.append((s, f, "SL1", round(rng.random() * 5, 4), f"Thuoc {i}"))
    _avg(D, avg)
    _config([(s, f, rng.choice(("LIGHTGBM", "AVG_DEMAND")), None) for s, f in keys if rng.random() < 0.6])
    return keys


def _excel_totals(xl: dict) -> dict:
    out: dict = {}
    for x in xl.values():
        d = x["target_date"].date().isoformat()
        out[d] = out.get(d, 0) + x["forecast_used"]
    return out


def test_random_50_sku_fc_and_daily_totals_equal_excel(sel2_on, client, monkeypatch):
    """50 random SKU x FC of a mixed day (R1 / R2 / R3' / R3'' / R4 / NULL AVG / PENDING) and the daily totals: the
    Results detail, the Daily Forecast rows and the summary equal the daily Excel of the run's day, column by column."""
    sel2_view.clear_cache()
    monkeypatch.setattr(daily_routes, "_scope", lambda c: dict(SC))
    monkeypatch.setattr(export, "_scope_key", lambda conn: (SCOPE, None))
    _big_scenario()
    xl = _excel_rows(D)
    xkeys = sorted({(k[0], k[1]) for k in xl})
    reasons = {x["fallback_reason"] for x in xl.values()}
    assert {export.REASON_OUT_ZERO, export.REASON_PREVIOUS, export.REASON_NO_NUMBER} <= reasons   # the mix is real
    for k in random.Random(11).sample(xkeys, 50):
        r = client.get(f"/api/daily-forecast/sel2-values?run_id=RC&sku_id={k[0]}&fc_id={k[1]}&limit=20").json()
        assert r["total"] == 7 and [x["horizon_day"] for x in r["rows"]] == list(range(1, 8))
        for x in r["rows"]:
            e = xl[(k[0], k[1], x["horizon"])]
            for c in SEL2_COLS:
                want = e[c].date().isoformat() if c == "data_cutoff_date" and e[c] is not None else e[c]
                assert _same(x[c], want), (k, x["horizon"], c, x[c], want)
            assert x["forecast_qty"] == e["forecast_used"]
        d = client.get(f"/api/daily-forecast/values?run_id=RC&q={k[0]}").json()
        got = {(x["sku_code"], x["fc_code"], x["horizon"]): x for x in d["rows"]}
        for h in range(1, 8):
            assert got[(k[0], k[1], h)]["forecast_used"] == xl[(k[0], k[1], h)]["forecast_used"]
    s = client.get("/api/daily-forecast/sel2-summary?run_id=RC&horizon=7&limit=1000").json()
    assert s["n_series"] == len(xkeys)
    assert {x["target_date"]: x["total"] for x in s["daily"]} == _excel_totals(xl)
    assert s["grand_total"] == sum(x["forecast_used"] for x in xl.values())
    assert client.get("/api/daily-forecast/values?run_id=RC").json()["total"] == len(xl)


def test_older_run_equals_its_own_day_excel_and_stale_days(sel2_on, client, monkeypatch):
    """An older run (RB of D-2) shown by id equals the Excel of D-2. On a day without a run (D+1: NO_RUN_FOR_DAY, D+5:
    NO_RUN_3_DAYS) the pages keep the newest run RC with its own day D in the info line (never a mix with the stale
    file of that day)."""
    sel2_view.clear_cache()
    monkeypatch.setattr(daily_routes, "_scope", lambda c: dict(SC))
    monkeypatch.setattr(export, "_scope_key", lambda conn: (SCOPE, None))
    _big_scenario(seed=3, n=120)
    xb = _excel_rows(D - timedelta(days=2))
    s = client.get("/api/daily-forecast/sel2-summary?run_id=RB&horizon=7&limit=1000").json()
    assert s["run"]["id"] == "RB" and {x["target_date"]: x["total"] for x in s["daily"]} == _excel_totals(xb)
    rows = []
    for p in range(0, 100):
        r = client.get(f"/api/daily-forecast/values?run_id=RB&page={p}").json()
        rows += r["rows"]
        if (p + 1) * r["page_size"] >= r["total"]:
            break
    assert len(rows) == len(xb)
    for x in rows:
        e = xb[(x["sku_code"], x["fc_code"], x["horizon"])]
        assert (x["forecast_used"], x["fallback_reason"], x["model_used"]) == \
            (e["forecast_used"], e["fallback_reason"], e["model_used"])
    for later, reason in ((D + timedelta(days=1), "STALE"), (D + timedelta(days=5), export.STALE_NO_RUN_3_DAYS)):
        res = export.write_daily_export(later, scope_key=SCOPE)
        assert res["is_stale"] is True and reason in res["flags"], res["flags"]
    info = client.get("/api/forecast-info").json()
    assert (info["run_id"], info["forecast_date"]) == ("RC", D.isoformat())
    assert client.get("/api/daily-forecast/sel2-summary").json()["start_date"] == D.isoformat()


# ------------------------------------------------------------------ cache invalidation
def _used(client, sku, fc, h=1, run_id=None):
    url = f"/api/daily-forecast/sel2-values?sku_id={sku}&fc_id={fc}&horizon=7" + (f"&run_id={run_id}" if run_id else "")
    r = client.get(url).json()
    return r["run"]["id"], next(x["forecast_used"] for x in r["rows"] if x["horizon"] == h)


def test_cache_new_run_avg_read_and_rule_change(scenario, client):
    assert _used(client, "S1", "F1") == ("R1", 1)
    _run("R2", D + timedelta(days=1), {("S1", "F1"): ("A", "MOC", {h: (40 + h, 40.0) for h in range(1, 8)})},
         created="2026-11-05T23:30:00+00:00")
    assert _used(client, "S1", "F1") == ("R2", 41)                        # newly published run: shown at once
    assert _used(client, "S2", "F1", run_id="R1") == ("R1", 4)            # AVG of D (S2 default AVG_DEMAND)
    with db.tx() as c:
        c.execute("DELETE FROM avg_demand_daily WHERE business_date=? AND sku_code='S2'", (D.isoformat(),))
    _avg(D, [("S2", "F1", "SL1", 9.2, "Thuoc B")])                        # a new AVG read of D
    assert _used(client, "S2", "F1", run_id="R1") == ("R1", 10)
    assert _used(client, "S5", "F1", run_id="R1")[1] == 0                 # two sellers, rule PENDING -> no number
    ss.update("sel2_pipeline", {"avg_seller_rule": "SELLER:SL2"}, note="tests: rule")
    assert _used(client, "S5", "F1", run_id="R1")[1] == 2                 # the rule change rebuilds the view


def test_cache_source_config_change(scenario, client):
    assert _used(client, "S2", "F1") == ("R1", 4)                         # AVG_DEMAND (default)
    timeutil.set_now_override(lambda: datetime(2026, 11, 5, 5, 0, 1, tzinfo=timezone.utc))
    try:
        source_config.set_one("S2", "F1", "LIGHTGBM", confirm=True, changed_by="tester")
    finally:
        timeutil.set_now_override(None)
    assert _used(client, "S2", "F1") == ("R1", 1)                         # LightGBM number of R1


def test_cache_source_config_two_changes_in_the_same_second(scenario, client):
    """BUG probe: the view signature is (COUNT(*), MAX(updated_at)) of forecast_source_config (one-second
    timestamps). A second change in the same second to an already configured SKU x FC keeps both values: the page
    keeps the old numbers for up to VIEW_TTL_SECONDS."""
    t = datetime(2026, 11, 5, 5, 0, 0, tzinfo=timezone.utc)
    timeutil.set_now_override(lambda: t)
    try:
        source_config.set_one("S2", "F1", "LIGHTGBM", confirm=True, changed_by="tester")
        assert _used(client, "S1", "F1") == ("R1", 1)                     # view built after the first change
        source_config.set_one("S1", "F1", "AVG_DEMAND", confirm=True, changed_by="tester")   # same second
        assert _used(client, "S1", "F1") == ("R1", 3)                     # AVG 2.5 -> 3
    finally:
        timeutil.set_now_override(None)


def test_cache_ttl_rebuilds(scenario, client, monkeypatch):
    builds = []
    orig = sel2_view.View.__init__

    def counting(self, c, run):
        builds.append(run["id"])
        orig(self, c, run)
    monkeypatch.setattr(sel2_view.View, "__init__", counting)
    _used(client, "S1", "F1")
    _used(client, "S1", "F1")
    assert builds == ["R1"]                                               # second request: cache hit
    monkeypatch.setattr(sel2_view, "VIEW_TTL_SECONDS", -1)
    _used(client, "S1", "F1")
    assert builds == ["R1", "R1"]                                         # expired: rebuilt


def test_history_second_request_reuses_the_day_cache(scenario, client, monkeypatch):
    """BUG probe: used_at keeps the horizon-2 numbers of each SEL2 day, but Sel2Part then calls sel2_view.view() for
    the product names of every day, which rebuilds the full view (one view cached at a time): every history request
    rebuilds one full view per SEL2 day of the range."""
    builds = []
    orig = sel2_view.View.__init__

    def counting(self, c, run):
        builds.append(run["id"])
        orig(self, c, run)
    monkeypatch.setattr(sel2_view.View, "__init__", counting)
    url = "/api/history/summary?run_from=2026-11-04&run_to=2026-11-05"
    first = client.get(url).json()
    n1 = len(builds)
    assert client.get(url).json()["daily"] == first["daily"]
    assert len(builds) == n1, builds


# ------------------------------------------------------------------ history at the 04/11 boundary
def _old_run(n: int, created_vn: str, origin: str, keys, base: float) -> str:
    """A 1.3.x published forecast run (forecast_runs) of the scope, recorded in the history (fh.capture)."""
    from app import forecast_history as fh
    rid, tid = f"FCR-B{n}", f"TRN-B{n}"
    t = datetime.fromisoformat(created_vn).replace(tzinfo=timeutil.VN_TZ).astimezone(timezone.utc)
    at = t.isoformat(timespec="seconds")
    d0 = date.fromisoformat(origin)
    with db.tx() as c:
        c.execute("INSERT INTO training_runs(id, model_version, scope_key, data_source, status, started_at, "
                  "quality_gate_json) VALUES (?,?,?, 'BIGQUERY', 'ACCEPTED', ?, '{}')", (tid, f"MV-B{n}", SCOPE, at))
        c.execute("INSERT INTO forecast_runs(id, training_run_id, model_version, scope_key, data_source, forecast_origin, "
                  "data_as_of, horizons_json, max_horizon, n_series, status, created_at, job_id) "
                  "VALUES (?,?,?,?, 'BIGQUERY', ?,?, '[3]', 3, ?, 'PUBLISHED', ?, NULL)",
                  (rid, tid, f"MV-B{n}", SCOPE, origin, str(d0 - timedelta(days=1)), len(keys), at))
        c.executemany("INSERT INTO forecast_values(run_id, sku_id, fc_id, target_date, horizon_day, yhat, method) "
                      "VALUES (?,?,?,?,?,?, 'LIGHTGBM')",
                      [(rid, s, f, str(d0 + timedelta(days=h)), h + 1, base + i + h) for i, (s, f) in enumerate(keys)
                       for h in range(3)])
    assert fh.capture(rid)["decision"] == "SELECTED"
    return rid


def test_history_boundary_no_double_count_and_labels(scenario, client):
    """1.3.x history on 03/11 and 04/11 + SEL2 runs on 04/11 and 05/11: 04/11 is counted once (SEL2), 03/11 keeps
    its 1.3.x numbers with the label LIGHTGBM_CU; KPI rows = the rows of the chart days; paging over the joined list
    gives every row once."""
    old_keys = (("S1", "F1"), ("S3", "F1"), ("S8", "HN"))
    _old_run(1, "2026-11-03 08:00", "2026-11-03", old_keys, 100.0)
    _old_run(2, "2026-11-04 08:00", "2026-11-04", old_keys, 500.0)
    _publish(D - timedelta(days=1), D)
    rng = "run_from=2026-11-01&run_to=2026-11-05"
    s = client.get(f"/api/history/summary?{rng}").json()
    by = {x["run_date"]: x for x in s["daily"]}
    assert by["2026-11-03"]["source_label"] == "LIGHTGBM_CU" and by["2026-11-03"]["forecast_source"] == "PRIMARY"
    assert by["2026-11-03"]["n_rows"] == 3 and by["2026-11-03"]["forecast"] == pytest.approx(101 + 102 + 103)
    assert by["2026-11-04"]["source_label"] == "SEL2" and by["2026-11-04"]["forecast_run_id"] == "R0"
    assert by["2026-11-04"]["forecast"] < 500                               # never the 1.3.x numbers of 04/11
    assert by["2026-11-02"]["has_history"] is False and by["2026-11-02"]["source_label"] is None
    k = s["kpi"]
    assert k["n_rows"] == sum(x["n_rows"] for x in s["daily"]) and k["days_sel2"] == 2 and k["days_primary"] == 1
    assert k["forecast_total"] == pytest.approx(sum(x["forecast"] or 0 for x in s["daily"]))
    full = client.get(f"/api/history/rows?{rng}&limit=1000").json()
    assert full["total"] == len(full["rows"]) == by["2026-11-04"]["n_rows"] + by["2026-11-05"]["n_rows"] + 3
    assert not [x for x in full["rows"] if x["run_date"] >= "2026-11-04" and x["source_label"] != "SEL2"]
    assert {x["source_label"] for x in full["rows"] if x["run_date"] == "2026-11-03"} == {"LIGHTGBM_CU"}
    for sort in ("date", "abs_error", "forecast"):
        seen = []
        for off in range(0, full["total"] + 4, 4):
            seen += client.get(f"/api/history/rows?{rng}&limit=4&offset={off}&sort={sort}").json()["rows"]
        ids = [(x["run_date"], x["sku_id"], x["fc_id"]) for x in seen]
        assert len(ids) == len(set(ids)) == full["total"], sort
    # a range before SEL2_FROM only: unchanged 1.3.x rows, labelled
    old = client.get("/api/history/rows?run_from=2026-11-01&run_to=2026-11-03").json()
    assert old["total"] == 3 and {x["source_label"] for x in old["rows"]} == {"LIGHTGBM_CU"}


def test_history_export_contains_the_sel2_days(scenario, client):
    """BUG probe: the page export (Excel of all rows of the filter) must carry the same SEL2 rows as the page."""
    rng = "run_from=2026-11-04&run_to=2026-11-05"
    _publish(D - timedelta(days=1), D)
    page = client.get(f"/api/history/rows?{rng}&limit=1000").json()
    assert any(x["sku_id"] == "S1" for x in page["rows"])
    r = client.get(f"/api/history/export.xlsx?{rng}")
    assert r.status_code == 200
    wb = load_workbook(io.BytesIO(r.content), read_only=True)
    cells = {v for ws in wb.worksheets for row in ws.iter_rows(values_only=True) for v in row if v is not None}
    assert "S1" in cells and "S2" in cells


def _detail_ids(content: bytes) -> list[tuple]:
    """(run_date, sku, fc) of the SKU x FC detail sheet (the last sheet) of a history export, in file order."""
    ws = load_workbook(io.BytesIO(content), read_only=True).worksheets[-1]
    it = ws.iter_rows(values_only=True)
    next(it)
    return [(r[0].date().isoformat() if hasattr(r[0], "date") else str(r[0]), r[5], r[7]) for r in it]


@pytest.mark.parametrize("rng", ["run_from=2026-11-04&run_to=2026-11-05", "run_from=2026-11-01&run_to=2026-11-05"])
def test_history_every_sort_of_the_page_on_sel2_and_mixed_ranges(scenario, client, rng):
    """Every sort the History page offers (forecast_history.SORTS) works on a SEL2 range and on a range across
    04/11: rows 200, the pages joined = one request (each row once), the Excel export 200 with the same order; the SEL2
    part follows the 1.3.x semantics (actual DESC with no actual last, sku -> fc -> newest run date)."""
    from app import forecast_history as fh
    _old_run(1, "2026-11-03 08:00", "2026-11-03", (("S1", "F1"), ("S3", "F1"), ("S8", "HN")), 100.0)
    _demand([(D, "S3", "F1", 3.0), (D, "S7", "F1", 5.0)])
    _publish(D - timedelta(days=1), D)
    assert set(fh.SORTS) <= set(history_routes.SEL2_SORTS)
    for sort in fh.SORTS:
        full = client.get(f"/api/history/rows?{rng}&limit=1000&sort={sort}")
        assert full.status_code == 200, (sort, full.text)
        full = full.json()
        ids = [(x["run_date"], x["sku_id"], x["fc_id"]) for x in full["rows"]]
        assert full["total"] == len(ids) == len(set(ids)) and full["total"] > 0, sort
        seen = []
        for off in range(0, full["total"], 3):
            seen += client.get(f"/api/history/rows?{rng}&limit=3&offset={off}&sort={sort}").json()["rows"]
        assert [(x["run_date"], x["sku_id"], x["fc_id"]) for x in seen] == ids, sort
        r = client.get(f"/api/history/export.xlsx?{rng}&sort={sort}")
        assert r.status_code == 200, (sort, r.text)
        assert _detail_ids(r.content) == ids, sort
        sel2 = [x for x in full["rows"] if x["source_label"] == "SEL2"]
        assert sel2 and full["rows"][:len(sel2)] == sel2                       # the SEL2 part first
        if sort == "actual":
            acts = [x["actual"] for x in sel2]
            known = [a for a in acts if a is not None]
            assert known == sorted(known, reverse=True) and acts == known + [None] * (len(acts) - len(known))
            assert known and None in acts
        if sort == "sku":
            keys = [(x["sku_id"], x["fc_id"], [-int(p) for p in x["run_date"].split("-")]) for x in sel2]
            assert keys == sorted(keys)
        if "2026-11-01" in rng:
            assert any(x["source_label"] == "LIGHTGBM_CU" for x in full["rows"]), sort
    assert client.get(f"/api/history/rows?{rng}&sort=nope").status_code == 422


# ------------------------------------------------------------------ AVG_DEMAND read of the export (sel2_view)
def _all_values(client, run_id="R1") -> dict:
    got, page = {}, 0
    while True:
        r = client.get(f"/api/daily-forecast/values?run_id={run_id}&page={page}").json()
        for x in r["rows"]:
            got[(x["sku_code"], x["fc_code"], x["horizon"])] = x
        page += 1
        if page * r["page_size"] >= r["total"]:
            return got


def _assert_page_equals_excel(client, xl: dict) -> None:
    got = _all_values(client)
    assert set(got) == set(xl)
    for k, x in xl.items():
        for c in ("forecast_used", "avg_demand", "forecast_source", "fallback_reason"):
            assert _same(got[k][c], x[c]), (k, c, got[k][c], x[c])
    s = client.get("/api/daily-forecast/sel2-summary?run_id=R1&horizon=7").json()
    assert s["grand_total"] == sum(x["forecast_used"] for x in xl.values())


def _new_read(day: date, rows, table: str, completed_at: str, kind: str = "CURRENT", replace: bool = False):
    """A later AVG_DEMAND read of day (replace=True: the rows of that table are replaced, as avg_demand._store_day)."""
    with db.tx() as c:
        if replace:
            c.execute("DELETE FROM avg_demand_daily WHERE business_date=? AND source_table=?", (day.isoformat(), table))
        c.executemany("INSERT INTO avg_demand_daily(business_date, sku_code, fc_code, seller_code, avg_demand, "
                      "product_name, source_table, source_modified, loaded_at) VALUES (?,?,?,?,?,?,?,?,?)",
                      [(day.isoformat(), s, f, sel, v, n, table, completed_at, completed_at) for s, f, sel, v, n in rows])
        c.execute("INSERT INTO avg_demand_reads(id, source_table, business_date, kind, n_rows, source_modified, "
                  "completed_at) VALUES (?,?,?,?,?,?,?)",
                  (db.new_id("ADR"), table, day.isoformat(), kind, len(rows), completed_at, completed_at))


NEW_AVG = [("S1", "F1", "SL1", 7.5, "Thuoc A"), ("S2", "F1", "SL1", 9.2, "Thuoc B"), ("S6", "BD", "SL1", 6.0, "Thuoc F")]


def test_daily_page_keeps_the_avg_read_of_its_export(scenario, client):
    """The export used a HISTORICAL read of D; a CURRENT read landing after the export (latest_read prefers it) never
    changes the page: page values = the Excel, no flag."""
    hist = ss.get("sel2_pipeline").avg_demand_hist_table
    with db.tx() as c:
        c.execute("UPDATE avg_demand_reads SET kind='HISTORICAL', source_table=? WHERE business_date=?", (hist, D.isoformat()))
        c.execute("UPDATE avg_demand_daily SET source_table=? WHERE business_date=?", (hist, D.isoformat()))
    xl = _excel_rows(D)
    assert xl[("S2", "F1", 1)]["forecast_used"] == 4
    _new_read(D, NEW_AVG, ss.get("sel2_pipeline").avg_demand_table, "2026-11-05T09:00:00+00:00")
    _assert_page_equals_excel(client, xl)
    assert _all_values(client)[("S2", "F1", 1)]["forecast_used"] == 4            # never 10 (the later read)
    assert "avg_flag" not in client.get("/api/forecast-info").json()


def test_daily_page_of_an_export_without_avg_read_ignores_a_later_read(scenario, client):
    """The export was written without any completed AVG_DEMAND read: a read landing afterwards is not used."""
    with db.tx() as c:
        c.execute("DELETE FROM avg_demand_daily WHERE business_date=?", (D.isoformat(),))
        c.execute("DELETE FROM avg_demand_reads WHERE business_date=?", (D.isoformat(),))
    xl = _excel_rows(D)
    assert all(x["avg_demand"] is None for x in xl.values())
    _new_read(D, NEW_AVG, ss.get("sel2_pipeline").avg_demand_table, "2026-11-05T09:00:00+00:00")
    _assert_page_equals_excel(client, xl)
    assert "avg_flag" not in client.get("/api/forecast-info").json()


def test_avg_read_replaced_or_not_recorded_is_flagged(scenario, client):
    """The rows of the export's read replaced by a later read of the same table (cannot be rebuilt), or an export
    without the AVG record: the page uses the day's newest read with today's rule and says so (avg_flag)."""
    _excel_rows(D)
    table = ss.get("sel2_pipeline").avg_demand_table
    _new_read(D, NEW_AVG, table, "2026-11-05T09:00:00+00:00", replace=True)
    assert client.get("/api/forecast-info").json()["avg_flag"] == sel2_view.AVG_FLAG
    assert _all_values(client)[("S2", "F1", 1)]["forecast_used"] == 10           # newest read (9.2 -> 10)
    _new_read(D, NEW_AVG, table, "2026-11-05T09:30:00+00:00", replace=True)
    with db.tx() as c:                                         # an export recorded without the AVG summary
        c.execute("UPDATE export_runs SET summary_json = json_remove(summary_json, '$.avg')")
    sel2_view.clear_cache()
    assert client.get("/api/forecast-info").json()["avg_flag"] == sel2_view.AVG_FLAG
    assert _all_values(client)[("S2", "F1", 1)]["forecast_used"] == 10


# ------------------------------------------------------------------ info line
def test_info_vn_midnight_and_newest_first_tie(scenario, client):
    """refreshed_at in Vietnam time across the UTC/VN date boundary; two runs of the same day with the same second:
    the higher rowid wins for the info line, the Daily page, the run list and the daily Excel alike."""
    for rid in ("RT1", "RT2"):
        _run(rid, D + timedelta(days=1), {("S1", "F1"): ("A", "MOC", {h: (int(rid[-1]) * 10, 1.0) for h in range(1, 8)})},
             created="2026-11-05T17:30:00+00:00")
    info = client.get("/api/forecast-info").json()
    assert info == {"source": "SEL2", "run_id": "RT2", "refreshed_at": "2026-11-06 00:30:00",
                    "data_cutoff_date": "2026-11-05", "forecast_date": "2026-11-06"}
    assert client.get("/api/daily-forecast/values").json()["run"]["id"] == "RT2"
    assert client.get("/api/daily-forecast/sel2-runs").json()[0]["id"] == "RT2"
    assert client.get("/api/daily-forecast/sel2-summary").json()["run"]["id"] == "RT2"
    assert export.write_daily_export(D + timedelta(days=1), scope_key=SCOPE)["summary"]["refresh_run_id"] == "RT2"


def test_info_old_pipeline_label(sel2_on, client, monkeypatch):
    monkeypatch.setattr(daily_routes, "_scope", lambda c: dict(SC))
    _old_run(9, "2026-11-03 23:40", "2026-11-04", (("S1", "F1"),), 1.0)
    assert client.get("/api/forecast-info").json() == {
        "source": "LIGHTGBM_CU", "run_id": "FCR-B9", "refreshed_at": "2026-11-03 23:40:00",
        "data_cutoff_date": "2026-11-03", "forecast_date": None}


def test_info_names_the_run_the_daily_page_shows(scenario, client):
    """BUG probe: emergency switch (sel2_pipeline.enabled = False) -> 1.3.1 refresh runs are published again; the
    Daily Forecast page shows the newest refresh run, the info line must describe that same run."""
    ss.update("sel2_pipeline", {"enabled": False}, note="tests: emergency switch")
    _run("OLD131", D + timedelta(days=1), {("S1", "F1"): ("A", "LGBM", {1: (5, 4.6)})}, cv="v131:abc",
         created="2026-11-05T23:30:00+00:00")
    shown = client.get("/api/daily-forecast/values").json()["run"]["id"]
    assert shown == "OLD131"
    assert client.get("/api/forecast-info").json()["run_id"] == shown


# ------------------------------------------------------------------ actual_daily in SEL2 mode
def _actual_rows():
    with db.read() as c:
        return {(r[0], r[2]): r[3] for r in c.execute("SELECT date, fc_code, sku_code, demand FROM actual_daily "
                                                      "WHERE scope_key=?", (SCOPE,))}


def _put_actual(rows):
    with db.tx() as c:
        c.executemany("INSERT INTO actual_daily(scope_key, date, fc_code, sku_code, demand, total_open_hours, "
                      "updated_at) VALUES (?,?, 'F1', ?, ?, NULL, '2026-10-02T00:00:00+00:00')",
                      [(SCOPE, d.isoformat(), s, q) for d, s, q in rows])


def test_actual_refresh_range_edges_and_rewrite(sel2_on):
    """D-15 and D are never touched (even with demand rows); D-14 .. D-1 is rewritten: a stale row of a day without
    demand disappears, a changed demand is taken at the next refresh, the same call twice gives the same rows."""
    _put_actual([(D - timedelta(days=15), "S1", 9.0), (D, "S1", 5.0), (D - timedelta(days=7), "S9", 99.0)])
    _demand([(D - timedelta(days=15), "S1", "F1", 1.0), (D, "S1", "F1", 1.0), (D - timedelta(days=14), "S1", "F1", 2.0),
             (D - timedelta(days=1), "S2", "F1", 0.0)])
    out = jobs.actual_refresh(D, dict(SC))
    assert out == {"rows": 2, "start": "2026-10-22", "end": "2026-11-04"}
    first = _actual_rows()
    assert first == {("2026-10-21", "S1"): 9.0, ("2026-11-05", "S1"): 5.0, ("2026-10-22", "S1"): 2.0,
                     ("2026-11-04", "S2"): 0.0}
    assert jobs.actual_refresh(D, dict(SC))["rows"] == 2 and _actual_rows() == first
    with db.tx() as c:
        c.execute("UPDATE demand_daily SET qty=6 WHERE scope_key=? AND order_date='2026-10-22'", (SCOPE,))
    jobs.actual_refresh(D, dict(SC))
    assert _actual_rows()[("2026-10-22", "S1")] == 6.0


def test_actual_refresh_clipped_to_data_window(sel2_on):
    ss.update("data_policy", {"window_start_date": (D - timedelta(days=5)).isoformat()}, note="tests: window")
    _put_actual([(D - timedelta(days=10), "S1", 7.0)])
    _demand([(D - timedelta(days=10), "S1", "F1", 1.0), (D - timedelta(days=5), "S1", "F1", 4.0)])
    jobs.actual_refresh(D, dict(SC))
    assert _actual_rows() == {("2026-10-26", "S1"): 7.0, ("2026-10-31", "S1"): 4.0}   # before the window: kept


def test_refresh_flags_actual_failure_and_still_runs_the_day(sel2_on, monkeypatch):
    import app.data.demand as demand_mod
    monkeypatch.setattr(demand_mod, "resolve_scope", lambda c: dict(SC))

    def boom(*a, **k):
        raise RuntimeError("locked")
    monkeypatch.setattr(daily_refresh, "refresh_actual_daily", boom)
    calls = []
    monkeypatch.setattr(jobs, "call_cli", lambda args, cancel=None, timeout=None:
                        calls.append(args) or {"ok": True, "result": {"status": "PUBLISHED", "run_id": "RX"},
                                               "exit_code": 0})
    out = jobs.refresh("J9", {"business_date": D.isoformat()}, trigger="MANUAL")
    assert calls and calls[0][0] == "sel2-day"                            # the day's forecast still ran
    assert out["status"] == "PUBLISHED" and jobs.FLAG_ACTUAL_DAILY_FAILED in out["flags"]
    assert out["actual_daily"]["rows"] is None and "RuntimeError: locked" in out["actual_daily"]["error"]
    with db.read() as c:
        al = db.rows(c, "SELECT level, code, entity_id FROM alerts WHERE code=?", (daily_refresh.ACTUAL_DAILY_ALERT,))
    assert [(a["level"], a["entity_id"]) for a in al] == [("WARNING", SCOPE)]


# ------------------------------------------------------------------ 144-T2-fix6: Results page as 1.4.3 (QA findings)
def test_results_sel2_order_as_1_4_3_and_stable_pages(scenario, client):
    """Totals: total DESC, sku, fc (the 1.3.x summary order), consistent paging; daily detail: sku, fc, date."""
    full = client.get("/api/daily-forecast/sel2-summary?run_id=R1&horizon=7&limit=1000").json()["series"]
    order = [(x["sku_id"], x["fc_id"]) for x in full]
    assert order == [(x["sku_id"], x["fc_id"]) for x in sorted(full, key=lambda x: (-x["total"], x["sku_id"], x["fc_id"]))]
    assert full[0]["total"] > 0 and full[-1]["total"] <= full[0]["total"]
    paged = []
    for off in range(0, len(full), 2):
        paged += client.get(f"/api/daily-forecast/sel2-summary?run_id=R1&horizon=7&limit=2&offset={off}").json()["series"]
    assert [(x["sku_id"], x["fc_id"]) for x in paged] == order
    h3 = client.get("/api/daily-forecast/sel2-summary?run_id=R1&horizon=3&limit=1000").json()["series"]
    assert [x["total"] for x in h3] == sorted((x["total"] for x in h3), reverse=True)
    rows = client.get("/api/daily-forecast/sel2-values?run_id=R1&horizon=7&limit=1000").json()["rows"]
    got = [(x["sku_id"], x["fc_id"], x["target_date"]) for x in rows]
    assert got == sorted(got) and len(got) == len(full) * 7
    pages = []
    for off in range(0, len(got), 5):
        pages += [(x["sku_id"], x["fc_id"], x["target_date"]) for x in client.get(
            f"/api/daily-forecast/sel2-values?run_id=R1&horizon=7&limit=5&offset={off}").json()["rows"]]
    assert pages == got


def test_results_sel2_run_blocks(scenario, client):
    """The blocks of the 1.4.3 page carry SEL2-true content: horizons offered vs configured (nothing to extend), data
    used as recorded with the run (no invented window / sync time), product-name source."""
    run = client.get("/api/daily-forecast/sel2-summary?run_id=R1").json()["run"]
    cov = run["horizon_coverage"]
    assert cov["run_horizons"] == list(range(1, 8)) == run["horizons"]
    assert cov["configured"] == sorted(set(ss.get("horizons").enabled)) and cov["configured_missing_in_run"] == []
    lin = run["lineage"]
    assert lin["data_source"] == "BIGQUERY" and lin["batch_id"] == SCOPE and lin["table"] is None
    assert lin["train_start"] is None and lin["train_end"] is None and lin["last_sync"] is None   # detail_json '{}'
    assert "product_names" in run
    rec = {"scope_key": "BIGQUERY:p.d.t", "detail_json": '{"inputs": {"window_start": "2025-01-01", "end": "2026-11-04"}}'}
    assert daily_routes._sel2_lineage(rec, "BIGQUERY") == {
        "data_source": "BIGQUERY", "scope_key": "BIGQUERY:p.d.t", "table": "p.d.t", "batch_id": None,
        "train_start": "2025-01-01", "train_end": "2026-11-04", "last_sync": None}
    assert daily_routes._sel2_lineage({"scope_key": "X", "detail_json": "not json"}, "DEMO")["train_start"] is None


def test_results_sel2_actual_so_far_today(scenario, client, monkeypatch):
    """The actual so far today of the 1.3.x page (D0 snapshot, read only) on the SEL2 summary and detail."""
    from app.data import intraday
    s = client.get("/api/daily-forecast/sel2-summary?run_id=R1").json()
    assert s["actual"]["status"] == "NO_DATA_TODAY" and s["actual"]["total"] is None
    monkeypatch.setattr(intraday, "today_vn", lambda: D)
    with db.tx() as c:
        c.execute("INSERT INTO d0_snapshots(id, data_source, scope_key, order_date, snapshot_at, sync_status, rows_read, "
                  "rows_valid, rows_error, created_at) VALUES ('SNP1', 'BIGQUERY', ?, ?, '2026-11-05T03:00:00+00:00', "
                  "'SUCCEEDED', 2, 2, 0, '2026-11-05T03:00:00+00:00')", (SCOPE, D.isoformat()))
        c.executemany("INSERT INTO d0_snapshot_values(snapshot_id, sku_id, fc_id, cumulative_qty) VALUES ('SNP1',?,?,?)",
                      [("S1", "F1", 4.0), ("S6", "BD", 2.0), ("S99", "F1", 9.0)])
    s = client.get("/api/daily-forecast/sel2-summary?run_id=R1&limit=1000").json()
    a = s["actual"]
    assert a["date"] == D.isoformat() and a["in_horizon"] is True and a["total"] == 6.0 and a["n_series"] == 6
    by = {(x["sku_id"], x["fc_id"]): x["actual_today"] for x in s["series"]}
    assert by[("S1", "F1")] == 4.0 and by[("S2", "F1")] == 0.0        # a read day without a row = 0 (D0 rule)
    assert [d["actual_today"] for d in s["daily"]] == [6.0] + [None] * 6
    assert client.get("/api/daily-forecast/sel2-summary?run_id=R1&fc_id=BD").json()["actual"]["total"] == 2.0
    v = client.get("/api/daily-forecast/sel2-values?run_id=R1&sku_id=S1&limit=10").json()
    assert v["actual"]["status"] in ("PARTIAL_DAY", "STALE") and "values" not in v["actual"]
    assert [x["actual_today"] for x in v["rows"]] == [4.0] + [None] * 6


def test_history_fallback_days_exclude_sel2_days(scenario, client, monkeypatch):
    """A run date with a SEL2 publication is never listed as a day using the backup snapshot (overview, summary)
    and today's banner names the SEL2 publication."""
    from app import forecast_history as fh
    _publish(D)

    def fake_backup(c, sk, today=None):
        return [{"run_date": d, "target_date": str(date.fromisoformat(d) + timedelta(days=1)), "snapshot_id": "EOD-" + d,
                 "snapshot_business_date": "2026-11-02", "snapshot_created_at": "2026-11-02T16:55:00+00:00",
                 "forecast_run_id": "FR-OLD", "source_run_date": "2026-11-02", "session_started_at": None,
                 "published_at": None, "model_version": "MV-OLD"} for d in ("2026-11-05", "2026-11-03")]
    day = {"run_date": "2026-11-02", "target_date": "2026-11-03", "forecast_run_id": "FR-OLD"}
    monkeypatch.setattr(fh, "fallback_days", fake_backup)
    monkeypatch.setattr(fh, "days", lambda c, sk: [dict(day)])
    monkeypatch.setattr(fh, "today_vn", lambda: D)
    monkeypatch.setattr(fh, "scopes", lambda c: [{"scope_key": SCOPE, "data_source": "BIGQUERY", "n_days": 1}])
    ov = client.get("/api/history/overview").json()
    assert [d["run_date"] for d in ov["backup_days"]] == ["2026-11-03"] and ov["today_backup"] is None
    assert ov["today_sel2"]["run_date"] == D.isoformat() and ov["today_sel2"]["forecast_run_id"] == "R1"
    assert "_export" not in ov["today_sel2"]
    s = client.get("/api/history/summary?run_from=2026-11-01&run_to=2026-11-05").json()
    assert [d["run_date"] for d in s["backup_days"]] == ["2026-11-03"]
