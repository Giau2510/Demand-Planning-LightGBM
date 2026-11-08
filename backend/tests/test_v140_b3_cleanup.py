"""1.4.0 B3: periodic cleanup scripts/ops/don_dep_dinh_ky.ps1 (+ register-don-dep-task.ps1 -Plan).

Everything runs in an isolated temporary tree: a fake project folder, a fake %LOCALAPPDATA% (set for the child
PowerShell only) with storage.json pointing at a fake data folder, and a fake -TmpRoot. Junctions (cmd mklink /J) are
placed both as group roots / parents of a group root and nested inside a group; each points at a folder holding a
sentinel that would be a candidate if the junction were followed. Never touches the real project, data, %LOCALAPPDATA%
or D:\\Buymed\\tmp; the scheduled task is never registered (-Plan only). 08/11/2026 rules (installs, dist_versions,
deploy_temp, concluded reports, backups of the current / previous version, 30 newest export days + _bo files, worktree
info, the don_dep_current.ps1 wrapper): same isolation; %TEMP% of the child PowerShell is a temporary folder too."""
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
WRAPPER = ROOT / "scripts" / "ops" / "don_dep_current.ps1"

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
    temp = la.parent / "TEMP"                       # the deploy_temp group never sees the real %TEMP%
    temp.mkdir(parents=True, exist_ok=True)
    env["TEMP"] = env["TMP"] = str(temp)
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
    exp: dict[str, set[str]] = {k: set() for k in ("backups", "exports", "logs", "tmp", "reports", "installs", "dist_versions",
                                                   "deploy_temp")}

    # fake %LOCALAPPDATA%: storage.json (data logs folder behind a junction PARENT), one installed version
    (proj / "scripts").mkdir(parents=True)
    protected = [_file(la / "DemandForecast" / "keep_me.txt"), _file(data / "db" / "app.db"), _file(data / "models" / "m.txt")]
    pd = la / "Programs" / "DemandForecast"
    protected += [_file(pd / "1.4.0" / "VERSION", b"1.4.0"), _file(pd / "current.txt", b"1.4.0"),
                  _file(pd / "1.3.9" / "VERSION", b"1.3.9")]                  # current + previous version: kept
    _file(pd / "1.3.8" / "app" / "x.py")
    exp["installs"].add(_n(pd / "1.3.8"))
    protected += [_file(pd / "1.5.0" / "VERSION"), _file(pd / "staging" / "x.txt")]   # newer / not a version: uncertain
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
    # 08/11 rule: only the newest backup overall, the last 7 days and the backups before the installs of the current /
    # previous version stay (here: the 5-day-old pre-upgrade backup)
    for i in range(9):
        exp["backups"].add(_n(_file(bk / f"backup-{_stamp(base + timedelta(days=i))}-manual.zip")))
    exp["backups"].add(_n(_file(bk / f"backup-{_stamp(base)}-manual.zip.sha256", b"ab")))
    exp["backups"].add(_n(_file(bk / f"config-{_stamp(base + timedelta(minutes=1))}-manual.json", b"{}")))
    for j in range(8):
        exp["backups"].add(_n(_file(bk / f"backup-{_stamp(base + timedelta(days=j, hours=6))}-cli.zip")))
    exp["backups"].add(_n(_file(bk / f"backup-{_stamp(NOW - timedelta(days=100))}-pre-upgrade.zip")))
    kept = [_file(bk / f"backup-{_stamp(NOW - timedelta(days=5))}-pre-upgrade.zip"), _file(bk / "notes.txt")]
    junctions.append(_junction(bk / "linked", outside / "bk"))
    sentinels.append(_file(outside / "bk" / f"backup-{_stamp(base - timedelta(days=1))}-manual.zip"))

    # exports: the 30 newest days (1..30 days ago) stay, one older day folder goes, one old-named junction; _bo files of
    # the kept days: day 10 (candidate), day 2 (too young), day 20 without a current file (kept_uncertain)
    du = data / "exports" / "du_bao"
    d_old = du / old120.strftime("%Y%m%d")
    _file(d_old / "du_bao.xlsx")
    exp["exports"].add(_n(d_old))
    for k in range(1, 31):
        ymd = (NOW - timedelta(days=k)).strftime("%Y%m%d")
        if k != 20:
            kept.append(_file(du / ymd / f"du_bao_{ymd}.xlsx"))
        if k in (2, 10, 20):
            if k != 20:
                kept.append(_file(du / ymd / f"du_bao_{ymd}_v2.xlsx"))          # the newer version of the day
            bo = _file(du / ymd / f"du_bao_{ymd}_v1_bo.xlsx")
            times.append((bo, NOW - timedelta(days=k)))
            if k == 10:
                exp["exports"].add(_n(bo))
            else:
                kept.append(bo)
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
    # dist of a worktree: packages of the current (1.4.0) and previous (1.3.9) version stay, 1.3.8 goes
    wd = proj / "worktrees" / "wt1" / "dist"
    kept += [_file(wd / "DemandForecast-1.4.0-win64-portable.zip"), _file(wd / "DemandForecast-1.4.0-win64-portable.zip.sha256"),
             _file(wd / "DemandForecast-1.4.0-win64-portable.manifest.json"), _file(wd / "DemandForecast-1.3.9-win64-portable.zip"),
             _file(wd / ".cache" / "python-embed.zip"), _file(wd / "DemandForecast-notes.txt")]
    exp["dist_versions"] |= {_n(_file(wd / "DemandForecast-1.3.8-win64-portable.zip")),
                             _n(_file(wd / "DemandForecast-1.3.8-win64-portable.zip.sha256"))}
    _file(wd / "DemandForecast-1.3.8" / "VERSION")
    exp["dist_versions"].add(_n(wd / "DemandForecast-1.3.8"))

    # %TEMP% (isolated, see _run): an old DemandForecast-deploy-<stamp> folder goes; a new one, the managed
    # DemandForecast-deploy root and another old folder stay
    tp = tmp_path / "TEMP"
    od = tp / "DemandForecast-deploy-20261101-000000"
    times += [(_file(od / "pkg.zip"), old3), (od, old3)]
    exp["deploy_temp"].add(_n(od))
    kept.append(_file(tp / "DemandForecast-deploy-20261107-000000" / "pkg.zip"))
    for p in (_file(tp / "DemandForecast-deploy" / "20261101-000000" / "pkg.zip"), _file(tp / "other_old" / "a.txt")):
        kept.append(p)
        times += [(p, old3), (p.parent, old3)]

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


