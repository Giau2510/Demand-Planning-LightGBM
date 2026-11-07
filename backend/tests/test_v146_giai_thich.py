"""1.4.6 C3 (owner decision 06/11/2026 21:20): sheet GIAI_THICH of the daily Excel (ml/sel2/giai_thich.py, pipeline
sidecar, export.py). Unit tests of the pure parts (history, ly_do, TreeSHAP additivity on a small model) and one
integration with fakes: the SEL2 pipeline on synthetic rows in the isolated test database (no live data)."""
import shutil
from datetime import date, timedelta

import lightgbm as lgb
import numpy as np
import pytest
from openpyxl import load_workbook

from app import db, paths
from app import settings_service as ss
from app.export_i18n import giai_thich_labels
from app.ml.sel2 import export, giai_thich, pipeline, select, store
from test_v140_t4a_pipeline import SCOPE, _plenty_of_memory, _seed

L = giai_thich_labels("vi")[1]


# ------------------------------------------------------------------ history
def test_history_stats_on_a_synthetic_series():
    G = 40
    daily = np.zeros((2, G))
    oh = np.full((2, G), 8.0, dtype=np.float32)
    daily[0, G - 1], daily[0, G - 3], daily[0, G - 10] = 4, 2, 6          # series 0: sales 1, 3, 10 days before
    oh[1, G - 9:] = 0                                                    # series 1: closed the last 9 days, no sale
    oh[1, G - 12] = np.nan
    h = giai_thich.history_stats(daily, oh, G)
    assert h["yday"].tolist() == [4, 0]
    assert h["mean7"][0] == pytest.approx(6 / 7) and h["mean28"][0] == pytest.approx(12 / 28)
    assert h["med28"].tolist() == [0, 0] and h["sale28"].tolist() == [3, 0]
    assert h["open28"].tolist() == [28, 28 - 9 - 1]
    assert h["last"].tolist() == [G - 1, -1] and h["closed"].tolist() == [0, 9]
    daily[0, G - 1] = 0
    assert giai_thich.history_stats(daily, oh, G)["last"][0] == G - 3


# ------------------------------------------------------------------ ly_do
@pytest.mark.parametrize("kw, want", [
    (dict(used=3), None),
    (dict(reason="NGOAI_PHAM_VI_GAN_0"), "ngoài phạm vi lần chạy"),
    (dict(reason="KHONG_CO_SO_NAO"), L["ly_do"]["no_number"]),
    (dict(src="AVG_DEMAND", avg=0.15), "cấu hình AVG_DEMAND: dùng avg_demand (0,15)"),
    (dict(closed=9), "không mở bán 9 ngày gần đây"),
    (dict(closed=365), "không mở bán từ 365 ngày trở lên"),
    (dict(mu="V36_two_stage@0.6+TSB", p=0.35, v36=0.0, raw=0.05), "xác suất có đơn thấp (P = 0,35 < 0,6)"),
    (dict(mu="V36_two_stage@0.6+TSB", p=0.75, v36=0.0, raw=0.13), "bán lác đác: dự báo 0,13 < 0,2"),
    (dict(raw=0.13), "bán lác đác: dự báo 0,13 < 0,2"),
    (dict(raw=0.0, sale28=0), "không có đơn trong 28 ngày gần đây"),
    (dict(raw=0.0, sale28=2), "các mô hình được chọn đều dự báo 0"),
])
def test_ly_do_rules(kw, want):
    a = dict(used=0, reason=None, src="LIGHTGBM", raw=None, avg=None, mu="MOC+DOW4", p=None, v36=None, closed=0,
             sale28=1)
    a.update(kw)
    assert giai_thich.ly_do(a["used"], a["reason"], a["src"], a["raw"], a["avg"], a["mu"], a["p"], a["v36"], 0.6,
                            a["closed"], a["sale28"], L) == want


