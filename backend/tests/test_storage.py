"""Storage path resolution, safety (no silent empty DB), storage migration + rollback, secrets in diagnostics."""
import json
import os
import shutil
import sqlite3
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import backup, db, diagnostics, paths, storage_migrate

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def no_env(tmp_path, monkeypatch):
    """Real resolution rules: no DF_DATA_DIR; %LOCALAPPDATA% redirected to a temp folder WITH SPACES."""
    local = tmp_path / "Local App Data With Spaces"
    local.mkdir()
    for k in ("DF_DATA_DIR", "DF_STORAGE_CONFIG", "DF_LOGS_DIR", "DF_BACKUPS_DIR", "DF_REPORTS_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    return local


@pytest.fixture
def d_drive_dir():
    """A real folder on drive D: (inside the project) - removed afterwards."""
    from app.logging_setup import reset_logging
    root = PROJECT_ROOT / "data" / f"test-tmp {uuid.uuid4().hex[:6]}"
    reset_logging()
    yield root
    reset_logging()      # release the log file handle before deleting
    if root.exists():
        shutil.rmtree(root)


def _cfg(**kw):
    paths.write_storage_config({"version": 1, **{k: str(v) if isinstance(v, Path) else v for k, v in kw.items()}})


def test_default_location_and_cwd_independence(no_env, tmp_path, monkeypatch):
    r = paths.ensure_storage()
    assert r["data_dir"] == (no_env / "DemandForecast").resolve() and r["sources"]["data_dir"] == "default"
    db.migrate()
    other = tmp_path / "some other cwd"
    other.mkdir()
    monkeypatch.chdir(other)
    assert paths.db_path() == r["db_path"]                       # cwd never influences the location
    db.migrate()
    assert not list(other.rglob("*.db"))                          # nothing created in the cwd


def test_configured_d_drive_location_all_files_land_there(no_env, d_drive_dir):
    data, logs, bks, reps = (d_drive_dir / "runtime", d_drive_dir / "logs runtime", d_drive_dir / "backups",
                             d_drive_dir / "reports")
    if PROJECT_ROOT.drive.upper() == "D:":      # the real installation; a clone elsewhere checks the same paths
        assert str(data).upper().startswith("D:")
    _cfg(data_dir=data, logs_dir=logs, backups_dir=bks, reports_dir=reps, allow_create=True)
    from app import settings_service as ss
    from app.api import background
    from app.main import create_app
    background.SYNC_MODE = True
    try:
        with TestClient(create_app(), headers={"X-DF-Client": "web"}) as c:
            ss.update("model", {"num_boost_round": 30, "backtest_folds": 2, "backtest_horizon_days": 7,
                                "min_total_history_days": 42})
            ss.update("quality", {"min_backtest_points": 20})
            assert c.post("/api/demo/generate", json={"days": 120, "n_skus": 6}).status_code == 200
            assert c.post("/api/training/run", json={}).json()["reason_code"] == "FORECAST_PUBLISHED"
            assert c.post("/api/system/backups").status_code == 200
            assert c.post("/api/system/diagnostics/save").status_code == 200
            sample = c.get("/api/templates/import-template.xlsx").content
            up = c.post("/api/imports/upload", files={"file": ("t.xlsx", sample, "application/octet-stream")}).json()
            p = c.get("/api/system/paths").json()
    finally:
        background.SYNC_MODE = False
    assert p["db_path"] == str(data / "db" / "app.db") and p["sources"]["data_dir"] == "storage.json"
    assert (data / "db" / "app.db").exists()
    assert list((data / "models").glob("MV-*.txt"))               # model artifacts
    assert list(bks.glob("backup-*.zip"))                          # backups
    assert list(reps.glob("demandforecast_diagnostic_*.md"))       # reports
    assert (data / "uploads" / f"{up['upload_id']}.xlsx").exists()  # temp upload
    default = no_env / "DemandForecast"
    assert sorted(x.name for x in default.iterdir()) == ["storage.json"]   # nothing else in the old place
    assert "runtime_file" not in p


def test_restart_keeps_the_same_database(no_env, d_drive_dir):
    _cfg(data_dir=d_drive_dir / "rt", allow_create=True)
    from app.main import create_app
    with TestClient(create_app(), headers={"X-DF-Client": "web"}) as c:
        c.post("/api/demo/generate", json={"days": 70, "n_skus": 3})
        first = c.get("/api/system/status").json()["scope"]["scope_key"]
    with TestClient(create_app(), headers={"X-DF-Client": "web"}) as c:
        assert c.get("/api/system/status").json()["scope"]["scope_key"] == first


def test_missing_configured_location_is_an_error_not_a_new_empty_db(no_env, tmp_path):
    gone = tmp_path / "unplugged drive" / "runtime"
    _cfg(data_dir=gone)
    with pytest.raises(paths.StorageError) as e:
        paths.ensure_storage()
    assert e.value.code == "STORAGE_NOT_FOUND" and not gone.exists()
    gone.mkdir(parents=True)                                      # folder exists but holds no database
    with pytest.raises(paths.StorageError) as e:
        db.migrate()
    assert e.value.code == "STORAGE_NOT_FOUND" and not (gone / "db" / "app.db").exists()
    with pytest.raises(paths.StorageError):
        db.connect()                                              # sqlite would have created an empty file
    from app.main import create_app
    with pytest.raises(paths.StorageError):
        with TestClient(create_app()):
            pass
    assert not (gone / "db" / "app.db").exists()


def test_unwritable_location_is_reported(no_env, tmp_path):
    blocker = tmp_path / "logs-is-a-file"
    blocker.write_text("x")
    _cfg(data_dir=tmp_path / "rt", logs_dir=blocker, allow_create=True)
    with pytest.raises(paths.StorageError) as e:
        paths.ensure_storage()
    assert e.value.code == "STORAGE_NOT_WRITABLE"


def test_invalid_storage_config(no_env):
    _cfg(data_dir="relative\\path")
    with pytest.raises(paths.StorageError) as e:
        paths.ensure_storage()
    assert e.value.code == "STORAGE_CONFIG_INVALID"


def _populate_default():
    from app.data.demo import create_demo_batch
    db.migrate()
    create_demo_batch(days=70, n_skus=4)
    (paths.models_dir() / "MV-test.txt").write_text("model")
    with open(paths.logs_dir() / "app.log", "a", encoding="utf-8") as f:
        f.write('{"level": "INFO", "msg": "old log"}\n')
    return storage_migrate.inventory(paths.db_path())


def test_storage_migration_preserves_everything_and_switches(no_env, d_drive_dir):
    before = _populate_default()
    old = paths.resolve_all()
    tgt, logs, bks = d_drive_dir / "data" / "runtime", d_drive_dir / "logs" / "runtime", d_drive_dir / "backups"
    rec = storage_migrate.migrate(str(tgt), str(logs), str(bks))
    assert rec["status"] == "SUCCEEDED" and rec["backup"]["ok"]
    r = paths.ensure_storage()
    assert r["db_path"] == tgt / "db" / "app.db" and r["logs_dir"] == logs
    after = storage_migrate.inventory(r["db_path"])
    assert after["counts"] == before["counts"] and after["objects"] == before["objects"]
    assert after["schema_version"] == before["schema_version"] and after["integrity"] == "ok"
    assert after["foreign_key_violations"] == 0
    assert (tgt / "models" / "MV-test.txt").read_text() == "model"
    assert list(logs.glob("legacy-*/app.log"))                     # old logs copied, not moved
    assert (old["logs_dir"] / "app.log").exists()
    assert not old["db_path"].exists()                             # old DB no longer looks primary...
    assert old["db_path"].parent.is_file()                         # guard: old versions cannot recreate a DB there
    with pytest.raises(OSError):
        old["db_path"].parent.mkdir(exist_ok=True)                 # what v1.0.0 does at startup -> fails loudly
    assert (Path(rec["archive"]) / "app.db").exists()              # ...but is kept (renamed, not deleted)
    assert Path(rec["backup"]["file"]).exists()                    # verified backup kept
    # the backup restores to exactly the same data
    assert storage_migrate.verify_backup_zip(Path(rec["backup"]["file"]), before)["ok"]


def test_storage_migration_refuses_unsafe_cases(no_env, d_drive_dir, monkeypatch):
    _populate_default()
    tgt = d_drive_dir / "rt"
    (tgt / "db").mkdir(parents=True)
    (tgt / "db" / "app.db").write_text("existing")
    with pytest.raises(storage_migrate.MigrationAborted):
        storage_migrate.migrate(str(tgt))                          # never overwrite an existing database
    monkeypatch.setattr(storage_migrate, "app_running", lambda: {"pid": 1})
    with pytest.raises(storage_migrate.MigrationAborted):
        storage_migrate.migrate(str(d_drive_dir / "rt2"))          # never while the app runs


def test_failure_during_switch_rolls_back_automatically(no_env, d_drive_dir, monkeypatch):
    before = _populate_default()
    old_db = paths.db_path()
    real_rename = os.rename

    def failing_rename(a, b):
        if "db.migrated-" in str(b):
            raise OSError("simulated: file in use")
        return real_rename(a, b)
    monkeypatch.setattr(storage_migrate.os, "rename", failing_rename)
    with pytest.raises(OSError):
        storage_migrate.migrate(str(d_drive_dir / "rt"))
    assert not paths.storage_config_path().exists()                # previous (default) configuration restored
    assert paths.ensure_storage()["db_path"] == old_db
    assert storage_migrate.inventory(old_db)["counts"] == before["counts"]
    assert list((d_drive_dir / "rt").glob("NOT-PRIMARY-*.txt"))


def test_rollback_restores_previous_database_and_config(no_env, d_drive_dir):
    before = _populate_default()
    old_db = paths.db_path()
    storage_migrate.migrate(str(d_drive_dir / "rt"))
    res = storage_migrate.rollback()
    assert res["status"] == "ROLLBACK_SUCCEEDED" and res["active_db"] == str(old_db)
    assert res["counts"] == before["counts"] and res["integrity"] == "ok"
    assert not paths.storage_config_path().exists()
    assert paths.ensure_storage()["db_path"] == old_db
    assert list((d_drive_dir / "rt").glob("NOT-PRIMARY-*.txt"))     # the copy is clearly not primary
    assert not (d_drive_dir / "rt" / paths.MARKER_FILE).exists()


def test_backup_is_verified_and_handles_spaces(no_env):
    _populate_default()
    z = backup.backup_database("spaces test")
    assert " " in str(z.parent) and z.exists()
    assert storage_migrate.verify_backup_zip(z, storage_migrate.inventory(paths.db_path()))["ok"]


def test_no_secrets_in_diagnostics_or_paths_api(no_env, client):
    from app import settings_service as ss
    from app.security import write_runtime
    token = write_runtime(8765)
    ss.update("bigquery", {"service_account_file": "C:\\keys\\super-secret-sa.json"})
    with open(paths.logs_dir() / "app.log", "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "x", "level": "ERROR", "logger": "df.t", "msg": "auth failed token=SECRET123",
                            "exc": "ValueError: password=hunter2"}) + "\n")
    (paths.data_dir() / "app.env").write_text("DF_PORT=8765\nSOME_KEY=SECRET_ENV_VALUE\n")
    md = diagnostics.to_markdown(diagnostics.build())
    api = client.get("/api/system/diagnostics").text + client.get("/api/system/paths").text
    for secret in ("SECRET123", "hunter2", token, "super-secret-sa", "SECRET_ENV_VALUE"):
        assert secret not in md and secret not in api
    assert "auth failed token=***" in md