# ------------------------------------------------------------------ 08/11/2026 rules


def _install(la: Path, current: str | None, versions: list[str]) -> Path:
    pd = la / "Programs" / "DemandForecast"
    for v in versions:
        _file(pd / v / "VERSION", v.encode())
    if current is not None:
        _file(pd / "current.txt", current.encode())
    (la / "DemandForecast").mkdir(parents=True, exist_ok=True)
    return pd


def _uncertain(g: dict) -> set[str]:
    return {_n(u["path"]) for u in _list(g.get("kept_uncertain"))}


def test_backups_installs_and_dist_versions_keep_current_and_previous(tmp_path: Path):
    """current 1.4.7, previous 1.4.6: backups (pre-<ver> names, install times, 7 days, newest), version folders (one
    used by a running process, one newer than current) and dist packages of the project and of a worktree."""
    la, proj = tmp_path / "LA", tmp_path / "proj"
    (proj / "scripts").mkdir(parents=True)
    pd = _install(la, "1.4.7", ["1.4.4", "1.4.5", "1.4.6", "1.4.7", "1.5.0"])
    times = [(pd / "1.4.7", NOW - timedelta(days=19)), (pd / "1.4.6", NOW - timedelta(days=29)),
             (pd / "1.4.5", NOW - timedelta(days=45)), (pd / "1.4.4", NOW - timedelta(days=60)), (pd / "1.5.0", NOW - timedelta(days=1))]
    bk = proj / "backups"

    def b(days: float, kind: str, minutes: int = 0) -> Path:
        return _file(bk / f"backup-{_stamp(NOW - timedelta(days=days, minutes=minutes))}-{kind}.zip")

    # b2 newest pre-146, b3 newest pre-147 (and newest before the 1.4.7 install), b5 last 7 days + newest overall,
    # b7 newest before the 1.4.6 install; b8 30 min before that install (not within 20 min)
    b1, b2, b3, b4 = b(40, "pre-146"), b(30, "pre-146"), b(20, "pre-147"), b(25, "cli")
    b5, b6, b7, b8 = b(3, "manual"), b(50, "pre-145"), b(29, "manual", 10), b(29, "cli", 30)
    s1, s4 = _file(Path(f"{b1}.sha256"), b"ab"), _file(Path(f"{b4}.sha256"), b"ab")
    want_bk = {_n(p) for p in (b1, s1, b4, s4, b6, b8)}
    kept = [b2, b3, b5, b7]
    dist, wdist = proj / "dist", proj / "worktrees" / "w1" / "dist"
    kept += [_file(dist / n) for n in ("DemandForecast-1.4.7-win64-portable.zip", "DemandForecast-1.4.7-win64-portable.zip.sha256",
                                        "DemandForecast-1.4.7-win64-portable.manifest.json", "DemandForecast-1.4.6-win64-portable.zip",
                                        "DemandForecast-1.4.7-superseded-20261101-000000-win64-portable.zip")]
    kept.append(_file(dist / ".cache" / "python-3.14-embed-amd64.zip"))
    want_dist = {_n(_file(dist / "DemandForecast-1.4.5-win64-portable.zip")),
                 _n(_file(dist / "DemandForecast-1.4.5-win64-portable.zip.sha256")),
                 _n(_file(wdist / "DemandForecast-1.4.4-abc1234-linux-src.tar.gz"))}
    _file(dist / "DemandForecast-1.4.5" / "VERSION")
    want_dist.add(_n(dist / "DemandForecast-1.4.5"))
    _set_times(tmp_path, times)
    user = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)", str(pd / "1.4.4")])
    try:
        code, out = _run(CLEANUP, ["-ProjectRoot", str(proj), "-TmpRoot", str(tmp_path / "tmproot")], la)
        assert code == 0, out
        rep = _report(out)
        assert rep["current_version"] == "1.4.7" and rep["previous_version"] == "1.4.6"
        g = _groups(rep)
        assert g["backups"]["status"] == "ok" and _cands(g["backups"]) == want_bk, g["backups"]
        assert _cands(g["installs"]) == {_n(pd / "1.4.5")}, g["installs"]
        assert _uncertain(g["installs"]) == {_n(pd / "1.5.0")}
        assert "used by running process" in _skips(rep)[_n(pd / "1.4.4")]
        assert _cands(g["dist_versions"]) == want_dist, g["dist_versions"]
        # -DistKeep keeps one more version (the old switch also applies to dist_versions)
        code, out = _run(CLEANUP, ["-ProjectRoot", str(proj), "-TmpRoot", str(tmp_path / "tmproot"), "-DistKeep", "1.4.5"], la)
        assert code == 0, out
        assert _cands(_groups(_report(out))["dist_versions"]) == {_n(wdist / "DemandForecast-1.4.4-abc1234-linux-src.tar.gz")}
        code, out = _run(CLEANUP, ["-ProjectRoot", str(proj), "-TmpRoot", str(tmp_path / "tmproot"), "-Apply"], la)
        assert code == 0, out
        g = _groups(_report(out))
        for name, want in (("backups", want_bk), ("installs", {_n(pd / "1.4.5")}), ("dist_versions", want_dist)):
            assert {_n(c["path"]) for c in _list(g[name]["candidates"]) if c.get("deleted")} == want, name
        for p in want_bk | want_dist | {_n(pd / "1.4.5")}:
            assert not os.path.lexists(p), p
        for p in kept + [pd / "current.txt", pd / "1.4.4" / "VERSION", pd / "1.4.6" / "VERSION", pd / "1.4.7" / "VERSION",
                         pd / "1.5.0" / "VERSION"]:
            assert p.is_file(), p
        assert (pd / "current.txt").read_text() == "1.4.7"
    finally:
        user.kill()
        user.wait()