def test_factor_model_and_fallback_code():
    assert giai_thich.factor_model("TSB+V33_L112") == "V33_L112"
    assert giai_thich.factor_model("FALLBACK:V33_L112") == "V33_L112"
    assert giai_thich.factor_model("TSB+AVG7") is None
    assert giai_thich.fallback_code(True, 20, 20, True) is None
    assert giai_thich.fallback_code(False, 0, 0, True) == "NO_OPEN_DAY"
    assert giai_thich.fallback_code(False, 9, 20, True) == "FEW_DAYS"
    assert giai_thich.fallback_code(True, 20, 20, False) == "SECOND_MISSING"


# ------------------------------------------------------------------ TreeSHAP
def test_top3_contributions_and_shap_additivity_on_a_small_model():
    rng = np.random.default_rng(3)
    X = rng.normal(size=(400, 6))
    y = np.maximum(0, np.round(np.exp(0.8 * X[:, 0] - 0.5 * X[:, 2]) * rng.poisson(1.0, 400)))
    b = lgb.train({"objective": "tweedie", "num_leaves": 7, "verbose": -1, "num_threads": 1, "seed": 1},
                  lgb.Dataset(X, y), num_boost_round=30)
    names = [f"f{i}" for i in range(6)]
    c = b.predict(X[:50], pred_contrib=True)
    assert np.allclose(c.sum(axis=1), b.predict(X[:50], raw_score=True))          # additivity (raw score)
    assert np.allclose(np.exp(c.sum(axis=1)), b.predict(X[:50]))                  # tweedie: log link
    top = giai_thich.top_contributions(c, X[:50], names)
    for row, cr, xr in zip(top, c, X[:50]):
        assert len(row) == 3
        mags = [abs(t[2]) for t in row]
        assert mags == sorted(mags, reverse=True) and min(mags) >= np.sort(np.abs(cr[:6]))[-3] - 1e-12
        for name, val, con in row:
            j = names.index(name)
            assert val == pytest.approx(xr[j]) and con == pytest.approx(cr[j])


# ------------------------------------------------------------------ pipeline + export (integration with fakes)
D = date(2026, 10, 28)


@pytest.fixture
def published_day(sel2_on, monkeypatch):
    monkeypatch.setattr(pipeline, "MIN_COMMIT_MB", 0)
    _plenty_of_memory(monkeypatch)
    _seed()
    for o in (date(2026, 10, 12), date(2026, 10, 19), date(2026, 10, 26)):   # Mondays
        pipeline.train_week(o, scope_key=SCOPE)
    for i in range(16, 0, -1):
        pipeline.candidates_for_day(D - timedelta(days=i), scope_key=SCOPE)
    res = pipeline.run_day(D, scope_key=SCOPE, trigger="test")
    assert res["status"] == "PUBLISHED" and res["giai_thich"]["ok"], res.get("giai_thich")
    print("GIAI_THICH child:", {k: res["giai_thich"].get(k) for k in ("seconds", "seconds_total", "peak_private_mb",
                                                                       "series")})
    return res


def _sheets(rel):
    wb = load_workbook(paths.data_dir() / rel, read_only=True)
    out = {n: [list(r) for r in wb[n].iter_rows(values_only=True)] for n in wb.sheetnames}
    wb.close()
    return out


