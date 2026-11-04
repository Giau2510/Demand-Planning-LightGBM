"""1.4.2 tests: (A) the SEL2 FORECAST_REFRESH reads the open hours of the BigQuery scope up to D-1 before the day's
child (ml/sel2/jobs.open_hours_read -> daily_refresh.sync_open_hours; a failed read is the flag OPEN_HOURS_READ_FAILED
and never blocks; no read for another source, without a scope or for a past business day) and (B) the backup keeps the
nested model files (models/sel2/<scope hash>/<origin>/<file>, without the .tmp / .lock files of the subfolders) and the
restore writes them back at their relative path, checking every member before the safety backup and the DB swap.

The heavy child is always a fake (sel2_jobs.set_child_runner), BigQuery always a fake client (fake_bq.FakeBQ / OhBQ),
isolated databases and model folders (conftest), fixed Vietnam times: unit tests and integration with fakes only."""
import hashlib
import json
import shutil
import sqlite3
import sys
import zipfile
from datetime import timedelta

import pytest

from app import backup, db, paths
from app import settings_service as ss
from app.bq import aux_sources, connector
from app.messages import AppError
from app.ml import daily_refresh as dr
from app.ml.sel2 import avg_demand
from app.ml.sel2 import jobs as sel2_jobs

from fake_bq import FakeBQ
from test_v131_refresh import _d1_ok, _fake_oh, _freeze, _no_real_bigquery  # noqa: F401 (autouse fixture)
from test_v131_refresh_jobs import _bq_scope, _patched_get, _sched
from test_v140_t4b_jobs import PUBLISHED, _child, _refresh, _reset_child, _result, env  # noqa: F401 (fixtures)
from test_v140_t4b_planning import TUE, _at


def _fake_sync(order, result=None, exc=None):
    """A daily_refresh.sync_open_hours stand-in recording its call (and its place among the other steps)."""
    calls = []

    def sync(d, floor=None, cfg=None):
        order.append("open_hours")
        calls.append((d, floor, cfg))
        if exc is not None:
            raise exc
        return dict(result if result is not None else {"start": "2026-08-01", "end": str(d - timedelta(days=1)),
                                                        "mode": "INCREMENTAL", "rows": 4, "last_day": str(d - timedelta(days=1))})
    return sync, calls


def _recording(monkeypatch, order, **kw):
    """Record the order of the open-hours read, the AVG_DEMAND read and the child."""
    sync, calls = _fake_sync(order, **kw)
    monkeypatch.setattr(dr, "sync_open_hours", sync)
    inner = avg_demand.read_current

    def avg(d, cfg=None, bq=None):
        order.append("avg")
        return inner(d, cfg, bq)
    monkeypatch.setattr(avg_demand, "read_current", avg)
    child_calls = []

    def run(args, timeout, cancel):
        order.append("child")
        child_calls.append(list(args))
        return PUBLISHED
    sel2_jobs.set_child_runner(run)
    return calls, child_calls


# ================================================================== (A) open-hours read before the day's run
def test_a1_open_hours_read_runs_before_the_avg_read_and_the_child(env, monkeypatch):
    order = []
    calls, child_calls = _recording(monkeypatch, order)
    row = _refresh()
    assert row["status"] == "SUCCEEDED" and row["reason_code"] == "SEL2_PUBLISHED"
    assert order == ["open_hours", "avg", "child"]
    (d, floor, cfg), = calls
    assert d == TUE and floor == ss.get("data_policy").window_start_date      # data window floor of the BQ scope
    assert cfg is not None and cfg.openhours_table == ss.get("daily_forecast").openhours_table
    res = _result(row)
    assert res["open_hours"] == {"start": "2026-08-01", "end": str(TUE - timedelta(days=1)), "mode": "INCREMENTAL",
                                 "rows": 4, "last_day": str(TUE - timedelta(days=1))}
    assert "OPEN_HOURS_READ_FAILED" not in res["flags"] and res["flags"] == ["MODEL_PREV_WEEK"]
    assert child_calls[0][:3] == ["sel2-day", "--date", str(TUE)]


def test_a1_vietnam_day_just_after_midnight_is_today_although_utc_is_still_yesterday(sel2_on, monkeypatch):
    _bq_scope()
    _freeze(_at(TUE, "00:30"))                                       # 17:30 UTC of 02/11
    _d1_ok(day=TUE)
    monkeypatch.setattr(ss, "get", _patched_get(_sched(refresh_enabled=True)))
    monkeypatch.setattr(avg_demand, "read_current", lambda d, cfg=None, bq=None: {"read_id": None, "rows": 0})
    order = []
    calls, _child_calls = _recording(monkeypatch, order)
    row = _refresh(key="FORECAST_REFRESH:2026-11-03:00:30")
    assert row["status"] == "SUCCEEDED" and [c[0] for c in calls] == [TUE] and order[0] == "open_hours"