def test_storage_init_then_locked_against_recreation(no_env, d_drive_dir):
    paths.init_storage_config(str(d_drive_dir / "rt"), str(d_drive_dir / "logs"))
    db.migrate()                                           # first DB created in the chosen folder
    cfg = paths.read_storage_config()
    assert cfg["allow_create"] is False and cfg["storage_id"]
    shutil.move(str(d_drive_dir / "rt" / "db"), str(d_drive_dir / "db-away"))   # e.g. folder emptied
    with pytest.raises(paths.StorageError) as e:
        db.migrate()
    assert e.value.code == "STORAGE_NOT_FOUND"
    with pytest.raises(paths.StorageError):                # existing DB at current location -> must migrate
        shutil.move(str(d_drive_dir / "db-away"), str(d_drive_dir / "rt" / "db"))
        paths.init_storage_config(str(d_drive_dir / "elsewhere"))


# ---------------------------------------------------------------- lost storage.json (v1.1.0 regression)
def _migrated_setup(d_drive_dir):
    """Data at default location -> migrated to a D: folder; returns (record, inventory before)."""
    before = _populate_default()
    rec = storage_migrate.migrate(str(d_drive_dir / "data" / "runtime"), str(d_drive_dir / "logs" / "runtime"),
                                  str(d_drive_dir / "backups"), str(d_drive_dir / "reports"))
    from app.logging_setup import reset_logging
    reset_logging()
    return rec, before


