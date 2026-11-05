"""1.4.3 (05/11/2026, owner): deploy-upgrade.ps1 skips its two backups (the online backup and the install.ps1 pre-upgrade
backup) when the operator passes a backup restore-tested OK within the last 6 hours (-VerifiedBackup + -RestoreReport).
The backup must be of the live database at its current schema, directly in the installation's backups folder and named
backup-YYYYMMDD-HHMMSS-<reason>.zip (its age comes from that Vietnam-time stamp). Any condition not met only means: the
normal backups are taken (never a precheck failure).

Runs the real deploy-upgrade.ps1 in the isolated fake installation of test_v1213_deploy_preflight (temporary LOCALAPPDATA
and TEMP, stub CLI, stub app on a random local port, never 8765, fake versions 9.8.6 -> 9.8.7; the fake database is a
small SQLite file with schema_migrations) and the real install.ps1 inside a fake package whose stop/start/check-env/
autostart scripts are stubs. Nothing outside the temporary folder is read or written."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from test_v1213_deploy_preflight import (INSTALL, NEW_CMDS, Session, _account, _deploy_log, _env, _release_package,  # noqa: F401
                                         _serve_full, _snapshot, _stub_cli, app_server)

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "scripts" / "deploy-upgrade.ps1"
INSTALL_PS1 = ROOT / "scripts" / "install.ps1"
VN = timezone(timedelta(hours=7))   # backup names carry Vietnam time (backup.py: now_vn)
SCHEMA = 11
NOTE = ("writes after it (D0 snapshots, publishes, imports, settings) are NOT in it - D0 values cannot be fetched again; "
        "a restore first takes a 'pre-restore' safety backup: keep it; if this upgrade changes the schema, the newer "
        "'pre-migration' backup (db.migrate) is the first restore point")
pytestmark = pytest.mark.skipif(sys.platform != "win32" or not shutil.which("powershell"), reason="Windows PowerShell only")

# the stub install.ps1 of a 1.4.3 package: declares -SkipBackup and reports what it received to the stub app
INSTALL_SKIP = (INSTALL.replace("param([switch]$NoShortcuts)\n", "param([switch]$NoShortcuts, [switch]$SkipBackup)\n")
                .replace('Ev "stop $prev"\n', 'Ev "args SkipBackup=$SkipBackup env=$env:DF_DEPLOY_VERIFIED_BACKUP"\nEv "stop $prev"\n'))
assert INSTALL_SKIP.count("SkipBackup") == 3


def _args(zp: Path | None = None) -> str:
    """The event of the stub install: -SkipBackup received, with DF_DEPLOY_VERIFIED_BACKUP naming the verified zip."""
    return f"args SkipBackup=True env={zp}" if zp else "args SkipBackup=False env="


def _package(tmp: Path, owner: dict, url: str) -> tuple[Path, str]:
    """A fake 9.8.7 package whose install.ps1 knows -SkipBackup."""
    assert ":8765" not in url
    p = tmp / "DemandForecast-9.8.7-win64-portable.zip"
    d = "DemandForecast-9.8.7"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr(f"{d}/VERSION", "9.8.7")
        z.writestr(f"{d}/scripts/install.ps1", INSTALL_SKIP.replace("__MODE__", "ok").replace("__URL__", url).replace("__VERSION__", "9.8.7"))
        z.writestr(f"{d}/backend/app/__init__.py", "")
        z.writestr(f"{d}/backend/app/cli.py", _stub_cli(NEW_CMDS, owner["paths"], "9.8.7", owner["calls"]))
    return p, hashlib.sha256(p.read_bytes()).hexdigest().upper()


def _setup(tmp: Path, srv, old_install: bool = False) -> tuple[dict, Path, str]:
    """The fake installation of test_v1213 with a SQLite database at schema SCHEMA and a backups folder in its paths."""
    port = srv.server_address[1]
    owner = _account(tmp, "owner", "9.8.6", NEW_CMDS, port)
    db = Path(owner["paths"]["db_path"])
    db.unlink()
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)")
    c.executemany("INSERT INTO schema_migrations VALUES (?, ?, ?)", [(v, f"m{v}", "2026-11-01T00:00:00Z") for v in range(1, SCHEMA + 1)])
    c.commit()
    c.close()
    owner["backups"].mkdir()
    owner["paths"]["backups_dir"] = str(owner["backups"])
    (owner["base"] / "9.8.6" / "backend" / "app" / "cli.py").write_text(_stub_cli(NEW_CMDS, owner["paths"], "9.8.6", owner["calls"]))
    _serve_full(srv, owner, "9.8.6")
    url = f"http://127.0.0.1:{port}"
    pkg, sha = _release_package(tmp, "9.8.7", owner, url) if old_install else _package(tmp, owner, url)
    return owner, pkg, sha


def _verified(tmp: Path, owner: dict, age_h: float = 1.0, name: str | None = None, folder: Path | None = None,
              mtime_age_h: float | None = None, report_after_s: float = 60, sha: str | None = None, path: str | None = None,
              integrity: str = "ok", diffs=None, absent_diffs: bool = False, with_db: bool = True, extra: dict | None = None,
              drop: tuple = ()) -> tuple[Path, Path, str]:
    """A restore-tested backup zip in the backups folder, named with a Vietnam-time stamp `age_h` hours old, + its report
    (the format the ops script writes by merging the backup and restore results, with an extra key); `extra` overrides
    keys, `drop` removes them. The zip's write time is the stamp time unless `mtime_age_h` says otherwise."""
    folder = folder or owner["backups"]
    folder.mkdir(parents=True, exist_ok=True)
    stamp = (datetime.now(VN) - timedelta(hours=age_h)).strftime("%Y%m%d-%H%M%S")
    zp = folder / (name or f"backup-{stamp}-manual.zip")
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("db/app.db" if with_db else "db/other.db", b"stub database")
    real = hashlib.sha256(zp.read_bytes()).hexdigest().upper()
    rep = {"backup": path or str(zp), "sha256": sha or real.lower(), "db_path": owner["paths"]["db_path"], "schema_version": SCHEMA,
           "integrity": integrity, "restored_at": "2026-11-05T01:10:00Z"}
    if not absent_diffs:
        rep["count_differences"] = {} if diffs is None else diffs
    rep.update(models_equal_live_list=True, model_sha_mismatch=[], passed=True)
    rep.update(extra or {})
    for k in drop:
        rep.pop(k)
    rp = tmp / "reports" / (zp.stem + ".json")
    rp.parent.mkdir(exist_ok=True)
    rp.write_text(json.dumps(rep), encoding="utf-8")
    zt = time.time() - (age_h if mtime_age_h is None else mtime_age_h) * 3600
    os.utime(zp, (zt, zt))
    os.utime(rp, (zt + report_after_s, zt + report_after_s))
    return zp, rp, real


