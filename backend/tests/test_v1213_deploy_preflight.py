"""1.2.13: scripts/deploy-upgrade.ps1 run for real in an ISOLATED fake installation - a temporary LOCALAPPDATA and TEMP,
a stub CLI (stdlib only) run by a hard link / copy of the base interpreter, a stub app on a random local port (never
8765) and, for the upgrade itself, a fake package whose install.ps1 is a stub that reports to the stub app instead of
stopping anything. Nothing outside the temporary folder is read or written. The upgrade tests use fake versions
(9.8.6 -> 9.8.7): no answer typed by a test can confirm a real package.

Preflight (22/10/2026): the CheckOnly started from ANOTHER Windows account - that account's own, older 1.1.0
installation (a CLI without storage-verify) and its own storage.json, while the app answering on the port was 1.2.11 of
the account that runs it. The precheck must stay BLOCKED, name the cause, and change nothing - also when the other
account's installation reports the same version (the case the version comparison alone did not catch).

Confirmation (22/10/2026 23:10, the first upgrade confirmed by typing - every earlier one passed -ConfirmToken): the
answer read after the backup was not the word and nothing records what it was (a transcript keeps neither a Read-Host
prompt nor its answer). The question is now printed, the answer trimmed and reported; a wrong, empty or impossible
answer stops before anything is stopped or installed; any stop after the prechecks exits 1. (Keys typed before the
question are discarded too; that needs a real console and is not covered here: these tests type through stdin.)

The helpers below are also used by reports/release-1.2.13-20261022/tests (the owner scripts of the release)."""
import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "deploy-upgrade.ps1"
pytestmark = pytest.mark.skipif(sys.platform != "win32" or not shutil.which("powershell"), reason="Windows PowerShell only")

# subcommands of the old 1.1.0 build seen in the 22/10 run (before storage-verify / storage-repair existed)
OLD_CMDS = ["serve", "migrate", "backup", "restore", "check-env", "demo", "info", "paths", "diagnose", "storage-inventory",
            "storage-migrate", "storage-rollback", "storage-init"]
NEW_CMDS = OLD_CMDS + ["storage-verify", "storage-repair", "data-check"]
STUB = '''import argparse
import json
import sys
CMDS = __CMDS__
PATHS = __PATHS__
VERSION = __VERSION__
CALLS = __CALLS__
DATA_CHECK = __DATA_CHECK__
ap = argparse.ArgumentParser(prog="app.cli")
sub = ap.add_subparsers(dest="cmd", required=True)
for c in CMDS:
    sub.add_parser(c)
a = ap.parse_args()
if CALLS:
    with open(CALLS, "a", encoding="utf-8") as f:
        f.write(VERSION + " " + a.cmd + "\\n")
if a.cmd == "paths":
    print(json.dumps(PATHS))
elif a.cmd == "storage-verify":
    print(json.dumps({"ok": True, "problems": []}))
elif a.cmd == "data-check":
    print("data-check (stub)")
    print(json.dumps({"status": DATA_CHECK, "checks": [{"check": "stub", "status": DATA_CHECK}]}, indent=2))
    sys.exit(1 if DATA_CHECK == "FAIL" else 0)
'''
# install.ps1 of a FAKE package: tells the stub app "stop <old>" / "start <new>" instead of stopping or starting anything.
# ok = installs and starts the new version | fail = exits 1 after starting the previous version again | stay = exits 0
# but the previous version keeps running (what deploy-upgrade's post-checks must catch)
INSTALL = r'''param([switch]$NoShortcuts)
$ErrorActionPreference = "Stop"
$mode = "__MODE__"
$url = "__URL__"
$ver = "__VERSION__"
$base = Join-Path $env:LOCALAPPDATA "Programs\DemandForecast"
$prev = (Get-Content (Join-Path $base "current.txt") -Raw).Trim()
function Ev([string]$e) { Invoke-RestMethod -Method Post -Uri "$url/__test/event" -ContentType "application/json" -Body (ConvertTo-Json @{ event = $e }) | Out-Null }
Ev "stop $prev"
if ($mode -eq "fail") { Ev "start $prev"; Write-Host "stub install: failed, $prev started again"; exit 1 }
$dst = Join-Path $base $ver
New-Item -ItemType Directory -Force -Path $dst | Out-Null
Copy-Item -Recurse -Path (Join-Path $base "$prev\python") -Destination (Join-Path $dst "python")
Copy-Item -Recurse -Path (Join-Path $PSScriptRoot "..\backend") -Destination (Join-Path $dst "backend")
Set-Content -Path (Join-Path $base "current.txt") -Value $ver -Encoding ASCII
if ($mode -eq "stay") { Ev "start $prev" } else { Ev "start $ver" }
Write-Host "stub install: $ver installed"
exit 0
'''


