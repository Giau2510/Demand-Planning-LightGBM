"""1.4.4 T2-fix3: the published SEL2 numbers kept for the history page in sidecar files (ml/sel2/published.py, no
database table): the export writes one horizon-2 row per SKU x FC atomically next to its version file, a sidecar
failure never fails the export, a missing / stale sidecar is rebuilt from the recorded xlsx (sha256 checked), the
history never recomputes a published day (a later forecast source change leaves it unchanged), history summary / rows
over 30 days x 58k SKU x FC stay small in memory (streamed, no view), the backfill of days exported before 1.4.4
(1.4.2 / 1.4.3 / 1.4.4 layouts, dry run by default, idempotent), the Daily page of a day with an Excel uses the
configuration of that file and a day >= 04/11 with only a 1.3.x publication keeps its 1.3.x row. Integration with
fakes (isolated temporary database and data folder, TestClient)."""
import gzip
import hashlib
import json
import time
import tracemalloc
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from openpyxl import Workbook

from app import db, paths, timeutil
from app.api import history_routes, sel2_view
from app.ml.sel2 import export, published, source_config

from test_v144_ui_data import D, SC, SCOPE, _excel_rows, _old_run, scenario  # noqa: F401


@pytest.fixture(autouse=True)
def _fresh_lru():
    published.clear_cache()
    yield
    published.clear_cache()


def _record(export_run_id: str) -> dict:
    with db.read() as c:
        return db.one(c, "SELECT id, forecast_date, path, sha256, flags FROM export_runs WHERE id=?", (export_run_id,))


def _sidecar_file(export_run_id: str) -> Path:
    return published.sidecar_path(paths.data_dir() / _record(export_run_id)["path"])


def _sidecar(export_run_id: str) -> dict | None:
    p = _sidecar_file(export_run_id)
    if not p.is_file():
        return None
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return json.load(f)


def test_export_writes_one_horizon_1_sidecar_row_per_sku_fc(scenario):
    res = export.write_daily_export(D, scope_key=SCOPE)
    doc = _sidecar(res["id"])
    xl = _excel_rows(D)                                     # writes v2 with its own sidecar; v1 unchanged
    keys = {(k[0], k[1]) for k in xl}
    assert published.HISTORY_HORIZONS == (1,) and doc["horizons"] == [1]          # 1.4.5: target = forecast day
    assert doc["export_run_id"] == res["id"] and doc["sha256_of_xlsx"] == res["sha256"]
    assert doc["forecast_date"] == D.isoformat()
    assert len(doc["rows"]) == len(keys) == res["n_rows"] // export.H_ALL
    assert {(r[0], r[1]) for r in doc["rows"]} == keys
    for sku, fc, td, used, src, reason in doc["rows"]:
        x = xl[(sku, fc, 1)]
        assert (td, used, src, reason) == (x["target_date"].date().isoformat(), x["forecast_used"],
                                           x["forecast_source"], x["fallback_reason"])
    assert _sidecar(res["id"]) == doc                       # a later version never changes the earlier sidecar
    assert not [p for p in _sidecar_file(res["id"]).parent.iterdir() if p.suffix == ".tmp"]   # atomic: no temp left
    day = (paths.data_dir() / _record(res["id"])["path"]).parent       # the day folder lists the Excel files only
    assert _sidecar_file(res["id"]).parent == day.parent / ".published" / day.name
    assert all(p.suffix == ".xlsx" for p in day.iterdir())
    assert list(published.load(_record(res["id"]))) == [tuple(r) for r in doc["rows"]]


def test_sidecar_write_failure_never_fails_the_export(scenario, monkeypatch):
    real = published.write

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(published, "write", boom)
    res = export.write_daily_export(D, scope_key=SCOPE)
    assert published.FLAG_WRITE_FAILED in res["flags"] and published.FLAG_WRITE_FAILED in _record(res["id"])["flags"]
    assert _sidecar(res["id"]) is None
    monkeypatch.setattr(published, "write", real)            # the rows are rebuilt from the recorded xlsx
    rows = published.load(_record(res["id"]))
    assert len(rows) == res["n_rows"] // export.H_ALL and _sidecar(res["id"])["flags"]["rebuilt_from_xlsx"]