def test_unreadable_current_version_selects_nothing_in_version_groups(tmp_path: Path):
    la, proj = tmp_path / "LA", tmp_path / "proj"
    (proj / "scripts").mkdir(parents=True)
    pd = _install(la, "garbage", ["1.4.5", "1.4.6"])
    old = _file(proj / "backups" / f"backup-{_stamp(NOW - timedelta(days=90))}-cli.zip")
    _file(proj / "backups" / f"backup-{_stamp(NOW - timedelta(days=80))}-cli.zip")
    pkg = _file(proj / "dist" / "DemandForecast-1.4.5-win64-portable.zip")
    code, out = _run(CLEANUP, ["-ProjectRoot", str(proj), "-TmpRoot", str(tmp_path / "tmproot"), "-Apply"], la)
    assert code == 0, out
    g = _groups(_report(out))
    for name in ("backups", "installs", "dist_versions"):
        assert g[name]["status"] == "skipped" and g[name]["candidate_count"] == 0, (name, g[name])
        assert "x.y.z" in g[name]["note"], g[name]["note"]
    assert old.is_file() and pkg.is_file() and (pd / "1.4.5" / "VERSION").is_file()


def test_concluded_reports_and_keep_list(tmp_path: Path):
    """A copy of the script with its own lists (the lists are read next to the script): concluded folder done1
    (intermediate files, superseded versions), done2 with a package folder (kept_uncertain), keepme in both lists."""
    la, proj, tool = tmp_path / "LA", tmp_path / "proj", tmp_path / "tool" / "scripts" / "ops"
    (proj / "scripts").mkdir(parents=True)
    la.mkdir()
    tool.mkdir(parents=True)
    script = tool / CLEANUP.name
    shutil.copy2(CLEANUP, script)
    (tool / "don_dep_giu.txt").write_text("# keep\nkeepme\n", encoding="ascii")
    (tool / "don_dep_ket_luan.txt").write_text("# done\ndone1\ndone2\nkeepme\nmissing\n", encoding="ascii")
    rp = proj / "reports"
    d1 = rp / "done1"
    want = {_n(_file(d1 / n)) for n in ("a.parquet", "sub/b.pkl", "x.log", "c.npz", "d.npy", "e.feather", "f.tmp",
                                         "r_v1.csv", "m_v1.xlsx", "m_v2.xlsx", "sub/t_v1.dat")}
    # code / text always stays (also older versions); r_v2 is the newest plain version (r_v2b is a variant, not newer)
    kept = [_file(d1 / n) for n in ("r_v2.csv", "m_v10.xlsx", "s_v1.py", "s_v2.py", "n_v1.md", "n_v2.md", "c_v1.json",
                                     "c_v2.json", "plain.csv", "r_v1.txt", "sub/t_v2.dat", "solo_v3.csv", "k_v1.ps1",
                                     "k_v2.ps1", "q_v1.sql", "q_v2.sql", "nb_v1.ipynb", "nb_v2.ipynb", "w_v1.sh", "w_v2.sh",
                                     "z_v1.R", "z_v2.R", "y_v1.bat", "y_v2.bat", "l_v1.txt", "l_v2.txt", "cfg_v1.yaml",
                                     "cfg_v2.yaml", "o_v1.yml", "o_v2.yml")]
    d2 = rp / "done2"
    unc = {_n(_file(d2 / "package" / "p.parquet")), _n(_file(d2 / "package" / "q_v1.csv")), _n(_file(d1 / "r_v2b.csv"))}
    kept += [_file(d2 / "package" / "q_v2.csv"), _file(d2 / "README.md")]
    want.add(_n(_file(d2 / "out.parquet")))
    kept += [_file(rp / "keepme" / "a.parquet"), _file(rp / "keepme" / "r_v1.csv"), _file(rp / "keepme" / "r_v2.csv"),
             _file(rp / "other" / "a.parquet")]
    code, out = _run(script, ["-ProjectRoot", str(proj), "-TmpRoot", str(tmp_path / "tmproot")], la)
    assert code == 0, out
    rep = _report(out)
    g = _groups(rep)["reports"]
    assert g["status"] == "ok", g
    assert _cands(g) == want
    assert _uncertain(g) == unc
    skips = _skips(rep)
    assert "keep list" in skips[_n(rp / "keepme")]
    assert "not found" in skips[_n(rp / "missing")]
    assert {_n(u["path"]) for u in _list(rep["kept_uncertain"])} >= unc
    code, out = _run(script, ["-ProjectRoot", str(proj), "-TmpRoot", str(tmp_path / "tmproot"), "-Apply"], la)
    assert code == 0, out
    for p in want:
        assert not os.path.lexists(p), p
    for p in kept + [Path(u) for u in unc]:
        assert Path(p).is_file(), p