def _stub_cli(cmds: list[str], paths: dict, version: str, calls: Path | None = None, data_check: str = "OK") -> str:
    return (STUB.replace("__CMDS__", repr(cmds)).replace("__PATHS__", repr(paths)).replace("__VERSION__", repr(version))
            .replace("__CALLS__", repr(str(calls) if calls else "")).replace("__DATA_CHECK__", repr(data_check)))


class _App(http.server.BaseHTTPRequestHandler):
    """The stub app: `routes` (GET) and `posts` (POST/PUT) map a path to a body, or to a function of the request body
    that returns a body or (status, body); every request is recorded in `requests`, with its X-DF-Client header in
    `client_headers`. Like the real app (app/security.py), a write to /api/ without `X-DF-Client: web` is refused."""

    def _route(self, table: dict):
        path = self.path.split("?")[0]
        client = self.headers.get("X-DF-Client")
        self.server.requests.append((self.command, path))
        self.server.client_headers.append((self.command, path, client))
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        route = table.get(path)
        if self.command != "GET" and path.startswith("/api/") and client != "web":
            code, body = 403, {"code": "CSRF_BLOCKED"}
        elif route is None:
            code, body = 404, {"detail": "not in the stub"}
        else:
            body = route(json.loads(raw) if raw else None) if callable(route) else route
            code, body = body if isinstance(body, tuple) else (200, body)
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        self._route(self.server.routes)

    def do_POST(self):  # noqa: N802
        self._route(self.server.posts)

    do_PUT = do_POST

    def log_message(self, *a):
        pass


@pytest.fixture
def app_server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _App)
    assert srv.server_address[1] != 8765
    srv.routes, srv.posts, srv.requests, srv.client_headers, srv.state = {}, {}, [], [], {}
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _package(tmp: Path, version: str = "1.2.13") -> tuple[Path, str]:
    p = tmp / f"DemandForecast-{version}-win64-portable.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr(f"DemandForecast-{version}/VERSION", version)
    return p, hashlib.sha256(p.read_bytes()).hexdigest().upper()


def _release_package(tmp: Path, version: str, owner: dict, url: str, install: str = "ok", data_check: str = "OK") -> tuple[Path, str]:
    """A fake package for a whole upgrade: VERSION, the stub install.ps1 (`install`: see INSTALL) and the stub CLI of
    the new version (its data-check answers `data_check`)."""
    assert ":8765" not in url
    p = tmp / f"DemandForecast-{version}-win64-portable.zip"
    d = f"DemandForecast-{version}"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr(f"{d}/VERSION", version)
        z.writestr(f"{d}/scripts/install.ps1", INSTALL.replace("__MODE__", install).replace("__URL__", url).replace("__VERSION__", version))
        z.writestr(f"{d}/backend/app/__init__.py", "")
        z.writestr(f"{d}/backend/app/cli.py", _stub_cli(NEW_CMDS, owner["paths"], version, owner["calls"], data_check))
    return p, hashlib.sha256(p.read_bytes()).hexdigest().upper()


