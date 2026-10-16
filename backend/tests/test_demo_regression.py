"""Regression tests for the v1.0.0 bug: 2nd DEMO generation -> sqlite3.IntegrityError FOREIGN KEY constraint failed."""
import sqlite3

import pytest

from app import db
from app import settings_service as ss
from app.data import demo
from app.data.demand import resolve_scope
from app.messages import AppError

SMALL = dict(days=70, n_skus=4)


def _demo_state():
    with db.read() as c:
        batches = db.rows(c, "SELECT id, status, replaces_batch_id, replaced_by_batch_id FROM import_batches "
                             "WHERE data_source='DEMO' ORDER BY created_at, rowid")
        lines = {r["batch_id"]: r["n"] for r in db.rows(c, "SELECT batch_id, COUNT(*) n FROM order_lines GROUP BY batch_id")}
        demand = {r["scope_key"]: r["n"] for r in db.rows(c, "SELECT scope_key, COUNT(*) n FROM demand_daily GROUP BY scope_key")}
        fks = db.fk_violations(c)
    return batches, lines, demand, fks


def test_first_second_and_many_generations_succeed_with_one_active():
    ids = []
    for i in range(4):
        r = demo.create_demo_batch(seed=i, **SMALL)
        ids.append(r["batch_id"])
        batches, lines, demand, fks = _demo_state()
        active = [b for b in batches if b["status"] == "ACTIVE"]
        assert [b["id"] for b in active] == [r["batch_id"]]          # exactly one ACTIVE DEMO
        assert fks == []                                              # PRAGMA foreign_key_check clean
        assert set(lines) == {r["batch_id"]} and set(demand) == {r["batch_id"]}  # only the active one has data
    batches, *_ = _demo_state()
    by_id = {b["id"]: b for b in batches}
    for prev, new in zip(ids, ids[1:]):
        assert by_id[prev]["status"] == "REPLACED" and by_id[prev]["replaced_by_batch_id"] == new
        assert by_id[new]["replaces_batch_id"] == prev
    assert resolve_scope()["scope_key"] == ids[-1]


def test_failed_generation_rolls_back_and_previous_demo_stays_usable(monkeypatch):
    first = demo.create_demo_batch(**SMALL)
    before = _demo_state()

    def boom(*a, **k):
        raise RuntimeError("simulated failure while aggregating")
    monkeypatch.setattr(demo, "aggregate_batch", boom)
    with pytest.raises(RuntimeError):
        demo.create_demo_batch(seed=9, **SMALL)
    after = _demo_state()
    assert after == before                                  # nothing half-written, no PENDING leftover
    assert resolve_scope()["scope_key"] == first["batch_id"]


def test_database_rejects_two_active_demo_batches():
    demo.create_demo_batch(**SMALL)
    with pytest.raises(sqlite3.IntegrityError):
        with db.tx() as c:
            c.execute("INSERT INTO import_batches(id, data_source, status, created_at) "
                      "VALUES ('DEMO-X', 'DEMO', 'ACTIVE', 'x')")


def test_api_generate_twice_and_dashboard_follows_active_dataset(client):
    st = client.get("/api/system/status").json()
    assert st["scope_error"]["code"] == "NO_ACTIVE_DATASET"   # correct: nothing generated yet
    for _ in range(2):
        r = client.post("/api/demo/generate", json={"days": 70, "n_skus": 4})
        assert r.status_code == 200, r.text
        bid = r.json()["batch_id"]
        st = client.get("/api/system/status").json()
        assert st["scope_error"] is None and st["scope"]["scope_key"] == bid
        assert client.get("/api/dashboard").status_code == 200


def test_no_active_dataset_only_in_the_right_conditions(client):
    ss.update("general", {"active_source": "MANUAL_IMPORT"})
    with pytest.raises(AppError) as e:
        resolve_scope()
    assert e.value.code == "NO_ACTIVE_DATASET"
    # pointer to a batch that is not ACTIVE -> explicit inconsistency, never a silently chosen batch
    ss.update("general", {"active_import_batch_id": "IMP-DOES-NOT-EXIST"})
    with pytest.raises(AppError) as e:
        resolve_scope()
    assert e.value.code == "ACTIVE_DATASET_INCONSISTENT"
    st = client.get("/api/system/status").json()
    assert st["scope_error"]["code"] == "ACTIVE_DATASET_INCONSISTENT"
    assert st["scope_error"]["category"] == "CONFIG"


def test_scheduled_job_without_dataset_is_skipped_not_failed():
    from app.jobs import runner
    r = runner.execute("TRAIN_PUBLISH", "TRAIN_PUBLISH:first-start")
    assert r["status"] == "SKIPPED" and r["reason_code"] == "NO_ACTIVE_DATASET"
    r = runner.execute("D0_SYNC", "D0_SYNC:first-start")
    assert r["status"] == "SKIPPED"
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM alerts WHERE level='ERROR'").fetchone()[0] == 0


def test_database_errors_return_stable_code_without_traceback(client, monkeypatch):
    def raise_fk(*a, **k):
        raise sqlite3.IntegrityError("FOREIGN KEY constraint failed")
    monkeypatch.setattr(demo, "create_demo_batch", raise_fk)
    r = client.post("/api/demo/generate", json={})
    body = r.json()
    assert r.status_code == 409 and body["code"] == "DATABASE_CONSTRAINT" and body["category"] == "DATABASE"
    assert body["request_id"] and "Traceback" not in r.text and "FOREIGN KEY" not in r.text
    assert "xóa database" in body["vi"]          # advises NOT to delete the database


def test_upgrade_from_v1_database_keeps_data_and_relations(monkeypatch, tmp_path, data_dir):
    # rebuild a pure v1 (0001 only) database, put data in it, then upgrade to the current schema
    for f in data_dir.glob("db/app.db*"):
        f.unlink()
    v1 = tmp_path / "mig_v1"
    v1.mkdir()
    first = db.available_migrations()[0][1]
    (v1 / first.name).write_text(first.read_text(encoding="utf-8"), encoding="utf-8")
    real_dir = db.MIGRATIONS_DIR
    monkeypatch.setattr(db, "MIGRATIONS_DIR", v1)
    db.migrate()
    a = demo.create_demo_batch(**SMALL)
    with db.read() as c:
        counts = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("import_batches", "order_lines", "demand_daily", "audit_log")}
        assert c.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 1
    monkeypatch.setattr(db, "MIGRATIONS_DIR", real_dir)
    res = db.migrate()
    assert "0002_one_active_demo.sql" in res["applied"] and res["backup"]      # backup taken before upgrade
    with db.read() as c:
        after = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in counts}
        assert after == counts and db.fk_violations(c) == []
    b = demo.create_demo_batch(seed=5, **SMALL)                                  # 2nd generation on upgraded DB
    batches, *_ = _demo_state()
    assert {x["id"]: x["status"] for x in batches} == {a["batch_id"]: "REPLACED", b["batch_id"]: "ACTIVE"}