def test_sidecar_values_counts_and_factors(published_day):
    res = published_day
    doc = giai_thich.load(SCOPE, D, res["run_id"])
    assert doc is not None and doc["candidates"] == list(select.CANDIDATES)
    c = doc["cols"]
    with db.read() as conn:
        today = store.read_day(conn, SCOPE, D)
        used = {(r[0], r[1]): r[2] for r in conn.execute(
            "SELECT sku_code, fc_code, method FROM forecast_refresh_values WHERE run_id=? AND horizon=1",
            (res["run_id"],))}
    keys = list(zip(doc["sku"], doc["fc"]))
    assert set(keys) == set(used) and [used[k] for k in keys] == c["model_used"]
    # candidate values = the stored candidate forecasts of D at horizon 1
    for j, name in enumerate(doc["candidates"]):
        f = today[name][today[name]["horizon"] == 1]
        stored = dict(zip(zip(f["sku_code"], f["fc_code"]), f["value"]))
        assert [c[f"val_{j}"][i] for i in range(len(keys))] == pytest.approx([stored[k] for k in keys])
    # 28-day counts = select.py's scoring, computed again independently
    s = ss.get("sel2_pipeline")
    inp = pipeline.load(SCOPE, D, s)
    sk = inp.scope_keys(D)
    import pandas as pd
    idx = pd.MultiIndex.from_frame(sk[["sku_code", "fc_code"]])
    counts = {}
    with db.read() as conn:
        select._scores(D, idx, list(select.CANDIDATES), store.History(conn, SCOPE, D, s.window_days),
                       inp.actuals(D, s.window_days), inp.open_days(D, s.window_days),
                       inp.groups(D, s.group_mode, s.group_fixed_start, s.group_fixed_end), None, None,
                       s.window_days, counts)
    pos = {k: i for i, k in enumerate(zip(sk["sku_code"], sk["fc_code"]))}
    for j in range(len(select.CANDIDATES)):
        assert c[f"dung_{j}"] == [int(counts["n_dung"][j, pos[k]]) for k in keys]
        assert c[f"cham_{j}"] == [int(counts["n_cells"][j, pos[k]]) for k in keys]
    assert sum(c["cham_0"]) > 0 and any(c["ok"])
    # factors: the factor model's own prediction equals the stored candidate value; raw score = exp-linked prediction
    assert doc["counts"]["with_factors"] > 0 and doc["counts"]["factor_mismatch"] == 0
    for i in range(len(keys)):
        if c["f_model"][i] and c["f_part"][i] == "reg":
            assert np.exp(c["f_raw"][i]) == pytest.approx(c["f_pred"][i], rel=1e-6)
            assert len(c["f_top"][i]) == 3


def test_export_sheet_rows_and_unchanged_sheets(published_day, tmp_path):
    res = published_day
    with_gt = export.write_daily_export(D, scope_key=SCOPE)
    a = _sheets(with_gt["path"])
    names = list(a)
    assert names[-3:] == ["GIAI_THICH", "TOM_TAT", "CONFIG"] and all(n.startswith("DU_BAO_") for n in names[:-3])
    cols = giai_thich.columns(select.CANDIDATES)
    assert a["GIAI_THICH"][0] == cols
    gt = [dict(zip(cols, r)) for r in a["GIAI_THICH"][1:]]
    du = [dict(zip(export.COLUMNS20, r)) for n in names if n.startswith("DU_BAO_") for r in a[n][1:]]
    h1 = [(r["sku_code"], r["fc_code"]) for r in du if r["horizon"] == 1 and r["lightgbm_forecast"] is not None]
    assert [(r["sku_code"], r["fc_code"]) for r in gt] == h1 and len(set(h1)) == len(h1) > 0   # one row per SKU x FC
    for r in gt:
        assert r["lan_chay_giai_thich"] == f"{D.isoformat()}:{res['run_id']}"
        assert (r["ly_do"] is None) == (r["forecast_used"] != 0)
        assert (r["ly_do_fallback"] is None) == (not str(r["model_used"]).startswith("FALLBACK"))
        assert r["MOC_du_bao"] is not None and r["tb_28_ngay"] is not None
    s = {r[0]: r[1] for r in a["TOM_TAT"][1:]}
    assert s["giai_thich_rows"] == len(gt) and s["giai_thich_rows_without_detail"] == 0 and "giai_thich" in s
    # without the sidecar: the 1.4.5 file (no GIAI_THICH, no extra TOM_TAT line); the other sheets cell-identical
    p = giai_thich.sidecar_path(SCOPE, D, res["run_id"])
    shutil.move(p, tmp_path / p.name)
    b = _sheets(export.write_daily_export(D, scope_key=SCOPE)["path"])
    assert list(b) == [n for n in names if n != "GIAI_THICH"]
    for n in b:
        if n.startswith("DU_BAO_") or n == "CONFIG":
            assert a[n] == b[n], n
    skip = ("export_version", "export_time_utc", "export_time_vn", "generated_at")
    ta = [r for r in a["TOM_TAT"] if r[0] not in skip and not str(r[0]).startswith("giai_thich")]
    tb = [r for r in b["TOM_TAT"] if r[0] not in skip]
    assert ta == tb and not any(str(r[0]).startswith("giai_thich") for r in b["TOM_TAT"])


