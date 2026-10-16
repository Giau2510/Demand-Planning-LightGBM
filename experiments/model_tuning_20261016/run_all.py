"""Resumable driver of the isolated experiment. Each configuration runs in its OWN process
(`harness.py run <name>`), one after another; stdout+stderr go to logs/<name>.log. A configuration whose
runs/<name>.json and EXP_POINTS/<name>.npz both exist is skipped (completed work is reused, never overwritten).
After every configuration progress/<name>.json records status, exit code, start/end time and duration.
Usage (same environment variables as harness.py): run_all.py <name> [<name> ...]"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

EXP = Path(__file__).resolve().parent
POINTS = Path(os.environ["EXP_POINTS"]).resolve()
(EXP / "progress").mkdir(exist_ok=True)
(EXP / "logs").mkdir(exist_ok=True)


def status(name, **kw):
    f = EXP / "progress" / f"{name}.json"
    cur = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"name": name}
    cur.update(kw)
    f.write_text(json.dumps(cur, indent=1), encoding="utf-8")


for name in sys.argv[1:]:
    if (EXP / "runs" / f"{name}.json").exists() and (POINTS / f"{name}.npz").exists():
        status(name, status="DONE_REUSED", checked_at=datetime.now().isoformat(timespec="seconds"))
        print(f"{name}: already complete, reused", flush=True)
        continue
    log = EXP / "logs" / f"{name}.log"
    if log.exists():                       # keep the log of an earlier attempt
        log.rename(log.with_name(f"{name}.attempt-{datetime.now():%Y%m%d-%H%M%S}.log"))
    start = time.time()
    status(name, status="RUNNING", started=datetime.now().isoformat(timespec="seconds"), pid=os.getpid(), log=str(log))
    with open(log, "w", encoding="utf-8") as out:
        rc = subprocess.call([sys.executable, "-X", "utf8", str(EXP / "harness.py"), "run", name],
                             stdout=out, stderr=subprocess.STDOUT)
    ok = rc == 0 and (EXP / "runs" / f"{name}.json").exists() and (POINTS / f"{name}.npz").exists()
    status(name, status="DONE" if ok else "FAILED", exit_code=rc, ended=datetime.now().isoformat(timespec="seconds"),
           seconds=round(time.time() - start, 1))
    print(f"{name}: {'DONE' if ok else 'FAILED'} exit {rc} {time.time() - start:.0f}s", flush=True)
