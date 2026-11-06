"""Isolation of the ops script tests: a fresh temporary folder and every ops_config path (DF_OPS_*) pointed into it,
so that no test reads or writes the project reports, the installed app, storage.json or the real OPS_LOCK. Call
isolate() BEFORE importing any ops script (ops_config reads the environment once, at import)."""
import os
import sys
import tempfile
from pathlib import Path

OPS = Path(__file__).resolve().parent.parent      # scripts\ops
REPO = OPS.parent.parent                           # repository root (backend\ for the app's xlsx_stream)


def isolate(prefix):
    t = Path(tempfile.mkdtemp(prefix=prefix))
    os.environ.update({
        "DF_OPS_CONFIG": str(t / "no_ops_config.json"),     # a local scripts\ops\ops_config.json is never used here
        "DF_OPS_REPORTS": str(t / "reports"), "DF_OPS_TMP": str(t / "tmp"), "DF_OPS_WORKTREES": str(t / "worktrees"),
        "DF_OPS_REMOTE_DIR": str(t / "remote"), "DF_OPS_PROGS": str(t / "progs"),
        "DF_OPS_STORAGE_JSON": str(t / "storage.json"), "DF_OPS_STATUS_MD": str(t / "STATUS.md"),
        "DF_OPS_LIVE_DB": str(t / "no_live.db"), "DF_OPS_LOCK": str(t / "OPS_LOCK"),
    })
    for k in ("DF_OPS_PROJECT_ROOT", "DF_OPS_DATA_DIR", "DF_OPS_BACKUPS", "DF_OPS_BAN", "DF_OPS_VENV"):
        os.environ.pop(k, None)
    for p in (str(OPS / "runner"), str(OPS)):
        if p not in sys.path:
            sys.path.insert(0, p)
    return t
