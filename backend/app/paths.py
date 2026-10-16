"""Single source of truth for every filesystem location the app uses.

Resolution order (first match wins), per location:

  data_dir     env DF_DATA_DIR    > storage.json "data_dir"    > %LOCALAPPDATA%\\DemandForecast   (default)
  logs_dir     env DF_LOGS_DIR    > storage.json "logs_dir"    > <data_dir>\\logs
  backups_dir  env DF_BACKUPS_DIR > storage.json "backups_dir" > <data_dir>\\backups
  reports_dir  env DF_REPORTS_DIR > storage.json "reports_dir" > <data_dir>\\reports
  db           <data_dir>\\db\\app.db          models   <data_dir>\\models
  uploads      <data_dir>\\uploads (temporary Excel uploads, removed after confirm/cancel)
  runtime.json <data_dir>\\runtime.json (pid/port/shutdown token of the running server)

storage.json (the "bootstrap" file) lives at a FIXED per-user location independent of where the app is
started from:  %LOCALAPPDATA%\\DemandForecast\\storage.json  (override path with env DF_STORAGE_CONFIG).
No path depends on the current working directory or on a hard-coded Windows user name.

Safety: a configured data_dir (storage.json) that is missing, has no database, or belongs to another storage
id is an ERROR - the app never silently creates an empty database somewhere else. Only the built-in default
location (first start) or an explicit `allow_create: true` / env DF_DATA_DIR may create a new database.
"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
REPO_DIR = BACKEND_DIR.parent
DB_FILE = "app.db"
MARKER_FILE = "storage-id.json"


class StorageError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _local_appdata() -> Path:
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local)


def default_data_dir() -> Path:
    return (_local_appdata() / "DemandForecast").resolve()


def storage_config_path() -> Path:
    env = os.environ.get("DF_STORAGE_CONFIG")
    return Path(env).resolve() if env else default_data_dir() / "storage.json"


def read_storage_config() -> dict:
    p = storage_config_path()
    if not p.exists():
        return {}
    try:
        cfg = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception as e:  # noqa: BLE001
        raise StorageError("STORAGE_CONFIG_INVALID", f"{p}: {type(e).__name__}") from e
    if not isinstance(cfg, dict):
        raise StorageError("STORAGE_CONFIG_INVALID", f"{p}: not a JSON object")
    for k in ("data_dir", "logs_dir", "backups_dir", "reports_dir"):
        v = cfg.get(k)
        if v is not None and (not isinstance(v, str) or not Path(v).is_absolute()):
            raise StorageError("STORAGE_CONFIG_INVALID", f"{p}: '{k}' must be an absolute path")
    return cfg


def write_storage_config(cfg: dict) -> Path:
    """Atomic write (temp file + replace)."""
    p = storage_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
    return p


def _resolve(env_key: str, cfg_key: str, default: Path, cfg: dict) -> tuple[Path, str]:
    if os.environ.get(env_key):
        return Path(os.environ[env_key]).resolve(), f"env:{env_key}"
    if cfg.get(cfg_key):
        return Path(cfg[cfg_key]).resolve(), "storage.json"
    return default.resolve(), "default"


def resolve_all() -> dict:
    """Effective locations + where each one came from. Pure: creates nothing."""
    cfg = read_storage_config()
    data, data_src = _resolve("DF_DATA_DIR", "data_dir", default_data_dir(), cfg)
    logs, logs_src = _resolve("DF_LOGS_DIR", "logs_dir", data / "logs", cfg)
    backups, b_src = _resolve("DF_BACKUPS_DIR", "backups_dir", data / "backups", cfg)
    reports, r_src = _resolve("DF_REPORTS_DIR", "reports_dir", data / "reports", cfg)
    return {"data_dir": data, "logs_dir": logs, "backups_dir": backups, "reports_dir": reports,
            "db_path": data / "db" / DB_FILE, "models_dir": data / "models", "uploads_dir": data / "uploads",
            "runtime_file": data / "runtime.json", "storage_config": storage_config_path(),
            "sources": {"data_dir": data_src, "logs_dir": logs_src, "backups_dir": b_src, "reports_dir": r_src},
            "config": cfg}


def _creation_allowed(r: dict) -> bool:
    src = r["sources"]["data_dir"]
    return src in ("default", "env:DF_DATA_DIR") or bool(r["config"].get("allow_create"))


def _check_writable(d: Path) -> None:
    probe = d / f".write-test-{secrets.token_hex(4)}"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        raise StorageError("STORAGE_NOT_WRITABLE", f"{d}: {e.strerror or type(e).__name__}") from e


HISTORY_FILE = "storage-migrations.json"


def history_path() -> Path:
    """Storage migration history lives next to storage.json (fixed per-user location)."""
    return storage_config_path().parent / HISTORY_FILE


def last_storage_event() -> dict | None:
    p = history_path()
    if not p.exists():
        return None
    try:
        hist = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception as e:  # noqa: BLE001
        raise StorageError("STORAGE_CONFIG_INVALID", f"{p}: {type(e).__name__}") from e
    events = [h for h in hist if h.get("status") in ("SUCCEEDED", "ROLLBACK", "ROLLBACK_SUCCEEDED")]
    return events[-1] if events else None


def _check_config_not_lost(r: dict) -> None:
    """storage.json missing although the data was moved away -> refuse (never start on a new empty database)."""
    if r["sources"]["data_dir"] != "default" or r["storage_config"].exists():
        return
    ev = last_storage_event()
    if ev and ev.get("status") == "SUCCEEDED":
        raise StorageError("STORAGE_CONFIG_MISSING",
                           f"{r['storage_config']} is missing, but the data was moved to {ev['target']['data_dir']} "
                           f"(storage migration {ev.get('stamp')}). Restore it with: python -m app.cli storage-repair "
                           "(scripts\\repair-storage.ps1)")
    if r["db_path"].parent.is_file():
        raise StorageError("STORAGE_CONFIG_MISSING",
                           f"{r['db_path'].parent} is a 'data moved' guard file and {r['storage_config']} is missing. "
                           "Restore it with: python -m app.cli storage-repair (scripts\\repair-storage.ps1)")


def ensure_storage() -> dict:
    """Validate (and, only when allowed, create) the storage layout. Call at process start before any DB use."""
    r = resolve_all()
    _check_config_not_lost(r)
    data = r["data_dir"]
    allowed = _creation_allowed(r)
    if not data.exists():
        if not allowed:
            raise StorageError("STORAGE_NOT_FOUND", f"configured data folder does not exist: {data}")
        try:
            data.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise StorageError("STORAGE_NOT_FOUND", f"cannot create {data}: {e.strerror or type(e).__name__}") from e
    db = r["db_path"]
    marker = data / MARKER_FILE
    if not db.exists() and not allowed:
        raise StorageError("STORAGE_NOT_FOUND", f"no database at the configured location {db}; refusing to create "
                                                "an empty one (check the drive, or roll back the storage migration)")
    want = r["config"].get("storage_id") if r["sources"]["data_dir"] == "storage.json" else None
    if want and marker.exists():
        try:
            have = json.loads(marker.read_text(encoding="utf-8-sig")).get("storage_id")
        except ValueError as e:
            raise StorageError("STORAGE_CONFIG_INVALID", f"{marker}: not valid JSON") from e
        if have != want:
            raise StorageError("STORAGE_CONFIG_INVALID", f"{data} belongs to storage id {have}, expected {want}")
    for key in ("data_dir", "logs_dir", "backups_dir", "reports_dir"):
        try:
            r[key].mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise StorageError("STORAGE_NOT_WRITABLE", f"cannot create {r[key]}: {e.strerror or type(e).__name__}") from e
        _check_writable(r[key])
    for sub_dir in ("db", "models", "uploads"):
        (data / sub_dir).mkdir(exist_ok=True)
    if not marker.exists():
        marker.write_text(json.dumps({"storage_id": want or secrets.token_hex(8)}), encoding="utf-8")
    r["db_exists"] = db.exists()
    r["creation_allowed"] = allowed
    return r


def _get(key: str) -> Path:
    return resolve_all()[key]


def _sub(key: str) -> Path:
    p = _get(key)
    if not p.exists():
        # only create sub folders of an existing data folder; never recreate a missing (e.g. unplugged) root
        if not _get("data_dir").exists():
            raise StorageError("STORAGE_NOT_FOUND", f"data folder missing: {_get('data_dir')}")
        p.mkdir(parents=True, exist_ok=True)
    return p


def data_dir() -> Path:
    d = _get("data_dir")
    if not d.exists():
        raise StorageError("STORAGE_NOT_FOUND", f"data folder missing: {d} (call ensure_storage first)")
    return d


def db_path() -> Path:
    return _get("db_path")


def models_dir() -> Path:
    return _sub("models_dir")


def logs_dir() -> Path:
    return _sub("logs_dir")


def backups_dir() -> Path:
    return _sub("backups_dir")


def reports_dir() -> Path:
    return _sub("reports_dir")


def uploads_dir() -> Path:
    return _sub("uploads_dir")


def runtime_file() -> Path:
    return _get("runtime_file")


def describe() -> dict:
    """Effective paths for diagnostics / the System page (no secrets live in any of these)."""
    r = resolve_all()
    out = {k: str(v) for k, v in r.items() if isinstance(v, Path)}
    out["sources"] = r["sources"]
    db = r["db_path"]
    out["db_exists"] = db.exists()
    out["db_size_bytes"] = db.stat().st_size if db.exists() else None
    out["wal_files"] = [p.name for p in db.parent.glob(DB_FILE + "-*")] if db.parent.exists() else []
    out["storage_config_exists"] = r["storage_config"].exists()
    out["exports"] = "browser download (Excel exports and reports are streamed, not stored on the server)"
    return out


def frontend_dist() -> Path:
    env = os.environ.get("DF_FRONTEND_DIST")
    if env:
        return Path(env)
    for cand in (REPO_DIR / "frontend" / "dist", REPO_DIR / "web"):
        if (cand / "index.html").exists():
            return cand
    return REPO_DIR / "frontend" / "dist"


def lock_storage_config() -> None:
    """After the first database was created in a configured folder, forbid creating another one there:
    allow_create -> false and pin the folder's storage id (so an unplugged/emptied drive is an error)."""
    r = resolve_all()
    cfg = r["config"]
    if r["sources"]["data_dir"] != "storage.json" or not cfg.get("allow_create") or not r["db_path"].exists():
        return
    marker = r["data_dir"] / MARKER_FILE
    sid = json.loads(marker.read_text(encoding="utf-8-sig")).get("storage_id") if marker.exists() else None
    write_storage_config({**cfg, "allow_create": False, "storage_id": sid or cfg.get("storage_id")})


def init_storage_config(data_dir: str, logs_dir: str | None = None, backups_dir: str | None = None,
                        reports_dir: str | None = None) -> dict:
    """Point a FRESH installation at a chosen folder. Refuses when a database already exists at the current
    location (that data must be moved with storage-migrate instead, so nothing is left behind)."""
    r = resolve_all()
    if r["db_path"].exists():
        raise StorageError("STORAGE_CONFIG_INVALID", f"a database already exists at {r['db_path']}; "
                                                     "use storage-migrate to move it")
    cfg = {"version": 1, "data_dir": str(Path(data_dir).resolve()), "allow_create": True}
    for k, v in (("logs_dir", logs_dir), ("backups_dir", backups_dir), ("reports_dir", reports_dir)):
        if v:
            cfg[k] = str(Path(v).resolve())
    write_storage_config(cfg)
    return cfg