# ------------------------------------------------------------------ 1.4.6 fix round: safety of the night run
def test_child_failure_timeout_and_low_memory_never_fail_the_run_or_the_excel(published_day, monkeypatch):
    import sys
    # the child's build raises: the run is published, the Excel is written without GIAI_THICH and flagged
    boom = ("import sys; from app.ml.sel2 import giai_thich as g; "
            "g.build = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')); "
            "raise SystemExit(g.child_main(sys.argv[1:]))")
    monkeypatch.setattr(pipeline, "_giai_thich_cmd", lambda args: [sys.executable, "-c", boom, *args])
    res = pipeline.run_day(D, scope_key=SCOPE, trigger="test", force=True)
    assert res["status"] == "PUBLISHED" and res["run_id"] != published_day["run_id"]
    gtr = res["giai_thich"]
    assert gtr["ok"] is False and gtr["status"] == "FAILED" and "boom" in gtr["reason"]
    assert not giai_thich.exists(SCOPE, D, res["run_id"])
    assert giai_thich.read_status(SCOPE, D, res["run_id"])["status"] == "FAILED"
    assert not list(giai_thich.sidecar_path(SCOPE, D, res["run_id"]).parent.glob("*.npz"))   # temporary file removed
    exp = export.write_daily_export(D, scope_key=SCOPE)        # (the test DB has no active scope for the hook's export)
    assert giai_thich.FLAG_SKIPPED in exp["flags"]
    book = _sheets(exp["path"])
    assert "GIAI_THICH" not in book and exp["summary"]["giai_thich"]["status"] == "FAILED"
    assert giai_thich.FLAG_SKIPPED in {r[0]: r[1] for r in book["TOM_TAT"][1:]}["file_flags"]
    # timeout: the child is killed, status TIMEOUT
    monkeypatch.setattr(pipeline, "_giai_thich_cmd", lambda args: [sys.executable, "-c", "import time; time.sleep(60)"])
    monkeypatch.setattr(pipeline, "GIAI_THICH_TIMEOUT_S", 0)
    r = pipeline._giai_thich_hook(D, SCOPE, "RUN-T", {"keys": [], "candidates": ["MOC"],
                                                      **{k: np.zeros(0) for k in giai_thich.DETAIL_KEYS}})
    assert r["ok"] is False and r["status"] == "TIMEOUT" and r["seconds_total"] < 30
    # low free commit: skipped before any child, status file written
    monkeypatch.setattr(pipeline, "GIAI_THICH_MIN_COMMIT_MB", 1 << 40)
    r = pipeline._giai_thich_hook(D, SCOPE, "RUN-M", {"keys": []})
    assert r["status"] == "SKIPPED_LOW_MEMORY" and giai_thich.read_status(SCOPE, D, "RUN-M")["status"] == r["status"]