def _stamp_text(zp: Path) -> str:
    s = zp.name.split("-")
    return datetime.strptime(s[1] + s[2], "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")


def _run(owner: dict, pkg: Path, sha: str, *extra: str) -> tuple[int, str]:
    with Session(["-NonInteractive", "-File", str(DEPLOY), "-Package", str(pkg), "-ExpectedSha256", sha, *extra],
                 _env(owner["local"]), owner["local"]) as s:
        return s.finish()


def _vb_args(zp: Path, rp: Path) -> list[str]:
    return ["-VerifiedBackup", str(zp), "-RestoreReport", str(rp)]


def _upgraded(srv, owner: dict, out: str):
    assert "UPGRADE OK: 9.8.6 -> 9.8.7" in out, out
    assert (owner["base"] / "current.txt").read_text().strip() == "9.8.7"


@pytest.mark.parametrize("absent_optional", [False, True])
def test_accepted_verified_backup_skips_both_backups(tmp_path, app_server, absent_optional):
    """absent_optional: count_differences, models_equal_live_list and model_sha_mismatch absent (only "passed" is required)."""
    owner, pkg, sha = _setup(tmp_path, app_server)
    drop = ("models_equal_live_list", "model_sha_mismatch") if absent_optional else ()
    zp, rp, real = _verified(tmp_path, owner, age_h=1.0, absent_diffs=absent_optional, drop=drop)
    st = _stamp_text(zp)
    rc, out = _run(owner, pkg, sha, "-ConfirmToken", "UPGRADE-9.8.7", *_vb_args(zp, rp))
    assert rc == 0, out
    assert "computing SHA-256 of the backup (can take minutes)..." in out
    assert (f"[OK] verified backup {zp.name} (taken {st} Vietnam time, age 1 h, schema {SCHEMA}, restore test ok): "
            "the two backups are skipped") in out
    assert f"restore point: verified backup {zp} taken {st}; {NOTE}" in out
    assert f"backup: skipped, verified backup {zp} sha256 {real}" in out
    assert app_server.state["backups"] == 0                          # no online backup
    assert app_server.state["events"] == [_args(zp), "stop 9.8.6", "start 9.8.7"]   # install got -SkipBackup + the variable
    _upgraded(app_server, owner, out)
    assert (f"UPGRADE OK: 9.8.6 -> 9.8.7. Rollback if needed: scripts\\rollback-version.ps1 -To 9.8.6 "
            f"(restore point: verified backup {zp} taken {st}; {NOTE})") in out
    assert f"backup: skipped, verified backup {zp} sha256 {real}" in _deploy_log(owner)