def test_a2_read_error_is_a_flag_and_the_refresh_is_still_published(env, monkeypatch):
    order = []
    _recording(monkeypatch, order, result={"start": "x", "end": "y", "mode": "FULL", "rows": 0, "error": "BQ: boom"})
    row = _refresh()
    assert row["status"] == "SUCCEEDED" and row["reason_code"] == "SEL2_PUBLISHED" and order[-1] == "child"
    res = _result(row)
    assert res["open_hours"]["error"] == "BQ: boom"
    assert res["flags"] == ["OPEN_HOURS_READ_FAILED", "MODEL_PREV_WEEK"]
    assert sel2_jobs.FLAG_OPEN_HOURS_READ_FAILED == dr.OPEN_HOURS_ALERT == "OPEN_HOURS_READ_FAILED"


@pytest.mark.parametrize("exc, text", [(RuntimeError("socket closed"), "RuntimeError: socket closed"),
                                       (AppError("BQ_NOT_CONFIGURED", 409, detail="no table"),
                                        "BQ_NOT_CONFIGURED: no table")])
def test_a2_read_raising_never_escapes_and_is_a_flag(env, monkeypatch, exc, text):
    order = []
    _recording(monkeypatch, order, exc=exc)
    row = _refresh()
    assert row["status"] == "SUCCEEDED" and order == ["open_hours", "avg", "child"]
    res = _result(row)
    assert res["open_hours"] == {"error": text} and "OPEN_HOURS_READ_FAILED" in res["flags"]
    # the helper alone: never raises
    assert sel2_jobs.open_hours_read(TUE, {"scope_key": "BIGQUERY:x", "data_source": "BIGQUERY"}) == {"error": text}


def test_a2_real_read_failing_on_the_fake_client_flags_alerts_once_and_publishes(env):
    connector.set_client_factory(FakeBQ(errors={"daily_open_hours": RuntimeError("boom")}))
    calls = []
    _child(calls, PUBLISHED)
    row = _refresh()
    assert row["status"] == "SUCCEEDED" and len(calls) == 1
    res = _result(row)
    assert "boom" in res["open_hours"]["error"] and "OPEN_HOURS_READ_FAILED" in res["flags"]
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM alerts WHERE code='OPEN_HOURS_READ_FAILED' AND entity_id=?",
                         (str(TUE),)).fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM aux_source_reads").fetchone()[0] == 0


def test_a3_without_an_active_scope_nothing_is_read_and_the_child_reports(sel2_on, monkeypatch):
    _freeze(_at(TUE, "05:10"))                                       # default DEMO source, no demo batch: no scope
    monkeypatch.setattr(ss, "get", _patched_get(_sched(refresh_enabled=True)))
    monkeypatch.setattr(avg_demand, "read_current", lambda d, cfg=None, bq=None: {"read_id": None, "rows": 0})
    order = []
    calls, child_calls = _recording(monkeypatch, order)
    row = _refresh()
    assert calls == [] and order == ["avg", "child"] and len(child_calls) == 1
    assert row["status"] == "SUCCEEDED" and _result(row)["open_hours"] is None
    assert "OPEN_HOURS_READ_FAILED" not in _result(row)["flags"]


def test_a3_another_source_today_is_not_ready_and_reads_nothing(sel2_on, monkeypatch):
    from app.data.demo import create_demo_batch
    _freeze(_at(TUE, "05:10"))
    create_demo_batch(days=20, n_skus=2, seed=1)
    monkeypatch.setattr(ss, "get", _patched_get(_sched(refresh_enabled=True)))
    order = []
    calls, child_calls = _recording(monkeypatch, order)
    row = _refresh()
    assert row["status"] == "SKIPPED" and row["reason_code"] == "NOT_APPLICABLE_FOR_SOURCE"
    assert calls == [] and child_calls == [] and order == []


def test_a3_another_source_on_a_past_day_runs_the_child_without_a_read(sel2_on, monkeypatch):
    from app.data.demo import create_demo_batch
    _freeze(_at(TUE, "05:10"))
    create_demo_batch(days=20, n_skus=2, seed=1)
    monkeypatch.setattr(ss, "get", _patched_get(_sched(refresh_enabled=True)))
    monkeypatch.setattr(avg_demand, "read_current", lambda d, cfg=None, bq=None: {"read_id": None, "rows": 0})
    order = []
    calls, child_calls = _recording(monkeypatch, order)
    past = TUE - timedelta(days=2)
    row = runner_execute(past)
    assert calls == [] and order == ["avg", "child"] and child_calls[0][:3] == ["sel2-day", "--date", str(past)]
    assert _result(row)["open_hours"] is None


