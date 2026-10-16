import sqlite3

import pytest

from app import backup, db, paths

LATEST = db.available_migrations()[-1][0]


def test_init_creates_schema_and_is_idempotent():
    with db.read() as c:
        assert c.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == LATEST
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ("import_batches", "order_lines", "demand_daily", "training_runs", "forecast_runs", "forecast_values",
              "d0_snapshots", "job_runs", "job_locks", "audit_log", "app_settings", "settings_history"):
        assert t in tables
    again = db.migrate()
    assert again["applied"] == [] and again["to"] == LATEST


def test_newer_db_version_is_refused():
    with db.tx() as c:
        c.execute("INSERT INTO schema_migrations(version, name, applied_at) VALUES (99, 'future', 'x')")
    with pytest.raises(db.MigrationError):
        db.migrate()


def test_pending_migration_takes_backup_first(monkeypatch, tmp_path):
    extra = tmp_path / "mig"
    extra.mkdir()
    for v, p in db.available_migrations():
        (extra / p.name).write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    (extra / "0099_test.sql").write_text("CREATE TABLE t_extra (x INTEGER);", encoding="utf-8")
    monkeypatch.setattr(db, "MIGRATIONS_DIR", extra)
    res = db.migrate()
    assert res["applied"] == ["0099_test.sql"]
    assert res["backup"] and res["backup"].endswith(".zip")


def test_failed_migration_rolls_back(monkeypatch, tmp_path):
    extra = tmp_path / "mig"
    extra.mkdir()
    for v, p in db.available_migrations():
        (extra / p.name).write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    (extra / "0099_bad.sql").write_text("CREATE TABLE ok_tbl (x INTEGER);\nTHIS IS NOT SQL;", encoding="utf-8")
    monkeypatch.setattr(db, "MIGRATIONS_DIR", extra)
    with pytest.raises(db.MigrationError):
        db.migrate()
    with db.read() as c:
        assert c.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == LATEST
        assert not c.execute("SELECT name FROM sqlite_master WHERE name='ok_tbl'").fetchone()


def test_forecast_values_are_immutable():
    with db.tx() as c:
        c.execute("INSERT INTO training_runs(id, scope_key, data_source, status, started_at) VALUES "
                  "('T1','s','DEMO','ACCEPTED','x')")
        c.execute("INSERT INTO forecast_runs(id, training_run_id, model_version, scope_key, data_source, forecast_origin, "
                  "data_as_of, horizons_json, max_horizon, n_series, status, created_at) VALUES "
                  "('F1','T1','M1','s','DEMO','2026-01-01','2025-12-31','[7]',7,1,'PUBLISHED','x')")
        c.execute("INSERT INTO forecast_values VALUES ('F1','A','B','2026-01-01',1,5.0,'LIGHTGBM',NULL)")
    for sql in ("UPDATE forecast_values SET yhat=1", "DELETE FROM forecast_values",
                "UPDATE forecast_runs SET model_version='X'", "DELETE FROM forecast_runs"):
        with pytest.raises(sqlite3.IntegrityError):
            with db.tx() as c:
                c.execute(sql)


def test_backup_and_restore_roundtrip():
    from app import settings_service as ss
    ss.update("quality", {"wape_max": 0.42})
    f = backup.backup_database("test")
    ss.update("quality", {"wape_max": 0.99})
    res = backup.restore_backup(f)
    assert res["safety_backup"]
    assert ss.get("quality").wape_max == 0.42
    assert paths.db_path().exists()


def test_restore_rejects_foreign_zip(tmp_path):
    import zipfile
    z = tmp_path / "x.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("hello.txt", "x")
    with pytest.raises(ValueError):
        backup.restore_backup(z)
