"""1.2.14: the staging folder of scripts/deploy-upgrade.ps1 (scripts/_deploy_staging.ps1).

A deploy unpacks its package into ONE managed folder <TEMP>\\DemandForecast-deploy\\<stamp> with a marker; at the end only
that folder is removed, only after the upgrade passed its post-checks, the installed copy is complete, nothing runs from it
and the rollback version is installed. Everything runs in temporary folders (unit tests of the helper) or in the isolated
fake installation of test_v1213_deploy_preflight (the real deploy-upgrade.ps1 with a stub app and a stub install.ps1).
Never touches the real %TEMP%, %LOCALAPPDATA% or the running app."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from test_v1213_deploy_preflight import app_server  # noqa: F401 - the stub app fixture (tests/ is on sys.path)

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "_deploy_staging.ps1"
DEPLOY = ROOT / "scripts" / "deploy-upgrade.ps1"
SHA = "AB" * 32
STAMP = "20261026-120000"

pytestmark = pytest.mark.skipif(sys.platform != "win32" or not shutil.which("powershell"), reason="Windows PowerShell only")


def _ps(tmp: Path, body: str) -> tuple[dict, str]:
    """Runs `body` after dot-sourcing the helper; the last line starting with '{' is the JSON result."""
    drv = tmp / f"drv_{uuid.uuid4().hex[:8]}.ps1"
    drv.write_text("$ErrorActionPreference = 'Stop'\n. '" + str(HELPER) + "'\n" + body + "\n", encoding="ascii")
    p = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(drv)],
                       capture_output=True, timeout=180)
    out = (p.stdout + p.stderr).decode("utf-8", errors="replace")
    assert p.returncode == 0, out
    lines = [ln for ln in out.splitlines() if ln.startswith("{")]
    assert lines, out
    return json.loads(lines[-1]), " ".join(out.split())


def _new(tmp: Path, root: Path, stamp: str = STAMP, sha: str = SHA, version: str = "9.8.7") -> Path:
    r, _ = _ps(tmp, f"$p = New-DeployStaging '{root}' '{stamp}' '{version}' '{sha}'\n@{{ path = $p }} | ConvertTo-Json -Compress")
    p = Path(r["path"])
    (p / f"DemandForecast-{version}" / "python").mkdir(parents=True)
    (p / f"DemandForecast-{version}" / "VERSION").write_text(version)
    (p / f"DemandForecast-{version}" / "python" / "python.exe").write_bytes(b"MZ")
    return p


def _long_file(base: Path) -> Path:
    """A file whose full path is longer than 260 characters (created through the \\\\?\\ prefix)."""
    deep = Path("\\\\?\\" + str(base)) / ("d" * 60) / ("e" * 60) / ("f" * 60) / ("g" * 40)
    os.makedirs(deep, exist_ok=True)
    f = deep / "long-name-file.txt"
    with open(f, "w") as fh:
        fh.write("x")
    assert len(str(f)) > 264
    return f


def _programs(tmp: Path, current: str = "9.8.7", installed=("9.8.6", "9.8.7")) -> Path:
    base = tmp / "L" / "Programs" / "DemandForecast"
    for v in installed:
        (base / v / "python").mkdir(parents=True, exist_ok=True)
        (base / v / "python" / "python.exe").write_bytes(b"MZ")
    (base / "current.txt").write_text(current)
    return base


def _complete(tmp: Path, root: Path, path, succeeded: bool, base: Path, new="9.8.7", prev="9.8.6", sha=SHA) -> tuple[dict, str]:
    p = "$null" if path is None else f"'{path}'"
    return _ps(tmp, f"$r = Complete-DeployStaging -Path {p} -Root '{root}' -Stamp '{STAMP}' -PackageSha256 '{sha}' "
                    f"-Succeeded ${str(succeeded).lower()} -NewVersion '{new}' -PrevVersion '{prev}' -ProgramsBase '{base}'\n"
                    "$r | ConvertTo-Json -Compress")


def _remove(tmp: Path, root: Path, path, stamp: str = STAMP, sha: str = SHA) -> tuple[dict, str]:
    return _ps(tmp, f"Remove-DeployStaging '{path}' '{root}' '{stamp}' '{sha}' | ConvertTo-Json -Compress")


@pytest.fixture
def area(tmp_path):
    temp = tmp_path / "T"
    root = temp / "DemandForecast-deploy"
    legacy = temp / "DemandForecast-deploy-20261015-163950"          # a pre-1.2.14 staging folder: never touched
    (legacy / "DemandForecast-1.1.6").mkdir(parents=True)
    (legacy / "DemandForecast-1.1.6" / "VERSION").write_text("1.1.6")
    return {"tmp": tmp_path, "temp": temp, "root": root, "legacy": legacy}


# --- 1. success: this run's folder is removed (also paths > 260 characters), nothing else ---
def test_success_removes_only_this_runs_staging(area):
    tmp, root = area["tmp"], area["root"]
    stage = _new(tmp, root)
    _long_file(stage)
    other = _new(tmp, root, stamp="20261025-080000")                # another run's managed folder
    base = _programs(tmp)
    r, out = _complete(tmp, root, stage, True, base)
    assert r["action"] == "REMOVED", out
    assert not stage.exists() and not Path(str(stage) + ".removing").exists()
    assert other.exists() and (other / ".df-deploy-staging.json").exists()
    assert area["legacy"].exists() and (area["legacy"] / "DemandForecast-1.1.6" / "VERSION").exists()
    assert (base / "9.8.7" / "python" / "python.exe").exists() and (base / "9.8.6" / "python" / "python.exe").exists()
    assert "staging: removed" in out


# --- 2. failed deploy: kept for the investigation ---
def test_failed_deploy_keeps_the_staging(area):
    tmp, root = area["tmp"], area["root"]
    stage = _new(tmp, root)
    r, out = _complete(tmp, root, stage, False, _programs(tmp, current="9.8.6"))
    assert r["action"] == "KEPT" and "investigation" in r["reason"], out
    assert (stage / ".df-deploy-staging.json").exists() and (stage / "DemandForecast-9.8.7" / "VERSION").exists()


@pytest.mark.parametrize("case", ["current_mismatch", "no_installed_copy", "no_rollback_version"])
def test_unmet_post_condition_keeps_the_staging(area, case):
    tmp, root = area["tmp"], area["root"]
    stage = _new(tmp, root)
    base = {"current_mismatch": lambda: _programs(tmp, current="9.8.6"),
            "no_installed_copy": lambda: _programs(tmp, installed=("9.8.6",)),
            "no_rollback_version": lambda: _programs(tmp, installed=("9.8.7",))}[case]()
    r, out = _complete(tmp, root, stage, True, base)
    expect = {"current_mismatch": "current.txt is '9.8.6'", "no_installed_copy": "has no python",
              "no_rollback_version": "rollback version 9.8.6 is not installed"}[case]
    assert r["action"] == "KEPT" and expect in r["reason"], out
    assert stage.exists() and "WARNING staging kept" in out


def test_a_process_running_from_the_staging_keeps_it(area):
    """The app (or anything) started from the unpacked package: the folder is still needed."""
    tmp, root = area["tmp"], area["root"]
    stage = _new(tmp, root)
    py = stage / "DemandForecast-9.8.7" / "runner"
    py.mkdir()
    ver = f"python{sys.version_info.major}{sys.version_info.minor}.dll"
    for f in ("python.exe", "python3.dll", ver, "vcruntime140.dll", "vcruntime140_1.dll"):
        src = Path(sys.base_prefix) / f
        if src.exists():
            shutil.copy2(src, py / f)
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "VIRTUAL_ENV")}
    env["PYTHONHOME"] = sys.base_prefix
    proc = subprocess.Popen([str(py / "python.exe"), "-c", "import time; time.sleep(120)"], env=env)
    try:
        r, out = _complete(tmp, root, stage, True, _programs(tmp))
        assert r["action"] == "KEPT" and "running from the staging folder" in r["reason"] and str(proc.pid) in r["reason"], out
        assert stage.exists()
    finally:
        proc.kill()
        proc.wait(30)


# --- 3. folders that are not this run's staging are refused, untouched ---
@pytest.mark.parametrize("marker", ["none", "other_stamp", "other_package", "other_kind"])
def test_folder_not_created_by_this_run_is_refused(area, marker):
    tmp, root = area["tmp"], area["root"]
    stage = _new(tmp, root)
    mf = stage / ".df-deploy-staging.json"
    if marker == "none":
        mf.unlink()
    else:
        m = json.loads(mf.read_text())
        m.update({"other_stamp": {"stamp": "20261024-000000"}, "other_package": {"package_sha256": "CD" * 32},
                  "other_kind": {"kind": "something-else"}}[marker])
        mf.write_text(json.dumps(m))
    r, out = _remove(tmp, root, stage)
    assert r["action"] == "REFUSED", out
    assert (stage / "DemandForecast-9.8.7" / "VERSION").exists()


# --- 4. wrong / out-of-scope paths are refused, untouched ---
@pytest.mark.parametrize("kind", ["traversal", "sibling_dir", "the_root_itself", "bad_stamp", "legacy_folder"])
def test_paths_outside_the_managed_folder_are_refused(area, kind):
    tmp, root, temp = area["tmp"], area["root"], area["temp"]
    stage = _new(tmp, root)
    elsewhere = temp / "elsewhere"
    elsewhere.mkdir()
    shutil.copy2(stage / ".df-deploy-staging.json", elsewhere / ".df-deploy-staging.json")   # even with a copied marker
    path, stamp = {"traversal": (f"{stage}\\..\\..\\elsewhere", STAMP), "sibling_dir": (str(elsewhere), STAMP),
                   "the_root_itself": (str(root), STAMP), "bad_stamp": (f"{root}\\..", ".."),
                   "legacy_folder": (str(area["legacy"]), STAMP)}[kind]
    r, out = _remove(tmp, root, path, stamp=stamp)
    assert r["action"] == "REFUSED", out
    assert stage.exists() and elsewhere.exists() and area["legacy"].exists() and root.exists()


def test_junction_is_refused_and_its_target_untouched(area):
    tmp, root, temp = area["tmp"], area["root"], area["temp"]
    target = _new(tmp, root, stamp="20261025-090000")                  # a real folder with a valid marker of its own
    root.mkdir(parents=True, exist_ok=True)
    link = root / STAMP
    subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    m = json.loads((target / ".df-deploy-staging.json").read_text())
    m["stamp"] = STAMP                                                  # marker would match through the link
    (target / ".df-deploy-staging.json").write_text(json.dumps(m))
    try:
        r, out = _remove(tmp, root, link)
        assert r["action"] == "REFUSED" and "link" in r["reason"], out
        assert (target / "DemandForecast-9.8.7" / "VERSION").exists()
    finally:
        os.rmdir(link)                                                  # removes the junction only


# --- 5. a folder in use is kept (no lock is forced), removed once released ---
def test_folder_in_use_is_kept_then_removed_when_released(area):
    tmp, root = area["tmp"], area["root"]
    stage = _new(tmp, root)
    f = stage / "DemandForecast-9.8.7" / "VERSION"
    r, out = _ps(tmp, f"$h = [IO.File]::Open('{f}', 'Open', 'Read', 'Read')\n"
                      f"$a = Remove-DeployStaging '{stage}' '{root}' '{STAMP}' '{SHA}'\n"
                      "$h.Close()\n"
                      f"$b = Remove-DeployStaging '{stage}' '{root}' '{STAMP}' '{SHA}'\n"
                      "@{ first = $a.action; first_reason = $a.reason; second = $b.action } | ConvertTo-Json -Compress")
    assert r["first"] == "KEPT_IN_USE" and "in use" in r["first_reason"], out
    assert r["second"] == "REMOVED", out
    assert not stage.exists()


# --- 6. a permission error is reported as FAILED with a warning; the folder stays under its own name ---
def test_permission_error_is_reported_and_the_folder_kept(area):
    tmp, root = area["tmp"], area["root"]
    stage = _new(tmp, root)
    sub = stage / "DemandForecast-9.8.7" / "python"
    user = os.environ["USERNAME"]
    subprocess.run(["icacls", str(sub), "/deny", f"{user}:(OI)(CI)(DE,DC)", "/Q"], check=True, capture_output=True)
    try:
        r, out = _remove(tmp, root, stage)
        assert r["action"] == "FAILED" and "delete failed" in r["reason"], out
        assert "WARNING could not remove the staging folder" in out
        assert stage.exists() and not Path(str(stage) + ".removing").exists()   # name put back: found where the log says
    finally:
        subprocess.run(["icacls", str(sub), "/remove:d", user, "/T", "/Q"], capture_output=True)
    r2, out2 = _remove(tmp, root, stage)                                # once the cause is gone, a re-run removes it
    assert r2["action"] == "REMOVED", out2


# --- 7. no staging / 8. repeated runs ---
def test_missing_staging_is_not_an_error(area):
    tmp, root = area["tmp"], area["root"]
    r, out = _remove(tmp, root, root / STAMP)
    assert r["action"] == "NOT_FOUND", out
    r, out = _complete(tmp, root, None, True, _programs(tmp))
    assert r["action"] == "NOT_FOUND" and "stopped before unpacking" in out, out


def test_repeated_runs_remove_once_and_touch_nothing_else(area):
    tmp, root = area["tmp"], area["root"]
    stage = _new(tmp, root)
    other = _new(tmp, root, stamp="20261025-080000")
    base = _programs(tmp)
    results = [_complete(tmp, root, stage, True, base)[0]["action"] for _ in range(3)]
    assert results == ["REMOVED", "NOT_FOUND", "NOT_FOUND"]
    assert other.exists() and area["legacy"].exists()


# --- deploy-upgrade.ps1 wiring + the real script in the isolated fake installation ---
def test_deploy_upgrade_uses_the_managed_staging_and_ships_the_helper():
    s = DEPLOY.read_text(encoding="ascii")
    assert '. "$PSScriptRoot\\_deploy_staging.ps1"' in s
    assert "$stage = New-DeployStaging $stagingRoot $stamp $newVersion $sha" in s
    assert 'Join-Path $env:TEMP "DemandForecast-deploy-$stamp"' not in s
    done = s.index("$code = 0")                                         # cleanup decided after the post-checks, in finally
    assert s.index("Complete-DeployStaging", done) > done and "-Succeeded ($code -eq 0)" in s
    assert "Remove-Item" not in s and "rd /s" not in s                  # no other deletion in the deploy script
    assert '"_deploy_staging.ps1"' in (ROOT / "scripts" / "build-package.ps1").read_text(encoding="ascii")
    HELPER.read_text(encoding="ascii")                                  # ASCII only (Windows PowerShell 5.1)


def _staging_dirs(owner: dict) -> tuple[Path, list[Path]]:
    temp = owner["local"].parent / "temp"
    root = temp / "DemandForecast-deploy"
    return temp, sorted(p for p in root.glob("*") if p.is_dir()) if root.exists() else []


def test_real_deploy_success_removes_its_staging_only(tmp_path, app_server):
    from test_v1213_deploy_preflight import _deploy_log, _env, _upgrade, _upgrade_setup
    owner, pkg, sha = _upgrade_setup(tmp_path, app_server)
    temp = Path(_env(owner["local"])["TEMP"])
    legacy = temp / "DemandForecast-deploy-20261015-163950"
    legacy.mkdir(parents=True)
    (legacy / "keep.txt").write_text("old run")
    with _upgrade(owner, pkg, sha, "-ConfirmToken", "UPGRADE-9.8.7", console=False) as s:
        rc, out = s.finish()
    assert rc == 0, out
    assert "UPGRADE OK: 9.8.6 -> 9.8.7" in out
    _, left = _staging_dirs(owner)
    assert left == [], left
    log = _deploy_log(owner)
    assert "staging: created" in log and "staging: removed" in log
    assert "WARNING staging" not in log and "staging folder was not removed" not in log
    assert (legacy / "keep.txt").exists()
    assert (owner["base"] / "9.8.7" / "python" / "python.exe").exists() and (owner["base"] / "9.8.6").exists()


@pytest.mark.parametrize("install", ["fail", "stay"])
def test_real_deploy_failure_keeps_its_staging(tmp_path, app_server, install):
    from test_v1213_deploy_preflight import _deploy_log, _upgrade, _upgrade_setup
    owner, pkg, sha = _upgrade_setup(tmp_path, app_server, install=install)
    with _upgrade(owner, pkg, sha, "-ConfirmToken", "UPGRADE-9.8.7", console=False) as s:
        rc, out = s.finish()
    assert rc == 1, out
    _, left = _staging_dirs(owner)
    assert len(left) == 1 and (left[0] / ".df-deploy-staging.json").exists(), left
    assert json.loads((left[0] / ".df-deploy-staging.json").read_text())["package_sha256"] == sha
    assert "kept for the investigation" in _deploy_log(owner)
