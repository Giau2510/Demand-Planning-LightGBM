"""Machine paths of the operations scripts (scripts\\ops), in one place. Each value is, by priority:
  1. environment variable DF_OPS_<KEY> (e.g. DF_OPS_PROJECT_ROOT, DF_OPS_TMP); OPS_LOCK also keeps DF_OPS_LOCK;
  2. key "<key>" (lower case) of scripts\\ops\\ops_config.json (optional, machine-specific, kept out of Git; see
     ops_config.example.json);
  3. the default below, computed from this file's location and %LOCALAPPDATA% (no configuration needed on the
     owner's PC: the scripts behave exactly as before).
DATA_DIR and BACKUPS come from %LOCALAPPDATA%\\DemandForecast\\storage.json (data_dir, backups_dir) and are read only
when a script asks for them (data_dir(), backups_dir()). Nothing here writes a file."""
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent                     # <repo>\scripts\ops
_FILE = Path(os.environ.get("DF_OPS_CONFIG") or HERE / "ops_config.json")


def _load_file():
    if not _FILE.exists():
        return {}
    with open(_FILE, encoding="utf-8-sig") as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict):
        raise ValueError(f"{_FILE}: not a JSON object")
    return cfg


_CFG = _load_file()


def get(key, default):
    """DF_OPS_<KEY> env, else ops_config.json "<key>", else default (a Path, or None)"""
    v = os.environ.get("DF_OPS_" + key.upper()) or _CFG.get(key.lower())
    return Path(v) if v else default


PROJECT_ROOT = get("project_root", HERE.parent.parent)      # repository root (the folder holding scripts\ops)
LOCALAPPDATA = get("localappdata", Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"))
STORAGE_JSON = get("storage_json", LOCALAPPDATA / "DemandForecast" / "storage.json")
PROGS = get("progs", LOCALAPPDATA / "Programs" / "DemandForecast")                 # installed versions + current.txt
REMOTE_DIR = get("remote_dir", LOCALAPPDATA / "DemandForecastRemote")             # remote link tooling state
VENV = str(get("venv", PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"))       # dev python (openpyxl, pytest)
REPORTS = get("reports", PROJECT_ROOT / "reports")                               # outputs and evidence (outside Git)
STATUS_MD = get("status_md", PROJECT_ROOT / "STATUS.md")
TMP = get("tmp", PROJECT_ROOT.parent / "tmp")                                    # isolated restore tests etc.
WORKTREES = get("worktrees", PROJECT_ROOT.parent)                                # release worktrees ban-<version>
def _main_root(root):
    """the main working tree of a git worktree (its .git is a file "gitdir: <main>\\.git\\worktrees\\<name>"): a copy
    run from a release worktree must see the same operations lock as the live scripts (fail closed, not open)"""
    g = root / ".git"
    try:
        if g.is_file():
            gd = Path(g.read_text(encoding="utf-8").split("gitdir:", 1)[1].strip())
            if gd.parent.name == "worktrees" and gd.parent.parent.name == ".git":
                return gd.parent.parent.parent
    except (OSError, IndexError):
        pass
    return root


OPS_LOCK = Path(os.environ.get("DF_OPS_LOCK") or get("ops_lock", _main_root(PROJECT_ROOT) / "run" / "OPS_LOCK"))


def worktree(name):
    """release worktree of one version (the cai_14x install scripts): DF_OPS_BAN overrides, else <WORKTREES>\\<name>"""
    return get("ban", WORKTREES / name)


def _storage(key):
    with open(STORAGE_JSON, encoding="utf-8-sig") as f:
        v = json.load(f).get(key)
    if not v:
        raise RuntimeError(f"storage.json has no {key}")
    return Path(v)


def data_dir():
    """the app's data folder (db, models, exports): DF_OPS_DATA_DIR / "data_dir", else storage.json data_dir"""
    return get("data_dir", None) or _storage("data_dir")


def backups_dir():
    """DF_OPS_BACKUPS / "backups", else storage.json backups_dir"""
    return get("backups", None) or _storage("backups_dir")


def live_db_uri():
    """read-only SQLite URI of the live DB (DF_OPS_LIVE_DB / "live_db" overrides the file)"""
    return "file:" + str(get("live_db", None) or data_dir() / "db" / "app.db") + "?mode=ro"