def _account(tmp: Path, name: str, installed: str, cmds: list[str], port: int) -> dict:
    """A Windows account's installation: %LOCALAPPDATA%\\Programs\\DemandForecast\\<installed> + its storage.json + data.
    Every CLI call is appended to `calls` ("<version> <command>")."""
    local = tmp / name / "L"
    base = local / "Programs" / "DemandForecast"
    py = base / installed / "python"
    py.mkdir(parents=True)
    ver = f"python{sys.version_info.major}{sys.version_info.minor}.dll"
    for f in ("python.exe", "python3.dll", ver, "vcruntime140.dll", "vcruntime140_1.dll"):
        src = Path(sys.base_prefix) / f
        if src.exists():
            try:
                os.link(src, py / f)          # a hard link: deleting it never touches the interpreter itself
            except OSError:
                shutil.copy2(src, py / f)
    app = base / installed / "backend" / "app"
    app.mkdir(parents=True)
    (app / "__init__.py").write_text("")
    data = tmp / name / "data"
    (data / "db").mkdir(parents=True)
    (data / "logs").mkdir()
    (data / "db" / "app.db").write_bytes(b"\0" * 4096)
    rt = data / "runtime.json"
    rt.write_text(json.dumps({"port": port}))
    cfg = local / "DemandForecast" / "storage.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"data_dir": str(data)}))
    calls = tmp / name / "calls.log"
    calls.write_text("")
    paths = {"data_dir": str(data), "db_path": str(data / "db" / "app.db"), "db_exists": True, "runtime_file": str(rt),
             "logs_dir": str(data / "logs"), "storage_config": str(cfg)}
    (app / "cli.py").write_text(_stub_cli(cmds, paths, installed, calls))
    (base / "current.txt").write_text(installed)
    return {"local": local, "base": base, "paths": paths, "calls": calls, "backups": tmp / name / "backups",
            "watched": [base, local / "DemandForecast", data]}


def _snapshot(dirs) -> dict:
    return {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for d in dirs for p in Path(d).rglob("*") if p.is_file()}


def _env(local: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("DF_") and k not in ("PYTHONPATH", "VIRTUAL_ENV", "PYTHONHOME")}
    temp = local.parent / "temp"
    temp.mkdir(exist_ok=True)
    env.update(LOCALAPPDATA=str(local), TEMP=str(temp), TMP=str(temp), PYTHONHOME=sys.base_prefix,
               PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    return env


def _checkonly(local: Path, pkg: Path, sha: str, cwd: Path | None = None) -> tuple[int, str]:
    p = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
                        "-Package", str(pkg), "-ExpectedSha256", sha, "-CheckOnly"],
                       env=_env(local), capture_output=True, timeout=300, cwd=str(cwd or local))
    out = (p.stdout + p.stderr).decode("utf-8", errors="replace")
    return p.returncode, " ".join(out.split())      # Write-Host wraps long lines: compare on collapsed whitespace


def _serve(srv, version: str, owner: dict):
    srv.routes = {"/api/health": {"ok": True, "version": version}, "/api/jobs": [],
                  "/api/system/paths": {"db_path": owner["paths"]["db_path"], "data_dir": owner["paths"]["data_dir"],
                                        "storage_config": owner["paths"]["storage_config"]}}


def _serve_full(srv, owner: dict, version: str):
    """The stub app for a whole upgrade: /api/health follows the stub install's stop/start events, the online backup is
    a real zip with db/app.db, the training gate is open with the six keys, no job runs."""
    srv.state.update(version=version, events=[], backups=0)
    p = owner["paths"]
    srv.routes = {
        # the real /api/health answer (ok, version, time): a PSCustomObject in PowerShell, as in the 23/10 Customer ID stop
        "/api/health": lambda _: {"ok": True, "version": srv.state["version"], "time": "2026-10-22T17:13:43+00:00"},
        "/api/jobs": [],
        "/api/system/paths": {k: p[k] for k in ("db_path", "data_dir", "storage_config", "logs_dir")},
        "/api/system/status": {"data_dir": p["data_dir"], "active_source": "BIGQUERY"},
        "/api/features/registry": {"next_training": {"blocked_by": None},
                                   "decisions": {"open_hours": {"window_check": {"override_rows": 6, "override": {"not_applied": []}}},
                                                 "customer": {"used": False, "coverage": None}}},
    }

    def backup(_):
        srv.state["backups"] += 1
        owner["backups"].mkdir(exist_ok=True)
        name = f"backup-{srv.state['backups']}-manual.zip"
        with zipfile.ZipFile(owner["backups"] / name, "w") as z:
            z.writestr("db/app.db", b"stub")
        return {"dir": str(owner["backups"]), "file": name}

    def event(body):
        srv.state["events"].append(body["event"])
        if body["event"].startswith("start "):
            srv.state["version"] = body["event"].split(" ", 1)[1]
        return {"ok": True}

    srv.posts = {"/api/system/backups": backup, "/__test/event": event}


def _writes(srv) -> list:
    """Requests that would change the app (the stub install's own stop/start reports excluded)."""
    return [(m, p) for m, p in srv.requests if m != "GET" and p != "/__test/event"]