def test_temp_export_writes_no_sidecar(scenario):
    try:
        export.write_temp_export(D, scope_key=SCOPE)
    except Exception:  # noqa: BLE001 - only the sidecar folder matters here (the temp export needs candidate runs)
        pass
    assert not list(paths.data_dir().rglob("*.h2.json.gz"))


def test_rebuild_on_missing_or_stale_sidecar_and_refusal_of_a_changed_xlsx(scenario):
    res = export.write_daily_export(D, scope_key=SCOPE)
    rec = _record(res["id"])
    want = list(published.load(rec))
    _sidecar_file(res["id"]).unlink()
    published.clear_cache()
    assert list(published.load(rec)) == want and _sidecar(res["id"]) is not None          # rebuilt + written
    doc = _sidecar(res["id"])
    doc["sha256_of_xlsx"], doc["rows"] = "0" * 64, [["S1", "F1", "2026-11-06", 999, "LIGHTGBM", None]]
    with gzip.open(_sidecar_file(res["id"]), "wt", encoding="utf-8") as f:
        json.dump(doc, f)
    published.clear_cache()
    assert list(published.load(rec)) == want                # stale sidecar (sha) -> rebuilt from the xlsx
    _sidecar_file(res["id"]).unlink()
    with open(paths.data_dir() / rec["path"], "ab") as f:  # the xlsx itself changed: never read
        f.write(b"x")
    published.clear_cache()
    assert published.load(rec) is None