def test_touched_write_time_with_a_fresh_stamp_is_accepted(tmp_path, app_server):
    """The age comes from the stamp in the name: a write time 10 h old (a touch, a copy) does not reject a fresh backup."""
    owner, pkg, sha = _setup(tmp_path, app_server)
    zp, rp, _ = _verified(tmp_path, owner, age_h=0.5, mtime_age_h=10)
    rc, out = _run(owner, pkg, sha, "-ConfirmToken", "UPGRADE-9.8.7", *_vb_args(zp, rp))
    assert rc == 0, out
    assert "age 0.5 h" in out and "the two backups are skipped" in out
    assert app_server.state["backups"] == 0 and app_server.state["events"][0] == _args(zp)
    _upgraded(app_server, owner, out)


def test_stop_after_an_accepted_verified_backup_names_the_restore_point(tmp_path, app_server):
    owner, pkg, sha = _setup(tmp_path, app_server)
    zp, rp, _ = _verified(tmp_path, owner)
    rc, out = _run(owner, pkg, sha, "-ConfirmToken", "UPGRADE-9.8.6", *_vb_args(zp, rp))
    assert rc == 1, out
    assert (f"expected UPGRADE-9.8.7) - nothing was stopped or installed (restore point: verified backup {zp} taken "
            f"{_stamp_text(zp)}; {NOTE})") in out
    assert app_server.state["backups"] == 0 and app_server.state["events"] == []


def test_report_path_spelled_differently_is_the_same_file(tmp_path, app_server):
    """report.backup and report.db_path are compared normalized and case-insensitive (forward slashes, other case)."""
    owner, pkg, sha = _setup(tmp_path, app_server)
    zp, rp, _ = _verified(tmp_path, owner, extra={"db_path": owner["paths"]["db_path"].upper().replace("\\", "/")})
    rep = json.loads(rp.read_text(encoding="utf-8"))
    rep["backup"] = str(zp).upper().replace("\\", "/")
    rp.write_text(json.dumps(rep), encoding="utf-8")
    rc, out = _run(owner, pkg, sha, "-ConfirmToken", "UPGRADE-9.8.7", *_vb_args(zp, rp))
    assert rc == 0, out
    assert "the two backups are skipped" in out and app_server.state["backups"] == 0