def _nothing_stopped_or_installed(srv, owner: dict, installed: str = "9.8.6", new: str = "9.8.7"):
    assert srv.state["events"] == [], srv.state["events"]          # install.ps1 never ran (it reports stop/start)
    assert srv.state["version"] == installed
    assert (owner["base"] / "current.txt").read_text().strip() == installed
    assert not (owner["base"] / new).exists()


class Session:
    """A PowerShell script whose keyboard is its own stdin. Read-Host reads redirected stdin and prints no prompt, so a
    test waits for the text printed before a question (`wait_for`) and then `answer`s it. `finish` closes stdin first: a
    question nobody expected then reads an empty answer instead of hanging."""

    def __init__(self, args: list[str], env: dict, cwd: Path):
        self.p = subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", *args], env=env, cwd=str(cwd),
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self._buf = bytearray()
        self._pos = 0
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self):
        while True:
            b = os.read(self.p.stdout.fileno(), 65536)
            if not b:
                return
            self._buf.extend(b)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if self.p.poll() is None:
            self.p.kill()
            self.p.wait(30)

    def text(self) -> str:
        return " ".join(self._buf.decode("utf-8", "replace").split())

    def wait_for(self, *needles: str, timeout: float = 300) -> str | None:
        """The first of `needles` printed after the previous match, or None when the script ended without printing one."""
        end = time.monotonic() + timeout
        while True:
            ended = self.p.poll() is not None
            if ended:
                self._reader.join(10)
            s = self.text()
            hits = sorted((s.find(n, self._pos), n) for n in needles if s.find(n, self._pos) >= 0)
            if hits:
                self._pos = hits[0][0] + len(hits[0][1])
                return hits[0][1]
            if ended:
                return None
            if time.monotonic() > end:
                raise AssertionError(f"no {needles} within {timeout}s: ...{s[-4000:]}")
            time.sleep(0.1)

    def answer(self, line: str):
        self.p.stdin.write(line.encode() + b"\r\n")
        self.p.stdin.flush()

    def finish(self, timeout: float = 300) -> tuple[int, str]:
        try:
            self.p.stdin.close()
        except OSError:
            pass
        rc = self.p.wait(timeout)
        self._reader.join(10)
        return rc, self.text()


def test_other_account_old_install_stays_blocked_and_names_the_cause(tmp_path, app_server):
    """The 22/10 run: account 'admin' has an old 1.1.0 (no storage-verify); the app on the port is 1.2.11 of 'owner'."""
    port = app_server.server_address[1]
    owner = _account(tmp_path, "owner", "1.2.11", NEW_CMDS, port)
    admin = _account(tmp_path, "admin", "1.1.0", OLD_CMDS, port)
    _serve(app_server, "1.2.11", owner)
    pkg, sha = _package(tmp_path)
    before = _snapshot(admin["watched"] + owner["watched"])
    rc, out = _checkonly(admin["local"], pkg, sha)
    assert rc == 3, out
    assert f"running app 1.2.11 on port {port}" in out                      # the stub, never the real app
    assert "running version 1.2.11 differs from current.txt 1.1.0" in out   # the version comparison is kept
    assert "storage-verify failed" in out and "has no storage-verify" in out
    assert "is not the installation of Windows account" in out and "run the upgrade as the Windows user that runs the app" in out
    assert "PRECHECK FAILED - nothing was changed." in out
    assert _snapshot(admin["watched"] + owner["watched"]) == before         # nothing written anywhere


def test_other_account_same_version_is_blocked(tmp_path, app_server):
    """Another account whose own installation happens to report the running version: the version check alone passed;
    the installation identity (database + storage.json of the running app) now blocks it."""
    port = app_server.server_address[1]
    owner = _account(tmp_path, "owner", "1.2.11", NEW_CMDS, port)
    other = _account(tmp_path, "other", "1.2.11", NEW_CMDS, port)
    _serve(app_server, "1.2.11", owner)
    pkg, sha = _package(tmp_path)
    rc, out = _checkonly(other["local"], pkg, sha)
    assert rc == 3, out
    assert "differs from current.txt" not in out
    assert "is not the installation of Windows account" in out
    assert "PRECHECK FAILED - nothing was changed." in out