def test_report_lists_passed_as_parameters(tmp_path: Path):
    """-KeepListFile / -ConcludedListFile replace the lists next to the script (the wrapper passes the source copies)."""
    la, proj = tmp_path / "LA", tmp_path / "proj"
    (proj / "scripts").mkdir(parents=True)
    la.mkdir()
    giu, kl = _file(tmp_path / "lists" / "giu.txt", b"keepme\n"), _file(tmp_path / "lists" / "kl.txt", b"done1\nkeepme\n")
    rp = proj / "reports"
    want = _file(rp / "done1" / "a.parquet")
    kept = [_file(rp / "keepme" / "a.parquet"), _file(rp / "cai-tien-20261031" / "a.parquet")]
    code, out = _run(CLEANUP, ["-ProjectRoot", str(proj), "-TmpRoot", str(tmp_path / "tmproot"), "-KeepListFile", str(giu),
                               "-ConcludedListFile", str(kl), "-Apply"], la)
    assert code == 0, out
    g = _groups(_report(out))["reports"]
    assert _cands(g) == {_n(want)} and str(kl) in g["note"], g
    assert not want.exists() and all(p.is_file() for p in kept)


def _git(cwd: Path, *a: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
                    "-c", "tag.gpgsign=false", *a], cwd=cwd, check=True, capture_output=True)