# kwargs of _verified (or a function of tmp, owner that returns them) -> the reason; {real} {db} {bdir} {stamp} are filled in
REJECTIONS = {
    "age": (dict(age_h=7.0), "backup age 7 h (allowed 0-6 h)"),
    "future": (dict(age_h=-1.0), "backup time stamp {stamp} is in the future"),
    "sha": (dict(sha="00" * 32), "backup SHA256 {real} differs from the restore report (" + "00" * 32 + ")"),
    "path": (dict(path="C:\\elsewhere\\backup-other.zip"), "restore report is for another file (C:\\elsewhere\\backup-other.zip)"),
    "outside_backups": (lambda tmp, o: dict(folder=tmp / "elsewhere"), "backup is not directly in the backups folder {bdir}"),
    "backups_subfolder": (lambda tmp, o: dict(folder=o["backups"] / "sub"), "backup is not directly in the backups folder {bdir}"),
    "bad_name": (dict(name="mybackup.zip"), "backup name mybackup.zip is not backup-YYYYMMDD-HHMMSS-<reason>.zip"),
    "bad_stamp": (dict(name="backup-20261399-250000-manual.zip"), "backup name backup-20261399-250000-manual.zip has no valid time stamp"),
    "db_path_other": (dict(extra={"db_path": "C:\\other\\db\\app.db"}), "backup is of another database (C:\\other\\db\\app.db; live {db})"),
    "db_path_missing": (dict(drop=("db_path",)), "restore report names no database (db_path)"),
    "schema_other": (dict(extra={"schema_version": SCHEMA - 1}), f"backup schema version {SCHEMA - 1} differs from the live database ({SCHEMA})"),
    "schema_missing": (dict(drop=("schema_version",)), f"backup schema version missing differs from the live database ({SCHEMA})"),
    "integrity": (dict(integrity="failed"), "restore test integrity 'failed' (expected ok)"),
    "differences": (dict(diffs={"forecast_history": -3}), "restore test reported 1 count difference(s)"),
    "no_db": (dict(with_db=False), "backup has no db/app.db"),
    "report_older": (dict(report_after_s=-60), "restore report is older than the backup"),
    "passed_false": (dict(extra={"passed": False}), "restore test passed is not true (False)"),
    "passed_missing": (dict(drop=("passed",)), "restore test passed is not true (missing)"),
    "passed_text": (dict(extra={"passed": "true"}), "restore test passed is not true (true)"),
    "model_sha_mismatch": (dict(extra={"model_sha_mismatch": ["MV-20261104-1"]}), "restore test reported 1 model SHA256 mismatch(es)"),
    "models_not_live": (dict(extra={"models_equal_live_list": False}),
                        "restored models differ from the live model list (models_equal_live_list False)"),
}


@pytest.mark.parametrize("case", sorted(REJECTIONS))
def test_rejected_verified_backup_falls_back_to_the_normal_backups(tmp_path, app_server, case):
    kw, reason = REJECTIONS[case]
    owner, pkg, sha = _setup(tmp_path, app_server)
    zp, rp, real = _verified(tmp_path, owner, **(kw(tmp_path, owner) if callable(kw) else kw))
    stamp = _stamp_text(zp) if case == "future" else ""
    reason = (reason.replace("{real}", real).replace("{db}", owner["paths"]["db_path"]).replace("{bdir}", str(owner["backups"]))
              .replace("{stamp}", stamp))
    rc, out = _run(owner, pkg, sha, "-ConfirmToken", "UPGRADE-9.8.7", *_vb_args(zp, rp))
    assert rc == 0, out
    assert f"verified backup not accepted: {reason} - normal backups" in out
    assert "the two backups are skipped" not in out and "backup: skipped" not in out and "restore point:" not in out
    assert app_server.state["backups"] == 1                          # the online backup was taken
    assert app_server.state["events"] == [_args(), "stop 9.8.6", "start 9.8.7"]
    _upgraded(app_server, owner, out)


@pytest.mark.parametrize("which, reason", [("report_missing", "restore report not found"), ("no_report", "no -RestoreReport given"),
                                           ("zip_missing", "backup not found")])
