"""1.4.0 install E1: restore test of the pre-1.4.0 backup - unzip DB + models into <TMP>\\e1_rt (isolated,
deleted right after), then fs_restore_verify.py (integrity, row counts = live counts taken with the backup, model files /
SHA). argv: <backup json of e1_backup.py> <out json>. Exit 0 = restore test passed."""
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

OPS = Path(__file__).resolve().parent
sys.path.insert(0, str(OPS))
import ops_config  # noqa: E402  (machine paths)

VENV = ops_config.VENV
RT = ops_config.TMP / "e1_rt"
b = json.load(open(sys.argv[1], encoding="utf-8"))
if RT.exists():
    shutil.rmtree(RT)
(RT / "data" / "db").mkdir(parents=True)
(RT / "data" / "models").mkdir()
with zipfile.ZipFile(b["backup"]) as z:
    for n in z.namelist():
        if n == "db/app.db":
            with z.open(n) as s, open(RT / "data" / "db" / "app.db", "wb") as d:
                shutil.copyfileobj(s, d, 8 << 20)
        elif n.startswith("models/") and not n.endswith("/"):
            with z.open(n) as s, open(RT / "data" / "models" / n.split("/", 1)[1], "wb") as d:
                shutil.copyfileobj(s, d, 8 << 20)
rc = subprocess.call([VENV, "-X", "utf8", str(OPS / "fs_restore_verify.py"), sys.argv[1], str(RT / "data"), sys.argv[2]])
res = json.load(open(sys.argv[2], encoding="utf-8"))
shutil.rmtree(RT)                       # temporary copy: deleted as soon as the check is done (owner rule 03/11)
ok = rc == 0 and res["integrity"] == "ok" and not res["count_differences"] and res["models_equal_live_list"] \
    and not res["model_sha_mismatch"]
print("RESTORE TEST", "PASSED" if ok else "FAILED", json.dumps(res)[:600])
sys.exit(0 if ok else 1)