def test_a4_past_business_day_of_the_bigquery_scope_is_not_read(env, monkeypatch):
    order = []
    calls, child_calls = _recording(monkeypatch, order)
    past = TUE - timedelta(days=1)
    row = runner_execute(past)
    assert row["status"] == "SUCCEEDED" and calls == [] and order == ["avg", "child"]
    assert child_calls[0][:3] == ["sel2-day", "--date", str(past)]
    res = _result(row)
    assert res["open_hours"] is None and "OPEN_HOURS_READ_FAILED" not in res["flags"]


def runner_execute(d):
    from app.jobs import runner
    return runner.execute("FORECAST_REFRESH", f"FORECAST_REFRESH:{d}:PAST", "SCHEDULE", None, {"business_date": str(d)})


def test_a5_refresh_fills_open_hours_daily_up_to_d_minus_1_with_the_fake_client(env):
    """Integration with fakes: the real read (daily_refresh.sync_open_hours + aux_sources.fetch_open_hours) through a
    fake client fills the table / seller that sel2/data.py checks (MAX(open_date) <= D-1)."""
    fake = _fake_oh(keys=[("HN", "A"), ("HCM", "B")])
    calls = []
    _child(calls, PUBLISHED)
    row = _refresh()
    assert row["status"] == "SUCCEEDED" and len(calls) == 1
    oh = _result(row)["open_hours"]
    y = str(TUE - timedelta(days=1))
    assert oh["mode"] == "FULL" and oh["end"] == y and oh["last_day"] == y and oh["rows"] > 0 and "error" not in oh
    tbl, seller = aux_sources.open_hours_source()
    with db.read() as c:
        last = c.execute("SELECT MAX(open_date) FROM open_hours_daily WHERE source_table=? AND seller_code=? AND "
                         "open_date <= ?", (tbl, seller, y)).fetchone()[0]       # the query of sel2/data.py
        n = c.execute("SELECT COUNT(*) FROM open_hours_daily WHERE source_table=? AND seller_code=?",
                      (tbl, seller)).fetchone()[0]
        reads = db.rows(c, "SELECT kind, source_table, seller_code, range_end, last_day FROM aux_source_reads "
                           "ORDER BY range_end DESC, rowid DESC")
    assert last == y and n == oh["rows"]
    assert reads and reads[0] == {"kind": "OPEN_HOURS", "source_table": tbl, "seller_code": seller, "range_end": y,
                                  "last_day": y}
    assert len(reads) == oh["reads"]
    # a rerun of the same day with the table unchanged since the last completed read: nothing read again
    fake.modified = _at(TUE, "04:00")
    _child(calls, PUBLISHED)
    second = _refresh(key="FORECAST_REFRESH:2026-11-03:RERUN1", force=True)
    assert "error" not in _result(second)["open_hours"] and _result(second)["open_hours"]["rows"] > 0
    nq = len(fake.queries)
    _child(calls, PUBLISHED)
    third = _refresh(key="FORECAST_REFRESH:2026-11-03:RERUN2", force=True)
    assert _result(third)["open_hours"]["skipped"] == dr.SOURCE_NOT_REFRESHED and len(fake.queries) == nq
    assert len(calls) == 3


# ================================================================== (B) backup / restore of nested model files
FILES = {
    "MV-1.txt": b"top model",
    "MV-1.json": b'{"a": 1}',
    "top.tmp": b"top-level tmp kept as before",
    "train.lock": b"top-level lock kept as before",
    "sel2/abc123/2026-11-03/MOC_x.txt": b"tree\x00\x01binary",
    "sel2/abc123/2026-11-03/MOC_x.json": "{\"name\": \"Vi\u1ec7t\"}".encode("utf-8"),
    "sel2/abc123/2026-10-27/S5.txt": b"older origin",
    "sel2/def456/meta.json": b"{}",
}
SKIPPED = {"sel2/abc123/2026-11-03/MOC_y.tmp": b"being written", "sel2/abc123/train.lock": b"",
           "sel2/def456/2026-11-03/x.lock": b"lock"}


def _write_models(files):
    root = paths.models_dir()
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def _model_files():
    root = paths.models_dir()
    return {f.relative_to(root).as_posix(): f.read_bytes() for f in root.rglob("*") if f.is_file()}


def _clear_models():
    root = paths.models_dir()
    for p in list(root.iterdir()):
        shutil.rmtree(p) if p.is_dir() else p.unlink()