def test_missing_files_fall_back_to_the_normal_backups(tmp_path, app_server, which, reason):
    owner, pkg, sha = _setup(tmp_path, app_server)
    zp, rp, _ = _verified(tmp_path, owner)
    if which == "report_missing":
        extra = _vb_args(zp, tmp_path / "missing.json")
    elif which == "no_report":
        extra = ["-VerifiedBackup", str(zp)]
    else:
        extra = _vb_args(owner["backups"] / "backup-20261105-010000-missing.zip", rp)
    rc, out = _run(owner, pkg, sha, "-ConfirmToken", "UPGRADE-9.8.7", *extra)
    assert rc == 0, out
    assert f"verified backup not accepted: {reason}" in out
    assert app_server.state["backups"] == 1 and app_server.state["events"][0] == _args()
    _upgraded(app_server, owner, out)


def test_without_the_parameters_nothing_changes(tmp_path, app_server):
    owner, pkg, sha = _setup(tmp_path, app_server)
    rc, out = _run(owner, pkg, sha, "-ConfirmToken", "UPGRADE-9.8.7")
    assert rc == 0, out
    assert "verified backup" not in out and "has no -SkipBackup" not in out and "restore point" not in out
    assert app_server.state["backups"] == 1
    assert app_server.state["events"] == [_args(), "stop 9.8.6", "start 9.8.7"]
    _upgraded(app_server, owner, out)


def test_checkonly_reports_the_decision_and_writes_nothing(tmp_path, app_server):
    owner, pkg, sha = _setup(tmp_path, app_server)
    zp, rp, _ = _verified(tmp_path, owner, age_h=2.5)
    old, old_rp, _ = _verified(tmp_path, owner, age_h=6.5)
    before = _snapshot(owner["watched"] + [owner["backups"]])
    rc, out = _run(owner, pkg, sha, "-CheckOnly", *_vb_args(zp, rp))
    assert rc == 0, out
    assert f"[OK] verified backup {zp.name} (taken {_stamp_text(zp)} Vietnam time, age 2.5 h, schema {SCHEMA}, restore test ok)" in out
    assert "PRECHECK OK (check-only: nothing was changed)." in out
    rc2, out2 = _run(owner, pkg, sha, "-CheckOnly", *_vb_args(old, old_rp))
    assert rc2 == 0, out2
    assert "verified backup not accepted: backup age 6.5 h (allowed 0-6 h) - normal backups" in out2
    assert "PRECHECK OK (check-only: nothing was changed)." in out2
    assert _snapshot(owner["watched"] + [owner["backups"]]) == before   # the live database was only read (mode=ro)
    assert app_server.state["backups"] == 0 and app_server.state["events"] == []


def test_age_is_checked_again_before_the_backup_stage(tmp_path, app_server):
    """Accepted at the precheck, but slow prechecks after the decision push it past 6 h: the normal backups are taken."""
    owner, pkg, sha = _setup(tmp_path, app_server)
    paths_body, jobs_body = app_server.routes["/api/system/paths"], app_server.routes["/api/jobs"]
    app_server.routes["/api/system/paths"] = lambda _: (time.sleep(12), paths_body)[1]   # under its 15 s timeout
    app_server.routes["/api/jobs"] = lambda _: (time.sleep(8), jobs_body)[1]              # under its 10 s timeout
    zp, rp, _ = _verified(tmp_path, owner, age_h=6 - 12 / 3600)
    rc, out = _run(owner, pkg, sha, "-ConfirmToken", "UPGRADE-9.8.7", *_vb_args(zp, rp))
    assert rc == 0, out
    assert "the two backups are skipped" in out                      # accepted at the precheck
    assert "h old (more than 6 h): normal backups" in out and "backup: skipped" not in out
    assert app_server.state["backups"] == 1
    assert app_server.state["events"] == [_args(), "stop 9.8.6", "start 9.8.7"]
    _upgraded(app_server, owner, out)