def test_lost_storage_json_is_detected_and_never_creates_empty_db(no_env, d_drive_dir):
    rec, _ = _migrated_setup(d_drive_dir)
    default_db = no_env / "DemandForecast" / "db" / "app.db"
    paths.storage_config_path().unlink()                          # storage.json lost, runtime DB still on D:
    with pytest.raises(paths.StorageError) as e:
        paths.ensure_storage()
    assert e.value.code == "STORAGE_CONFIG_MISSING" and rec["target"]["data_dir"] in e.value.detail
    with pytest.raises(paths.StorageError):
        db.migrate()
    from app.main import create_app
    with pytest.raises(paths.StorageError):
        with TestClient(create_app()):
            pass
    (no_env / "DemandForecast" / "db").unlink()                    # even without the guard file...
    with pytest.raises(paths.StorageError) as e:
        db.migrate()                                               # ...the history still blocks an empty DB
    assert e.value.code == "STORAGE_CONFIG_MISSING"
    assert not default_db.exists()
    assert storage_migrate.verify_storage()["ok"] is False


def test_guard_file_alone_blocks_when_history_is_missing(no_env, d_drive_dir):
    _migrated_setup(d_drive_dir)
    paths.storage_config_path().unlink()
    paths.history_path().unlink()
    with pytest.raises(paths.StorageError) as e:
        paths.ensure_storage()
    assert e.value.code == "STORAGE_CONFIG_MISSING"               # not a raw FileExistsError any more