@pytest.mark.skipif(not shutil.which("git"), reason="git not installed")
def test_worktree_info_lists_finished_worktrees_only(tmp_path: Path):
    la, proj = tmp_path / "LA", tmp_path / "proj"
    (proj / "scripts").mkdir(parents=True)
    _install(la, "1.4.7", ["1.4.7"])
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "-q", "--bare")
    res = {}
    for name, dirty in (("done", False), ("busy", True)):
        w = proj / "worktrees" / name
        _file(w / "backend" / "app" / "__init__.py", b'__version__ = "1.4.7"\n')
        _git(w, "init", "-q")
        _git(w, "add", "-A")
        _git(w, "commit", "-q", "-m", "x")
        _git(w, "remote", "add", "origin", str(remote))
        _git(w, "push", "-q", "origin", f"HEAD:refs/heads/{name}")
        _git(w, "fetch", "-q", "origin")
        _git(w, "tag", "v1.4.7")
        if dirty:
            _file(w / "new.txt")
        res[name] = w
    code, out = _run(CLEANUP, ["-ProjectRoot", str(proj), "-TmpRoot", str(tmp_path / "tmproot")], la)
    assert code == 0, out
    info = {_n(w["path"]): w for w in _list(_report(out)["worktrees"])}
    assert info[_n(res["done"])]["can_remove"] is True, info
    assert info[_n(res["busy"])]["can_remove"] is False and "uncommitted" in info[_n(res["busy"])]["reason"]
    flat = " ".join(out.split())
    assert f"worktree_can_remove {res['done']}" in flat
    assert (res["busy"] / "new.txt").is_file() and (res["done"] / ".git").is_dir()


_STUB_CLEANUP = ("param([string]$ProjectRoot = '', [switch]$Apply, [switch]$IncludeDist, [string[]]$DistKeep = @(), [string]$TmpRoot = '')\n"
                 "Set-Content -LiteralPath (Join-Path $PSScriptRoot 'ran.txt') -Encoding UTF8 "
                 "-Value \"root=$ProjectRoot|apply=$Apply|dist=$IncludeDist|keep=$($DistKeep -join ',')|tmp=$TmpRoot\"\n"
                 "exit 3\n")


