"""Backup / restore of the application database (SQLite online backup API) and model files."""
from __future__ import annotations

import logging
import shutil
import sqlite3
import zipfile
from pathlib import Path

from . import paths
from .timeutil import now_vn

log = logging.getLogger("df.backup")


def backup_database(reason: str = "manual", dest_dir: Path | None = None) -> Path:
    """Consistent copy of the live DB (safe while the app is running) + model files, as one .zip."""
    dest_dir = dest_dir or paths.backups_dir()
    stamp = now_vn().strftime("%Y%m%d-%H%M%S")
    safe_reason = "".join(ch for ch in reason if ch.isalnum() or ch in "-_")[:40]
    tmp_db = dest_dir / f"app-{stamp}-{safe_reason}.db"
    if not paths.db_path().exists():
        raise paths.StorageError("STORAGE_NOT_FOUND", f"database not found: {paths.db_path()}")
    src = sqlite3.connect(paths.db_path().as_uri() + "?mode=ro", uri=True)  # URI-encoded: safe with spaces
    dst = sqlite3.connect(str(tmp_db))
    try:
        src.backup(dst)
        # verify the copy before it is accepted as a backup
        ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
        n_tables = dst.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    finally:
        dst.close()
        src.close()
    if ok != "ok" or n_tables == 0:
        tmp_db.unlink(missing_ok=True)
        raise RuntimeError(f"backup verification failed (integrity={ok}, tables={n_tables}); no backup written")
    out = dest_dir / f"backup-{stamp}-{safe_reason}.zip"
    # 1.2.9: written under a temporary name and verified before it gets the backup name, so a failed or cut write never
    # leaves a file that looks like a backup (list_backups only lists backup-*.zip)
    part = out.with_name(out.name + ".part")
    try:
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(tmp_db, "db/app.db")
            for f in paths.models_dir().glob("*"):
                if f.is_file():
                    z.write(f, f"models/{f.name}")
        with zipfile.ZipFile(part) as z:
            bad = z.testzip()
        if bad is not None:
            raise RuntimeError(f"backup zip verification failed ({bad}); no backup written")
        part.replace(out)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    finally:
        tmp_db.unlink(missing_ok=True)
    log.info("backup created", extra={"ctx": {"file": str(out), "reason": reason}})
    return out


def list_backups() -> list[dict]:
    out = []
    for f in sorted(paths.backups_dir().glob("backup-*.zip"), reverse=True):
        st = f.stat()
        out.append({"file": f.name, "size_bytes": st.st_size})
    return out


def restore_backup(backup_zip: Path) -> dict:
    """Restore a backup. The app MUST be stopped. The current DB is saved as a safety backup first."""
    backup_zip = Path(backup_zip)
    if not backup_zip.exists():
        raise FileNotFoundError(backup_zip)
    with zipfile.ZipFile(backup_zip) as z:
        names = z.namelist()
        if "db/app.db" not in names:
            raise ValueError("Not a DemandForecast backup (db/app.db missing)")
        for n in names:  # path traversal guard
            if n.startswith("/") or ".." in Path(n).parts:
                raise ValueError(f"Unsafe path in backup: {n}")
        safety = None
        if paths.db_path().exists():
            safety = backup_database(reason="pre-restore")
        tmp = paths.db_path().with_suffix(".restoring")
        with z.open("db/app.db") as src, open(tmp, "wb") as dst:
            shutil.copyfileobj(src, dst)
        # integrity check before swapping in
        c = sqlite3.connect(str(tmp))
        ok = c.execute("PRAGMA integrity_check").fetchone()[0]
        c.close()
        if ok != "ok":
            tmp.unlink(missing_ok=True)
            raise ValueError(f"Backup database failed integrity check: {ok}")
        for suffix in ("-wal", "-shm"):
            Path(str(paths.db_path()) + suffix).unlink(missing_ok=True)
        tmp.replace(paths.db_path())
        for n in names:
            if n.startswith("models/") and not n.endswith("/"):
                target = paths.models_dir() / Path(n).name
                with z.open(n) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    log.info("backup restored", extra={"ctx": {"file": str(backup_zip)}})
    return {"restored": str(backup_zip), "safety_backup": str(safety) if safety else None}