def test_package_install_without_skipbackup_takes_its_own_backup(tmp_path, app_server):
    """An install.ps1 that has no -SkipBackup (older package) is called without it instead of failing on the parameter."""
    owner, pkg, sha = _setup(tmp_path, app_server, old_install=True)
    zp, rp, _ = _verified(tmp_path, owner)
    rc, out = _run(owner, pkg, sha, "-ConfirmToken", "UPGRADE-9.8.7", *_vb_args(zp, rp))
    assert rc == 0, out
    assert "restore test ok): only the online backup is skipped (install.ps1 of the package has no -SkipBackup" in out
    assert "install.ps1 of the package has no -SkipBackup: it takes its own pre-upgrade backup" in out
    assert app_server.state["backups"] == 0 and app_server.state["events"] == ["stop 9.8.6", "start 9.8.7"]
    _upgraded(app_server, owner, out)


def _interactive(owner: dict, pkg: Path, sha: str, zp: Path, rp: Path) -> Session:
    return Session(["-File", str(DEPLOY), "-Package", str(pkg), "-ExpectedSha256", sha, *_vb_args(zp, rp)], _env(owner["local"]), owner["local"])


def test_age_is_checked_again_right_before_the_install(tmp_path, app_server):
    """Accepted at the precheck and at the backup stage, but it ages past 6 h while the question waits: the online backup
    stays skipped, install.ps1 is called WITHOUT -SkipBackup (it takes its own backup)."""
    owner, pkg, sha = _setup(tmp_path, app_server)
    zp, rp, _ = _verified(tmp_path, owner, age_h=6 - 30 / 3600)
    expires = datetime.strptime(_stamp_text(zp), "%Y-%m-%d %H:%M:%S").replace(tzinfo=VN).timestamp() + 6 * 3600
    with _interactive(owner, pkg, sha, zp, rp) as s:
        assert s.wait_for("== confirmation ==")
        assert "backup: skipped, verified backup" in s.text()
        time.sleep(max(0.0, expires - time.time()) + 3)              # a slow answer
        s.answer("UPGRADE-9.8.7")
        rc, out = s.finish()
    assert rc == 0, out
    assert "h old (more than 6 h): install.ps1 takes its own pre-upgrade backup" in out
    assert app_server.state["backups"] == 0                          # the online backup was skipped at its stage
    assert app_server.state["events"] == [_args(), "stop 9.8.6", "start 9.8.7"]   # no -SkipBackup, no variable
    _upgraded(app_server, owner, out)


def test_backup_written_again_before_the_install_is_not_trusted(tmp_path, app_server):
    """The zip's write time changes between the precheck and the install (stamp still fresh): install.ps1 is called
    WITHOUT -SkipBackup."""
    owner, pkg, sha = _setup(tmp_path, app_server)
    zp, rp, _ = _verified(tmp_path, owner)
    with _interactive(owner, pkg, sha, zp, rp) as s:
        assert s.wait_for("== confirmation ==")
        assert "backup: skipped, verified backup" in s.text()
        os.utime(zp, None)                                           # written again (now)
        s.answer("UPGRADE-9.8.7")
        rc, out = s.finish()
    assert rc == 0, out
    assert "verified backup changed or removed since the prechecks: install.ps1 takes its own pre-upgrade backup" in out
    assert app_server.state["backups"] == 0
    assert app_server.state["events"] == [_args(), "stop 9.8.6", "start 9.8.7"]
    _upgraded(app_server, owner, out)


# --- install.ps1 itself, in a fake package (stub stop/start/check-env/autostart scripts, stub CLI) ---

