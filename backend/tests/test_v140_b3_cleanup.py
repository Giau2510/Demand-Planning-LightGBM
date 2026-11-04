"""1.4.0 B3: periodic cleanup scripts/ops/don_dep_dinh_ky.ps1 (+ register-don-dep-task.ps1 -Plan).

Everything runs in an isolated temporary tree: a fake project folder, a fake %LOCALAPPDATA% (set for the child
PowerShell only) with storage.json pointing at a fake data folder, and a fake -TmpRoot. Junctions (cmd mklink /J) are
placed both as group roots / parents of a group root and nested inside a group; each points at a folder holding a
sentinel that would be a candidate if the junction were followed. Never touches the real project, data, %LOCALAPPDATA%
or D:\\Buymed\\tmp; the scheduled task is never registered (-Plan only)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLEANUP = ROOT / "scripts" / "ops" / "don_dep_dinh_ky.ps1"
REGISTER = ROOT / "scripts" / "ops" / "register-don-dep-task.ps1"

pytestmark = pytest.mark.skipif(sys.platform != "win32" or not shutil.which("powershell"), reason="Windows PowerShell only")

NOW = datetime.now().replace(microsecond=0)


def _junction(link: Path, target: Path) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    link.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    return link


def _file(p: Path, data: bytes = b"x" * 64) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _set_times(tmp: Path, items: list[tuple[Path, datetime]]) -> None:
    """Sets creation, last write and last access time (in list order: children before their folder)."""
    lst = tmp / "_times.txt"
    lst.write_text("\n".join(f"{p}|{t:%Y-%m-%dT%H:%M:%S}" for p, t in items), encoding="utf-8")
    drv = tmp / "_set_times.ps1"
    drv.write_text("$ErrorActionPreference = 'Stop'\n"
                   "foreach ($l in Get-Content -LiteralPath $args[0] -Encoding UTF8) {\n"
                   "  $p, $t = $l.Split('|'); $d = [datetime]::ParseExact($t, 's', [Globalization.CultureInfo]::InvariantCulture)\n"
                   "  $i = Get-Item -LiteralPath $p -Force; $i.CreationTime = $d; $i.LastWriteTime = $d; $i.LastAccessTime = $d }\n",
                   encoding="ascii")
    p = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(drv),
                        str(lst)], capture_output=True, timeout=120)
    assert p.returncode == 0, (p.stdout + p.stderr).decode("utf-8", errors="replace")


def _run(script: Path, args: list[str], la: Path) -> tuple[int, str]:
    env = dict(os.environ)
    env["LOCALAPPDATA"] = str(la)
    p = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
                        *args], capture_output=True, timeout=300, env=env)
    return p.returncode, (p.stdout + p.stderr).decode("utf-8", errors="replace")


def _report(out: str) -> dict:
    lines = [ln.strip()[len("Report: "):] for ln in out.splitlines() if ln.strip().startswith("Report: ")]
    assert lines, out
    return json.loads(Path(lines[-1]).read_text(encoding="utf-8-sig"))


def _list(v) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _groups(rep: dict) -> dict[str, dict]:
    return {g["group"]: g for g in _list(rep["groups"])}


def _n(p) -> str:
    return os.path.normcase(str(p))


def _cands(g: dict) -> set[str]:
    return {_n(c["path"]) for c in _list(g.get("candidates"))}


def _skips(rep: dict) -> dict[str, str]:
    out = {}
    for g in _list(rep["groups"]):
        for s in _list(g.get("skipped")):
            out[_n(s["path"])] = s["reason"]
    return out


def _stamp(t: datetime) -> str:
    return t.strftime("%Y%m%d-%H%M%S")


@pytest.fixture()
def tree(tmp_path: Path) -> dict:
    """The full fake installation: returns paths, the expected candidates per group, sentinels and protected files."""
    la, proj, data, tmpr, outside = (tmp_path / n for n in ("LA", "proj", "data", "tmproot", "outside"))
    old3, old45, old120 = NOW - timedelta(days=3), NOW - timedelta(days=45), NOW - timedelta(days=120)
    times: list[tuple[Path, datetime]] = []
    sentinels: list[Path] = []
    junctions: list[Path] = []
    exp: dict[str, set[str]] = {k: set() for k in ("backups", "exports", "logs", "tmp", "reports")}

    # fake %LOCALAPPDATA%: storage.json (data logs folder behind a junction PARENT), one installed version
    (proj / "scripts").mkdir(parents=True)
    protected = [_file(la / "DemandForecast" / "keep_me.txt"), _file(data / "db" / "app.db"), _file(data / "models" / "m.txt")]
    _file(la / "Programs" / "DemandForecast" / "1.4.0" / "VERSION", b"1.4.0")
    _file(la / "Programs" / "DemandForecast" / "current.txt", b"1.4.0")
    via = _junction(tmp_path / "via", outside / "datalogs_target")
    sentinels.append(_file(outside / "datalogs_target" / "datalogs" / "old.log"))
    times.append((sentinels[-1], old45))
    junctions.append(via)
    (la / "DemandForecast" / "storage.json").write_text(json.dumps({"data_dir": str(data), "logs_dir": str(via / "datalogs")}),
                                                        encoding="utf-8")
    protected.append(la / "DemandForecast" / "storage.json")

    # backups: 9 manual, 8 cli, one old and one young pre-upgrade, companions, a nested junction
    bk = proj / "backups"
    base = (NOW - timedelta(days=200)).replace(hour=8, minute=0, second=0)
    for i in range(9):
        z = _file(bk / f"backup-{_stamp(base + timedelta(days=i))}-manual.zip")
        if i < 2:
            exp["backups"].add(_n(z))
    exp["backups"].add(_n(_file(bk / f"backup-{_stamp(base)}-manual.zip.sha256", b"ab")))
    exp["backups"].add(_n(_file(bk / f"config-{_stamp(base + timedelta(minutes=1))}-manual.json", b"{}")))
    for j in range(8):
        z = _file(bk / f"backup-{_stamp(base + timedelta(days=j, hours=6))}-cli.zip")
        if j == 0:
            exp["backups"].add(_n(z))
    exp["backups"].add(_n(_file(bk / f"backup-{_stamp(NOW - timedelta(days=100))}-pre-upgrade.zip")))
    kept = [_file(bk / f"backup-{_stamp(NOW - timedelta(days=5))}-pre-upgrade.zip"), _file(bk / "notes.txt")]
    junctions.append(_junction(bk / "linked", outside / "bk"))
    sentinels.append(_file(outside / "bk" / f"backup-{_stamp(base - timedelta(days=1))}-manual.zip"))

    # exports: one day folder older than 90 days, one recent, one old-named junction
    du = data / "exports" / "du_bao"
    d_old = du / old120.strftime("%Y%m%d")
    _file(d_old / "du_bao.xlsx")
    exp["exports"].add(_n(d_old))
    kept.append(_file(du / (NOW - timedelta(days=10)).strftime("%Y%m%d") / "du_bao.xlsx"))
    junctions.append(_junction(du / (old120 - timedelta(days=1)).strftime("%Y%m%d"), outside / "exp"))
    sentinels.append(_file(outside / "exp" / "du_bao.xlsx"))

    # project logs: one old, one new, a nested junction to an old log
    old_log = _file(proj / "logs" / "old.log")
    times.append((old_log, old45))
    exp["logs"].add(_n(old_log))
    kept.append(_file(proj / "logs" / "new.log"))
    junctions.append(_junction(proj / "logs" / "linked", outside / "logs_sub"))
    sentinels.append(_file(outside / "logs_sub" / "old2.log"))
    times.append((sentinels[-1], old45))

    # reports: a packaged experiment, one in the keep list, one without package
    rp = proj / "reports"
    kept += [_file(rp / "exp1" / "package" / "x.parquet"), _file(rp / "exp1" / "README.md"), _file(rp / "exp1" / "other.json"),
             _file(rp / "cai-tien-20261031" / "package" / "a.txt"), _file(rp / "cai-tien-20261031" / "data.csv"),
             _file(rp / "plain" / "data.csv")]
    exp["reports"] |= {_n(_file(rp / "exp1" / "data.parquet")), _n(_file(rp / "exp1" / "order_lines_2025.txt"))}
    junctions.append(_junction(rp / "exp1" / "linked", outside / "rep"))
    sentinels.append(_file(outside / "rep" / "data.csv"))

    # dist: the group ROOT is a junction (as in a worktree)
    junctions.append(_junction(proj / "dist", outside / "dist"))
    sentinels.append(_file(outside / "dist" / "DemandForecast-1.3.1-win64-portable.zip"))

    # tmp: old folder / file (candidates), a copied file with an old last write but a new creation time (kept),
    # a new file, a junction into %LOCALAPPDATA%\DemandForecast
    oc = tmpr / "old_copy"
    times += [(_file(oc / "app.db"), old3), (oc, old3)]
    exp["tmp"].add(_n(oc))
    times.append((_file(tmpr / "old_file.txt"), old3))
    exp["tmp"].add(_n(tmpr / "old_file.txt"))
    copied = _file(tmpr / "copied" / "copy.db")
    os.utime(copied, (old3.timestamp(), old3.timestamp()))            # last write old, creation time = now
    times.append((tmpr / "copied", old3))
    kept += [copied, _file(tmpr / "new_file.txt")]
    junctions.append(_junction(tmpr / "old_link", la / "DemandForecast"))

    _set_times(tmp_path, times)
    return {"la": la, "proj": proj, "tmp": tmpr, "via": via, "exp": exp, "sentinels": sentinels, "junctions": junctions,
            "protected": protected, "kept": kept}


def _args(t: dict, *extra: str) -> list[str]:
    return ["-ProjectRoot", str(t["proj"]), "-TmpRoot", str(t["tmp"]), *extra]


def _assert_untouched(t: dict) -> None:
    for p in t["sentinels"] + t["protected"] + t["kept"]:
        assert p.is_file(), p
    for j in t["junctions"]:
        assert os.path.lexists(j) and Path(j).is_junction(), j


def test_dry_run_deletes_nothing_and_lists_exactly_the_candidates(tree):
    code, out = _run(CLEANUP, _args(tree), tree["la"])
    assert code == 0, out
    rep = _report(out)
    assert rep["mode"] == "DRY_RUN"
    g = _groups(rep)
    for name, want in tree["exp"].items():
        assert g[name]["status"] == "ok", (name, g[name])
        assert _cands(g[name]) == want, name
    for name in tree["exp"]:
        for c in tree["exp"][name]:
            assert os.path.exists(c), c
    _assert_untouched(tree)
    # every junction is reported and skipped: nested ones as entries, the dist root and the data log root (parent)
    skips = _skips(rep)
    for j in tree["junctions"]:
        if j != tree["via"]:
            assert _n(j) in skips, (j, skips)
    assert "reparse point in path" in skips[_n(tree["via"] / "datalogs")]
    assert _n(tree["via"]) in _n(skips[_n(tree["via"] / "datalogs")])
    assert g["dist"]["status"] == "skipped" and "reparse" in g["dist"]["note"]
    assert "reparse point in path" in skips[_n(tree["proj"] / "dist")]
    assert rep["totals"]["deleted_count"] == 0


def test_apply_deletes_exactly_the_candidates_and_never_through_a_junction(tree):
    code, out = _run(CLEANUP, _args(tree, "-Apply"), tree["la"])
    assert code == 0, out
    rep = _report(out)
    assert rep["mode"] == "APPLY"
    g = _groups(rep)
    expected = set().union(*tree["exp"].values())
    for name, want in tree["exp"].items():
        assert _cands(g[name]) == want, name
        assert {_n(c["path"]) for c in _list(g[name]["candidates"]) if c.get("deleted")} == want, name
    for c in expected:
        assert not os.path.lexists(c), c
    assert rep["totals"]["deleted_count"] == len(expected)
    _assert_untouched(tree)
    # the old log went into the archive next to it before deletion
    zips = list((tree["proj"] / "logs").glob("logs-archive-*.zip"))
    assert len(zips) == 1
    import zipfile
    with zipfile.ZipFile(zips[0]) as z:
        assert "old.log" in z.namelist()
    assert g["dist"]["status"] == "skipped" and g["dist"]["deleted_count"] == 0


def test_group_root_junctions_are_skipped_with_apply(tmp_path: Path):
    """reports\\ and -TmpRoot are junctions themselves: nothing behind them is selected or deleted."""
    la, proj, outside = tmp_path / "LA", tmp_path / "proj", tmp_path / "outside"
    (proj / "scripts").mkdir(parents=True)
    la.mkdir()
    rep_link = _junction(proj / "reports", outside / "rep")
    s1 = _file(outside / "rep" / "exp" / "data.parquet")
    _file(outside / "rep" / "exp" / "package" / "a.txt")
    tmp_link = _junction(tmp_path / "tmplink", outside / "tmp")
    s2 = _file(outside / "tmp" / "old.txt")
    bk_link = _junction(proj / "backups", la / "DemandForecast")
    s3 = _file(la / "DemandForecast" / f"backup-{_stamp(NOW - timedelta(days=300))}-pre-upgrade.zip")
    # a newer old backup: s3 is no longer "the newest before the install", so the old code would have deleted it
    s4 = _file(la / "DemandForecast" / f"backup-{_stamp(NOW - timedelta(days=200))}-pre-upgrade.zip")
    _file(la / "Programs" / "DemandForecast" / "1.4.0" / "VERSION")
    _set_times(tmp_path, [(s1, NOW - timedelta(days=5)), (s2, NOW - timedelta(days=5))])
    code, out = _run(CLEANUP, ["-ProjectRoot", str(proj), "-TmpRoot", str(tmp_link), "-Apply"], la)
    assert code == 0, out
    rep = _report(out)
    g = _groups(rep)
    skips = _skips(rep)
    for name, link in (("reports", rep_link), ("tmp", tmp_link), ("backups", bk_link)):
        assert g[name]["status"] == "skipped", (name, g[name])
        assert g[name]["candidate_count"] == 0
        assert "reparse point in path" in skips[_n(link)], name
    for p in (s1, s2, s3, s4):
        assert p.is_file(), p
    for j in (rep_link, tmp_link, bk_link):
        assert j.is_junction(), j
    assert rep["totals"]["deleted_count"] == 0


def test_include_dist_without_dist_keep_is_refused(tree):
    code, out = _run(CLEANUP, _args(tree, "-Apply", "-IncludeDist"), tree["la"])
    assert code == 2, out
    assert "-IncludeDist needs -DistKeep" in out
    code, out = _run(CLEANUP, _args(tree, "-Apply", "-IncludeDist", "-DistKeep", "latest"), tree["la"])
    assert code == 2, out
    assert "not a version" in out
    for c in set().union(*tree["exp"].values()):
        assert os.path.exists(c), c
    _assert_untouched(tree)
    assert not (tree["proj"] / "logs" / "don_dep").exists()


def test_project_root_inside_the_installation_is_refused(tree):
    la = tree["la"]
    inst = la / "Programs" / "DemandForecast" / "1.4.0"
    (inst / "scripts" / "ops").mkdir(parents=True)
    old = _file(inst / "logs" / "old.log")
    data_proj = la / "DemandForecast" / "src"
    (data_proj / "scripts").mkdir(parents=True)
    _set_times(la.parent, [(old, NOW - timedelta(days=60))])
    for root in (inst, data_proj):
        code, out = _run(CLEANUP, ["-ProjectRoot", str(root), "-TmpRoot", str(tree["tmp"]), "-Apply"], la)
        assert code == 2, out
        assert "pass -ProjectRoot <source folder>" in out
    # the packaged copy run without -ProjectRoot (default = the installed version folder)
    shutil.copy2(CLEANUP, inst / "scripts" / "ops" / CLEANUP.name)
    code, out = _run(inst / "scripts" / "ops" / CLEANUP.name, ["-TmpRoot", str(tree["tmp"]), "-Apply"], la)
    assert code == 2, out
    assert old.is_file()
    assert not (inst / "logs" / "don_dep").exists()
    _assert_untouched(tree)


def test_register_plan_checks_dist_keep_and_project_root(tree):
    la, proj = tree["la"], tree["proj"]
    code, out = _run(REGISTER, ["-Plan", "-Apply", "-IncludeDist", "-ProjectRoot", str(proj)], la)
    assert code == 2, out
    assert "-IncludeDist needs -DistKeep" in out
    inst = la / "Programs" / "DemandForecast" / "1.4.0"
    (inst / "scripts").mkdir(parents=True)
    code, out = _run(REGISTER, ["-Plan", "-ProjectRoot", str(inst)], la)
    assert code == 2, out
    assert "pass -ProjectRoot <source folder>" in out
    code, out = _run(REGISTER, ["-Plan", "-Apply", "-IncludeDist", "-DistKeep", "1.3.1,1.2.14", "-ProjectRoot", str(proj)], la)
    assert code == 0, out
    flat = " ".join(out.split())
    assert "nothing registered" in flat
    assert '-IncludeDist -DistKeep "1.3.1,1.2.14"' in flat
    assert f'-ProjectRoot "{proj}"' in flat


def _short(p: Path) -> str | None:
    """8.3 short form of an existing path, or None when 8.3 names are not available (form unchanged)."""
    import ctypes
    buf = ctypes.create_unicode_buffer(32768)
    n = ctypes.windll.kernel32.GetShortPathNameW(str(p), buf, len(buf))
    s = buf.value if 0 < n < len(buf) else ""
    return s if s and os.path.normcase(s) != os.path.normcase(str(p)) else None


def test_short_8dot3_project_root_and_installed_version_folder_are_refused(tmp_path: Path):
    la = tmp_path / "LA"
    inst = la / "Programs" / "DemandForecast" / "1.4.0"          # no VERSION / current.txt: only the path check refuses
    (inst / "scripts").mkdir(parents=True)
    (la / "DemandForecast").mkdir(parents=True)
    old = _file(inst / "logs" / "old.log")
    _set_times(tmp_path, [(old, NOW - timedelta(days=60))])
    short = _short(inst)
    if short is None:
        pytest.skip("8.3 short names are not available on this volume")
    code, out = _run(CLEANUP, ["-ProjectRoot", short, "-TmpRoot", str(tmp_path / "tmproot"), "-Apply"], la)
    assert code == 2, out
    assert "is inside" in out and "pass -ProjectRoot <source folder>" in out
    code, out = _run(REGISTER, ["-Plan", "-ProjectRoot", short], la)
    assert code == 2, out
    assert "is inside" in out
    # an installed version folder outside this %LOCALAPPDATA% (VERSION + current.txt next to it)
    other = tmp_path / "other" / "1.3.1"
    (other / "scripts").mkdir(parents=True)
    _file(other / "VERSION", b"1.3.1")
    _file(other.parent / "current.txt", b"1.3.1")
    for script in (CLEANUP, REGISTER):
        args = ["-ProjectRoot", str(other)] + (["-TmpRoot", str(tmp_path / "tmproot"), "-Apply"] if script == CLEANUP else ["-Plan"])
        code, out = _run(script, args, la)
        assert code == 2, out
        assert "installed version folder" in out
    assert old.is_file()
    assert not (inst / "logs" / "don_dep").exists() and not (other / "logs").exists()


def test_tmp_root_drive_root_or_parent_of_project_data_or_localappdata_is_refused(tree):
    t = tree
    data = Path(json.loads((t["la"] / "DemandForecast" / "storage.json").read_text(encoding="utf-8"))["data_dir"])
    for bad in (Path(str(t["proj"])[:3]), t["proj"].parent, t["proj"], data, t["la"]):
        code, out = _run(CLEANUP, ["-ProjectRoot", str(t["proj"]), "-TmpRoot", str(bad), "-Apply"], t["la"])
        assert code == 2, (bad, out)
        assert "-TmpRoot" in out and "refused" in out, (bad, out)
    for c in set().union(*t["exp"].values()):
        assert os.path.exists(c), c
    _assert_untouched(t)
    assert not (t["proj"] / "logs" / "don_dep").exists()


_STUB_PRUNE = ("param([string[]]$Keep = @(), [int]$KeepLatest = 1, [switch]$Apply)\n"
               "Set-Content -LiteralPath (Join-Path (Split-Path -Parent $PSScriptRoot) 'prune_ran.txt') "
               "-Value \"apply=$Apply keep=$($Keep -join ',')\"\n")


def test_nested_junction_under_dist_stops_prune_artifacts(tmp_path: Path):
    """prune-artifacts.ps1 recurses through junctions: with one anywhere under dist\\ it is never run, even with
    -Apply -IncludeDist -DistKeep. A stub prune-artifacts.ps1 records every run."""
    la, proj, outside = tmp_path / "LA", tmp_path / "proj", tmp_path / "outside"
    (la / "DemandForecast").mkdir(parents=True)
    (proj / "scripts" / "prune-artifacts.ps1").parent.mkdir(parents=True)
    (proj / "scripts" / "prune-artifacts.ps1").write_text(_STUB_PRUNE, encoding="ascii")
    _file(proj / "dist" / "DemandForecast-1.3.1-win64-portable.zip")
    link = _junction(proj / "dist" / "sub" / "linked", outside / "d")
    sentinel = _file(outside / "d" / "DemandForecast-1.2.0-win64-portable.zip")
    marker = proj / "prune_ran.txt"
    code, out = _run(CLEANUP, ["-ProjectRoot", str(proj), "-TmpRoot", str(tmp_path / "tmproot"), "-Apply", "-IncludeDist",
                               "-DistKeep", "1.3.1"], la)
    assert code == 0, out
    g = _groups(_report(out))["dist"]
    assert g["status"] == "skipped" and "prune-artifacts.ps1 not run" in g["note"], g
    assert _n(link) in {_n(s["path"]) for s in _list(g["skipped"])}
    assert not marker.exists()
    assert sentinel.is_file() and link.is_junction()
    # control: without the junction the (stub) prune-artifacts.ps1 does run
    os.rmdir(link)                                                    # removes the junction only, never its target
    assert sentinel.is_file()
    code, out = _run(CLEANUP, ["-ProjectRoot", str(proj), "-TmpRoot", str(tmp_path / "tmproot"), "-IncludeDist",
                               "-DistKeep", "1.3.1"], la)
    assert code == 0, out
    assert _groups(_report(out))["dist"]["status"] == "ok"
    assert marker.read_text(encoding="utf-8-sig").strip() == "apply=False keep=1.3.1"


def test_log_archive_that_is_a_junction_is_refused(tree):
    t = tree
    old_log = t["proj"] / "logs" / "old.log"
    month = datetime.fromtimestamp(old_log.stat().st_mtime).strftime("%Y%m")
    link = _junction(t["proj"] / "logs" / f"logs-archive-{month}.zip", t["proj"].parent / "outside" / "zip_target")
    sentinel = _file(t["proj"].parent / "outside" / "zip_target" / "keep.txt")
    code, out = _run(CLEANUP, _args(t, "-Apply"), t["la"])
    assert code == 1, out
    g = _groups(_report(out))["logs"]
    assert any("reparse point in path" in e for e in _list(g["errors"])), g["errors"]
    assert old_log.is_file() and sentinel.is_file() and link.is_junction()
    assert g["deleted_count"] == 0