def test_wrapper_runs_the_installed_version_script(tmp_path: Path):
    la = tmp_path / "LA"
    proj = tmp_path / "my proj"
    (proj / "scripts").mkdir(parents=True)
    la.mkdir()
    code, out = _run(WRAPPER, ["-ProjectRoot", str(proj)], la)
    assert code == 2 and "current.txt not found" in out, out
    pd = _install(la, "nonsense", [])
    code, out = _run(WRAPPER, ["-ProjectRoot", str(proj)], la)
    assert code == 2 and "x.y.z" in out, out
    (pd / "current.txt").write_text("1.4.7\n", encoding="ascii")
    code, out = _run(WRAPPER, ["-ProjectRoot", str(proj)], la)
    assert code == 2 and "has no scripts" in out, out
    ops = pd / "1.4.7" / "scripts" / "ops"
    ops.mkdir(parents=True)
    (ops / "don_dep_dinh_ky.ps1").write_text(_STUB_CLEANUP, encoding="ascii")
    _file(pd / "1.4.6" / "scripts" / "ops" / "don_dep_dinh_ky.ps1", b"exit 9\n")       # an older version: never run
    code, out = _run(WRAPPER, ["-ProjectRoot", str(proj) + "\\", "-Apply", "-IncludeDist", "-DistKeep", "1.4.6,1.4.5",
                               "-TmpRoot", str(tmp_path / "tmproot")], la)
    assert code == 3, out
    ran = (ops / "ran.txt").read_text(encoding="utf-8-sig").strip()
    assert ran == f"root={proj}|apply=True|dist=True|keep=1.4.6,1.4.5|tmp={tmp_path / 'tmproot'}", ran
    code, out = _run(WRAPPER, [], la)                     # default -ProjectRoot: the source folder of the wrapper
    assert code == 3, out
    ran = (ops / "ran.txt").read_text(encoding="utf-8-sig").strip()
    assert ran == f"root={ROOT}|apply=False|dist=False|keep=|tmp=", ran


# ------------------------------------------------------------------ 08/11/2026 fix loop 1


def test_versions_previous_from_existing_folders_newer_kept_and_two_digit_parts(tmp_path: Path):
    """S1: install history names 1.4.7 but only the 1.4.6 folder exists -> previous = 1.4.6 (its package stays).
    C1: a package newer than the current version is never a candidate. 1.4.10 > 1.4.9 (numeric, not text).
    current.txt changed between the plan and the apply: the folder of the new current version is not deleted."""
    la, proj = tmp_path / "LA", tmp_path / "proj"
    (proj / "scripts").mkdir(parents=True)
    pd = _install(la, "1.4.8", ["1.4.5", "1.4.6", "1.4.8"])
    hist = proj / "logs" / "don_dep" / "install-history.json"
    _file(hist, json.dumps({"installs": [{"version": "1.4.7", "created": (NOW - timedelta(days=9)).strftime("%Y-%m-%dT%H:%M:%S"),
                                          "source": "version folder"}]}).encode())
    dist = proj / "dist"
    pk = {v: _file(dist / f"DemandForecast-{v}-win64-portable.zip") for v in ("1.4.5", "1.4.6", "1.4.7", "1.4.8", "1.4.9", "1.4.10")}
    args = ["-ProjectRoot", str(proj), "-TmpRoot", str(tmp_path / "tmproot")]
    code, out = _run(CLEANUP, args, la)
    assert code == 0, out
    rep = _report(out)
    assert rep["previous_version"] == "1.4.6", rep["previous_version"]
    g = _groups(rep)
    assert _cands(g["dist_versions"]) == {_n(pk["1.4.5"]), _n(pk["1.4.7"])}, g["dist_versions"]
    assert _uncertain(g["dist_versions"]) == {_n(pk["1.4.9"]), _n(pk["1.4.10"])}
    assert _cands(g["installs"]) == {_n(pd / "1.4.5")}
    # 1.4.10 current, 1.4.9 previous (two-digit part), 1.4.8 / 1.4.5 / 1.4.6 go, 1.4.10 and 1.4.9 packages stay
    _install(la, "1.4.10", ["1.4.9", "1.4.10"])
    code, out = _run(CLEANUP, args, la)
    assert code == 0, out
    rep = _report(out)
    assert rep["current_version"] == "1.4.10" and rep["previous_version"] == "1.4.9", rep
    g = _groups(rep)
    assert _cands(g["dist_versions"]) == {_n(pk[v]) for v in ("1.4.5", "1.4.6", "1.4.7", "1.4.8")}
    assert _uncertain(g["dist_versions"]) == set()
    assert _cands(g["installs"]) == {_n(pd / v) for v in ("1.4.5", "1.4.6", "1.4.8")}
    # current.txt goes back to 1.4.8 after this plan: the apply run keeps 1.4.8 (and 1.4.6 as its previous)
    (pd / "current.txt").write_text("1.4.8", encoding="ascii")
    code, out = _run(CLEANUP, args + ["-Apply"], la)
    assert code == 0, out
    assert (pd / "1.4.8" / "VERSION").is_file() and (pd / "1.4.6" / "VERSION").is_file() and not (pd / "1.4.5").exists()
    assert (pd / "1.4.9" / "VERSION").is_file() and (pd / "1.4.10" / "VERSION").is_file()      # newer than current: kept
    assert pk["1.4.6"].is_file() and pk["1.4.8"].is_file() and pk["1.4.9"].is_file() and pk["1.4.10"].is_file()