def _fake_install_package(tmp: Path) -> tuple[Path, Path, dict]:
    local = tmp / "L"
    src = tmp / "pkg" / "DemandForecast-9.8.7"
    scripts = src / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(INSTALL_PS1, scripts / "install.ps1")
    marker = tmp / "stub-scripts.log"
    for name in ("stop.ps1", "start.ps1", "check-env.ps1", "register-autostart.ps1"):
        (scripts / name).write_text(f"Add-Content -Path '{marker}' -Value '{name}'\n", encoding="ascii")
    (src / "VERSION").write_text("9.8.7")
    py = src / "python"
    py.mkdir()
    ver = f"python{sys.version_info.major}{sys.version_info.minor}.dll"
    for f in ("python.exe", "python3.dll", ver, "vcruntime140.dll", "vcruntime140_1.dll"):
        s = Path(sys.base_prefix) / f
        if s.exists():
            shutil.copy2(s, py / f)
    data = tmp / "fake-data"            # tmp/data is the data folder of conftest
    (data / "db").mkdir(parents=True)
    (data / "db" / "app.db").write_bytes(b"\0" * 4096)
    calls = tmp / "calls.log"
    calls.write_text("")
    paths = {"data_dir": str(data), "db_path": str(data / "db" / "app.db"), "db_exists": True,
             "runtime_file": str(data / "runtime.json"), "logs_dir": str(data / "logs"), "backups_dir": str(data / "backups"),
             "reports_dir": str(data / "reports"), "storage_config": str(local / "DemandForecast" / "storage.json")}
    app = src / "backend" / "app"
    app.mkdir(parents=True)
    (app / "__init__.py").write_text("")
    (app / "cli.py").write_text(_stub_cli(NEW_CMDS, paths, "9.8.7", calls))
    local.mkdir()
    return local, src, {"calls": calls, "marker": marker}


@pytest.mark.skipif(not Path(os.environ.get("WINDIR", "C:\\Windows"), "System32", "vcomp140.dll").exists(),
                    reason="install.ps1 would try to install the VC++ runtime")
@pytest.mark.parametrize("case", ["no_switch", "deploy", "manual", "variable_no_file"])
def test_install_skipbackup_switch(tmp_path, case):
    """-SkipBackup is honoured only with DF_DEPLOY_VERIFIED_BACKUP naming an existing file (set by deploy-upgrade.ps1);
    a manual -SkipBackup is ignored and the backup is taken."""
    local, src, f = _fake_install_package(tmp_path)
    ps1 = src / "scripts" / "install.ps1"
    assert (src / "scripts" / "stop.ps1").read_text().startswith("Add-Content")    # the stub, never the real stop.ps1
    args = ["-NoShortcuts", "-NoStart"] + ([] if case == "no_switch" else ["-SkipBackup"])
    env = _env(local)
    vz = tmp_path / "verified.zip"
    if case == "deploy":
        vz.write_bytes(b"zip")
        env["DF_DEPLOY_VERIFIED_BACKUP"] = str(vz)
    elif case == "variable_no_file":
        env["DF_DEPLOY_VERIFIED_BACKUP"] = str(vz)                  # names no file
    p = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(ps1), *args],
                       env=env, capture_output=True, timeout=300, cwd=str(src / "backend"))
    out = " ".join((p.stdout + p.stderr).decode("utf-8", errors="replace").split())
    assert p.returncode == 0, out
    calls = f["calls"].read_text().split("\n")
    assert "9.8.7 migrate" in calls
    if case == "deploy":
        assert "Pre-upgrade backup skipped (-SkipBackup: verified backup given to deploy-upgrade.ps1)" in out
        assert f"Verified backup / restore point: {vz}" in out
        assert "9.8.7 backup" not in calls
    else:
        assert "Pre-upgrade backup skipped" not in out
        assert ("-SkipBackup ignored" in out) == (case != "no_switch")
        assert "9.8.7 backup" in calls and calls.index("9.8.7 backup") < calls.index("9.8.7 migrate")
    assert (local / "Programs" / "DemandForecast" / "current.txt").read_text().strip() == "9.8.7"
    assert "stop.ps1" in f["marker"].read_text()


@pytest.mark.parametrize("script", [DEPLOY, INSTALL_PS1])
def test_scripts_are_ascii_only(script):
    data = script.read_bytes()
    assert all(b < 128 for b in data), [i for i, b in enumerate(data) if b >= 128][:5]
