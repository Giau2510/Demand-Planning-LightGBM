"""Move the runtime storage (database, models, logs...) to a new location, safely, with rollback.

migrate():
  1. refuse while the app runs; validate source; refuse to overwrite an existing target database
  2. inventory source (schema version, row counts of every table, integrity, FK, schema objects)
  3. verified backup zip (SQLite online backup API) -> extract + integrity + counts must match
  4. copy DB with the SQLite backup API to <target>\\db\\app.db.migrating, verify, then rename
  5. copy model files (sha256 verified) and app.env; copy (not move) old logs to <logs>\\legacy-<ts>
  6. write storage.json atomically -> the resolver now points at the target; re-verify through the resolver
  7. archive the old db folder by RENAMING it (db -> db.migrated-<ts>, never deleted) so two databases can
     never both look primary; write a README next to it
  Any failure after step 6 restores the previous storage.json and the old db folder.
rollback(): undo the last migration (restore storage.json + old db folder), mark the target as NOT primary.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from . import __version__, backup, paths
from .timeutil import now_iso, now_vn

log = logging.getLogger("df.storage")
HISTORY_FILE = paths.HISTORY_FILE


class MigrationAborted(RuntimeError):
    pass


def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True)


def inventory(db_file: Path) -> dict:
    db_file = Path(db_file)
    c = _ro(db_file)
    try:
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                          "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        objects = sorted(tuple(r) for r in c.execute("SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
        return {"file": str(db_file), "size_bytes": db_file.stat().st_size,
                "wal_files": [p.name for p in db_file.parent.glob(db_file.name + "-*")],
                "schema_version": c.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0],
                "integrity": c.execute("PRAGMA integrity_check").fetchone()[0],
                "foreign_key_violations": len(c.execute("PRAGMA foreign_key_check").fetchall()),
                "counts": {t: c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables},
                "objects": [list(o) for o in objects]}
    finally:
        c.close()


def _same(a: dict, b: dict) -> list[str]:
    diffs = []
    for k in ("schema_version", "counts", "objects", "foreign_key_violations"):
        if a[k] != b[k]:
            diffs.append(k)
    if b["integrity"] != "ok":
        diffs.append("integrity")
    return diffs


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def app_running() -> dict | None:
    from .cli import _pid_alive
    from .security import read_runtime
    rt = read_runtime()
    return rt if rt and _pid_alive(rt.get("pid")) else None


def _history_path() -> Path:
    return paths.history_path()   # single definition, shared with the resolver's lost-config check


def _append_history(rec: dict) -> None:
    p = _history_path()
    hist = json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else []
    hist.append(rec)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(hist, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, p)


def verify_backup_zip(zip_file: Path, expected: dict) -> dict:
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(zip_file) as z:
            z.extract("db/app.db", td)
        inv = inventory(Path(td) / "db" / "app.db")
    diffs = _same(expected, inv)
    return {"file": str(zip_file), "integrity": inv["integrity"], "counts_match": "counts" not in diffs,
            "ok": not diffs, "diffs": diffs}


def migrate(target_data_dir: str, target_logs_dir: str | None = None, target_backups_dir: str | None = None,
            target_reports_dir: str | None = None, dry_run: bool = False) -> dict:
    if app_running():
        raise MigrationAborted("the app is running - stop it first (scripts\\stop.ps1)")
    if os.environ.get("DF_DATA_DIR"):
        raise MigrationAborted("DF_DATA_DIR environment override is set; unset it so storage.json is authoritative")
    src = paths.ensure_storage()
    src_db = src["db_path"]
    if not src_db.exists():
        raise MigrationAborted(f"no source database at {src_db}")
    tgt = Path(target_data_dir).resolve()
    if tgt == src["data_dir"]:
        raise MigrationAborted("target is the current data folder")
    tgt_db = tgt / "db" / paths.DB_FILE
    if tgt_db.exists():
        raise MigrationAborted(f"target already contains a database ({tgt_db}); refusing to overwrite")
    logs = Path(target_logs_dir).resolve() if target_logs_dir else tgt / "logs"
    backups = Path(target_backups_dir).resolve() if target_backups_dir else tgt / "backups"
    reports = Path(target_reports_dir).resolve() if target_reports_dir else tgt / "reports"
    stamp = now_vn().strftime("%Y%m%d_%H%M%S")
    rec: dict = {"stamp": stamp, "started_at": now_iso(), "app_version": __version__,
                 "source": {k: str(src[k]) for k in ("data_dir", "db_path", "logs_dir", "backups_dir", "reports_dir")},
                 "target": {"data_dir": str(tgt), "db_path": str(tgt_db), "logs_dir": str(logs),
                            "backups_dir": str(backups), "reports_dir": str(reports)},
                 "previous_storage_config": src["config"] or None, "steps": []}
    step = lambda name, **kw: rec["steps"].append({"step": name, "at": now_iso(), **kw})  # noqa: E731

    before = inventory(src_db)
    rec["inventory_before"] = {k: v for k, v in before.items() if k != "objects"}
    step("inventory", ok=before["integrity"] == "ok")
    if before["integrity"] != "ok":
        raise MigrationAborted(f"source database integrity check failed: {before['integrity']}")
    if dry_run:
        rec["dry_run"] = True
        return rec

    for d in (tgt, tgt / "db", tgt / "models", logs, backups, reports):
        d.mkdir(parents=True, exist_ok=True)
    # 3. verified backup (written to the target backups folder, kept forever)
    bzip = backup.backup_database(reason="pre-storage-migration", dest_dir=backups)
    bver = verify_backup_zip(bzip, before)
    rec["backup"] = bver
    step("backup", ok=bver["ok"], file=str(bzip))
    if not bver["ok"]:
        raise MigrationAborted(f"backup verification failed: {bver['diffs']} (backup kept at {bzip})")

    # 4. copy the database with the online backup API, verify, then rename into place
    tmp_db = tgt / "db" / (paths.DB_FILE + ".migrating")
    tmp_db.unlink(missing_ok=True)
    s, d = _ro(src_db), sqlite3.connect(str(tmp_db))
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()
    after = inventory(tmp_db)
    diffs = _same(before, after)
    step("copy_database", ok=not diffs, diffs=diffs)
    if diffs:
        tmp_db.unlink(missing_ok=True)
        raise MigrationAborted(f"copied database differs from the source: {diffs}")
    os.replace(tmp_db, tgt_db)

    # 5. models (+sha256), app.env, legacy logs copy
    copied = []
    for f in sorted(src["models_dir"].glob("*")) if src["models_dir"].exists() else []:
        if f.is_file():
            dst = tgt / "models" / f.name
            shutil.copy2(f, dst)
            if _sha(f) != _sha(dst):
                raise MigrationAborted(f"model file copy mismatch: {f.name}")
            copied.append(f.name)
    env_file = src["data_dir"] / "app.env"
    if env_file.exists():
        shutil.copy2(env_file, tgt / "app.env")
    legacy = None
    if src["logs_dir"].exists() and any(src["logs_dir"].iterdir()) and src["logs_dir"] != logs:
        legacy = logs / f"legacy-{stamp}"
        shutil.copytree(src["logs_dir"], legacy)
    step("copy_files", models=len(copied), app_env=env_file.exists(), legacy_logs=str(legacy) if legacy else None)

    # 6. switch the configuration (atomic), then verify through the resolver
    storage_id = os.urandom(8).hex()
    rec["storage_id"] = storage_id      # lets storage-repair verify the target folder 3-way later
    (tgt / paths.MARKER_FILE).write_text(json.dumps({"storage_id": storage_id, "created_at": now_iso(),
                                                     "migrated_from": str(src["data_dir"])}), encoding="utf-8")
    new_cfg = {"version": 1, "data_dir": str(tgt), "logs_dir": str(logs), "backups_dir": str(backups),
               "reports_dir": str(reports), "storage_id": storage_id, "allow_create": False,
               "updated_at": now_iso(), "note": f"storage migration {stamp}"}
    prev_cfg_exists = paths.storage_config_path().exists()
    archive = src["data_dir"] / f"db.migrated-{stamp}"
    try:
        paths.write_storage_config(new_cfg)
        rec["storage_config"] = str(paths.storage_config_path())
        r = paths.ensure_storage()
        if r["db_path"] != tgt_db:
            raise MigrationAborted(f"resolver points at {r['db_path']}, expected {tgt_db}")
        final = inventory(r["db_path"])
        if _same(before, final):
            raise MigrationAborted("database verification through the new configuration failed")
        step("switch_config", ok=True)
        # 7. archive the old database folder (rename only - nothing is deleted)
        os.rename(src_db.parent, archive)
        stale_rt = src["data_dir"] / "runtime.json"
        if stale_rt.exists():
            os.replace(stale_rt, archive / "runtime.json.stale")
        # Guard for older app versions (<=1.0.0) that only know the default folder: a FILE named "db" makes
        # their startup fail loudly instead of silently creating a new, empty database here.
        src_db.parent.write_text(f"Database moved to {tgt_db} on {stamp}. See MIGRATED-README.txt\n",
                                 encoding="utf-8")
        (src["data_dir"] / "MIGRATED-README.txt").write_text(
            f"Du lieu da duoc chuyen / data moved on {stamp} to:\n  {tgt}\n"
            f"Database cu (khong con la database chinh) / old database (no longer primary): {archive}\n"
            f"Backup da xac minh / verified backup: {bzip}\n"
            f"Rollback: scripts\\rollback-storage.ps1\n", encoding="utf-8")
        step("archive_old", ok=True, archive=str(archive))
    except Exception as e:
        log.error("storage migration failed - rolling back", exc_info=e)
        if src_db.parent.is_file():
            src_db.parent.unlink()
        if archive.exists() and not src_db.parent.exists():
            os.rename(archive, src_db.parent)
        if rec["previous_storage_config"]:
            paths.write_storage_config(rec["previous_storage_config"])
        elif not prev_cfg_exists:
            paths.storage_config_path().unlink(missing_ok=True)
        (tgt / f"NOT-PRIMARY-{stamp}.txt").write_text("Migration failed and was rolled back; this copy is not used.\n",
                                                      encoding="utf-8")
        (tgt / paths.MARKER_FILE).unlink(missing_ok=True)
        step("rolled_back", error=f"{type(e).__name__}: {e}")
        rec["status"] = "ROLLED_BACK"
        _append_history(rec)
        raise
    rec.update(status="SUCCEEDED", finished_at=now_iso(), archive=str(archive),
               inventory_after={k: v for k, v in final.items() if k != "objects"})
    _append_history(rec)
    (tgt / f"storage-migration-{stamp}.json").write_text(json.dumps(rec, indent=2, default=str), encoding="utf-8")
    log.info("storage migrated", extra={"ctx": {"from": rec["source"]["data_dir"], "to": str(tgt)}})
    return rec


def last_migration() -> dict | None:
    p = _history_path()
    if not p.exists():
        return None
    ok = [r for r in json.loads(p.read_text(encoding="utf-8-sig")) if r.get("status") == "SUCCEEDED"]
    return ok[-1] if ok else None


def rollback() -> dict:
    if app_running():
        raise MigrationAborted("the app is running - stop it first (scripts\\stop.ps1)")
    rec = last_migration()
    if not rec:
        raise MigrationAborted("no successful storage migration recorded")
    archive = Path(rec["archive"])
    old_db_dir = Path(rec["source"]["db_path"]).parent
    if not archive.exists():
        raise MigrationAborted(f"archived database folder not found: {archive}")
    if old_db_dir.is_file():
        old_db_dir.unlink()                      # the guard file written by migrate()
    elif old_db_dir.exists() and any(old_db_dir.iterdir()):
        raise MigrationAborted(f"{old_db_dir} is not empty; refusing to overwrite it")
    elif old_db_dir.exists():
        old_db_dir.rmdir()
    os.rename(archive, old_db_dir)
    if rec["previous_storage_config"]:
        paths.write_storage_config(rec["previous_storage_config"])
    else:
        paths.storage_config_path().unlink(missing_ok=True)
    stamp = now_vn().strftime("%Y%m%d_%H%M%S")
    tgt = Path(rec["target"]["data_dir"])
    if tgt.exists():
        (tgt / f"NOT-PRIMARY-{stamp}.txt").write_text(
            f"Rolled back on {stamp}. The primary database is again {rec['source']['db_path']}.\n"
            "This folder is kept untouched for inspection; it is NOT used by the app.\n", encoding="utf-8")
        (tgt / paths.MARKER_FILE).unlink(missing_ok=True)  # cannot be re-adopted by accident
    readme = Path(rec["source"]["data_dir"]) / "MIGRATED-README.txt"
    if readme.exists():
        readme.rename(readme.with_name(f"MIGRATED-README.rolled-back-{stamp}.txt"))
    # record the rollback BEFORE re-resolving: the history must say the default location is primary again,
    # otherwise the lost-config guard (correctly) refuses the default location
    _append_history({"stamp": stamp, "status": "ROLLBACK", "of_migration": rec["stamp"], "at": now_iso()})
    r = paths.ensure_storage()
    inv = inventory(r["db_path"])
    res = {"rolled_back_at": now_iso(), "of_migration": rec["stamp"], "active_db": str(r["db_path"]),
           "integrity": inv["integrity"], "counts": inv["counts"], "status": "ROLLBACK_SUCCEEDED"}
    _append_history({"stamp": stamp, **res})
    return res


# ---------------------------------------------------------------- verify / repair storage.json
def _check_target_against_record(rec: dict) -> tuple[list[str], dict]:
    """Compare a SUCCEEDED migration record with what is really on disk. Read-only."""
    problems: list[str] = []
    t = rec.get("target") or {}
    tgt = Path(t.get("data_dir", ""))
    db_file = Path(t.get("db_path") or tgt / "db" / paths.DB_FILE)
    info: dict = {"target": t, "stamp": rec.get("stamp")}
    if not t.get("data_dir") or not tgt.is_dir():
        return [f"target data folder missing: {tgt}"], info
    mk = tgt / paths.MARKER_FILE
    marker: dict = {}
    if not mk.exists():
        problems.append(f"{mk} missing")
    else:
        try:
            marker = json.loads(mk.read_text(encoding="utf-8-sig"))
        except ValueError as e:
            problems.append(f"{mk.name} is not valid JSON ({e.__class__.__name__})")
    sid = marker.get("storage_id")
    info["marker_storage_id"] = sid
    if not sid:
        problems.append("storage-id.json has no storage_id")
    if rec.get("storage_id") and rec["storage_id"] != sid:
        problems.append(f"storage_id mismatch: history {rec['storage_id']} vs folder {sid}")
    if marker.get("migrated_from") != (rec.get("source") or {}).get("data_dir"):
        problems.append("storage-id.json 'migrated_from' does not match the migration source")
    if not rec.get("storage_id"):
        # older records carry no storage_id: the marker must have been written during this very migration
        created, start, end = marker.get("created_at"), rec.get("started_at"), rec.get("finished_at")
        if not (created and start and end and start <= created <= end):
            problems.append("storage-id.json was not written by this migration "
                            f"(created_at {created} outside {start} .. {end})")
    local = tgt / f"storage-migration-{rec.get('stamp')}.json"
    if not local.exists():
        problems.append(f"{local.name} missing in the target folder")
    else:
        try:
            lr = json.loads(local.read_text(encoding="utf-8-sig"))
        except ValueError:
            lr = {}
        if lr.get("stamp") != rec.get("stamp") or lr.get("target") != t or lr.get("status") != "SUCCEEDED":
            problems.append(f"{local.name} does not match the history record")
    if not db_file.exists():
        problems.append(f"database missing: {db_file}")
    else:
        try:
            c = _ro(db_file)
            try:
                info["integrity"] = c.execute("PRAGMA integrity_check").fetchone()[0]
                info["foreign_key_violations"] = len(c.execute("PRAGMA foreign_key_check").fetchall())
                info["schema_version"] = c.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            finally:
                c.close()
            if info["integrity"] != "ok":
                problems.append(f"integrity_check: {info['integrity']}")
        except sqlite3.Error as e:
            problems.append(f"database unreadable: {e}")
    return problems, info


def verify_storage() -> dict:
    """Read-only consistency check: storage.json vs storage-id.json vs migration history vs database."""
    r = paths.resolve_all()
    out: dict = {"storage_config": str(r["storage_config"]), "storage_config_exists": r["storage_config"].exists(),
                 "data_dir": str(r["data_dir"]), "source": r["sources"]["data_dir"], "problems": []}
    ev = paths.last_storage_event()
    out["last_event"] = {"stamp": ev.get("stamp"), "status": ev.get("status")} if ev else None
    if r["storage_config"].exists():
        cfg = r["config"]
        if ev and ev.get("status") == "SUCCEEDED":
            probs, info = _check_target_against_record(ev)
            out.update(info)
            out["problems"] += probs
            for k in ("data_dir", "logs_dir", "backups_dir", "reports_dir"):
                if cfg.get(k) != ev["target"].get(k):
                    out["problems"].append(f"storage.json {k}={cfg.get(k)} differs from migration target "
                                           f"{ev['target'].get(k)}")
            if cfg.get("storage_id") != info.get("marker_storage_id"):
                out["problems"].append("storage.json storage_id differs from the folder's storage-id.json")
    else:
        try:
            paths._check_config_not_lost(r)
        except paths.StorageError as e:
            out["problems"].append(f"{e.code}: {e.detail}")
    out["ok"] = not out["problems"]
    return out


def repair_storage_config(dry_run: bool = False) -> dict:
    """Re-create a LOST storage.json from the last successful migration - only if every piece of evidence agrees.
    Never guesses: refuses when storage.json exists, when the last event is not a successful migration, or when
    the target folder / storage-id.json / per-folder record / database do not match the history record."""
    cfg_path = paths.storage_config_path()
    if cfg_path.exists():
        raise MigrationAborted(f"{cfg_path} exists - nothing to repair (use storage-verify)")
    if os.environ.get("DF_DATA_DIR"):
        raise MigrationAborted("DF_DATA_DIR override is set; unset it first")
    ev = paths.last_storage_event()
    if not ev:
        raise MigrationAborted("no storage migration history - nothing to restore from")
    if ev.get("status") != "SUCCEEDED":
        raise MigrationAborted(f"last storage event is {ev.get('status')} - the default location is primary; "
                               "nothing to restore")
    problems, info = _check_target_against_record(ev)
    if problems:
        raise MigrationAborted("evidence does not match, storage.json NOT written: " + "; ".join(problems))
    t = ev["target"]
    cfg = {"version": 1, "data_dir": t["data_dir"], "logs_dir": t["logs_dir"], "backups_dir": t["backups_dir"],
           "reports_dir": t["reports_dir"], "storage_id": info["marker_storage_id"], "allow_create": False,
           "updated_at": now_iso(), "note": f"restored by storage-repair from storage migration {ev['stamp']}"}
    res = {"verified": info, "config": cfg, "dry_run": dry_run}
    if dry_run:
        return res
    paths.write_storage_config(cfg)
    expected_db = Path(t.get("db_path") or Path(t["data_dir"]) / "db" / paths.DB_FILE)
    r = paths.ensure_storage()          # must resolve to the verified target, without creating anything
    if r["db_path"] != expected_db.resolve():
        cfg_path.unlink(missing_ok=True)
        raise MigrationAborted(f"resolver points at {r['db_path']} after repair - storage.json removed again")
    _append_history({"stamp": now_vn().strftime("%Y%m%d_%H%M%S"), "status": "CONFIG_REPAIRED",
                     "of_migration": ev["stamp"], "at": now_iso(), "storage_id": cfg["storage_id"]})
    res["status"] = "REPAIRED"
    return res