def test_select_day_detail_changes_nothing_and_v36_classifier_branch(published_day):
    import pandas as pd
    s = ss.get("sel2_pipeline")
    inp = pipeline.load(SCOPE, D, s)
    sk = inp.scope_keys(D)
    groups = inp.groups(D, s.group_mode, s.group_fixed_start, s.group_fixed_end)
    outs = []
    for det in (None, {}):
        with db.read() as conn:
            outs.append(select.select_day(D, sk, store.read_day(conn, SCOPE, D),
                                          store.History(conn, SCOPE, D, s.window_days),
                                          inp.actuals(D, s.window_days), inp.open_days(D, s.window_days), groups,
                                          best=s.fallback_model, window_days=s.window_days, min_days=s.min_days,
                                          detail=det))
    pd.testing.assert_frame_equal(outs[0], outs[1])
    # V36 two-stage below its threshold: the classifier is explained; its candidate value at that threshold is 0
    keys = list(zip(sk["sku_code"], sk["fc_code"]))
    with db.read() as conn:
        tids = {r["model"]: r["train_run_id"] for r in store.day_runs(conn, SCOPE, D) if r["train_run_id"]}
    S = len(keys)
    f = giai_thich._factors(D, inp.frame, keys, [giai_thich.TWO_STAGE] * S, tids, 1.01, np.ones(S, dtype=bool),
                            {giai_thich.TWO_STAGE: np.zeros(S)})
    assert f["f_part"] == ["clf"] * S and f["f_match"] == [True] * S
    assert np.allclose(1 / (1 + np.exp(-f["f_raw"])), f["f_pred"]) and np.allclose(f["f_pred"], f["p_v36"])
    # a training that cannot be read: its own text, never "not LightGBM"
    f = giai_thich._factors(D, inp.frame, keys, ["MOC"] * S, {}, 0.6, np.zeros(S, dtype=bool), {"MOC": np.zeros(S)})
    assert f["f_err"] == ["MOC"] * S and f["f_model"] == [None] * S


def test_export_loads_previous_sidecars_only_when_used(published_day, monkeypatch):
    calls = []
    real = giai_thich.load
    monkeypatch.setattr(giai_thich, "load", lambda sc, d, rid: calls.append(rid) or real(sc, d, rid))
    export.write_daily_export(D, scope_key=SCOPE)
    assert calls == [published_day["run_id"]]                # today's run only (no row from a previous run)


def test_retention_deletes_old_sidecars_only(data_dir):
    folder = giai_thich.sidecar_path("S", D, "R").parent
    folder.mkdir(parents=True)
    names = [f"{(D - timedelta(days=n)).isoformat()}_R{n}.json.gz" for n in (0, 119, 120, 121, 300)]
    names += [f"{(D - timedelta(days=200)).isoformat()}_R.status.json", "notes.txt"]
    for n in names:
        (folder / n).write_text("x")
    r = giai_thich.apply_retention(D, 120)
    assert r == {"cutoff": (D - timedelta(days=120)).isoformat(), "files": 3}
    assert sorted(p.name for p in folder.iterdir()) == sorted([names[0], names[1], names[2], "notes.txt"])


def test_backup_excludes_the_giai_thich_sidecars(data_dir, tmp_path):
    import zipfile
    from app import backup
    side = giai_thich.sidecar_path("S", D, "R")
    side.parent.mkdir(parents=True)
    side.write_bytes(b"x")
    model = store.model_dir("2026-10-26", "S") / "MOC_CTR1.txt"
    model.parent.mkdir(parents=True)
    model.write_text("m")
    with zipfile.ZipFile(backup.backup_database("test", dest_dir=tmp_path)) as z:
        names = z.namelist()
    rel = model.relative_to(paths.models_dir()).as_posix()
    assert f"models/{rel}" in names and not any("giai_thich" in n for n in names)


def test_run_day_applies_the_7_day_sidecar_retention(monkeypatch):
    """owner 07/11: the explanation sidecars are kept 7 days whatever sel2_pipeline.retention_days is"""
    from app.ml.sel2 import pipeline, giai_thich
    assert pipeline.GIAI_THICH_RETENTION_DAYS == 7
    import inspect
    src = inspect.getsource(pipeline)
    assert "giai_thich.apply_retention(d, GIAI_THICH_RETENTION_DAYS)" in src
    assert "giai_thich.apply_retention(d, s.retention_days)" not in src