def test_same_account_version_mismatch_stays_blocked(tmp_path, app_server):
    """The right account, but current.txt does not match the running app: still BLOCKED (unchanged rule)."""
    port = app_server.server_address[1]
    owner = _account(tmp_path, "owner", "1.2.10", NEW_CMDS, port)
    _serve(app_server, "1.2.11", owner)
    pkg, sha = _package(tmp_path)
    rc, out = _checkonly(owner["local"], pkg, sha)
    assert rc == 3, out
    assert "running version 1.2.11 differs from current.txt 1.2.10" in out
    assert "running app = this account's installation" in out
    assert "PRECHECK FAILED - nothing was changed." in out


def test_cli_is_the_installed_one_not_an_app_package_of_the_callers_folder(tmp_path, app_server):
    """`python -m app.cli` puts the current folder first on sys.path: started from a folder with an `app` package (the
    backend of a source checkout), the precheck used to run THAT code instead of the installed version's CLI."""
    port = app_server.server_address[1]
    owner = _account(tmp_path, "owner", "1.2.11", NEW_CMDS, port)
    _serve(app_server, "1.2.11", owner)
    decoy = tmp_path / "caller"
    (decoy / "app").mkdir(parents=True)
    (decoy / "app" / "__init__.py").write_text("")
    (decoy / "app" / "cli.py").write_text("import sys\nprint('DECOY CLI')\nsys.exit(5)\n")
    pkg, sha = _package(tmp_path)
    rc, out = _checkonly(owner["local"], pkg, sha, cwd=decoy)
    assert rc == 0, out
    assert "DECOY" not in out and "storage-verify ok" in out and "database present" in out


def test_cli_without_storage_paths_stops_before_any_app_call(tmp_path, app_server):
    """A broken installation whose CLI returns no storage paths: stop at once (the old script went on with empty paths and
    the default port 8765, i.e. it would query whatever app runs there)."""
    port = app_server.server_address[1]
    owner = _account(tmp_path, "owner", "1.2.11", NEW_CMDS, port)
    cli = owner["local"] / "Programs" / "DemandForecast" / "1.2.11" / "backend" / "app" / "cli.py"
    cli.write_text("print('not json')\n")
    _serve(app_server, "1.2.11", owner)
    pkg, sha = _package(tmp_path)
    rc, out = _checkonly(owner["local"], pkg, sha)
    assert rc == 2, out
    assert "returned no storage paths" in out and "not json" in out
    assert "running app" not in out and "8765" not in out


def test_same_account_consistent_installation_passes(tmp_path, app_server):
    port = app_server.server_address[1]
    owner = _account(tmp_path, "owner", "1.2.11", NEW_CMDS, port)
    _serve(app_server, "1.2.11", owner)
    pkg, sha = _package(tmp_path)
    before = _snapshot(owner["watched"])
    rc, out = _checkonly(owner["local"], pkg, sha)
    assert rc == 0, out
    assert "storage-verify ok" in out and "running app = this account's installation" in out and "no active job" in out
    assert "PRECHECK OK (check-only: nothing was changed)." in out
    assert _snapshot(owner["watched"]) == before


# --- the upgrade itself: confirmation and exit codes (fake 9.8.6 -> 9.8.7) ---

def _upgrade_setup(tmp_path: Path, srv, install: str = "ok") -> tuple[dict, Path, str]:
    port = srv.server_address[1]
    owner = _account(tmp_path, "owner", "9.8.6", NEW_CMDS, port)
    _serve_full(srv, owner, "9.8.6")
    pkg, sha = _release_package(tmp_path, "9.8.7", owner, f"http://127.0.0.1:{port}", install=install)
    return owner, pkg, sha


def _upgrade(owner: dict, pkg: Path, sha: str, *extra: str, console: bool = True) -> Session:
    """deploy-upgrade without -CheckOnly; console=False = a host that cannot ask (-NonInteractive, like an automation)."""
    flags = [] if console else ["-NonInteractive"]
    return Session([*flags, "-File", str(SCRIPT), "-Package", str(pkg), "-ExpectedSha256", sha, *extra], _env(owner["local"]), owner["local"])


def _deploy_log(owner: dict) -> str:
    logs = sorted(Path(owner["paths"]["logs_dir"]).glob("deploy-*.log"))
    assert len(logs) == 1, logs
    return " ".join(logs[0].read_text(encoding="utf-8-sig", errors="replace").split())