def test_exports_few_day_folders_and_bo_needs_a_newer_version(tmp_path: Path):
    """Fewer than 30 day folders: old ones stay. A _bo file goes only when a newer du_bao_<day>_v<M>.xlsx exists (a
    _TAM file does not count)."""
    la, proj, data = tmp_path / "LA", tmp_path / "proj", tmp_path / "data"
    (proj / "scripts").mkdir(parents=True)
    _install(la, None, [])
    (la / "DemandForecast" / "storage.json").write_text(json.dumps({"data_dir": str(data)}), encoding="utf-8")
    du = data / "exports" / "du_bao"
    d40, d50, d5 = ((NOW - timedelta(days=k)).strftime("%Y%m%d") for k in (40, 50, 5))
    kept = [_file(du / d40 / f"du_bao_{d40}_v2.xlsx"), _file(du / d50 / f"du_bao_{d50}.xlsx"), _file(du / d5 / f"du_bao_{d5}_TAM.xlsx")]
    bo40 = _file(du / d40 / f"du_bao_{d40}_v1_bo.xlsx")
    bo40b = _file(du / d40 / f"du_bao_{d40}_v2_bo.xlsx")            # no v3: kept_uncertain
    bo5 = _file(du / d5 / f"du_bao_{d5}_v1_bo.xlsx")                 # only a _TAM file next to it: kept_uncertain
    _set_times(tmp_path, [(bo40, NOW - timedelta(days=40)), (bo40b, NOW - timedelta(days=40)), (bo5, NOW - timedelta(days=5))])
    code, out = _run(CLEANUP, ["-ProjectRoot", str(proj), "-TmpRoot", str(tmp_path / "tmproot"), "-Apply"], la)
    assert code == 0, out
    g = _groups(_report(out))["exports"]
    assert g["status"] == "ok", g
    assert _cands(g) == {_n(bo40)}, g
    assert _uncertain(g) == {_n(bo40b), _n(bo5)}
    assert not bo40.exists() and all(p.is_file() for p in kept + [bo40b, bo5])


def test_deploy_temp_folder_used_by_a_process_is_kept(tmp_path: Path):
    la, proj = tmp_path / "LA", tmp_path / "proj"
    (proj / "scripts").mkdir(parents=True)
    la.mkdir()
    tp = tmp_path / "TEMP"
    used, free = tp / "DemandForecast-deploy-20261101-000000", tp / "DemandForecast-deploy-20261102-000000"
    times = []
    for d in (used, free):
        times += [(_file(d / "pkg.zip"), NOW - timedelta(days=3)), (d, NOW - timedelta(days=3))]
    _set_times(tmp_path, times)
    user = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)", str(used / "pkg.zip")])
    try:
        code, out = _run(CLEANUP, ["-ProjectRoot", str(proj), "-TmpRoot", str(tmp_path / "tmproot"), "-Apply"], la)
        assert code == 0, out
        rep = _report(out)
        assert _cands(_groups(rep)["deploy_temp"]) == {_n(free)}
        assert "used by running process" in _skips(rep)[_n(used)]
        assert (used / "pkg.zip").is_file() and not free.exists()
    finally:
        user.kill()
        user.wait()


_STUB_LISTS = ("param([string]$ProjectRoot = '', [switch]$Apply, [switch]$IncludeDist, [string[]]$DistKeep = @(), [string]$TmpRoot = '',\n"
               "      [string]$KeepListFile = '', [string]$ConcludedListFile = '')\n"
               "Set-Content -LiteralPath (Join-Path $PSScriptRoot 'ran.txt') -Encoding UTF8 "
               "-Value \"root=$ProjectRoot|giu=$KeepListFile|kl=$ConcludedListFile\"\n"
               "exit 0\n")


