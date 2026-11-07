"""Stop one process safely (owner 07/11/2026: actions a safety checker tends to block are done through a checked script).
usage: stop_process.py PID --expect "<substring of its command line>" [--tree] [--dry-run]
Refuses (exit 2) when: the PID does not exist; its command line does not contain --expect; it is this script, its
parent, the running app server (app.cli serve), a Claude Code process, or a system process (no command line).
Stops it with taskkill /PID (/T with --tree, always /F) and prints one line: STOPPED / REFUSED / NOT FOUND."""
import argparse
import json
import os
import subprocess
import sys

PROTECTED = ("app.cli serve", "claude", "explorer.exe", "winlogon", "services.exe", "lsass", "svchost")


def cmdline(pid):
    ps = (f"$p = Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}'; "
          "if ($p) { @{name=$p.Name; cmd=$p.CommandLine; parent=$p.ParentProcessId} | ConvertTo-Json -Compress }")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                         stdin=subprocess.DEVNULL).stdout.strip()
    return json.loads(out) if out else None


def main(argv=None):
    a = argparse.ArgumentParser()
    a.add_argument("pid", type=int)
    a.add_argument("--expect", required=True)
    a.add_argument("--tree", action="store_true")
    a.add_argument("--dry-run", action="store_true")
    o = a.parse_args(argv)
    if not o.expect.strip():
        print("REFUSED: empty --expect")
        return 2
    if o.pid in (os.getpid(), os.getppid()):
        print("REFUSED: own process")
        return 2
    info = cmdline(o.pid)
    if info is None:
        print(f"NOT FOUND: pid {o.pid}")
        return 1
    cmd = info.get("cmd") or ""
    low = cmd.lower()
    if not cmd:
        print(f"REFUSED: pid {o.pid} ({info.get('name')}) has no command line (system process)")
        return 2
    if o.expect.lower() not in low:
        print(f"REFUSED: pid {o.pid} command line does not contain the expected text")
        return 2
    if any(p in low for p in PROTECTED):
        print(f"REFUSED: pid {o.pid} is a protected process ({info.get('name')})")
        return 2
    if o.dry_run:
        print(f"WOULD STOP: pid {o.pid} ({info.get('name')})")
        return 0
    args = ["taskkill", "/PID", str(o.pid), "/F"] + (["/T"] if o.tree else [])
    r = subprocess.run(args, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    print(("STOPPED" if r.returncode == 0 else f"FAILED (taskkill exit {r.returncode})") + f": pid {o.pid} ({info.get('name')})")
    return 0 if r.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
