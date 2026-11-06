"""1.4.0 install E1 (owner plan 03/11): online backup of the live DB + models with the INSTALLED 1.3.1 code (source opened
mode=ro by backup.backup_database), reason "pre-1.4.0"; the row count of every live table BEFORE and AFTER the backup
(mode=ro): equal counts = no write during the backup, so the restore test can compare against them (02/11: a forecast
refresh writing during the backup made the restore comparison fail); the configuration export (app_settings +
storage.json) next to the backup. Run with the installed python, cwd = <install>\\backend. argv: <out json> [reason]"""
import hashlib
import json
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import backup, paths

sys.path.append(str(Path(__file__).resolve().parent))
import ops_config  # noqa: E402  (machine paths)

REASON = sys.argv[2] if len(sys.argv) > 2 else "pre-1.4.0"


def live_counts():
    c = sqlite3.connect(paths.db_path().as_uri() + "?mode=ro", uri=True)
    c.execute("PRAGMA query_only=1")
    n = {t: c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
         for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")}
    s = {k: json.loads(v) for k, v in c.execute("SELECT section, value_json FROM app_settings ORDER BY section")}
    c.close()
    return n, s


before, _ = live_counts()
t = time.time()
out = backup.backup_database(REASON)
seconds = round(time.time() - t, 1)
after, settings = live_counts()
h = hashlib.sha256()
with open(out, "rb") as f:
    for chunk in iter(lambda: f.read(8 << 20), b""):
        h.update(chunk)
models = sorted(p.name for p in paths.models_dir().glob("*") if p.is_file())
sj = ops_config.STORAGE_JSON
stamp = out.name[len("backup-"):len("backup-") + 15]
cfg = {"exported_at_vn": datetime.now(timezone(timedelta(hours=7))).isoformat(timespec="seconds"), "db_backup": out.name,
       "app_settings": settings, "storage_json_path": str(sj),
       "storage_json_sha256": hashlib.sha256(sj.read_bytes()).hexdigest().upper(),
       "storage_json": json.loads(sj.read_text(encoding="utf-8"))}
cfg_path = out.parent / f"config-{stamp}-{REASON}.json"
cfg_path.write_text(json.dumps(cfg, indent=1, ensure_ascii=False), encoding="utf-8")
changed = {k: (before.get(k), after.get(k)) for k in sorted(set(before) | set(after)) if before.get(k) != after.get(k)}
json.dump({"backup": str(out), "sha256": h.hexdigest().upper(), "bytes": out.stat().st_size, "seconds": seconds,
           "config": str(cfg_path), "live_counts_after": after, "written_during_backup": changed, "models": models},
          open(sys.argv[1], "w", encoding="utf-8"), indent=1)
print("backup", out, seconds, "s; sha256", h.hexdigest().upper(), "; tables", len(after), "; written during backup",
      changed or "none")
sys.exit(3 if changed else 0)