def test_repair_restores_exact_config_after_full_verification(no_env, d_drive_dir):
    rec, before = _migrated_setup(d_drive_dir)
    original = paths.read_storage_config()
    paths.storage_config_path().unlink()
    dry = storage_migrate.repair_storage_config(dry_run=True)
    assert dry["dry_run"] and not paths.storage_config_path().exists()          # dry run writes nothing
    res = storage_migrate.repair_storage_config()
    assert res["status"] == "REPAIRED"
    cfg = paths.read_storage_config()
    for k in ("data_dir", "logs_dir", "backups_dir", "reports_dir", "storage_id"):
        assert cfg[k] == original[k]
    assert cfg["allow_create"] is False
    r = paths.ensure_storage()
    assert str(r["db_path"]) == rec["target"]["db_path"]
    assert storage_migrate.inventory(r["db_path"])["counts"] == before["counts"]  # data untouched
    assert storage_migrate.verify_storage()["ok"]
    with pytest.raises(storage_migrate.MigrationAborted):
        storage_migrate.repair_storage_config()                                  # never overwrites storage.json


def test_repair_refuses_on_any_mismatch(no_env, d_drive_dir):
    rec, _ = _migrated_setup(d_drive_dir)
    tgt = Path(rec["target"]["data_dir"])
    paths.storage_config_path().unlink()
    marker = tgt / paths.MARKER_FILE
    good = marker.read_text(encoding="utf-8")
    marker.write_text(json.dumps({**json.loads(good), "storage_id": "deadbeefdeadbeef"}), encoding="utf-8")
    with pytest.raises(storage_migrate.MigrationAborted, match="storage_id mismatch"):
        storage_migrate.repair_storage_config()
    marker.write_text(good, encoding="utf-8")
    (tgt / "db" / "app.db").rename(tgt / "db" / "app.db.away")
    with pytest.raises(storage_migrate.MigrationAborted, match="database missing"):
        storage_migrate.repair_storage_config()
    (tgt / "db" / "app.db.away").rename(tgt / "db" / "app.db")
    rec_file = tgt / f"storage-migration-{rec['stamp']}.json"
    rec_file.rename(tgt / "record.away")
    with pytest.raises(storage_migrate.MigrationAborted, match="missing in the target folder"):
        storage_migrate.repair_storage_config()
    (tgt / "record.away").rename(rec_file)
    assert not paths.storage_config_path().exists()                # nothing was written by refused attempts
    assert storage_migrate.repair_storage_config()["status"] == "REPAIRED"