def test_wrapper_passes_the_source_lists_and_keeps_a_drive_root(tmp_path: Path):
    la, proj = tmp_path / "LA", tmp_path / "my proj"
    pd = _install(la, "1.4.8", [])
    ops = pd / "1.4.8" / "scripts" / "ops"
    ops.mkdir(parents=True)
    (ops / "don_dep_dinh_ky.ps1").write_text(_STUB_LISTS, encoding="ascii")
    giu = _file(proj / "scripts" / "ops" / "don_dep_giu.txt", b"x\n")
    code, out = _run(WRAPPER, ["-ProjectRoot", str(proj)], la)
    assert code == 0, out
    assert (ops / "ran.txt").read_text(encoding="utf-8-sig").strip() == f"root={proj}|giu={giu}|kl="
    kl = _file(proj / "scripts" / "ops" / "don_dep_ket_luan.txt", b"y\n")
    code, out = _run(WRAPPER, ["-ProjectRoot", str(proj)], la)
    assert code == 0, out
    assert (ops / "ran.txt").read_text(encoding="utf-8-sig").strip() == f"root={proj}|giu={giu}|kl={kl}"
    drive = str(tmp_path)[:3]                                        # e.g. C:\ (the stub only records it)
    code, out = _run(WRAPPER, ["-ProjectRoot", drive], la)
    assert code == 0, out
    assert (ops / "ran.txt").read_text(encoding="utf-8-sig").strip().startswith(f"root={drive}|")


def test_register_plan_uses_the_wrapper_unless_direct(tree):
    la, proj = tree["la"], tree["proj"]
    code, out = _run(REGISTER, ["-Plan", "-ProjectRoot", str(proj)], la)
    assert code == 0, out
    flat = " ".join(out.split())
    assert "don_dep_current.ps1" in flat and "nothing registered" in flat
    code, out = _run(REGISTER, ["-Plan", "-Direct", "-ProjectRoot", str(proj)], la)
    assert code == 0, out
    flat = " ".join(out.split())
    assert "don_dep_dinh_ky.ps1" in flat and "don_dep_current.ps1" not in flat


_TASK_DRIVER = """$ErrorActionPreference = 'Stop'
$ast = [System.Management.Automation.Language.Parser]::ParseFile($args[0], [ref]$null, [ref]$null)
$fn = $ast.Find({ param($x) $x -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $x.Name -eq 'Get-TaskActionVersions' }, $true)
Invoke-Expression $fn.Extent.Text
foreach ($l in Get-Content -LiteralPath $args[1] -Encoding UTF8) { '[' + (@(Get-TaskActionVersions $l $args[2]) -join ',') + ']' }
"""


def test_task_action_versions_helper(tmp_path: Path):
    """Get-TaskActionVersions (taken from the script by its AST; no task is registered): a file inside a version folder,
    quoted / unquoted, the %LOCALAPPDATA% form, a bare folder, and the 1.4.30 vs 1.4.3 prefix trap."""
    la = tmp_path / "LA"
    base = la / "Programs" / "DemandForecast"
    cases = [
        (f'powershell.exe -File "{base}\\1.4.3\\scripts\\start.ps1"', "1.4.3"),
        (f"{base}\\1.4.4\\python\\pythonw.exe -m app.cli serve", "1.4.4"),
        ("-File %LOCALAPPDATA%\\Programs\\DemandForecast\\1.4.5\\scripts\\x.ps1", "1.4.5"),
        (f"cmd /c cd {base}\\1.4.6", "1.4.6"),
        (f"'{base}\\1.4.7'", "1.4.7"),
        (f"{str(base).replace(chr(92), '/')}/1.4.8/run.bat", "1.4.8"),
        (f"{base}\\1.4.30\\x.ps1 {base}\\1.4.3x\\y", "1.4.30"),
        (f"{base}\\current.txt {la}\\Other\\1.4.9\\x.ps1", ""),
    ]
    drv = tmp_path / "_tav.ps1"
    drv.write_text(_TASK_DRIVER, encoding="ascii")
    lst = tmp_path / "_tav.txt"
    lst.write_text("\n".join(c for c, _ in cases), encoding="utf-8")
    code, out = _run(drv, [str(CLEANUP), str(lst), str(base)], la)
    assert code == 0, out
    got = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("[")]
    assert got == [f"[{w}]" for _, w in cases], (got, out)