def test_upgrade_wrong_token_parameter_stops_before_anything_is_stopped(tmp_path, app_server):
    owner, pkg, sha = _upgrade_setup(tmp_path, app_server)
    with _upgrade(owner, pkg, sha, "-ConfirmToken", "UPGRADE-9.8.6", console=False) as s:
        rc, out = s.finish()
    assert rc == 1, out
    assert "not confirmed (answer 'UPGRADE-9.8.6', 13 characters, expected UPGRADE-9.8.7) - nothing was stopped or installed" in out
    _nothing_stopped_or_installed(app_server, owner)
    assert app_server.state["backups"] == 1         # the online backup comes before the question; it is kept


def test_upgrade_without_token_and_without_console_stops_before_anything_is_stopped(tmp_path, app_server):
    """No -ConfirmToken and a host that cannot ask: the question cannot be answered, so nothing is stopped or installed."""
    owner, pkg, sha = _upgrade_setup(tmp_path, app_server)
    with _upgrade(owner, pkg, sha, console=False) as s:
        rc, out = s.finish()
    assert rc == 1, out
    assert "UPGRADE STOPPED" in out and "UPGRADE OK" not in out
    _nothing_stopped_or_installed(app_server, owner)


def test_upgrade_typed_answer_is_trimmed_and_the_question_is_logged(tmp_path, app_server):
    owner, pkg, sha = _upgrade_setup(tmp_path, app_server)
    with _upgrade(owner, pkg, sha) as s:
        assert s.wait_for("== confirmation ==")
        s.answer("  UPGRADE-9.8.7 ")                 # spaces around the word, as a paste can bring
        rc, out = s.finish()
    assert rc == 0, out
    assert "UPGRADE OK: 9.8.6 -> 9.8.7" in out
    assert app_server.state["events"] == ["stop 9.8.6", "start 9.8.7"]
    assert (owner["base"] / "current.txt").read_text().strip() == "9.8.7"
    log = _deploy_log(owner)                         # the question and the outcome are in deploy-upgrade's own log
    assert "Type UPGRADE-9.8.7 to continue" in log and "confirmed: UPGRADE-9.8.7" in log


@pytest.mark.parametrize("typed", ["", "UPGRADE-9.8.6", "UPGRADE 9.8.7"])
def test_upgrade_typed_wrong_or_empty_answer_stops_and_is_reported(tmp_path, app_server, typed):
    owner, pkg, sha = _upgrade_setup(tmp_path, app_server)
    with _upgrade(owner, pkg, sha) as s:
        assert s.wait_for("== confirmation ==")
        s.answer(typed)
        rc, out = s.finish()
    assert rc == 1, out
    assert f"not confirmed (answer '{typed}', {len(typed)} characters, expected UPGRADE-9.8.7)" in out
    _nothing_stopped_or_installed(app_server, owner)
    assert f"answer '{typed}'" in _deploy_log(owner)  # what was received is in the log, for the next investigation


def test_upgrade_with_the_token_parameter_installs(tmp_path, app_server):
    """-ConfirmToken (the way every upgrade before 22/10 was confirmed) still works unchanged."""
    owner, pkg, sha = _upgrade_setup(tmp_path, app_server)
    with _upgrade(owner, pkg, sha, "-ConfirmToken", "UPGRADE-9.8.7", console=False) as s:
        rc, out = s.finish()
    assert rc == 0, out
    assert "UPGRADE OK: 9.8.6 -> 9.8.7" in out and app_server.state["events"] == ["stop 9.8.6", "start 9.8.7"]


@pytest.mark.parametrize("install, cause", [("fail", "install.ps1 failed with code 1"), ("stay", "running version 9.8.6, expected 9.8.7")])
def test_upgrade_failure_after_the_confirmation_exits_1(tmp_path, app_server, install, cause):
    """What the owner scripts rely on: a failed install or post-check ends deploy-upgrade with exit code 1."""
    owner, pkg, sha = _upgrade_setup(tmp_path, app_server, install=install)
    with _upgrade(owner, pkg, sha, "-ConfirmToken", "UPGRADE-9.8.7", console=False) as s:
        rc, out = s.finish()
    assert rc == 1, out
    assert f"UPGRADE STOPPED: {cause}" in out and "UPGRADE OK" not in out