def test_old_history_record_without_storage_id_needs_matching_marker(no_env, d_drive_dir):
    """Records written by 1.1.0 before this fix carry no storage_id (like the real 20261014_102304 one)."""
    rec, _ = _migrated_setup(d_drive_dir)
    h = json.loads(paths.history_path().read_text(encoding="utf-8"))
    h[-1].pop("storage_id")
    paths.history_path().write_text(json.dumps(h), encoding="utf-8")
    paths.storage_config_path().unlink()
    tgt = Path(rec["target"]["data_dir"])
    marker = json.loads((tgt / paths.MARKER_FILE).read_text(encoding="utf-8"))
    (tgt / paths.MARKER_FILE).write_text(json.dumps({**marker, "created_at": "2000-01-01T00:00:00+00:00"}))
    with pytest.raises(storage_migrate.MigrationAborted, match="not written by this migration"):
        storage_migrate.repair_storage_config()
    (tgt / paths.MARKER_FILE).write_text(json.dumps(marker))
    assert storage_migrate.repair_storage_config()["config"]["storage_id"] == marker["storage_id"]


def test_repair_refuses_after_rollback_and_verify_flags_config_drift(no_env, d_drive_dir):
    _migrated_setup(d_drive_dir)
    cfg = paths.read_storage_config()
    paths.write_storage_config({**cfg, "storage_id": "0000000000000000"})
    v = storage_migrate.verify_storage()
    assert not v["ok"] and any("storage_id" in p for p in v["problems"])
    paths.write_storage_config(cfg)
    assert storage_migrate.verify_storage()["ok"]
    storage_migrate.rollback()
    with pytest.raises(storage_migrate.MigrationAborted, match="ROLLBACK"):
        storage_migrate.repair_storage_config()                    # default location is primary again
    assert paths.ensure_storage()["sources"]["data_dir"] == "default"


def test_repair_cli_writes_only_with_apply(no_env, d_drive_dir, capsys):
    from app import cli
    _migrated_setup(d_drive_dir)
    paths.storage_config_path().unlink()
    assert cli.main(["storage-repair"]) == 0 and not paths.storage_config_path().exists()     # default = dry run
    assert cli.main(["storage-repair", "--dry-run"]) == 0 and not paths.storage_config_path().exists()
    assert cli.main(["storage-verify"]) == 1                                                  # config missing
    assert cli.main(["storage-repair", "--apply"]) == 0 and paths.storage_config_path().exists()
    assert cli.main(["storage-verify"]) == 0
    assert cli.main(["storage-repair", "--apply"]) == 2                                       # never overwrites


def test_bom_encoded_config_and_marker_are_accepted(no_env, d_drive_dir):
    """storage.json / storage-id.json saved by Notepad or PowerShell 5.1 (UTF-8 with BOM) must still work."""
    rec, _ = _migrated_setup(d_drive_dir)
    cfg_path = paths.storage_config_path()
    cfg_path.write_bytes(b"\xef\xbb\xbf" + cfg_path.read_bytes())
    mk = Path(rec["target"]["data_dir"]) / paths.MARKER_FILE
    mk.write_bytes(b"\xef\xbb\xbf" + mk.read_bytes())
    assert str(paths.ensure_storage()["db_path"]) == rec["target"]["db_path"]
    assert storage_migrate.verify_storage()["ok"]


def test_corrupt_marker_is_a_clean_refusal_not_a_crash(no_env, d_drive_dir):
    rec, _ = _migrated_setup(d_drive_dir)
    paths.storage_config_path().unlink()
    (Path(rec["target"]["data_dir"]) / paths.MARKER_FILE).write_text("{not json", encoding="utf-8")
    with pytest.raises(storage_migrate.MigrationAborted, match="not valid JSON"):
        storage_migrate.repair_storage_config()
    assert not paths.storage_config_path().exists()