def test_concurrent_loads_of_a_missing_sidecar_rebuild_it_once(scenario, monkeypatch):
    """Two requests for the same day without a sidecar: one rebuild from the xlsx (lock per export), the second waits
    and reuses its rows."""
    import threading
    res = export.write_daily_export(D, scope_key=SCOPE)
    rec = _record(res["id"])
    want = list(published.load(rec))
    _sidecar_file(res["id"]).unlink()
    published.clear_cache()
    calls, real = [], published._rows_of_file

    def slow(p):
        calls.append(p)
        time.sleep(0.3)
        return real(p)
    monkeypatch.setattr(published, "_rows_of_file", slow)
    out: list = []
    ts = [threading.Thread(target=lambda: out.append(published.load(rec))) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(10)
    assert len(calls) == 1 and len(out) == 2 and all(list(x) == want for x in out)
    assert _sidecar(res["id"]) is not None


def test_history_unchanged_after_a_later_config_change(scenario, client):
    """C1 regression: the history shows the numbers of the file, never recomputed with today's configuration."""
    export.write_daily_export(D, scope_key=SCOPE)
    url = "/api/history/rows?run_from=2026-11-05&run_to=2026-11-05&limit=1000"
    before = {(x["sku_id"], x["fc_id"]): x["forecast_qty"] for x in client.get(url).json()["rows"]}
    summ = client.get("/api/history/summary?run_from=2026-11-05&run_to=2026-11-05").json()["daily"][0]["forecast"]
    assert before[("S2", "F1")] == 4                        # AVG_DEMAND 4.0 (default source)
    timeutil.set_now_override(lambda: datetime(2030, 1, 1, 1, 0, 0, tzinfo=timezone.utc))
    try:
        source_config.set_one("S2", "F1", "LIGHTGBM", confirm=True, changed_by="tester")
        source_config.set_one("S1", "F1", "AVG_DEMAND", confirm=True, changed_by="tester")
    finally:
        timeutil.set_now_override(None)
    sel2_view.clear_cache()
    after = {(x["sku_id"], x["fc_id"]): x["forecast_qty"] for x in client.get(url).json()["rows"]}
    assert after == before
    assert client.get("/api/history/summary?run_from=2026-11-05&run_to=2026-11-05").json()["daily"][0]["forecast"] == summ


def test_daily_page_of_an_exported_day_uses_the_files_configuration(scenario, client):
    """The Daily page of a run with an Excel keeps the numbers of that file after a later configuration change."""
    xl = _excel_rows(D)
    timeutil.set_now_override(lambda: datetime(2030, 1, 1, 1, 0, 0, tzinfo=timezone.utc))
    try:
        source_config.set_one("S2", "F1", "LIGHTGBM", confirm=True, changed_by="tester")   # after the export
    finally:
        timeutil.set_now_override(None)
    got = {}
    r = client.get("/api/daily-forecast/values?run_id=R1").json()
    for p in range(0, -(-r["total"] // r["page_size"])):
        for x in client.get(f"/api/daily-forecast/values?run_id=R1&page={p}").json()["rows"]:
            got[(x["sku_code"], x["fc_code"], x["horizon"])] = x
    assert set(got) == set(xl)
    for k, x in xl.items():
        assert (got[k]["forecast_used"], got[k]["forecast_source"], got[k]["fallback_reason"]) == \
            (x["forecast_used"], x["forecast_source"], x["fallback_reason"]), k
    assert "config_flag" not in client.get("/api/forecast-info").json()


def test_config_history_incomplete_is_flagged(scenario, client):
    export.write_daily_export(D, scope_key=SCOPE)
    with db.tx() as c:                                      # a row changed after the export without a history row
        c.execute("UPDATE forecast_source_config SET forecast_source='AVG_DEMAND', updated_at='2030-01-01T00:00:00+00:00' "
                  "WHERE sku_code='S1' AND fc_code='F1'")
    assert client.get("/api/forecast-info").json()["config_flag"] == "CONFIG_HISTORY_INCOMPLETE"


def test_day_after_0411_with_only_a_13x_publication_keeps_its_row(scenario, client):
    """Emergency switch-off: 05/11 has no SEL2 publication but a 1.3.x session -> its 1.3.x row (LIGHTGBM_CU)."""
    _old_run(5, "2026-11-05 08:00", "2026-11-05", (("S1", "F1"), ("S3", "F1")), 10.0)
    s = client.get("/api/history/summary?run_from=2026-11-04&run_to=2026-11-05").json()
    d5 = next(x for x in s["daily"] if x["run_date"] == "2026-11-05")
    assert d5["source_label"] == "LIGHTGBM_CU" and d5["has_history"] is True and d5["n_rows"] == 2
    rows = client.get("/api/history/rows?run_from=2026-11-04&run_to=2026-11-05").json()
    assert rows["total"] == 2 and {x["source_label"] for x in rows["rows"]} == {"LIGHTGBM_CU"}


# ------------------------------------------------------------------ memory over 30 days x 58k SKU x FC
N_KEYS, N_DAYS = 58_000, 30


@pytest.fixture
def big_history(sel2_on, monkeypatch):
    monkeypatch.setattr(history_routes, "resolve_scope", lambda c: dict(SC))
    start = date(2026, 11, 4)
    keys = [(f"S{i:05d}", "BD" if i % 2 else "HN") for i in range(N_KEYS)]
    for n in range(N_DAYS):
        d = start + timedelta(days=n)
        eid, rel, sha = f"EXP-B{n}", f"exports/du_bao/{d:%Y%m%d}/du_bao_{d:%Y%m%d}_v1.xlsx", f"{n:064d}"
        t = d.isoformat()                                   # 1.4.5: horizon 1, target = run date
        published.write(paths.data_dir() / rel, eid, d, sha, ((s, f, t, i % 7, "LIGHTGBM", None)
                                                              for i, (s, f) in enumerate(keys)))
        with db.tx() as c:
            c.execute("INSERT INTO export_runs(id, forecast_date, version, path, sha256, n_rows, is_stale, created_at, "
                      "summary_json) VALUES (?,?,1,?,?,?,0,?,?)",
                      (eid, d.isoformat(), rel, sha, N_KEYS * 20, f"{d.isoformat()}T01:00:00+00:00",
                       json.dumps({"scope_key": SCOPE, "model_version": "MV"})))
            c.executemany("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, loaded_at) "
                          "VALUES (?, 'BIGQUERY', ?, ?, ?, ?, '2026-12-10T00:00:00+00:00')",
                          [(SCOPE, t, s, f, 3.0) for s, f in keys[:500]])
    return start


def test_history_30_days_58k_keys_small_memory(big_history, client, monkeypatch):
    builds = []
    monkeypatch.setattr(sel2_view.View, "__init__", lambda self, c, run: builds.append(run["id"]))
    rng = f"run_from={big_history.isoformat()}&run_to={(big_history + timedelta(days=N_DAYS - 1)).isoformat()}"
    timeutil.set_now_override(lambda: datetime(2026, 12, 10, 12, 0, 0, tzinfo=timezone.utc))   # every target day past
    tracemalloc.start()
    t0 = time.monotonic()
    try:
        s = client.get(f"/api/history/summary?{rng}").json()
        r = client.get(f"/api/history/rows?{rng}&limit=100&offset=1000000").json()
        r2 = client.get(f"/api/history/rows?{rng}&limit=100&offset=500&sort=abs_error").json()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        timeutil.set_now_override(None)
    traced = time.monotonic() - t0
    t0 = time.monotonic()                                   # the same summary without tracemalloc (its overhead)
    timeutil.set_now_override(lambda: datetime(2026, 12, 10, 12, 0, 0, tzinfo=timezone.utc))
    try:
        assert client.get(f"/api/history/summary?{rng}").json()["kpi"]["n_rows"] == N_DAYS * N_KEYS
    finally:
        timeutil.set_now_override(None)
    elapsed = time.monotonic() - t0
    assert builds == []                                     # no view is built for the history
    assert peak < 150 * 2 ** 20, peak
    assert s["kpi"]["days_sel2"] == N_DAYS and s["kpi"]["n_rows"] == N_DAYS * N_KEYS
    assert sum(x["actual"] for x in s["daily"] if x["actual"] is not None) == pytest.approx(3.0 * 500 * N_DAYS)
    assert r["total"] == N_DAYS * N_KEYS and len(r["rows"]) == 100
    # the 1,000,000th row by date: newest day first, 58k rows per day
    day = big_history + timedelta(days=N_DAYS - 1 - 1_000_000 // N_KEYS)
    assert {x["run_date"] for x in r["rows"]} == {day.isoformat()}
    errs = [abs(x["forecast_qty"] - x["actual"]) for x in r2["rows"]]
    assert errs == sorted(errs, reverse=True) and len(r2["rows"]) == 100
    print(f"history 30 days x {N_KEYS}: summary {elapsed:.1f} s (traced run {traced:.1f} s), peak {peak / 2**20:.0f} MiB")
    assert elapsed < 30, (elapsed, traced)


def test_history_paging_equals_one_sorted_list(scenario, client):
    """Every sort: the pages joined = the rows of one request, each row once, in the same order."""
    export.write_daily_export(D - timedelta(days=1), scope_key=SCOPE)
    export.write_daily_export(D, scope_key=SCOPE)
    rng = "run_from=2026-11-04&run_to=2026-11-05"
    for sort in ("date", "forecast", "abs_error"):
        full = client.get(f"/api/history/rows?{rng}&limit=1000&sort={sort}").json()
        seen = []
        for off in range(0, full["total"], 3):
            seen += client.get(f"/api/history/rows?{rng}&limit=3&offset={off}&sort={sort}").json()["rows"]
        ids = [(x["run_date"], x["sku_id"], x["fc_id"]) for x in seen]
        assert ids == [(x["run_date"], x["sku_id"], x["fc_id"]) for x in full["rows"]], sort
        assert len(seen) == full["total"] == len(set(ids))


# ------------------------------------------------------------------ backfill of days exported before 1.4.4
H142 = ["sku_code", "ten_san_pham", "fc_code", "nhom", "forecast_date", "target_date", "horizon", "lightgbm_forecast",
        "avg_demand", "forecast_source", "forecast_used", "fallback_reason", "model_used", "raw_value", "model_version",
        "data_cutoff_date", "is_stale", "flags"]
H143 = export.COLUMNS


def _file(day: date, layout: str, version: int = 1) -> tuple[str, str]:
    """A daily Excel in the given layout (1.4.2 / 1.4.3: sheet DU_BAO; 1.4.4: DU_BAO_<fc>), recorded in export_runs.
    1.4.2: A2 has a fractional number, A3 none."""
    rel = f"exports/du_bao/{day.strftime('%Y%m%d')}/du_bao_{day.strftime('%Y%m%d')}_v{version}.xlsx"
    p = paths.data_dir() / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    wb.remove(wb.active)
    head = H142 if layout == "1.4.2" else list(H143) + (["cach_tinh"] if layout == "1.4.4" else [])
    sheets = {"DU_BAO": None} if layout != "1.4.4" else {"DU_BAO_BD": "BD", "DU_BAO_HN": "HN"}
    for name, only in sheets.items():
        ws = wb.create_sheet(name)
        ws.append(head)
        for sku, fc in (("A1", "BD"), ("A2", "HN"), ("A3", "BD")):
            if only and fc != only:
                continue
            for h in range(1, 8):
                used = 10 * h + int(sku[1])
                if layout == "1.4.2" and sku == "A3":
                    used = None
                elif layout == "1.4.2" and sku == "A2":
                    used += 0.5
                row = {"sku_code": sku, "fc_code": fc, "forecast_date": day, "target_date": day + timedelta(days=h - 1),
                       "horizon": h, "forecast_used": used, "forecast_source": "LIGHTGBM",
                       "fallback_reason": None if h != 2 else "X"}
                ws.append([row.get(c) for c in head])
    wb.save(p)
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    eid = f"EXP-{layout}-{day.isoformat()}-{version}"
    with db.tx() as c:
        c.execute("INSERT INTO export_runs(id, forecast_date, version, path, sha256, n_rows, is_stale, created_at, "
                  "summary_json) VALUES (?,?,?,?,?,?,0,?,?)",
                  (eid, day.isoformat(), version, rel, sha, 21, f"{day.isoformat()}T0{version}:00:00+00:00",
                   json.dumps({"scope_key": SCOPE})))
    return eid, rel


def test_backfill_three_layouts_idempotent(sel2_on):
    e2, _ = _file(date(2026, 11, 4), "1.4.2")
    e3, _ = _file(date(2026, 11, 5), "1.4.3")
    _file(date(2026, 11, 6), "1.4.3", version=1)
    e4, _ = _file(date(2026, 11, 6), "1.4.4", version=2)     # the newest export of 06/11 is the one read
    dry = published.backfill("2026-11-03", "2026-11-06")
    st = {x["forecast_date"]: x for x in dry["days"]}
    assert st["2026-11-03"]["status"] == "NO_EXPORT" and st["2026-11-04"]["status"] == "WOULD_CREATE"
    assert st["2026-11-04"]["rows"] == 2
    assert st["2026-11-04"]["flags"] == {"rows_without_number": 1, "rows_fractional": 1}
    assert st["2026-11-06"]["export_run_id"] == e4 and st["2026-11-06"]["layout"] == "DU_BAO_<fc>"
    assert not list(paths.data_dir().rglob("*.h2.json.gz"))  # dry run: nothing written
    res = published.backfill("2026-11-03", "2026-11-06", apply=True)
    assert [x["status"] for x in res["days"]] == ["NO_EXPORT", "CREATED", "CREATED", "CREATED"]
    assert _sidecar(e2)["rows"] == [["A1", "BD", "2026-11-04", 11, "LIGHTGBM", None],
                                    ["A2", "HN", "2026-11-04", 12.5, "LIGHTGBM", None]]  # never 0, kept as written (h1)
    assert len(_sidecar(e3)["rows"]) == 3 and len(_sidecar(e4)["rows"]) == 3
    snap = {e: _sidecar_file(e).read_bytes() for e in (e2, e3, e4)}
    again = published.backfill("2026-11-03", "2026-11-06", apply=True)
    assert [x["status"] for x in again["days"]][1:] == ["PRESENT"] * 3
    assert {e: _sidecar_file(e).read_bytes() for e in (e2, e3, e4)} == snap


def test_backfill_refuses_a_changed_or_missing_file(sel2_on):
    _, rel = _file(date(2026, 11, 4), "1.4.3")
    with open(paths.data_dir() / rel, "ab") as f:
        f.write(b"x")
    _, rel5 = _file(date(2026, 11, 5), "1.4.3")
    (paths.data_dir() / rel5).unlink()
    res = published.backfill("2026-11-04", "2026-11-05", apply=True)
    assert [x["status"] for x in res["days"]] == ["SHA256_MISMATCH", "FILE_MISSING"]
    assert not list(paths.data_dir().rglob("*.h2.json.gz"))


def test_backfill_cli_dry_run_by_default(sel2_on, capsys):
    from app import cli
    e3, _ = _file(date(2026, 11, 4), "1.4.3")
    assert cli.main(["sel2-published-backfill", "--start", "2026-11-04", "--end", "2026-11-04"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True and out["result"]["days"][0]["status"] == "WOULD_CREATE" and _sidecar(e3) is None
    assert cli.main(["sel2-published-backfill", "--start", "2026-11-04", "--end", "2026-11-04", "--yes"]) == 0
    assert len(_sidecar(e3)["rows"]) == 3


def test_no_schema_change_in_1_4_4():
    assert max(v for v, _ in db.available_migrations()) == 12


# ------------------------------------------------------------------ T2-fix4: sidecars under <export root>\.published
def _sidecars() -> list[Path]:
    return sorted(paths.data_dir().rglob("*.h2.json.gz"))


def test_backfill_cli_writes_under_published_and_is_idempotent(sel2_on, capsys):
    """sel2-published-backfill --yes: <export root>/.published/YYYYMMDD/<stem>.h2.json.gz, the day folder keeps the
    Excel only; a second run reports PRESENT and leaves every sidecar byte-identical (no duplicate, no rewrite)."""
    from app import cli
    e4, rel4 = _file(date(2026, 11, 4), "1.4.3")
    e5, rel5 = _file(date(2026, 11, 5), "1.4.4")
    args = ["sel2-published-backfill", "--start", "2026-11-04", "--end", "2026-11-05", "--yes"]
    assert cli.main(args) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is False and [x["status"] for x in out["result"]["days"]] == ["CREATED", "CREATED"]
    root = paths.data_dir() / "exports" / "du_bao"
    want = {root / ".published" / "20261104" / "du_bao_20261104_v1.h2.json.gz",
            root / ".published" / "20261105" / "du_bao_20261105_v1.h2.json.gz"}
    assert set(_sidecars()) == want and {_sidecar_file(e4), _sidecar_file(e5)} == want
    for rel in (rel4, rel5):                                 # the day folders list the Excel files only
        assert [p.name for p in (paths.data_dir() / rel).parent.iterdir()] == [Path(rel).name]
    assert _sidecar(e4)["rows"] and _sidecar(e5)["export_run_id"] == e5
    snap = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in want}
    assert cli.main(args) == 0
    again = json.loads(capsys.readouterr().out)
    assert [x["status"] for x in again["result"]["days"]] == ["PRESENT", "PRESENT"]
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in _sidecars()} == snap
    assert not [p for p in root.rglob("*") if p.suffix == ".tmp"]


def test_history_reads_several_days_under_published_and_ignores_the_folder(scenario, client):
    """Three exported days (04/11 v1, 05/11 v1 + v2): one .published/YYYYMMDD folder per day, the history reads the
    newest version of each day from there; the .published folder (and a stray file in it) is never taken as a day
    folder or a version: versions keep counting from export_runs and the day folders hold the Excel only."""
    d4, d6 = D - timedelta(days=1), D + timedelta(days=1)
    r4 = export.write_daily_export(d4, scope_key=SCOPE)
    r5a = export.write_daily_export(D, scope_key=SCOPE)
    r5b = export.write_daily_export(D, scope_key=SCOPE)
    assert (r5a["version"], r5b["version"]) == (1, 2)
    root = paths.data_dir() / "exports" / "du_bao"
    pub = root / ".published"
    assert sorted(p.name for p in pub.iterdir()) == ["20261104", "20261105"]
    assert sorted(p.name for p in (pub / "20261105").iterdir()) == ["du_bao_20261105_v1.h2.json.gz",
                                                                     "du_bao_20261105_v2.h2.json.gz"]
    (pub / "20261106").mkdir()                              # a stray folder / file for a day without an export
    (pub / "20261106" / "du_bao_20261106_v1.h2.json.gz").write_bytes(b"not a sidecar")
    assert sorted(p.name for p in root.iterdir()) == [".published", "20261104", "20261105"]
    for day in ("20261104", "20261105"):
        assert all(p.suffix == ".xlsx" for p in (root / day).iterdir())
    published.clear_cache()
    s = client.get("/api/history/summary?run_from=2026-11-04&run_to=2026-11-06")
    assert s.status_code == 200, s.text
    by = {x["run_date"]: x for x in s.json()["daily"]}
    assert by["2026-11-05"]["export_run_id"] == r5b["id"] and by["2026-11-04"]["export_run_id"] == r4["id"]
    assert by["2026-11-04"]["source_label"] == by["2026-11-05"]["source_label"] == "SEL2"
    assert by["2026-11-05"]["n_rows"] == len(_sidecar(r5b["id"])["rows"]) > 0
    assert by["2026-11-04"]["n_rows"] == len(_sidecar(r4["id"])["rows"]) > 0
    assert by.get("2026-11-06", {}).get("source_label") != "SEL2"   # the stray .published/20261106 is no publication
    rows = client.get("/api/history/rows?run_from=2026-11-04&run_to=2026-11-06&limit=1000").json()
    assert rows["total"] == by["2026-11-04"]["n_rows"] + by["2026-11-05"]["n_rows"]
    assert {x["export_run_id"] for x in rows["rows"]} == {r4["id"], r5b["id"]}
    r6 = export.write_daily_export(d6, scope_key=SCOPE)     # a new day after the stray file: version 1, own sidecar
    assert r6["version"] == 1 and _sidecar(r6["id"])["export_run_id"] == r6["id"]
    assert sorted(p.name for p in root.iterdir()) == [".published", "20261104", "20261105", "20261106"]


def _two_days(client) -> tuple[dict, dict, dict]:
    """Exports of 04/11 and 05/11 and the history summary of both read from intact sidecars."""
    r4 = export.write_daily_export(D - timedelta(days=1), scope_key=SCOPE)
    r5 = export.write_daily_export(D, scope_key=SCOPE)
    published.clear_cache()
    s = client.get("/api/history/summary?run_from=2026-11-04&run_to=2026-11-05").json()
    return r4, r5, {x["run_date"]: x for x in s["daily"]}


def _corrupt(p: Path, how: str) -> None:
    raw = p.read_bytes()
    if how == "truncated":
        p.write_bytes(raw[: len(raw) // 2])
    elif how == "not_gzip":
        p.write_bytes(b"this is not a gzip file")
    elif how == "bad_deflate":                              # valid gzip header (with its FNAME), damaged body
        head = raw.index(b"\x00", 10) + 1 if raw[3] & 0x08 else 10
        p.write_bytes(raw[:head] + b"\xff" * 64)
    elif how == "empty":
        p.write_bytes(b"")


@pytest.mark.parametrize("how", ["truncated", "not_gzip", "bad_deflate", "empty"])
def test_corrupt_sidecar_of_one_day_is_rebuilt_and_other_days_unchanged(scenario, client, how):
    """Documented: an unreadable sidecar is rebuilt from the recorded xlsx (sha256 checked); the other day is untouched."""
    r4, r5, before = _two_days(client)
    side5 = _sidecar_file(r5["id"]).read_bytes()
    _corrupt(_sidecar_file(r4["id"]), how)
    published.clear_cache()
    s = client.get("/api/history/summary?run_from=2026-11-04&run_to=2026-11-05")
    assert s.status_code == 200, s.text
    after = {x["run_date"]: x for x in s.json()["daily"]}
    for k in ("n_rows", "forecast", "export_run_id", "source_label"):
        assert after["2026-11-04"][k] == before["2026-11-04"][k], k
        assert after["2026-11-05"][k] == before["2026-11-05"][k], k
    assert _sidecar(r4["id"])["export_run_id"] == r4["id"]   # rewritten as a valid sidecar
    assert _sidecar_file(r5["id"]).read_bytes() == side5


@pytest.mark.parametrize("how", ["truncated", "bad_deflate", "missing"])
def test_unusable_day_without_its_xlsx_leaves_the_other_days(scenario, client, how):
    """Sidecar missing / corrupt AND the version xlsx gone: load() returns None (documented), that day shows no rows,
    the history request still answers and the other day keeps its numbers."""
    r4, r5, before = _two_days(client)
    if how == "missing":
        _sidecar_file(r4["id"]).unlink()
    else:
        _corrupt(_sidecar_file(r4["id"]), how)
    (paths.data_dir() / _record(r4["id"])["path"]).unlink()
    published.clear_cache()
    assert published.load(_record(r4["id"])) is None
    s = client.get("/api/history/summary?run_from=2026-11-04&run_to=2026-11-05")
    assert s.status_code == 200, s.text
    after = {x["run_date"]: x for x in s.json()["daily"]}
    assert after["2026-11-04"]["n_rows"] == 0
    for k in ("n_rows", "forecast", "export_run_id"):
        assert after["2026-11-05"][k] == before["2026-11-05"][k], k
    rows = client.get("/api/history/rows?run_from=2026-11-04&run_to=2026-11-05&limit=1000")
    assert rows.status_code == 200, rows.text
    assert {x["run_date"] for x in rows.json()["rows"]} == {"2026-11-05"}
    assert rows.json()["total"] == before["2026-11-05"]["n_rows"]


def test_backfill_cli_with_a_corrupt_sidecar_rebuilds_it(sel2_on, capsys):
    """A damaged sidecar is not PRESENT: the backfill rebuilds it from the xlsx at the same .published path."""
    from app import cli
    e4, _ = _file(date(2026, 11, 4), "1.4.3")
    args = ["sel2-published-backfill", "--start", "2026-11-04", "--end", "2026-11-04", "--yes"]
    assert cli.main(args) == 0
    good = _sidecar_file(e4).read_bytes()
    capsys.readouterr()
    _corrupt(_sidecar_file(e4), "bad_deflate")
    assert cli.main(args) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["result"]["days"][0]["status"] == "CREATED"
    assert _sidecar(e4)["rows"] == json.loads(gzip.decompress(good))["rows"]
    assert _sidecars() == [_sidecar_file(e4)]