def test_b1_backup_keeps_nested_models_without_subfolder_tmp_and_lock_and_restore_recreates_them(tmp_path):
    _write_models({**FILES, **SKIPPED})
    ss.update("quality", {"wape_max": 0.42})
    z = backup.backup_database("v142", dest_dir=tmp_path)
    with zipfile.ZipFile(z) as f:
        names = f.namelist()
        assert {n: f.read(n) for n in names if n.startswith("models/")} == {f"models/{k}": v for k, v in FILES.items()}
    assert "db/app.db" in names and not any("\\" in n for n in names)
    ss.update("quality", {"wape_max": 0.99})
    _clear_models()
    (paths.models_dir() / "MV-1.txt").write_bytes(b"changed")         # an existing file is overwritten by the backup
    res = backup.restore_backup(z)
    assert res["safety_backup"] and ss.get("quality").wape_max == 0.42
    assert _model_files() == FILES                                     # identical bytes, same relative paths
    with zipfile.ZipFile(res["safety_backup"]) as f:                   # the pre-restore backup has the state replaced
        assert f.read("models/MV-1.txt") == b"changed"


def test_b1_empty_models_folder_backs_up_the_db_only(tmp_path):
    _clear_models()
    z = backup.backup_database("empty", dest_dir=tmp_path)
    with zipfile.ZipFile(z) as f:
        assert f.namelist() == ["db/app.db"]
    backup.restore_backup(z)
    assert _model_files() == {}


def _db_bytes(tmp_path) -> bytes:
    z = backup.backup_database("src", dest_dir=tmp_path / "src")
    with zipfile.ZipFile(z) as f:
        return f.read("db/app.db")


def _zip(path, members):
    with zipfile.ZipFile(path, "w") as f:
        for n, data in members:
            f.writestr(n, data)
    return path


def test_b2_old_flat_backup_restores_as_before(tmp_path):
    ss.update("quality", {"wape_max": 0.42})
    (tmp_path / "src").mkdir()
    z = _zip(tmp_path / "old.zip", [("db/app.db", _db_bytes(tmp_path)), ("models/", b""), ("models/a.txt", b"A"),
                                    ("models/MV-9.json", b"{}")])
    ss.update("quality", {"wape_max": 0.99})
    _write_models({"sel2/keep/x.txt": b"kept"})                       # a restore never deletes other model files
    res = backup.restore_backup(z)
    assert res["safety_backup"] and ss.get("quality").wape_max == 0.42
    files = _model_files()
    assert files["a.txt"] == b"A" and files["MV-9.json"] == b"{}" and files["sel2/keep/x.txt"] == b"kept"


UNSAFE = ["models/../evil.txt", "/abs.txt", "models/sel2/../../x", "../evil.txt", "models/."]
if sys.platform == "win32":
    UNSAFE.append("models/C:/evil.txt")                                # a drive path joined to the models folder


@pytest.mark.parametrize("bad", UNSAFE)
def test_b3_unsafe_member_is_refused_before_the_safety_backup_and_the_db_swap(tmp_path, bad):
    ss.update("quality", {"wape_max": 0.42})
    (tmp_path / "src").mkdir()
    db_bytes = _db_bytes(tmp_path)
    ss.update("quality", {"wape_max": 0.99})                           # the live state a swap would replace
    z = _zip(tmp_path / "bad.zip", [("db/app.db", db_bytes), ("models/ok.txt", b"ok"), ("models/sel2/a/b.txt", b"b"),
                                    (bad, b"evil")])
    with zipfile.ZipFile(z) as f:
        assert bad in f.namelist()                                     # the member really is in the archive
    before_models = _model_files()
    before_backups = backup.list_backups()
    live = paths.db_path()
    with pytest.raises(ValueError, match="Unsafe path in backup"):
        backup.restore_backup(z)
    assert ss.get("quality").wape_max == 0.99                          # no DB swap
    assert backup.list_backups() == before_backups                    # no safety backup
    assert not live.with_suffix(".restoring").exists()
    assert _model_files() == before_models                             # not even the safe members written
    for p in (paths.models_dir().parent / "evil.txt", paths.models_dir().parent / "x", tmp_path / "evil.txt"):
        assert not p.exists()
    with sqlite3.connect(live.as_uri() + "?mode=ro", uri=True) as c:
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


@pytest.mark.skipif(sys.platform != "win32", reason="a backslash is a path separator on Windows only")
def test_b3_member_with_a_backslash_traversal_is_refused(tmp_path):
    """A zip written elsewhere may carry a backslash name (zipfile maps it to '/' on Windows when reading)."""
    (tmp_path / "src").mkdir()
    z = tmp_path / "bs.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("db/app.db", _db_bytes(tmp_path))
        info = zipfile.ZipInfo("models/x")
        info.filename = "models/..\\..\\evil.txt"                     # raw name, as another tool could write it
        f.writestr(info, b"evil")
    digest = hashlib.sha256(json.dumps(sorted(_model_files())).encode()).hexdigest()
    with pytest.raises(ValueError, match="Unsafe path in backup"):
        backup.restore_backup(z)
    assert hashlib.sha256(json.dumps(sorted(_model_files())).encode()).hexdigest() == digest
    assert not (paths.models_dir().parent / "evil.txt").exists()
