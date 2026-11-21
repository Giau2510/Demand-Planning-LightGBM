"""KL-2 (18/11/2026): master keep list of the periodic cleanup scripts/ops/don_dep_dinh_ky.ps1 (-KeepListMaster).

Integration on a fake tree, never on real data: every case builds a fake project folder, a fake %LOCALAPPDATA% (storage
.json, installed versions, current.txt), a fake -TmpRoot, a fake %TEMP% (with \\claude), a fake -ClaudeProjectsRoot, and
runs a COPY of the script from a fake tool folder, so that the script's own runner\\notify.py is a fake one (a status
notice never reaches the real phone / network). The fake project is never D:\\Buymed\\Lightgbm AI. The only read of real
data is the owner's docs\\quy-tac\\keep_list.txt (parsed, nothing deleted by it).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLEANUP = ROOT / "scripts" / "ops" / "don_dep_dinh_ky.ps1"

pytestmark = pytest.mark.skipif(sys.platform != "win32" or not shutil.which("powershell"), reason="Windows PowerShell only")

NOW = datetime.now().replace(microsecond=0)


# ------------------------------------------------------------------ helpers


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
    """Creation, last write and last access time (children before their folder)."""
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


def _n(p) -> str:
    return os.path.normcase(str(p))


def _list(v) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _stamp(t: datetime) -> str:
    return t.strftime("%Y%m%d-%H%M%S")


def _short(p: Path) -> str | None:
    """8.3 short form of an existing path, or None when 8.3 names are not available."""
    import ctypes
    buf = ctypes.create_unicode_buffer(32768)
    n = ctypes.windll.kernel32.GetShortPathNameW(str(p), buf, len(buf))
    s = buf.value if 0 < n < len(buf) else ""
    return s if s and os.path.normcase(s) != os.path.normcase(str(p)) else None


class World:
    """The fake installation around one test (all under pytest tmp_path)."""

    def __init__(self, tmp_path: Path):
        self.root = tmp_path.resolve()                      # long form (no 8.3 parts)
        r = self.root
        self.la, self.proj, self.data, self.tmproot = r / "LA", r / "proj", r / "data", r / "tmproot"
        self.temp = r / "TEMP"
        self.claude = self.temp / "claude"
        self.cproj = r / "cproj"
        self.outside = r / "outside"
        self.tool = r / "tool" / "scripts" / "ops"
        self.notify_log = r / "notify_calls.txt"
        (self.proj / "scripts").mkdir(parents=True)
        (self.proj / "docs" / "quy-tac").mkdir(parents=True)
        for d in (self.data, self.tmproot, self.temp, self.claude, self.cproj, self.outside):
            d.mkdir(parents=True, exist_ok=True)
        _file(self.la / "DemandForecast" / "storage.json", json.dumps({"data_dir": str(self.data)}).encode())
        pd = self.la / "Programs" / "DemandForecast"
        _file(pd / "1.4.14" / "VERSION", b"1.4.14")
        _file(pd / "1.4.13" / "VERSION", b"1.4.13")
        _file(pd / "current.txt", b"1.4.14")
        (self.tool / "runner").mkdir(parents=True)
        shutil.copy2(CLEANUP, self.tool / CLEANUP.name)
        (self.tool / "don_dep_giu.txt").write_text("# none\n", encoding="ascii")
        # fake notify.py (the script prefers <its own folder>\runner\notify.py): records its arguments, nothing else
        (self.tool / "runner" / "notify.py").write_text(
            "import sys\nwith open(r'%s', 'a', encoding='utf-8') as f:\n    f.write(' '.join(sys.argv[1:]) + '\\n')\n" % self.notify_log,
            encoding="ascii")
        self.keep_file = self.proj / "docs" / "quy-tac" / "keep_list.txt"

    # -- tree
    def p(self, rel: str) -> Path:
        return self.proj / rel

    def age(self, days: float, *paths: Path) -> None:
        """Sets all times of the paths (and everything below them) to <days> ago. Call BEFORE adding junctions."""
        t = NOW - timedelta(days=days)
        items: list[tuple[Path, datetime]] = []
        for r in paths:
            if r.is_dir():
                for dp, _dn, fn in os.walk(r, topdown=False):
                    items += [(Path(dp) / n, t) for n in fn]
                    items.append((Path(dp), t))
            else:
                items.append((r, t))
        _set_times(self.root, items)

    def write_keep(self, lines: list[str], bom: bool = True, crlf: bool = True) -> Path:
        text = ("\r\n" if crlf else "\n").join(lines) + ("\r\n" if crlf else "\n")
        self.keep_file.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
        return self.keep_file

    def fake_python(self) -> None:
        subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(self.proj / ".venv")], check=True, capture_output=True)
        assert (self.proj / ".venv" / "Scripts" / "python.exe").is_file()

    def notices(self) -> list[str]:
        return self.notify_log.read_text(encoding="utf-8").splitlines() if self.notify_log.exists() else []

    # -- run
    def _args(self, groups: str, apply: bool, keep: str | None, extra: list[str] | None) -> list[str]:
        args = ["-ProjectRoot", str(self.proj), "-TmpRoot", str(self.tmproot), "-ClaudeTempRoot", str(self.claude),
                "-ClaudeProjectsRoot", str(self.cproj), "-Groups", groups]
        if keep == "explicit":
            args += ["-KeepListMaster", str(self.keep_file)]
        elif keep:
            args += ["-KeepListMaster", keep]
        if apply:
            args.append("-Apply")
        return args + (extra or [])

    def exec(self, args: list[str], env_extra: dict | None = None, report: bool = True) -> tuple[int, str, dict | None]:
        env = dict(os.environ)
        env["LOCALAPPDATA"] = str(self.la)
        env["TEMP"] = env["TMP"] = str(self.temp)
        env.update(env_extra or {})
        p = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                            str(self.tool / CLEANUP.name), *args], capture_output=True, timeout=300, env=env)
        out = (p.stdout + p.stderr).decode("utf-8", errors="replace")
        lines = [ln.strip()[len("Report: "):] for ln in out.splitlines() if ln.strip().startswith("Report: ")]
        if not lines and not report:
            return p.returncode, out, None
        assert lines, out
        rep = json.loads(Path(lines[-1]).read_text(encoding="utf-8-sig"))
        return p.returncode, out, rep

    def plan(self, groups: str, keep: str | None = "explicit", extra: list[str] | None = None,
             env_extra: dict | None = None) -> tuple[int, str, dict]:
        """A dry run (no -Apply). The report carries plan_hash and keep_list.sha256, the output PLAN_HASH: /
        KEEP_LIST_SHA256: lines."""
        code, out, rep = self.exec(self._args(groups, False, keep, extra), env_extra)
        return code, out, rep

    def run(self, groups: str, apply: bool = False, keep: str | None = "explicit", extra: list[str] | None = None,
            hashes: str | tuple = "auto", env_extra: dict | None = None) -> tuple[int, str, dict]:
        """apply=False: a dry run. apply=True (1.4.15 plan lock): by default the SAME arguments are run first without
        -Apply and their PLAN_HASH / KEEP_LIST_SHA256 are given to the -Apply run (what the owner does by hand; a dry run
        that prints no hash passes none). hashes="none": -Apply without either hash; hashes=(plan, keep): these values
        (None leaves one out)."""
        args = self._args(groups, apply, keep, extra)
        if apply and hashes == "auto":
            _c, o, _r = self.exec(self._args(groups, False, keep, extra), env_extra)
            h = _hashes(o)
            if h[0] and h[1]:
                args += ["-PlanHash", h[0], "-KeepListHash", h[1]]
        elif apply and isinstance(hashes, tuple):
            if hashes[0] is not None:
                args += ["-PlanHash", hashes[0]]
            if hashes[1] is not None:
                args += ["-KeepListHash", hashes[1]]
        return self.exec(args, env_extra)


_HASH_LINE = re.compile(r"^(PLAN_HASH|KEEP_LIST_SHA256): ([0-9a-f]{64})\s*$", re.M)


def _hashes(out: str) -> tuple[str | None, str | None]:
    """(PLAN_HASH, KEEP_LIST_SHA256) printed by a run; None when a line is missing or the keep list was not read."""
    h = dict(_HASH_LINE.findall(out))
    return h.get("PLAN_HASH"), h.get("KEEP_LIST_SHA256")


@pytest.fixture()
def w(tmp_path: Path) -> World:
    return World(tmp_path)


def _groups(rep: dict) -> dict[str, dict]:
    return {g["group"]: g for g in _list(rep["groups"])}


def _cands(rep: dict, group: str) -> set[str]:
    return {_n(c["path"]) for c in _list(_groups(rep)[group].get("candidates"))}


def _blocked(rep: dict) -> dict[str, dict]:
    return {_n(b["path"]): b for b in _list(rep["keep_list"]["blocked"])}


def _alive(*paths: Path) -> None:
    for p in paths:
        assert os.path.lexists(p), p


def _gone(*paths: Path) -> None:
    for p in paths:
        assert not os.path.lexists(p), p


# ------------------------------------------------------------------ cases 1, 2, 3 (+ plan table, no regression)


def _build_plain_world(w: World) -> dict:
    """Entries of the groups tmp / logs / reports / deploy_temp / dist_versions: some candidates, some kept by the list."""
    t = w.tmproot
    old_plain, old_file = _file(t / "old_plain" / "f.txt"), _file(t / "old_file.txt")
    kept_dir, kept_file = _file(t / "kept_dir" / "f.txt"), _file(t / "kept_file.txt")
    parent = _file(t / "parent_of_kept" / "sub" / "keepme.txt")
    _file(t / "parent_of_kept" / "other.txt")
    w.age(3, t / "old_plain", old_file, t / "kept_dir", kept_file, t / "parent_of_kept")
    logs = w.p("logs")
    old_log = _file(logs / "old.log")
    kept_logs = _file(logs / "kept_logs" / "a.log"), _file(logs / "kept_logs" / "deep" / "b.log")
    single = _file(logs / "single.log")
    keepdeep = _file(logs / "keepdeep" / "x" / "y.log")
    free_deep = _file(logs / "keepdeep" / "z" / "free.log")
    w.age(45, logs)
    rp = w.p("reports")
    pk, data_pq, order_lines = _file(rp / "exp1" / "package" / "p.txt"), _file(rp / "exp1" / "data.parquet"), _file(rp / "exp1" / "order_lines_2025.txt")
    kept_exp = _file(rp / "exp3" / "package" / "p.txt"), _file(rp / "exp3" / "data.parquet")
    dep_old = _file(w.temp / "DemandForecast-deploy-20261101-000000" / "pkg.zip")
    dep_kept = _file(w.temp / "DemandForecast-deploy-20261102-000000" / "pkg.zip")
    w.age(3, w.temp / "DemandForecast-deploy-20261101-000000", w.temp / "DemandForecast-deploy-20261102-000000")
    dist = w.p("dist")
    pkg_old = _file(dist / "DemandForecast-1.4.5-win64-portable.zip")
    pkg_kept, pkg_kept_sha = _file(dist / "DemandForecast-1.4.4-win64-portable.zip"), _file(dist / "DemandForecast-1.4.4-win64-portable.zip.sha256")
    return dict(old_plain=old_plain, old_file=old_file, kept_dir=kept_dir, kept_file=kept_file, parent=parent, old_log=old_log,
                kept_logs=kept_logs, single=single, keepdeep=keepdeep, free_deep=free_deep, pk=pk, data_pq=data_pq,
                order_lines=order_lines, kept_exp=kept_exp, dep_old=dep_old, dep_kept=dep_kept, pkg_old=pkg_old,
                pkg_kept=pkg_kept, pkg_kept_sha=pkg_kept_sha)


def _plain_keep(w: World) -> list[str]:
    t = w.tmproot
    return ["# test list (header)", "",
            f"{t / 'kept_dir'}                         # case 1: kept folder, exact path; 18/11/2026",
            f"{t / 'kept_file.txt'}",
            f"{t / 'parent_of_kept' / 'sub' / 'keepme.txt'}   # case 3: the candidate parent_of_kept CONTAINS this",
            r"logs\kept_logs                           # case 2: relative to the project; inside a kept folder",
            r"logs\single.log",
            r"logs\keepdeep\x                          # case 2: file two levels inside",
            r"reports\exp1\order_lines_2025.txt        # a single kept file next to a candidate",
            r"reports\exp3",
            f"{w.temp / 'DemandForecast-deploy-20261102-000000'}",
            r"dist\DemandForecast-1.4.4*               # pattern: zip + .sha256"]


def test_kept_inside_and_containing_entries_are_blocked_plan_and_apply(w: World):
    f = _build_plain_world(w)
    w.write_keep(_plain_keep(w))
    keep_lines = _plain_keep(w)
    groups = "tmp,logs,reports,deploy_temp,dist_versions"
    want = {"tmp": {_n(w.tmproot / "old_plain"), _n(f["old_file"])}, "logs": {_n(f["old_log"]), _n(f["free_deep"])},
            "reports": {_n(f["data_pq"])}, "deploy_temp": {_n(f["dep_old"].parent)}, "dist_versions": {_n(f["pkg_old"])}}
    blocked_want = {                                         # path -> text fragment of the matching entry
        w.tmproot / "kept_dir": "kept_dir", f["kept_file"]: "kept_file.txt", w.tmproot / "parent_of_kept": "keepme.txt",
        f["kept_logs"][0]: r"logs\kept_logs", f["kept_logs"][1]: r"logs\kept_logs", f["single"]: r"logs\single.log",
        f["keepdeep"]: r"logs\keepdeep\x", f["order_lines"]: "order_lines_2025.txt",
        f["kept_exp"][1]: r"reports\exp3", f["dep_kept"].parent: "DemandForecast-deploy-20261102-000000",
        f["pkg_kept"]: r"dist\DemandForecast-1.4.4*", f["pkg_kept_sha"]: r"dist\DemandForecast-1.4.4*"}

    code, out, rep = w.run(groups)                           # plan: nothing deleted
    assert code == 0, out
    assert rep["mode"] == "DRY_RUN" and rep["keep_list"]["ok"] is True
    assert rep["keep_list"]["entries"] == sum(1 for ln in keep_lines if ln.strip() and not ln.startswith("#"))
    for g, s in want.items():
        assert _cands(rep, g) == s, (g, _cands(rep, g))
    blocked = _blocked(rep)
    for path, frag in blocked_want.items():
        assert _n(path) in blocked, (path, sorted(blocked))
        assert frag.lower() in blocked[_n(path)]["entry"].lower(), (path, blocked[_n(path)])
        assert blocked[_n(path)]["line"] >= 1
        # the printed KEEP_LIST line names the path and the matched entry
        line = next((ln for ln in out.splitlines() if ln.startswith("KEEP_LIST ") and str(path).lower() in ln.lower()), None)
        assert line and "entry '" in line and "keep list line" in line, (path, out)
    # reasons of the three kinds of match
    assert "is a kept path" in blocked[_n(w.tmproot / "kept_dir")]["how"]
    assert "contains kept" in blocked[_n(w.tmproot / "parent_of_kept")]["how"]
    assert "inside kept" in blocked[_n(f["kept_logs"][1])]["how"] or "inside kept" in blocked[_n(f["keepdeep"])]["how"]
    # blocked paths recorded in the group skip list with the KEEP_LIST reason
    sk = {_n(s["path"]): s["reason"] for s in _list(_groups(rep)["tmp"]["skipped"])}
    assert sk[_n(w.tmproot / "kept_dir")].startswith("KEEP_LIST:")
    # plan table: blocked count next to the to-delete count
    total = sum(len(s) for s in want.values())
    assert rep["totals"]["candidate_count"] == total and rep["keep_list"]["blocked_count"] == len(blocked_want)
    assert f"blocked by the keep list: {len(blocked_want)}" in out and f"se xoa / to delete: {total}" in out
    assert "MUC BI KEEP_LIST CHAN" in out
    assert rep["totals"]["deleted_count"] == 0
    for v in f.values():
        for p in (v if isinstance(v, tuple) else (v,)):
            assert p.exists(), p

    code, out, rep = w.run(groups, apply=True)               # apply: exactly the candidates go
    assert code == 0, out
    assert rep["mode"] == "APPLY" and rep["keep_list"]["blocked_count"] == len(blocked_want)
    assert rep["totals"]["deleted_count"] == total, (rep["totals"], out)
    # dist_versions deletes its package; the other files are the candidates themselves
    _gone(w.tmproot / "old_plain", f["old_file"], f["old_log"], f["free_deep"], f["data_pq"], f["dep_old"].parent, f["pkg_old"])
    _alive(w.tmproot / "kept_dir" / "f.txt", f["kept_file"], f["parent"], w.tmproot / "parent_of_kept" / "other.txt",
           *f["kept_logs"], f["single"], f["keepdeep"], f["order_lines"], f["pk"], *f["kept_exp"], f["dep_kept"],
           f["pkg_kept"], f["pkg_kept_sha"])
    assert "MUC BI KEEP_LIST CHAN" in out and f"candidates: {total}" in out


# ------------------------------------------------------------------ case 4: wildcards


def test_wildcards_match_names_and_ancestors_and_parents_of_the_pattern_folder(w: World):
    t = w.tmproot
    a, b = _file(t / "wild_a" / "f.txt"), _file(t / "wild_b.txt")
    q1, q10 = _file(t / "q1" / "f.txt"), _file(t / "q10" / "f.txt")
    lit, lit_free = _file(t / "lit[1]_x" / "f.txt"), _file(t / "lit1_x" / "f.txt")
    case, case_free = _file(t / "casepat_1" / "f.txt"), _file(t / "other_casepat_1" / "f.txt")
    parent2 = _file(t / "parent2" / "x" / "f.txt")
    plain = _file(t / "plain" / "f.txt")
    w.age(3, t / "wild_a", b, t / "q1", t / "q10", t / "lit[1]_x", t / "lit1_x", t / "casepat_1", t / "other_casepat_1",
          t / "parent2", t / "plain")
    logs = w.p("logs")
    in_anc = _file(logs / "sub2" / "deep" / "a.log")                 # parent sub2 matches logs\sub?
    free = _file(logs / "sub22" / "a.log")                           # sub22 does not match sub?
    star = _file(logs / "arch" / "2026" / "n.log")                   # arch\* matches 2026 (a parent folder)
    w.age(45, logs)
    w.write_keep(["# patterns", f"{t}\\wild_*", f"{t}\\q?", f"{t}\\lit[1]_*", str(t).upper() + "\\CASEPAT_*",
                  f"{t}\\parent2\\keep_*", r"logs\sub?", r"logs/arch/*"], bom=False, crlf=False)
    code, out, rep = w.run("tmp,logs", apply=True)
    assert code == 0, out
    assert rep["keep_list"]["ok"] and rep["keep_list"]["entries"] == 7
    assert _cands(rep, "tmp") == {_n(t / "q10"), _n(t / "lit1_x"), _n(t / "other_casepat_1"), _n(t / "plain")}, _cands(rep, "tmp")
    assert _cands(rep, "logs") == {_n(free)}
    bl = _blocked(rep)
    for p, how in ((t / "wild_a", "matches the pattern"), (t / "wild_b.txt", "matches the pattern"), (t / "q1", "matches the pattern"),
                   (t / "lit[1]_x", "matches the pattern"), (t / "casepat_1", "matches the pattern"),
                   (t / "parent2", "contains"), (in_anc, "inside"), (star, "matches the pattern")):   # '*' also crosses '\'
        assert _n(p) in bl, (p, sorted(bl))
        assert how in bl[_n(p)]["how"], (p, bl[_n(p)])
    _alive(a, b, q1, lit, case, parent2, in_anc, star)
    _gone(q10.parent, lit_free.parent, case_free.parent, plain.parent, free)


# ------------------------------------------------------------------ case 6: path forms


def test_case_slash_trailing_backslash_relative_and_dot_forms_match(w: World):
    t = w.tmproot
    names = ["up_case", "fwd_slash", "trail", "rel_dots", "abs_dots", "with space", "hash#dir", "thu_muc_d\u1ea5u", "plain"]
    for n in names:
        _file(t / n / "f.txt")
    w.age(3, *(t / n for n in names))
    w.write_keep([
        "# forms",
        str(t / "up_case").upper() + "        # upper case",
        str(t / "fwd_slash").replace("\\", "/") + "      # forward slashes",
        str(t / "trail") + "\\",
        r"..\tmproot\.\x\..\rel_dots                # relative to the project, . and ..",
        f"{t}\\.\\sub\\..\\abs_dots",
        f"{t}\\with space  # a blank in the name and a comment",
        f"{t}\\hash#dir",
        f"{t}\\thu_muc_d\u1ea5u",
    ])
    code, out, rep = w.run("tmp", apply=True)
    assert code == 0, out
    assert _cands(rep, "tmp") == {_n(t / "plain")}, (_cands(rep, "tmp"), sorted(_blocked(rep)))
    assert rep["keep_list"]["blocked_count"] == len(names) - 1
    _gone(t / "plain")
    _alive(*(t / n / "f.txt" for n in names if n != "plain"))


def test_short_8dot3_form_of_a_kept_folder_matches(w: World):
    d = w.tmproot / "eightdot3_directory_long_name"
    _file(d / "f.txt")
    plain = _file(w.tmproot / "plain" / "f.txt")
    short = _short(d)
    if short is None:
        pytest.skip("8.3 short names are not available on this volume")
    w.age(3, d, w.tmproot / "plain")
    w.write_keep([short + "   # 8.3 form"])
    code, out, rep = w.run("tmp", apply=True)
    assert code == 0, out
    assert _cands(rep, "tmp") == {_n(w.tmproot / "plain")} and _n(d) in _blocked(rep)
    assert (d / "f.txt").is_file() and not plain.exists()


# ------------------------------------------------------------------ case 6: links


def test_junction_and_symlink_never_open_a_way_around_the_keep_list(w: World):
    t, o = w.tmproot, w.outside
    # (a) junctions inside the cleaned folder: never followed; their targets (one kept, one not) stay
    kept_target = _file(o / "kept_target" / "f.txt")
    free_target = _file(o / "free_target" / "f.txt")
    plain = _file(t / "plain" / "f.txt")
    # (b) the keep entry is written through a junction (and the junction itself is an entry): the real folder is kept
    real = w.p("logs") / "realdir"
    via_child = _file(real / "a" / "old.log")                          # kept through junction \a
    via_self = _file(w.p("logs") / "realdir2" / "x.log")               # kept through the junction itself
    free_log = _file(real / "b" / "old2.log")
    prot = _file(o / "prot.txt")
    w.age(3, plain.parent)
    w.age(45, w.p("logs"))
    jl_kept = _junction(t / "jl_to_kept", kept_target.parent)
    jl_free = _junction(t / "jl_free", free_target.parent)
    keepviews = _junction(w.p("keepviews"), real)
    realdir2_link = _junction(w.p("keepviews2"), real.parent / "realdir2")
    w.write_keep(["# links", str(kept_target.parent), str(prot), str(keepviews / "a"), str(realdir2_link)])
    code, out, rep = w.run("tmp,logs", apply=True)
    assert code == 0, out
    assert _cands(rep, "tmp") == {_n(plain.parent)}
    assert _cands(rep, "logs") == {_n(free_log)}, _cands(rep, "logs")
    bl = _blocked(rep)
    assert _n(via_child) in bl and "inside kept" in bl[_n(via_child)]["how"], sorted(bl)
    assert _n(via_self) in bl, sorted(bl)
    _alive(kept_target, free_target, prot, via_child, via_self)
    _gone(plain.parent, free_log)
    for j in (jl_kept, jl_free, keepviews, realdir2_link):
        assert os.path.lexists(j) and j.is_junction(), j
    sk = {_n(s["path"]): s["reason"] for s in _list(_groups(rep)["tmp"]["skipped"])}
    assert "reparse point" in sk[_n(jl_kept)] and "reparse point" in sk[_n(jl_free)]


def test_symlink_to_a_kept_file_is_not_followed_or_deleted(w: World):
    t, o = w.tmproot, w.outside
    prot, free = _file(o / "prot.txt"), _file(o / "free.txt")
    plain = _file(t / "plain" / "f.txt")
    w.age(3, plain.parent)
    try:
        os.symlink(prot, t / "sl_to_prot.txt")
        os.symlink(free, t / "sl_to_free.txt")
    except OSError:
        pytest.skip("symlinks cannot be created here (no privilege); not checked")
    w.write_keep([str(prot)])
    code, out, rep = w.run("tmp", apply=True)
    assert code == 0, out
    assert _cands(rep, "tmp") == {_n(plain.parent)}
    assert prot.is_file() and free.is_file() and os.path.islink(t / "sl_to_prot.txt") and os.path.islink(t / "sl_to_free.txt")


# ------------------------------------------------------------------ case 5: keep list missing / empty / bad line


def _fail_world(w: World) -> list[Path]:
    t = w.tmproot
    cands = [_file(t / "old_plain" / "f.txt"), _file(t / "old_file.txt")]
    w.age(3, t / "old_plain", cands[1])
    log = _file(w.p("logs") / "old.log")
    w.age(45, w.p("logs"))
    return cands + [log]


@pytest.mark.parametrize("variant", ["missing", "empty", "bad_char", "drive_relative", "no_drive", "colon", "dots_after_wildcard"])
def test_unusable_keep_list_deletes_nothing_exit_1_one_notice(w: World, variant: str):
    files = _fail_world(w)
    w.fake_python()
    good = "reports\\whatever"
    if variant == "missing":
        pass
    elif variant == "empty":
        w.write_keep(["# only comments", "   ", "", "# another"])
    else:
        bad = {"bad_char": "reports\\a|b", "drive_relative": "C:foo", "no_drive": "\\nodrive\\x", "colon": "reports\\a:b",
               "dots_after_wildcard": "reports\\*\\..\\x"}[variant]
        w.write_keep(["# list", good, bad + "   # a bad line"])
    # plan: exit 1, table printed, still nothing deleted, no notice
    code, out, rep = w.run("tmp,logs")
    assert code == 1, out
    assert "MUC BI KEEP_LIST CHAN" in out and "KEEP_LIST ERROR" in out and "NOT USABLE" in out
    assert rep["keep_list"]["ok"] is False and rep["keep_list"]["error"], rep["keep_list"]
    assert rep["exit_code"] == 1 and _cands(rep, "tmp") == set() and _cands(rep, "logs") == set()
    assert rep["keep_list"]["blocked_count"] >= 3                     # every candidate counts as blocked
    assert w.notices() == []
    _alive(*files)
    # apply: nothing deleted, exit 1, exactly ONE notice (status text only, no path)
    code, out, rep = w.run("tmp,logs", apply=True)
    assert code == 1, out
    assert rep["totals"]["deleted_count"] == 0
    _alive(*files)
    assert not list(w.p("logs").glob("logs-archive-*.zip"))
    calls = w.notices()
    assert len(calls) == 1, calls
    assert "KEEP_LIST" in calls[0] and "--priority high" in calls[0]
    assert str(w.root) not in calls[0]
    assert rep["keep_list"]["notified"] is True and "sent once" in out
    if variant in ("bad_char", "drive_relative", "no_drive", "colon", "dots_after_wildcard"):
        assert "line 3" in rep["keep_list"]["error"], rep["keep_list"]["error"]


def test_keep_list_in_default_location_is_used_without_the_parameter(w: World):
    t = w.tmproot
    kept, plain = _file(t / "kept" / "f.txt"), _file(t / "plain" / "f.txt")
    w.age(3, t / "kept", t / "plain")
    w.write_keep([f"{t}\\kept"])                                       # <project>\docs\quy-tac\keep_list.txt
    code, out, rep = w.run("tmp", apply=True, keep=None)
    assert code == 0, out
    assert _n(rep["keep_list"]["file"]) == _n(w.keep_file)
    assert _cands(rep, "tmp") == {_n(plain.parent)}
    assert kept.is_file() and not plain.exists()
    # no keep list at the default location and no parameter: fail-closed
    w.keep_file.unlink()
    plain2 = _file(t / "plain2" / "f.txt")
    w.age(3, t / "plain2")
    code, out, rep = w.run("tmp", apply=True, keep=None)
    assert code == 1 and plain2.is_file() and "keep list not found" in out


def test_no_notice_when_the_keep_list_is_usable(w: World):
    files = _fail_world(w)
    w.fake_python()
    w.write_keep(["reports\\whatever"])
    code, out, rep = w.run("tmp,logs", apply=True)
    assert code == 0, out
    assert w.notices() == [] and rep["keep_list"]["notified"] is False
    _gone(files[0].parent, files[1], files[2])


def test_missing_python_for_the_notice_is_recorded_not_raised(w: World):
    files = _fail_world(w)                                           # no .venv in the fake project
    code, out, rep = w.run("tmp,logs", apply=True)
    assert code == 1, out
    assert w.notices() == [] and rep["keep_list"]["notified"] is False
    assert "notice not sent" in rep["keep_list"]["notify_note"]
    _alive(*files)


# ------------------------------------------------------------------ dist (prune-artifacts.ps1) stays stopped


# A stand-in for scripts\prune-artifacts.ps1 with the same output format as the real one (read from it): DELETE rows
# "<action,-6> <MB,10:N1> MB  <path relative to the project>  - <reason>" and the final "Dry run: nothing deleted." line
# without -Apply; with -Apply it deletes its DELETE rows (and prints "deleted <path>"). It records every call in
# <project>\prune_calls.txt ("apply=True|False") and reads switches from <project>\prune_mode.txt ("key=value" lines):
#   extra_from_dry=<n>  extra_row=<rel>  the <n>th DRY call (1 based, over the whole test) lists <rel> as one more DELETE row
#   no_dry_line=1                        the dry run prints no "Dry run: nothing deleted." line
#   omit_from_dry=<n>  omit_row=<rel>    the <n>th DRY call and later ones do not list <rel>
#   bad_row_from_dry=<n>                 the <n>th DRY call and later ones print a DELETE row in another format
#   apply_also_deletes=<rel>             -Apply also deletes <rel>, which no DELETE row names
_STUB_PRUNE = (
    "param([string[]]$Keep = @(), [switch]$Apply)\n"
    "$proj = Split-Path -Parent $PSScriptRoot\n"
    "$calls = Join-Path $proj 'prune_calls.txt'\n"
    "$nDry = 0\n"
    "if (Test-Path -LiteralPath $calls) { $nDry = @(Get-Content -LiteralPath $calls | Where-Object { $_ -eq 'apply=False' }).Count }\n"
    "Add-Content -LiteralPath $calls -Value \"apply=$Apply\"\n"
    "$mode = @{}\n"
    "$mf = Join-Path $proj 'prune_mode.txt'\n"
    "if (Test-Path -LiteralPath $mf) { foreach ($l in Get-Content -LiteralPath $mf) { $k, $v = $l.Split('=', 2); $mode[$k] = $v } }\n"
    "$rows = @('dist\\a.zip', 'dist\\b.zip', 'dist\\DemandForecast-1.4.5-win64-portable.zip')\n"
    "if (-not $Apply -and $mode.ContainsKey('extra_from_dry') -and ($nDry + 1) -ge [int]$mode['extra_from_dry']) { $rows += $mode['extra_row'] }\n"
    "if (-not $Apply -and $mode.ContainsKey('omit_from_dry') -and ($nDry + 1) -ge [int]$mode['omit_from_dry']) { $rows = @($rows | Where-Object { $_ -ne $mode['omit_row'] }) }\n"
    "$rows = @($rows | Where-Object { Test-Path -LiteralPath (Join-Path $proj $_) })\n"
    "if (-not $Apply -and $mode.ContainsKey('bad_row_from_dry') -and ($nDry + 1) -ge [int]$mode['bad_row_from_dry']) { Write-Host 'DELETE dist/z.zip old' }\n"
    "foreach ($r in $rows) { Write-Host ('{0,-6} {1,10:N1} MB  {2}  - {3}' -f 'DELETE', 1, $r, 'old package') }\n"
    "Write-Host ('To free: {0:N1} MB' -f $rows.Count)\n"
    "if (-not $Apply) {\n"
    "    if (-not $mode.ContainsKey('no_dry_line')) { Write-Host 'Dry run: nothing deleted. Re-run with -Apply to delete the DELETE rows.' }\n"
    "    return\n"
    "}\n"
    "foreach ($r in $rows) { Remove-Item -LiteralPath (Join-Path $proj $r) -Recurse -Force -Confirm:$false; Write-Host \"deleted $r\" }\n"
    "if ($mode.ContainsKey('apply_also_deletes')) { Remove-Item -LiteralPath (Join-Path $proj $mode['apply_also_deletes']) -Force -Confirm:$false }\n")


def _dist_world(w: World) -> tuple[Path, Path]:
    (w.proj / "scripts" / "prune-artifacts.ps1").write_text(_STUB_PRUNE, encoding="ascii")
    return _file(w.p("dist") / "a.zip"), _file(w.p("dist") / "b.zip")


def _prune_calls(w: World) -> list[str]:
    f = w.proj / "prune_calls.txt"
    return f.read_text(encoding="utf-8-sig").split() if f.exists() else []


def test_prune_artifacts_apply_does_not_run_when_the_keep_list_holds_a_plan_entry(w: World):
    a, b = _dist_world(w)
    w.write_keep([r"dist\b.zip    # kept"])
    code, out, rep = w.run("dist", apply=True, extra=["-IncludeDist", "-DistKeep", "1.4.14"])
    assert code == 1, out
    assert "apply=True" not in _prune_calls(w) and _prune_calls(w), _prune_calls(w)     # the plan ran, the delete did not
    g = _groups(rep)["dist"]
    assert any("not run: KEEP_LIST keeps an entry" in e for e in _list(g["errors"])), g["errors"]
    assert _cands(rep, "dist") == {_n(a)} and _n(b) in _blocked(rep)
    assert a.is_file() and b.is_file()


def test_prune_artifacts_apply_does_not_run_when_the_keep_list_is_missing(w: World):
    a, b = _dist_world(w)
    code, out, rep = w.run("dist", apply=True, extra=["-IncludeDist", "-DistKeep", "1.4.14"])
    assert code == 1, out
    assert "apply=True" not in _prune_calls(w)
    assert any("not usable" in e for e in _list(_groups(rep)["dist"]["errors"]))
    assert a.is_file() and b.is_file()


def test_prune_artifacts_apply_runs_when_the_keep_list_holds_no_plan_entry(w: World):
    _dist_world(w)
    w.write_keep([r"dist\other.zip"])
    code, out, rep = w.run("dist", apply=True, extra=["-IncludeDist", "-DistKeep", "1.4.14"])
    assert code == 0, out
    assert "apply=True" in _prune_calls(w)
    assert rep["keep_list"]["blocked_count"] == 0


# ------------------------------------------------------------------ case 7: claude_temp sessions


def test_claude_temp_session_in_the_keep_list_is_not_deleted_others_are(w: World):
    sid_keep = "145cefda-0000-4000-8000-000000000001"
    sid_inner = "85d15b29-0000-4000-8000-000000000002"
    sid_pat = "9a9a9a9a-0000-4000-8000-000000000003"
    sid_old = "aaaaaaaa-0000-4000-8000-000000000004"
    proj_dir = w.claude / "projx"
    for sid in (sid_keep, sid_inner, sid_pat, sid_old):
        _file(proj_dir / sid / "scratchpad" / "g1" / "db.txt")
        _file(proj_dir / sid / "a.txt")
    w.age(2, *(proj_dir / s for s in (sid_keep, sid_inner, sid_pat, sid_old)))
    w.write_keep(["# sessions",
                  str(proj_dir / sid_keep) + "      # 145cefda: the whole session folder (exact)",
                  str(proj_dir / sid_inner / "scratchpad" / "g1") + "     # an inner folder: the session CONTAINS it",
                  str(proj_dir / "9a9a9a9a-*")])
    code, out, rep = w.run("claude_temp")
    assert code == 0, out
    assert _cands(rep, "claude_temp") == {_n(proj_dir / sid_old)}, _cands(rep, "claude_temp")
    bl = _blocked(rep)
    for sid in (sid_keep, sid_inner, sid_pat):
        assert _n(proj_dir / sid) in bl, (sid, sorted(bl))
    code, out, rep = w.run("claude_temp", apply=True)
    assert code == 0, out
    _gone(proj_dir / sid_old)
    _alive(proj_dir / sid_keep / "a.txt", proj_dir / sid_inner / "scratchpad" / "g1" / "db.txt", proj_dir / sid_pat / "a.txt")
    assert rep["totals"]["deleted_count"] == 1


def test_claude_temp_unusable_keep_list_deletes_no_session(w: World):
    sid = "aaaaaaaa-0000-4000-8000-000000000004"
    _file(w.claude / "projx" / sid / "a.txt")
    w.age(2, w.claude / "projx" / sid)
    code, out, rep = w.run("claude_temp", apply=True)               # no keep list at all
    assert code == 1, out
    assert (w.claude / "projx" / sid / "a.txt").is_file() and rep["totals"]["deleted_count"] == 0


# ------------------------------------------------------------------ case 8: backups


def _backup_world(w: World) -> dict:
    bk = w.p("backups")
    z = {}
    for tag, days in (("z1", 100), ("z2", 90), ("z3", 80)):
        t = NOW - timedelta(days=days)
        zip_ = _file(bk / f"backup-{_stamp(t)}-manual.zip")
        sha = _file(Path(f"{zip_}.sha256"), b"ab")
        cfg = _file(bk / f"config-{_stamp(t + timedelta(minutes=1))}-manual.json", b"{}")
        z[tag] = (zip_, sha, cfg)
    z["recent"] = (_file(bk / f"backup-{_stamp(NOW - timedelta(days=1))}-manual.zip"),)
    z["notes"] = (_file(bk / "notes.txt"),)
    return z


def test_kept_backup_zip_keeps_its_sha256_and_config_others_follow_the_old_rule(w: World):
    z = _backup_world(w)
    w.write_keep(["# backups", str(z["z1"][0]) + "    # exact zip"])
    code, out, rep = w.run("backups")
    assert code == 0, out
    want = {_n(p) for tag in ("z2", "z3") for p in z[tag]}
    assert _cands(rep, "backups") == want, _cands(rep, "backups")
    assert any(k["reason"] == "KEEP_LIST" for k in _list(_groups(rep)["backups"]["kept"]))
    assert _n(z["z1"][0]) in _blocked(rep)
    code, out, rep = w.run("backups", apply=True)
    assert code == 0, out
    _gone(*z["z2"], *z["z3"])
    _alive(*z["z1"], *z["recent"], *z["notes"])
    assert rep["totals"]["deleted_count"] == 6

    # a pattern that names zip and sha256 together (as the owner's list does): the config copy stays too
    t4 = NOW - timedelta(days=70)
    w3 = _file(w.p("backups") / f"backup-{_stamp(t4)}-manual.zip")
    sha3 = _file(Path(f"{w3}.sha256"), b"ab")
    cfg3 = _file(w.p("backups") / f"config-{_stamp(t4 + timedelta(minutes=1))}-manual.json", b"{}")
    w.write_keep([str(w.p("backups") / w3.name) + "*"])
    code, out, rep = w.run("backups", apply=True)
    assert code == 0, out
    assert _cands(rep, "backups") == {_n(z["z1"][0]), _n(z["z1"][1]), _n(z["z1"][2])}, _cands(rep, "backups")
    _alive(w3, sha3, cfg3)
    _gone(*z["z1"])


# ------------------------------------------------------------------ case 9: no regression


def test_unrelated_keep_list_changes_nothing_old_rules_and_exit_codes_hold(w: World):
    f = _build_plain_world(w)
    z = _backup_world(w)
    w.write_keep(["# nothing here matches", r"reports\no_such_folder", f"{w.root}\\nowhere"])
    groups = "tmp,logs,reports,deploy_temp,dist_versions,backups"
    code, out, rep = w.run(groups)
    assert code == 0, out
    want_tmp = {_n(w.tmproot / n) for n in ("old_plain", "kept_dir", "parent_of_kept")} | {_n(w.tmproot / n) for n in ("old_file.txt", "kept_file.txt")}
    assert _cands(rep, "tmp") == want_tmp
    assert _cands(rep, "logs") == {_n(p) for p in (f["old_log"], f["single"], f["keepdeep"], f["free_deep"], *f["kept_logs"])}
    assert _cands(rep, "reports") == {_n(f["data_pq"]), _n(f["order_lines"]), _n(f["kept_exp"][1])}
    assert _cands(rep, "deploy_temp") == {_n(f["dep_old"].parent), _n(f["dep_kept"].parent)}
    assert _cands(rep, "dist_versions") == {_n(f["pkg_old"]), _n(f["pkg_kept"]), _n(f["pkg_kept_sha"])}
    assert _cands(rep, "backups") == {_n(p) for tag in ("z1", "z2", "z3") for p in z[tag]}
    assert rep["keep_list"]["blocked_count"] == 0 and rep["keep_list"]["ok"] is True
    total = rep["totals"]["candidate_count"]
    assert "MUC BI KEEP_LIST CHAN" in out and "blocked by the keep list: 0" in out and f"se xoa / to delete: {total}" in out
    code, out, rep = w.run(groups, apply=True)
    assert code == 0, out
    assert rep["totals"]["deleted_count"] == total, (rep["totals"], out)
    _gone(w.tmproot / "old_plain", w.tmproot / "kept_dir", f["old_log"], f["data_pq"], f["pkg_old"], f["dep_old"].parent, *z["z1"], *z["z2"], *z["z3"])
    _alive(*z["recent"], *z["notes"], f["pk"])


# ------------------------------------------------------------------ case 10: the owner's real list, ASCII, syntax


def _real_keep_list() -> Path | None:
    for base in (ROOT, ROOT.parents[1]):
        p = base / "docs" / "quy-tac" / "keep_list.txt"
        if p.is_file():
            return p
    return None


def test_real_keep_list_parses_without_a_bad_line(w: World):
    src = _real_keep_list()
    if src is None:
        pytest.skip("docs/quy-tac/keep_list.txt not found next to this checkout")
    raw = src.read_bytes()
    entries = []
    for line in raw.decode("utf-8-sig").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        s = re.sub(r"\s#.*$", "", s).strip().replace("/", "\\")
        entries.append(s)
        if re.match(r"^[A-Za-z]:\\", s):
            assert s.isascii(), f"absolute path not ASCII: {s!r}"
    assert len(entries) >= 30, len(entries)
    shutil.copyfile(src, w.keep_file)                                 # a copy: the real file is only read
    t = w.tmproot
    plain = _file(t / "plain" / "f.txt")
    w.age(3, t / "plain")
    code, out, rep = w.run("tmp", keep=None)                          # default location <project>\docs\quy-tac\keep_list.txt
    assert code == 0, out
    kl = rep["keep_list"]
    assert kl["ok"] is True and not kl["error"] and kl["entries"] == len(entries), kl
    assert _cands(rep, "tmp") == {_n(plain.parent)} and kl["blocked_count"] == 0
    assert "KEEP_LIST ERROR" not in out


def test_cleanup_script_is_ascii_and_parses_as_powershell(tmp_path: Path):
    data = CLEANUP.read_bytes()
    assert data.decode("ascii")                                       # raises on any non-ASCII byte
    chk = tmp_path / "parse.ps1"
    chk.write_text("$e = $null; $t = $null\n"
                   "[void][System.Management.Automation.Language.Parser]::ParseFile($args[0], [ref]$t, [ref]$e)\n"
                   "if ($e.Count) { $e | ForEach-Object { $_.Message + ' @' + $_.Extent.StartLineNumber }; exit 1 }\nexit 0\n",
                   encoding="ascii")
    p = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(chk),
                        str(CLEANUP)], capture_output=True, timeout=120)
    assert p.returncode == 0, (p.stdout + p.stderr).decode("utf-8", errors="replace")


# ================================================================== KL-8: S1 (wildcard in the middle of a pattern)
# Pattern such as tmp\*\package or d\*.zip: a candidate FOLDER that holds (at any depth) an entry matching the pattern is
# blocked (Find-PatternInTree). Fake trees only; the script copy in the fake tool folder is patched for the entry cap.


def _set_tree_max(w: World, n: int) -> None:
    """Technique: rewrite the number in `$Script:KeepTreeMax = 200000` in the COPY of the script (never the real script)."""
    p = w.tool / CLEANUP.name
    b, cnt = re.subn(rb"\$Script:KeepTreeMax = \d+", b"$Script:KeepTreeMax = %d" % n, p.read_bytes())
    assert cnt == 1
    p.write_bytes(b)


def _kept_line(out: str, path: Path) -> str:
    ln = next((x for x in out.splitlines() if x.startswith("KEEP_LIST ") and str(path).lower() in x.lower()), None)
    assert ln, (path, out)
    return ln


def test_s1_pattern_in_the_middle_blocks_folders_that_contain_a_match_and_keeps_the_rest(w: World):
    t = w.tmproot
    pk = _file(t / "exp1" / "x" / "package" / "a.txt")               # tmp\*\package  (star crosses \)
    other1 = _file(t / "exp1" / "data.csv")
    z = _file(t / "sub" / "deep" / "a.zip")                          # tmp\*.zip
    other2 = _file(t / "sub" / "b.txt")
    sp = _file(t / "with space" / "package" / "f.txt")               # a blank in the candidate name
    plain1, plain2 = _file(t / "plain" / "f.txt"), _file(t / "plain" / "y" / "z.txt")
    w.age(3, t / "exp1", t / "sub", t / "with space", t / "plain")
    w.write_keep(["# s1", f"{t}\\*\\package   # case 1", f"{t}\\*.zip   # case 2"])
    code, out, rep = w.run("tmp")                                    # plan
    assert code == 0, out
    assert _cands(rep, "tmp") == {_n(t / "plain")}, _cands(rep, "tmp")
    bl = _blocked(rep)
    for cand, hit, line in ((t / "exp1", t / "exp1" / "x" / "package", 2), (t / "sub", z, 3), (t / "with space", t / "with space" / "package", 2)):
        assert _n(cand) in bl, (cand, sorted(bl))
        assert "contains kept (pattern)" in bl[_n(cand)]["how"] and str(hit).lower() in bl[_n(cand)]["how"].lower(), bl[_n(cand)]
        assert bl[_n(cand)]["line"] == line, bl[_n(cand)]
        pl = _kept_line(out, cand)                                   # the printed line names the matching path and the keep list line
        assert "contains kept (pattern)" in pl and str(hit).lower() in pl.lower() and f"keep list line {line}" in pl, pl
    assert rep["totals"]["deleted_count"] == 0
    code, out, rep = w.run("tmp", apply=True)
    assert code == 0, out
    assert rep["totals"]["deleted_count"] == 1, (rep["totals"], out)
    _alive(pk, other1, z, other2, sp)                                # the matching entry is still there after -Apply
    _gone(plain1, plain2, t / "plain")


def test_s1_question_mark_brackets_and_blank_in_names(w: World):
    t = w.tmproot
    q_hit = _file(t / "qm" / "x" / "packXge" / "f.txt")              # ? = exactly one character
    q_miss = _file(t / "qm2" / "x" / "packXXge" / "f.txt")
    br_hit = _file(t / "br[1]" / "x" / "lit[1]" / "k.zip")           # [1] in names, written as literal [1] in the list
    br_miss = _file(t / "br2" / "x" / "lit1" / "k.zip")              # lit1 must NOT match the literal lit[1]
    w.age(3, t / "qm", t / "qm2", t / "br[1]", t / "br2")
    w.write_keep(["# s1", f"{t}\\*\\pack?ge", f"{t}\\*\\lit[1]\\*.zip"])
    code, out, rep = w.run("tmp", apply=True)
    assert code == 0, out
    assert _cands(rep, "tmp") == {_n(t / "qm2"), _n(t / "br2")}, (_cands(rep, "tmp"), sorted(_blocked(rep)))
    bl = _blocked(rep)
    assert _n(t / "qm") in bl and _n(t / "br[1]") in bl and "contains kept (pattern)" in bl[_n(t / "br[1]")]["how"]
    _alive(q_hit, br_hit)
    _gone(t / "qm2", t / "br2")


def test_s1_relative_patterns_root_pattern_and_dotdot_do_not_break(w: World):
    t = w.tmproot
    hit = _file(t / "exp1" / "x" / "package" / "a.txt")
    plain = _file(t / "plain" / "f.txt")
    z = _file(t / "ziphold" / "a.zip")                               # '*.zip' (project root pattern) covers only the project
    w.age(3, t / "exp1", t / "plain", t / "ziphold")
    w.write_keep(["# s1", r"..\tmproot\*\package   # relative to the project with .. before the wildcard", "*.zip   # root pattern"])
    code, out, rep = w.run("tmp", apply=True)
    assert code == 0 and rep["keep_list"]["ok"] is True and rep["keep_list"]["entries"] == 2, out
    bl = _blocked(rep)
    assert _n(t / "exp1") in bl and "contains kept (pattern)" in bl[_n(t / "exp1")]["how"] and bl[_n(t / "exp1")]["line"] == 2
    assert _cands(rep, "tmp") == {_n(t / "plain"), _n(t / "ziphold")}, _cands(rep, "tmp")
    _alive(hit)
    _gone(plain, z)                                                  # tmproot is outside the project: nothing compatible with '*.zip'


@pytest.mark.parametrize("group", ["claude_temp", "deploy_temp"])
def test_s1_other_groups_go_through_the_same_check(w: World, group: str):
    if group == "claude_temp":
        proj = w.claude / "projx"
        keep_c, free_c = "aaaaaaaa-0000-4000-8000-000000000011", "bbbbbbbb-0000-4000-8000-000000000012"
        hit = _file(proj / keep_c / "scratchpad" / "keep.dat")
        free_f = _file(proj / free_c / "a.txt")
        keep_dir, free_dir = proj / keep_c, proj / free_c
        pattern = f"{w.claude}\\projx\\*\\keep.dat"
    else:
        keep_dir, free_dir = w.temp / "DemandForecast-deploy-20261101-000000", w.temp / "DemandForecast-deploy-20261102-000000"
        hit, free_f = _file(keep_dir / "inner" / "keep.dat"), _file(free_dir / "pkg.zip")
        pattern = f"{w.temp}\\*\\keep.dat"
    w.age(3, keep_dir, free_dir)
    w.write_keep(["# s1", pattern])
    code, out, rep = w.run(group, apply=True)
    assert code == 0, out
    assert _cands(rep, group) == {_n(free_dir)}, (_cands(rep, group), sorted(_blocked(rep)))
    bl = _blocked(rep)
    assert _n(keep_dir) in bl and "contains kept (pattern)" in bl[_n(keep_dir)]["how"] and bl[_n(keep_dir)]["line"] == 2
    _alive(hit)
    _gone(free_f, free_dir)


def test_s1_entry_cap_fails_closed_and_only_compatible_patterns_list_the_tree(w: World):
    t = w.tmproot
    many = [_file(t / "many" / "a" / f"f{i}.txt") for i in range(1, 6)]   # 6 entries below (a + 5 files)
    edge = [_file(t / "edge" / f"{n}.txt") for n in "abc"]                # exactly 3 entries: not above the cap of 3
    small = _file(t / "small" / "f.txt")
    w.age(3, t / "many", t / "edge", t / "small")
    _set_tree_max(w, 3)
    w.write_keep(["# s1", f"{t}\\*.zip"])
    code, out, rep = w.run("tmp", apply=True)
    assert code == 0, out
    assert _cands(rep, "tmp") == {_n(t / "edge"), _n(t / "small")}, (_cands(rep, "tmp"), sorted(_blocked(rep)))
    b = _blocked(rep)[_n(t / "many")]
    assert "contains kept (pattern): fail-closed" in b["how"] and "more than 3 entries below" in b["how"], b
    _alive(*many)
    _gone(*edge, small)
    # only a pattern whose literal start is compatible with the folder lists it (cap 0: any listed folder is blocked)
    plain, other = _file(t / "plain" / "f.txt"), _file(t / "other" / "f.txt")
    w.age(3, t / "plain", t / "other")
    _set_tree_max(w, 0)
    w.write_keep(["# s1", f"{t}\\pl*\\f.zip"])                           # literal start t\pl: compatible with plain, not with other
    code, out, rep = w.run("tmp", apply=True)
    assert code == 0, out
    # many\ (kept in the first run, still there) is incompatible with t\pl* too, so it is a candidate again
    assert _cands(rep, "tmp") == {_n(t / "other"), _n(t / "many")}, (_cands(rep, "tmp"), sorted(_blocked(rep)))
    assert "more than 0 entries below" in _blocked(rep)[_n(t / "plain")]["how"]
    _alive(plain)
    _gone(other, t / "many")


def test_s1_junction_below_a_candidate_is_never_followed_nor_deleted(w: World):
    # The tmp group itself already keeps a folder that holds a reparse point; the keep-list check must not change that
    # (no listing through the junction, nothing behind it reached). The junction rules of Find-PatternInTree alone are
    # tested in test_s1_helper_functions_literal_start_cap_and_links.
    t, o = w.tmproot, w.outside
    tgt = _file(o / "tgt" / "a.zip")                                 # behind a junction: must never be reached
    tgt2 = _file(o / "tgt2" / "f.txt")
    plain = _file(t / "plain" / "f.txt")
    _file(t / "plain_j" / "f.txt")
    _file(t / "jz" / "f.txt")
    w.age(3, t / "plain", t / "plain_j", t / "jz")
    _junction(t / "plain_j" / "lnk", tgt.parent)                     # name does not match, a.zip behind it must not count
    _junction(t / "jz" / "lnk.zip", tgt2.parent)                     # the junction's own name matches *.zip
    # creating a junction re-dates its parent folder (NTFS applies it a few seconds later: with the dry run that the
    # 1.4.15 -Apply helper runs first, the script saw the new time and the folders counted as young); age them again
    w.age(3, t / "plain_j", t / "jz")
    w.write_keep(["# s1", f"{t}\\*.zip"])
    code, out, rep = w.run("tmp", apply=True)
    assert code == 0, out
    assert _cands(rep, "tmp") == {_n(t / "plain")}, (_cands(rep, "tmp"), sorted(_blocked(rep)))
    assert _n(t / "plain_j") not in _blocked(rep)                    # kept by the old rule, not "contains kept (pattern)"
    sk = {_n(s["path"]): s["reason"] for s in _list(_groups(rep)["tmp"]["skipped"])}
    assert "reparse point" in sk[_n(t / "plain_j" / "lnk")] and "reparse point" in sk[_n(t / "jz" / "lnk.zip")]
    _alive(tgt, tgt2, t / "plain_j" / "f.txt", t / "jz" / "f.txt", t / "jz" / "lnk.zip", t / "plain_j" / "lnk")
    _gone(plain)


def _deny_list(folder: Path) -> str:
    """Denies listing of <folder> to the current user on the FAKE tree; skips the test when that cannot be done."""
    user = os.environ.get("USERNAME", "")
    d = subprocess.run(["icacls", str(folder), "/deny", f"{user}:(RD)"], capture_output=True)
    if d.returncode != 0 or not user:
        pytest.skip("not checked: icacls /deny could not be applied to the fake folder here")
    try:
        list(os.scandir(folder))
    except PermissionError:
        return user
    subprocess.run(["icacls", str(folder), "/remove:d", user], capture_output=True)
    pytest.skip("not checked: the deny ACL does not stop listing the folder here")


def test_s1_unreadable_folder_is_never_deleted_by_the_script(w: World):
    # Through the whole script the tmp group already reports an unreadable candidate as an error and does not select it;
    # the fail-closed branch of Find-PatternInTree is tested directly in test_s1_unreadable_folder_fail_closed_in_the_helper.
    t = w.tmproot
    locked = _file(t / "locked" / "inner" / "p.zip")
    free = _file(t / "plain" / "f.txt")
    w.age(3, t / "locked", t / "plain")
    user = _deny_list(t / "locked")
    try:
        w.write_keep(["# s1", f"{t}\\*.zip"])
        code, out, rep = w.run("tmp", apply=True)
    finally:
        subprocess.run(["icacls", str(t / "locked"), "/remove:d", user], capture_output=True)
    assert _n(t / "locked") not in _cands(rep, "tmp") and locked.is_file()
    assert _groups(rep)["tmp"]["errors"] or _n(t / "locked") in _blocked(rep)      # reported, not silent
    _gone(free)


def test_s1_unreadable_folder_fail_closed_in_the_helper(tmp_path: Path):
    root = tmp_path.resolve() / "fn"
    _file(root / "locked" / "in" / "p.zip")
    drv = tmp_path / "fn_lock_driver.ps1"
    drv.write_text(_FN_HEAD + "$Script:KeepTreeMax = 200000\n"
                   "$r = Find-PatternInTree \"$Root\\locked\" @(\"$Root\\*.zip\")\n"
                   "$r | ConvertTo-Json -Compress\n", encoding="ascii")
    user = _deny_list(root / "locked")
    try:
        p = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(drv),
                            str(CLEANUP), str(root)], capture_output=True, timeout=120)
    finally:
        subprocess.run(["icacls", str(root / "locked"), "/remove:d", user], capture_output=True)
    out = (p.stdout + p.stderr).decode("utf-8", errors="replace")
    assert p.returncode == 0, out
    r = json.loads(out.strip().splitlines()[-1])
    assert "cannot be listed" in r["fail"], r


_FN_HEAD = r"""param($Src, $Root)
$ErrorActionPreference = 'Stop'
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Src, [ref]$null, [ref]$null)
foreach ($n in 'Get-PatternLiteral', 'Find-PatternInTree') {
    $fd = $ast.Find({ param($a) $a -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $a.Name -eq $n }, $true)
    . ([scriptblock]::Create($fd.Extent.Text))
}
"""

_FN_DRIVER = _FN_HEAD + r"""$Script:KeepTreeMax = 200000
$r = [ordered]@{}
$esc = [Management.Automation.WildcardPattern]::Escape("$Root\lit[1]")
$r.lit_dir = Get-PatternLiteral 'C:\a\b\*.zip'
$r.lit_q = Get-PatternLiteral 'C:\a\b?\x'
$r.lit_bracket_class = Get-PatternLiteral 'C:\a\[xy]\z'
$r.lit_escaped = Get-PatternLiteral 'C:\lit`[1`]\*.zip'
$r.lit_lone_backtick = Get-PatternLiteral 'C:\a`'
$r.lit_none = Get-PatternLiteral 'C:\plain'
$r.escaped_bracket = Find-PatternInTree "$Root\lit[1]" @($esc + '\*.zip')
$r.escaped_bracket_sibling = Find-PatternInTree "$Root\lit1" @($esc + '\*.zip')
$r.q_hit = Find-PatternInTree "$Root\q1" @("$Root\*\pack?ge")
$r.q_miss = Find-PatternInTree "$Root\q2" @("$Root\*\pack?ge")
$r.a_file = Find-PatternInTree "$Root\file.zip" @("$Root\*.zip")
$r.none_dir = Find-PatternInTree "$Root\many" @("$Root\*.zip")
$r.not_there = Find-PatternInTree "$Root\absent" @("$Root\*.zip")
$r.second_pattern = Find-PatternInTree "$Root\many" @("$Root\other\*.zip", "$Root\*\f3.txt")
$Script:KeepTreeMax = 0
$r.incompatible_no_listing = Find-PatternInTree "$Root\many" @("$Root\other\*.zip")
$r.compatible_listing = Find-PatternInTree "$Root\many" @("$Root\*.zip")
$r.parent_of_literal_listing = Find-PatternInTree "$Root\many" @("$Root\many\a\*.zip")
$Script:KeepTreeMax = 3
$r.cap = Find-PatternInTree "$Root\many" @("$Root\*.zip")
$Script:KeepTreeMax = 200000
$r.junction_not_followed = Find-PatternInTree "$Root\jd" @("$Root\*.zip")
$r.junction_by_name = Find-PatternInTree "$Root\jn" @("$Root\*.zip")
$r | ConvertTo-Json -Depth 4 -Compress
"""


def test_s1_helper_functions_literal_start_cap_and_links(tmp_path: Path):
    root = tmp_path.resolve() / "fn"
    _file(root / "lit[1]" / "x" / "k.zip")
    _file(root / "lit1" / "x" / "k.zip")
    _file(root / "q1" / "x" / "packXge" / "f.txt")
    _file(root / "q2" / "x" / "packXXge" / "f.txt")
    _file(root / "file.zip")
    for i in range(1, 6):
        _file(root / "many" / "a" / f"f{i}.txt")
    other = _file(root / "outside_t" / "a.zip")
    _file(root / "jd" / "f.txt")
    _file(root / "jn" / "f.txt")
    _junction(root / "jd" / "lnk", other.parent)                       # a.zip behind a junction
    _junction(root / "jn" / "lnk.zip", other.parent)                   # the junction's own name matches
    drv = tmp_path / "fn_driver.ps1"
    drv.write_text(_FN_DRIVER, encoding="ascii")
    p = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(drv),
                        str(CLEANUP), str(root)], capture_output=True, timeout=120)
    out = (p.stdout + p.stderr).decode("utf-8", errors="replace")
    assert p.returncode == 0, out
    r = json.loads(out.strip().splitlines()[-1])
    assert r["lit_dir"] == "C:\\a\\b\\" and r["lit_q"] == "C:\\a\\b" and r["lit_bracket_class"] == "C:\\a\\"
    assert r["lit_escaped"] == "C:\\lit[1]\\" and r["lit_none"] == "C:\\plain" and r["lit_lone_backtick"] == "C:\\a`"
    assert _n(r["escaped_bracket"]["path"]) == _n(root / "lit[1]" / "x" / "k.zip")
    assert r["escaped_bracket_sibling"] is None                        # [1] is literal: lit1 does not match, and it is not listed
    assert _n(r["q_hit"]["path"]) == _n(root / "q1" / "x" / "packXge") and r["q_miss"] is None
    assert r["a_file"] is None and r["not_there"] is None and r["none_dir"] is None
    assert r["second_pattern"]["path"].lower().endswith("f3.txt")
    assert r["incompatible_no_listing"] is None                         # nothing listed: cap 0 would have failed
    assert "more than 0" in r["compatible_listing"]["fail"] and "more than 0" in r["parent_of_literal_listing"]["fail"]
    assert "more than 3 entries below" in r["cap"]["fail"]
    assert r["junction_not_followed"] is None                           # a.zip behind the junction is not reached
    assert r["junction_by_name"]["path"].lower().endswith("lnk.zip")


# ================================================================== KL-8: G1 (notice status of an unusable keep list)


def _notify_rc(w: World, rc: int) -> None:
    """The fake notify.py of the fake tool folder: records its arguments, then exits with <rc>."""
    (w.tool / "runner" / "notify.py").write_text(
        "import sys\nwith open(r'%s', 'a', encoding='utf-8') as f:\n    f.write(' '.join(sys.argv[1:]) + '\\n')\nsys.exit(%d)\n" % (w.notify_log, rc),
        encoding="ascii")


def _tree_files(root: Path) -> set[str]:
    return {os.path.normcase(os.path.relpath(os.path.join(dp, f), root)) for dp, _d, fs in os.walk(root) for f in fs}


@pytest.mark.parametrize("rc", [0, 1, 3])
def test_g1_notice_status_follows_the_exit_code_of_notify(w: World, rc: int):
    files = _fail_world(w)
    w.fake_python()
    _notify_rc(w, rc)
    code, out, rep = w.run("tmp,logs", apply=True)                      # no keep list: unusable
    assert code == 1, out
    kl = rep["keep_list"]
    assert kl["ok"] is False and rep["exit_code"] == 1 and rep["totals"]["deleted_count"] == 0
    assert len(w.notices()) == 1
    _alive(*files)
    if rc == 0:
        assert kl["notice_status"] == "sent" and kl["notified"] is True and "da bao / sent once" in out
        assert kl["notify_note"] == "notify.py exit code 0"
        assert "BAO THAT BAI" not in out
    else:
        assert kl["notice_status"] == "failed" and kl["notified"] is False
        assert "BAO THAT BAI / notify FAILED" in out and "sent once" not in out
        assert f"notice not sent: notify.py exit code {rc}" in kl["notify_note"] and f"notice not sent: notify.py exit code {rc}" in out


def test_g1_missing_python_or_missing_notify_script_is_failed_with_no_call(w: World):
    files = _fail_world(w)                                              # no .venv
    code, out, rep = w.run("tmp,logs", apply=True)
    kl = rep["keep_list"]
    assert code == 1 and kl["notice_status"] == "failed" and kl["notified"] is False and w.notices() == []
    assert "not found" in kl["notify_note"] and "BAO THAT BAI / notify FAILED" in out
    # python present, runner\notify.py of the tool folder and of the project both absent
    w.fake_python()
    (w.tool / "runner" / "notify.py").unlink()
    code, out, rep = w.run("tmp,logs", apply=True)
    kl = rep["keep_list"]
    assert code == 1 and kl["notice_status"] == "failed" and w.notices() == [] and "not found" in kl["notify_note"]
    _alive(*files)


def test_g1_usable_keep_list_is_not_applicable_and_plan_mode_sends_nothing(w: World):
    files = _fail_world(w)
    w.fake_python()
    _notify_rc(w, 0)
    w.write_keep(["reports\\whatever"])
    code, out, rep = w.run("tmp,logs", apply=True)
    assert code == 0, out
    assert rep["keep_list"]["notice_status"] == "not_applicable" and rep["keep_list"]["notified"] is False
    assert w.notices() == [] and "KEEP_LIST notice" not in out
    # plan mode with an unusable list: exit 1, no notice, status stays not_applicable
    w.keep_file.unlink()
    files2 = _fail_world(w)
    code, out, rep = w.run("tmp,logs")
    assert code == 1, out
    assert rep["keep_list"]["notice_status"] == "not_applicable" and rep["keep_list"]["notified"] is False
    assert w.notices() == [] and "KEEP_LIST notice" not in out and "KEEP_LIST ERROR" in out
    _alive(*files2)


def test_g1_second_apply_run_tries_again_and_creates_no_state_file(w: World):
    files = _fail_world(w)
    w.fake_python()
    _notify_rc(w, 1)
    before = _tree_files(w.root)
    code, out, rep = w.run("tmp,logs", apply=True)
    assert code == 1 and rep["keep_list"]["notice_status"] == "failed" and len(w.notices()) == 1
    code, out, rep = w.run("tmp,logs", apply=True)                      # same unusable list, previous notice failed: tries again
    assert code == 1 and rep["keep_list"]["notice_status"] == "failed" and len(w.notices()) == 2, w.notices()
    _notify_rc(w, 0)                                                    # notify works again: the next run sends and says so
    code, out, rep = w.run("tmp,logs", apply=True)
    assert code == 1 and rep["keep_list"]["notice_status"] == "sent" and rep["keep_list"]["notified"] is True
    assert len(w.notices()) == 3
    _alive(*files)
    created = _tree_files(w.root) - before
    logdir = os.path.normcase(r"proj\logs\don_dep") + "\\"
    extra = {c for c in created if os.path.basename(c) != "notify_calls.txt" and not c.startswith(logdir)}
    assert not extra, sorted(extra)                                     # only the cleanup log / json report (+ the fake notify's own record)


# ================================================================== 1.4.15 plan lock (PLAN_HASH / KEEP_LIST_SHA256)
# -Apply needs -PlanHash and -KeepListHash equal to the values the same run computes again; -Apply reads only the
# project's own docs\quy-tac\keep_list.txt; prune-artifacts.ps1 -Apply runs only when its dry run equals the plan; a
# folder written during the run is not deleted. Fake trees only (the plan cases use the tmp group: no process other than
# the script is involved).

ACCENT = "thư_mục_dấu"                                # a folder name with letters with diacritics


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _lock_world(w: World, groups_text: str = "unrelated") -> dict[str, Path]:
    """Old tmp entries (candidates: folder, file, a folder with diacritics, keep1), a young one, a valid keep list that keeps
    nothing of them."""
    t = w.tmproot
    f = {"dir": _file(t / "old_plain" / "f.txt"), "file": _file(t / "old_file.txt"), "accent": _file(t / ACCENT / "f.txt"),
         "keep1": _file(t / "keep1" / "f.txt")}
    w.age(3, t / "old_plain", f["file"], t / ACCENT, t / "keep1")
    f["young"] = _file(t / "young.txt")                                # written now: never a candidate
    w.write_keep(["# unrelated entries: nothing the plan selects", r"reports\no_such_folder"])
    return f


def _tmp_olds(f: dict[str, Path]) -> list[Path]:
    return [f["dir"].parent, f["file"], f["accent"].parent, f["keep1"].parent]


def _reasons(rep: dict) -> list[str]:
    return _list(rep.get("apply_refused_reasons"))


def _no_delete(rep: dict, paths: list[Path]) -> None:
    assert rep["totals"]["deleted_count"] == 0, rep["totals"]
    _alive(*paths)


# ------------------------------------------------------------------ T1, H2: both hashes and the canonical text


def test_t1_dry_run_prints_both_hashes_and_the_plan_text_holds_exactly_the_hashed_bytes(w: World):
    f = _lock_world(w)
    code, out, rep = w.plan("tmp")
    assert code == 0, out
    ph, kh = _hashes(out)
    assert ph and kh, out
    # txt output, json report, the .txt report next to it
    assert rep["plan_hash"] == ph and rep["keep_list"]["sha256"] == kh
    assert rep["mode"] == "DRY_RUN" and rep["apply_gate"] == "DRY_RUN" and "apply_refused_reasons" not in rep
    json_path = [ln.strip()[len("Report: "):] for ln in out.splitlines() if ln.strip().startswith("Report: ")][-1]
    assert f"PLAN_HASH: {ph}" in Path(json_path[:-len(".json")] + ".txt").read_text(encoding="utf-8-sig").splitlines()
    assert "DRY RUN: nothing deleted" in out and "-PlanHash" in out and "-KeepListHash" in out
    # the keep list hash is the SHA-256 of the bytes of the file (BOM and CRLF included: the helper writes both)
    assert w.keep_file.read_bytes().startswith(b"\xef\xbb\xbf") and b"\r\n" in w.keep_file.read_bytes()
    assert kh == _sha(w.keep_file.read_bytes())
    # the plan text file: next to the report, byte for byte what was hashed
    pf = Path(rep["plan_text_file"])
    assert _n(pf.parent) == _n(w.proj / "logs" / "don_dep") and pf.name == Path(json_path).stem + ".plan.txt" and pf.is_file()
    raw = pf.read_bytes()
    assert _sha(raw) == ph
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw and raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    text = raw.decode("utf-8")
    assert ACCENT.lower() in text                                        # non-ASCII names are written as UTF-8, lower case
    # H2: the canonical text has every field of the run options, one line per group, then the sorted rows
    rows = sorted(["C|" + f"tmp|dir|{f['dir'].parent}".lower(), "C|" + f"tmp|file|{f['file']}".lower(),
                   "C|" + f"tmp|dir|{f['accent'].parent}".lower(), "C|" + f"tmp|dir|{f['keep1'].parent}".lower()])   # the prefix stays upper case
    want = ["v=1", "groups=tmp", "include_dist=0", "dist_keep=", "tmp_keep=", "claude_keep=", "tmp_min_age_hours=24",
            "claude_min_age_hours=24", f"project_root={w.proj}".lower(), f"tmp_root={w.tmproot}".lower(),
            f"keep_list={w.keep_file}".lower(), "group|tmp|ok", *rows]
    assert text == "\n".join(want) + "\n", text
    for forbidden in ("bytes", "age_days", "last_write", "T00:", "T1", "T2"):       # no size, no time
        assert forbidden not in text.replace("tmp_", "")


def test_t1_plan_text_carries_the_options_blocked_rows_and_other_groups(w: World):
    f = _lock_world(w)
    blocked = _file(w.tmproot / "blocked_dir" / "f.txt")
    w.age(3, blocked.parent)
    w.write_keep(["# one blocked entry", f"{w.tmproot}\\blocked_dir"])
    code, out, rep = w.plan("tmp,logs,exports", extra=["-DistKeep", "1.4.2,1.4.1", "-TmpKeep", "keep1,young.txt", "-ClaudeKeep", "AAAAAAAA",
                                                       "-TmpMinAgeHours", "7", "-ClaudeMinAgeHours", "9"])
    assert code == 0, out
    text = Path(rep["plan_text_file"]).read_bytes().decode("utf-8")
    lines = text.split("\n")
    assert lines[:11] == ["v=1", "groups=exports,logs,tmp", "include_dist=0", "dist_keep=1.4.1,1.4.2", "tmp_keep=keep1,young.txt",
                          "claude_keep=aaaaaaaa", "tmp_min_age_hours=7", "claude_min_age_hours=9", f"project_root={w.proj}".lower(),
                          f"tmp_root={w.tmproot}".lower(), f"keep_list={w.keep_file}".lower()], lines[:11]
    assert [ln for ln in lines if ln.startswith("group|")] == ["group|exports|skipped", "group|logs|ok", "group|tmp|ok"]   # no du_bao folder here
    # a candidate blocked by the keep list is a "B|" row (group|path|matched entry); it is not a "C|" row
    b_rows = [ln for ln in lines if ln.startswith("B|")]
    assert b_rows == ["B|" + f"tmp|{blocked.parent}|{w.tmproot}\\blocked_dir".lower()], b_rows      # the prefix stays upper case
    assert not any(ln.startswith("C|") and "blocked_dir" in ln for ln in lines)
    # rows are sorted (ordinal): the B row first, then the C rows
    rows = [ln for ln in lines if ln.startswith(("B|", "C|"))]
    assert rows == sorted(rows) and rows[0].startswith("B|")
    assert f["young"].is_file()


# ------------------------------------------------------------------ T2: same plan, same hash, same bytes


def _old_export_days(w: World) -> list[Path]:
    """30 recent day folders (the 30 newest stay) + two old ones (candidates), under <data>\\exports\\du_bao."""
    du = w.data / "exports" / "du_bao"
    for k in range(1, 31):
        (du / (NOW - timedelta(days=k)).strftime("%Y%m%d")).mkdir(parents=True, exist_ok=True)
    olds = []
    for k in (120, 121):
        d = du / (NOW - timedelta(days=k)).strftime("%Y%m%d")
        _file(d / "du_bao.xlsx")
        olds.append(d)
    return olds


def test_t2_two_dry_runs_of_an_unchanged_tree_give_the_same_hash_and_the_same_plan_bytes(w: World):
    f = _lock_world(w)
    olds = _old_export_days(w)
    c1, o1, r1 = w.plan("tmp,exports")
    assert c1 == 0, o1
    b1, p1 = Path(r1["plan_text_file"]).read_bytes(), _hashes(o1)
    assert {_n(c) for c in _cands(r1, "exports")} == {_n(d) for d in olds}
    time.sleep(1.2)                                                      # another report stamp: the plan holds no time
    (olds[0] / "du_bao.xlsx").write_bytes(b"y" * 5000)                   # another size and last write time: not in the plan
    c2, o2, r2 = w.plan("tmp,exports")
    assert c2 == 0, o2
    b2, p2 = Path(r2["plan_text_file"]).read_bytes(), _hashes(o2)
    assert r1["plan_text_file"] != r2["plan_text_file"]
    assert b1 == b2 and p1 == p2 and p1[0] and p1[1], (p1, p2)
    assert r1["plan_hash"] == r2["plan_hash"] == _sha(b1) and ACCENT.lower().encode("utf-8") in b1
    assert r1["keep_list"]["sha256"] == r2["keep_list"]["sha256"]
    _alive(*_tmp_olds(f), *olds)


# ------------------------------------------------------------------ T3: -Apply without a good pair of hashes


@pytest.mark.parametrize("variant", ["none", "plan_only", "keep_only", "plan_short", "plan_not_hex", "keep_long", "keep_not_hex"])
def test_t3_apply_without_valid_hashes_is_refused_exit_2_nothing_deleted(w: World, variant: str):
    f = _lock_world(w)
    code, out, plan = w.plan("tmp")
    ph, kh = _hashes(out)
    hashes = {"none": "none", "plan_only": (ph, None), "keep_only": (None, kh), "plan_short": (ph[:63], kh), "plan_not_hex": ("g" * 64, kh),
              "keep_long": (ph, kh + "0"), "keep_not_hex": (ph, "z" * 64)}[variant]
    code, out, rep = w.run("tmp", apply=True, hashes=hashes)
    assert code == 2, out
    assert rep["mode"] == "APPLY_REFUSED" and rep["apply_gate"] == "REFUSED" and rep["exit_code"] == 2
    assert "APPLY REFUSED" in out and "Nothing deleted (exit 2)" in out and "refused" in out
    assert rep["plan_hash"] == ph                                        # the plan is still computed and recorded
    why = " | ".join(_reasons(rep))
    assert _reasons(rep), rep
    if variant in ("none", "keep_only"):
        assert "-PlanHash missing" in why
    if variant in ("none", "plan_only"):
        assert "-KeepListHash missing" in why
    if variant in ("plan_short", "plan_not_hex"):
        assert "-PlanHash is not a SHA-256" in why
    if variant in ("keep_long", "keep_not_hex"):
        assert "-KeepListHash is not a SHA-256" in why
    _no_delete(rep, _tmp_olds(f))
    # every candidate of the refused run is listed as NOT deleted in the .txt report
    lines = _txt_report(out)
    assert all(any(ln.startswith("NOT deleted tmp ") and "apply refused" in ln for ln in lines) for _ in _tmp_olds(f))
    assert sum(ln.startswith("NOT deleted tmp ") for ln in lines) == 4 and not any(ln.startswith("deleted ") for ln in lines)


def _txt_report(out: str) -> list[str]:
    lines = [ln.strip()[len("Report: "):] for ln in out.splitlines() if ln.strip().startswith("Report: ")]
    return Path(lines[-1][:-len(".json")] + ".txt").read_text(encoding="utf-8-sig").splitlines()


# ------------------------------------------------------------------ T4: the right hashes (any case) delete as before


@pytest.mark.parametrize("case", ["lower", "upper", "mixed"])
def test_t4_apply_with_the_hashes_of_the_dry_run_deletes_the_plan_and_exits_0(w: World, case: str):
    f = _lock_world(w)
    code, out, plan = w.plan("tmp")
    ph, kh = _hashes(out)
    conv = {"lower": lambda x: x, "upper": str.upper, "mixed": lambda x: x[:32].upper() + x[32:]}[case]
    code, out, rep = w.run("tmp", apply=True, hashes=(conv(ph), conv(kh)))
    assert code == 0, out
    assert rep["mode"] == "APPLY" and rep["apply_gate"] == "MATCHED" and "apply_refused_reasons" not in rep
    assert rep["plan_hash"] == ph and rep["keep_list"]["sha256"] == kh and rep["exit_code"] == 0
    assert rep["totals"]["deleted_count"] == 4
    _gone(*_tmp_olds(f))
    _alive(f["young"])
    assert f"PLAN_HASH: {ph}" in out and "APPLY REFUSED" not in out


# ------------------------------------------------------------------ T5 / T6: the plan changed after the dry run


def test_t5_a_new_candidate_after_the_dry_run_refuses_the_whole_apply(w: World):
    f = _lock_world(w)
    code, out, plan = w.plan("tmp")
    ph, kh = _hashes(out)
    extra = _file(w.tmproot / "added_later.txt")
    w.age(3, extra)
    code, out, rep = w.run("tmp", apply=True, hashes=(ph, kh))
    assert code == 2, out
    assert rep["mode"] == "APPLY_REFUSED" and rep["apply_gate"] == "REFUSED"
    assert any(r.startswith("plan changed") and ph in r for r in _reasons(rep)), _reasons(rep)
    assert not any("keep_list changed" in r for r in _reasons(rep))
    assert rep["plan_hash"] != ph
    _no_delete(rep, _tmp_olds(f) + [extra])                              # not even the candidates that were in the plan


def test_t5_a_new_entry_blocked_by_the_keep_list_changes_the_plan_too(w: World):
    f = _lock_world(w)
    w.write_keep(["# keeps what is named blocked_*", f"{w.tmproot}\\blocked_*"])
    code, out, plan = w.plan("tmp")
    ph, kh = _hashes(out)
    new = _file(w.tmproot / "blocked_later.txt")                         # a "B|" row appears: the keep list itself is unchanged
    w.age(3, new)
    code, out, rep = w.run("tmp", apply=True, hashes=(ph, kh))
    assert code == 2, out
    assert any(r.startswith("plan changed") for r in _reasons(rep)) and not any("keep_list changed" in r for r in _reasons(rep))
    _no_delete(rep, _tmp_olds(f) + [new])


def test_t6_a_candidate_that_disappears_after_the_dry_run_refuses_the_whole_apply(w: World):
    f = _lock_world(w)
    code, out, plan = w.plan("tmp")
    ph, kh = _hashes(out)
    shutil.rmtree(f["dir"].parent)                                       # one planned folder is gone
    code, out, rep = w.run("tmp", apply=True, hashes=(ph, kh))
    assert code == 2, out
    assert any(r.startswith("plan changed") for r in _reasons(rep)), _reasons(rep)
    _no_delete(rep, [f["file"], f["accent"].parent, f["keep1"].parent])


# ------------------------------------------------------------------ T7: the keep list changed after the dry run


@pytest.mark.parametrize("variant", ["comment_line", "blank_line", "entry_text_changed", "now_blocks_a_candidate"])
def test_t7_a_keep_list_edited_after_the_dry_run_refuses_apply(w: World, variant: str):
    f = _lock_world(w)
    code, out, plan = w.plan("tmp")
    ph, kh = _hashes(out)
    old = w.keep_file.read_bytes()
    new = {"comment_line": old + b"# only a note, nothing else\r\n", "blank_line": old + b"\r\n",
           "entry_text_changed": old.replace(b"no_such_folder", b"no_such_folder2"),
           "now_blocks_a_candidate": old + f"{f['file']}\r\n".encode("utf-8")}[variant]
    assert new != old
    w.keep_file.write_bytes(new)
    code, out, rep = w.run("tmp", apply=True, hashes=(ph, kh))
    assert code == 2, out
    assert rep["mode"] == "APPLY_REFUSED" and rep["apply_gate"] == "REFUSED"
    why = _reasons(rep)
    assert any("keep_list changed after the plan" in r and kh in r and _sha(new) in r for r in why), why
    # only the candidates a new entry blocks also change the plan text
    assert any(r.startswith("plan changed") for r in why) == (variant == "now_blocks_a_candidate"), why
    assert rep["keep_list"]["sha256"] == _sha(new)
    _no_delete(rep, _tmp_olds(f))


# ------------------------------------------------------------------ T8: BOM / CRLF do not change the parsing, only the hash


def test_t8_keep_list_with_or_without_bom_and_with_crlf_or_lf_is_hashed_as_bytes_and_parsed_the_same(w: World):
    f = _lock_world(w)
    blocked = _file(w.tmproot / "blocked_dir" / "f.txt")
    w.age(3, blocked.parent)
    lines = ["# header with a non-ASCII word: dấu", f"{w.tmproot}\\blocked_dir   # reason 18/11/2026", r"reports\no_such_folder"]
    seen = {}
    for bom in (True, False):
        for crlf in (True, False):
            w.write_keep(lines, bom=bom, crlf=crlf)
            raw = w.keep_file.read_bytes()
            assert raw.startswith(b"\xef\xbb\xbf") == bom and (b"\r\n" in raw) == crlf
            code, out, rep = w.plan("tmp")
            assert code == 0, out
            ph, kh = _hashes(out)
            assert kh == _sha(raw) == rep["keep_list"]["sha256"], (bom, crlf)
            assert rep["keep_list"]["ok"] is True and rep["keep_list"]["entries"] == 2
            assert _cands(rep, "tmp") == {_n(p) for p in _tmp_olds(f)} and set(_blocked(rep)) == {_n(blocked.parent)}
            assert _blocked(rep)[_n(blocked.parent)]["line"] == 2                  # line numbers are the same in all four forms
            seen[(bom, crlf)] = (kh, ph)
    assert len({v[0] for v in seen.values()}) == 4                        # four different byte contents, four hashes
    assert len({v[1] for v in seen.values()}) == 1                        # the plan does not depend on them: one plan hash
    w.write_keep(lines, bom=True, crlf=False)                             # the last form: apply with the hashes of its own dry run
    code, out, plan = w.plan("tmp")
    ph, kh = _hashes(out)
    code, out, rep = w.run("tmp", apply=True, hashes=(ph, kh))
    assert code == 0, out
    assert rep["totals"]["deleted_count"] == 4 and (blocked).is_file()
    _gone(*_tmp_olds(f))


# ------------------------------------------------------------------ T9: every field of the canonical text is in the hash

_FIELDS = [
    ("include_dist", "tmp", ["-DistKeep", "1.4.1"], "tmp", ["-DistKeep", "1.4.1", "-IncludeDist"]),
    ("dist_keep", "tmp", ["-DistKeep", "1.4.1"], "tmp", ["-DistKeep", "1.4.2"]),
    ("tmp_keep", "tmp", ["-TmpKeep", "keep1"], "tmp", ["-TmpKeep", "keep1,young.txt"]),
    ("claude_keep", "tmp", ["-ClaudeKeep", "aaaaaaaa"], "tmp", ["-ClaudeKeep", "bbbbbbbb"]),
    ("tmp_min_age_hours", "tmp", ["-TmpMinAgeHours", "24"], "tmp", ["-TmpMinAgeHours", "25"]),
    ("claude_min_age_hours", "tmp", ["-ClaudeMinAgeHours", "24"], "tmp", ["-ClaudeMinAgeHours", "25"]),
    ("groups", "tmp,deploy_temp", [], "tmp", []),
]


@pytest.mark.parametrize("field", [x[0] for x in _FIELDS])
def test_t9_a_changed_option_at_apply_time_changes_the_plan_hash_and_is_refused(w: World, field: str):
    f = _lock_world(w)
    _name, g_plan, x_plan, g_apply, x_apply = next(x for x in _FIELDS if x[0] == field)
    code, out, plan = w.plan(g_plan, extra=x_plan)
    assert code == 0, out
    ph, kh = _hashes(out)
    code, out, rep = w.run(g_apply, apply=True, extra=x_apply, hashes=(ph, kh))
    assert code == 2, out
    assert rep["mode"] == "APPLY_REFUSED" and rep["apply_gate"] == "REFUSED"
    why = _reasons(rep)
    assert any(r.startswith("plan changed") for r in why) and not any("keep_list changed" in r for r in why), why
    assert re.search(r"PLAN_HASH now ([0-9a-f]{64})", " ".join(why)).group(1) != ph and rep["plan_hash"] != ph
    _no_delete(rep, [p for p in _tmp_olds(f) if p != f["keep1"].parent] if field == "tmp_keep" else _tmp_olds(f))


# ------------------------------------------------------------------ T10: -Apply reads only the project's own keep list


def test_t10_apply_with_another_keep_list_file_is_refused_before_anything_but_a_dry_run_works(w: World):
    f = _lock_world(w)
    other = w.root / "elsewhere" / "keep_list.txt"
    other.parent.mkdir(parents=True)
    shutil.copyfile(w.keep_file, other)                                  # same bytes: the PATH is what counts
    code, out, rep = w.plan("tmp", keep=str(other))                      # a dry run with it still runs and prints the hashes
    assert code == 0, out
    ph, kh = _hashes(out)
    assert ph and kh == _sha(other.read_bytes()) and _n(rep["keep_list"]["file"]) == _n(other)
    for hashes in ((ph, kh), None):
        args = w._args("tmp", True, str(other), ["-PlanHash", ph, "-KeepListHash", kh] if hashes else [])
        code, out, rep = w.exec(args, report=False)
        assert code == 2 and rep is None, out                            # refused before a report is written
        assert "-Apply: -KeepListMaster must be empty or" in out and "Nothing done" in out
        assert _n(w.keep_file) in _n(out) or "keep_list.txt" in out
        _alive(*_tmp_olds(f))
    # a relative-looking path to a copy inside the project but not the master file: refused too
    inner = w.proj / "docs" / "keep_copy.txt"
    shutil.copyfile(w.keep_file, inner)
    code, out, rep = w.exec(w._args("tmp", True, str(inner), ["-PlanHash", ph, "-KeepListHash", kh]), report=False)
    assert code == 2 and "must be empty or" in out
    _alive(*_tmp_olds(f))


@pytest.mark.parametrize("form", ["same_path", "upper_case", "dot_dot", "forward_slashes", "junction_to_the_folder"])
def test_t10_other_spellings_of_the_master_keep_list_are_accepted_with_apply(w: World, form: str):
    f = _lock_world(w)
    qt = w.proj / "docs" / "quy-tac"
    spelled = {"same_path": str(w.keep_file), "upper_case": str(w.keep_file).upper(), "dot_dot": str(qt / ".." / "quy-tac" / "keep_list.txt"),
               "forward_slashes": str(w.keep_file).replace("\\", "/"),
               "junction_to_the_folder": str(_junction(w.root / "keeplink", qt) / "keep_list.txt")}[form]
    code, out, plan = w.plan("tmp", keep=spelled)
    assert code == 0, out
    ph, kh = _hashes(out)
    code, out, rep = w.run("tmp", apply=True, keep=spelled, hashes=(ph, kh))
    assert code == 0, (form, out)
    assert rep["apply_gate"] == "MATCHED" and rep["totals"]["deleted_count"] == 4 and rep["plan_hash"] == ph
    _gone(*_tmp_olds(f))


# ------------------------------------------------------------------ T11: an unusable keep list: fail-closed as before (exit 1)


@pytest.mark.parametrize("variant", ["missing", "empty", "bad_line"])
def test_t11_unusable_keep_list_with_any_hashes_is_still_exit_1_one_notice_per_apply_nothing_deleted(w: World, variant: str):
    f = _lock_world(w)
    w.fake_python()
    if variant == "missing":
        w.keep_file.unlink()
    elif variant == "empty":
        w.write_keep(["# only comments", ""])
    else:
        w.write_keep(["# list", r"reports\ok", "C:drive-relative"])
    code, out, plan = w.plan("tmp")
    assert code == 1, out
    assert plan["apply_gate"] == "DRY_RUN" and plan["plan_hash"] == _hashes(out)[0]
    ph, kh = _hashes(out)
    assert (kh is None) == (variant == "missing")                       # a file that exists is hashed even when a line is bad
    assert w.notices() == []
    tries = ["none", ("0" * 64, "0" * 64), (ph, kh or "1" * 64)]
    for n, hashes in enumerate(tries, start=1):
        code, out, rep = w.run("tmp", apply=True, hashes=hashes)
        assert code == 1, (hashes, out)                                  # fail-closed (1), not "refused" (2)
        assert rep["mode"] == "APPLY" and rep["apply_gate"] == "KEEP_LIST_NOT_USABLE" and "apply_refused_reasons" not in rep
        assert rep["keep_list"]["ok"] is False and rep["keep_list"]["notice_status"] == "sent" and rep["exit_code"] == 1
        assert "APPLY REFUSED" not in out and "KEEP_LIST ERROR" in out
        assert len(w.notices()) == n and "KEEP_LIST" in w.notices()[-1], w.notices()      # exactly one notice per -Apply run
        _no_delete(rep, _tmp_olds(f))


def test_t11_keep_list_usable_at_the_dry_run_but_broken_at_apply_stays_fail_closed(w: World):
    f = _lock_world(w)
    w.fake_python()
    code, out, plan = w.plan("tmp")
    ph, kh = _hashes(out)
    w.write_keep(["# broken after the plan", "C:drive-relative"])
    code, out, rep = w.run("tmp", apply=True, hashes=(ph, kh))
    assert code == 1 and rep["apply_gate"] == "KEEP_LIST_NOT_USABLE" and len(w.notices()) == 1, out
    _no_delete(rep, _tmp_olds(f))


# ------------------------------------------------------------------ T12: the launcher don_dep_current.ps1

WRAPPER = ROOT / "scripts" / "ops" / "don_dep_current.ps1"

_STUB_ALL = ('param([string]$ProjectRoot = "", [switch]$Apply, [switch]$IncludeDist, [string[]]$DistKeep = @(), [string]$TmpRoot = "",\n'
             '      [string]$KeepListFile = "", [string]$ConcludedListFile = "", [string]$KeepListMaster = "", [string]$PlanHash = "",\n'
             '      [string]$KeepListHash = "")\n'
             "Set-Content -LiteralPath (Join-Path $PSScriptRoot 'args.txt') -Encoding UTF8 -Value (@($PSBoundParameters.Keys | Sort-Object |\n"
             "    ForEach-Object { \"$_=$($PSBoundParameters[$_])\" }) -join '|')\n"
             "exit 0\n")
_MARK = "Set-Content -LiteralPath (Join-Path $PSScriptRoot 'ran.txt') -Value ran\nexit 0\n"
_STUBS_WITHOUT_LOCK = {                                 # installed scripts that must NOT count as having the plan lock
    "names_only_in_a_comment": '# supports -KeepListMaster, -PlanHash and -KeepListHash (planned)\nparam([string]$ProjectRoot = "", [switch]$Apply)\n' + _MARK,
    "names_only_in_a_string": 'param([string]$ProjectRoot = "", [switch]$Apply)\n$null = \'param($KeepListMaster, $PlanHash, $KeepListHash)\'\n' + _MARK,
    "names_only_in_a_function": ('param([string]$ProjectRoot = "", [switch]$Apply)\n'
                                 'function Old { param($KeepListMaster, $PlanHash, $KeepListHash) }\n') + _MARK,
    "names_only_as_variables": 'param([string]$ProjectRoot = "", [switch]$Apply)\n$PlanHash = 1; $KeepListHash = 2; $KeepListMaster = 3\n' + _MARK,
    "two_of_three": 'param([string]$ProjectRoot = "", [switch]$Apply, [string]$KeepListMaster = "", [string]$PlanHash = "")\n' + _MARK,
    "keep_list_master_only": 'param([string]$ProjectRoot = "", [switch]$Apply, [string]$KeepListMaster = "")\n' + _MARK,
    "no_param_block": "$Apply = $true\n" + _MARK,
    "syntax_error": 'param([string]$ProjectRoot = "", [switch]$Apply, [string]$KeepListMaster = "", [string]$PlanHash = "", [string]$KeepListHash = "")\nif ( {\n',
}


class Launch:
    """The fake installation of a launcher run: installed version 1.4.14 with the given script."""

    def __init__(self, tmp_path: Path):
        self.root = tmp_path.resolve()
        self.la, self.proj, self.tmproot, self.temp = self.root / "LA", self.root / "proj", self.root / "tmproot", self.root / "TEMP"
        (self.proj / "scripts").mkdir(parents=True)
        self.temp.mkdir()
        pd = self.la / "Programs" / "DemandForecast"
        self.ops = pd / "1.4.14" / "scripts" / "ops"
        self.ops.mkdir(parents=True)
        _file(pd / "current.txt", b"1.4.14")
        (self.la / "DemandForecast").mkdir(parents=True)

    def install(self, text: str | bytes) -> Path:
        p = self.ops / "don_dep_dinh_ky.ps1"
        p.write_bytes(text if isinstance(text, bytes) else text.encode("ascii"))
        return p

    def run(self, *args: str) -> tuple[int, str]:
        env = dict(os.environ)
        env["LOCALAPPDATA"] = str(self.la)
        env["TEMP"] = env["TMP"] = str(self.temp)
        p = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER),
                            "-ProjectRoot", str(self.proj), "-TmpRoot", str(self.tmproot), *args], capture_output=True, timeout=300, env=env)
        return p.returncode, (p.stdout + p.stderr).decode("utf-8", errors="replace")


def _head_cleanup() -> bytes | None:
    """The cleanup script of the 1.4.14 release (tag v1.4.14: no KeepListMaster, no plan lock). A tag, not HEAD: once the
    plan lock is committed on this branch, HEAD has it and the old-script cases below would stop testing anything."""
    p = subprocess.run(["git", "show", "v1.4.14:scripts/ops/don_dep_dinh_ky.ps1"], cwd=ROOT, capture_output=True)
    return p.stdout if p.returncode == 0 and p.stdout else None


@pytest.fixture()
def lc(tmp_path: Path) -> Launch:
    return Launch(tmp_path)


def test_t12_an_installed_script_without_the_plan_lock_is_refused_with_apply_but_runs_as_a_dry_run(lc: Launch):
    old = _head_cleanup()
    assert old is not None, "tag v1.4.14 (the old installed script) is not available: this test must not be skipped"
    assert b"PlanHash" not in old and b"KeepListMaster" not in old, "v1.4.14:scripts/ops/don_dep_dinh_ky.ps1 is not an old script"
    lc.install(old)
    victim = _file(lc.tmproot / "old_entry" / "f.txt")                   # what the OLD script would delete with -Apply
    _set_times(lc.root, [(victim, NOW - timedelta(days=3)), (victim.parent, NOW - timedelta(days=3))])
    for extra in ([], ["-PlanHash", "a" * 64, "-KeepListHash", "b" * 64], ["-IncludeDist", "-DistKeep", "1.4.13"]):
        code, out = lc.run("-Apply", *extra)
        assert code == 2, out
        assert "-Apply refused" in out and "Nothing run" in out and "has no -KeepListMaster / -PlanHash / -KeepListHash" in out
        assert not (lc.proj / "logs" / "don_dep").exists()               # the old script did not run at all
        assert victim.is_file()
    # a dry run (no -Apply) still runs the older script: it reports, deletes nothing
    code, out = lc.run()
    assert code == 0, out
    reports = list((lc.proj / "logs" / "don_dep").glob("don_dep-*.json"))
    assert len(reports) == 1 and json.loads(reports[0].read_text(encoding="utf-8-sig"))["mode"] == "DRY_RUN"
    assert victim.is_file()


@pytest.mark.parametrize("variant", sorted(_STUBS_WITHOUT_LOCK))
def test_t12_the_parameters_of_the_installed_script_are_read_with_the_parser_not_by_text(lc: Launch, variant: str):
    lc.install(_STUBS_WITHOUT_LOCK[variant])
    code, out = lc.run("-Apply", "-PlanHash", "a" * 64, "-KeepListHash", "b" * 64)
    assert code == 2, (variant, out)
    assert "-Apply refused" in out and "Nothing run" in out, out
    assert ("cannot be parsed" in out) == (variant == "syntax_error"), out
    assert not (lc.ops / "ran.txt").exists() and not (lc.ops / "args.txt").exists()      # the script was not started


def test_t12_a_script_declaring_the_three_parameters_gets_the_hashes_and_apply(lc: Launch):
    lc.install(_STUB_ALL)
    ph, kh = "0123456789abcdef" * 4, "FEDCBA9876543210" * 4
    code, out = lc.run("-Apply", "-IncludeDist", "-DistKeep", "1.4.13", "-PlanHash", f"  {ph}  ", "-KeepListHash", kh)
    assert code == 0, out
    got = dict(kv.split("=", 1) for kv in (lc.ops / "args.txt").read_text(encoding="utf-8-sig").strip().split("|"))
    assert got["Apply"] == "True" and got["IncludeDist"] == "True" and got["DistKeep"] == "1.4.13"
    assert got["PlanHash"] == ph and got["KeepListHash"] == kh           # forwarded as given, only trimmed
    assert got["ProjectRoot"] == str(lc.proj) and got["TmpRoot"] == str(lc.tmproot) and "KeepListMaster" not in got
    # no hash given: none passed on; a dry run with hashes passes them too (the script decides what to do with them)
    code, out = lc.run("-Apply")
    assert code == 0, out
    got = dict(kv.split("=", 1) for kv in (lc.ops / "args.txt").read_text(encoding="utf-8-sig").strip().split("|"))
    assert "PlanHash" not in got and "KeepListHash" not in got and got["Apply"] == "True"
    code, out = lc.run("-PlanHash", ph)
    assert code == 0, out
    got = dict(kv.split("=", 1) for kv in (lc.ops / "args.txt").read_text(encoding="utf-8-sig").strip().split("|"))
    assert got["PlanHash"] == ph and "Apply" not in got and "KeepListHash" not in got


def test_t12_dry_run_of_a_script_without_the_lock_does_not_forward_the_hashes(lc: Launch):
    lc.install('param([string]$ProjectRoot = "", [switch]$Apply, [string]$TmpRoot = "")\n'
               "Set-Content -LiteralPath (Join-Path $PSScriptRoot 'ran.txt') -Value ran\nexit 0\n")
    code, out = lc.run("-PlanHash", "a" * 64, "-KeepListHash", "b" * 64)   # would be a parameter error if they were forwarded
    assert code == 0 and (lc.ops / "ran.txt").is_file(), out


def test_t12_the_current_script_through_the_launcher_plan_then_apply_with_the_printed_hashes(lc: Launch):
    cur = lc.install(CLEANUP.read_bytes())
    for n in ("don_dep_giu.txt", "don_dep_ket_luan.txt"):
        shutil.copyfile(CLEANUP.parent / n, lc.ops / n)
    (lc.ops / "runner").mkdir()
    (lc.proj / "docs" / "quy-tac").mkdir(parents=True)
    keep = lc.proj / "docs" / "quy-tac" / "keep_list.txt"
    keep.write_text("# nothing here matches\nreports\\no_such_folder\n", encoding="ascii")
    victim = _file(lc.tmproot / "old_entry" / "f.txt")
    _set_times(lc.root, [(victim, NOW - timedelta(days=3)), (victim.parent, NOW - timedelta(days=3))])
    assert cur.is_file()
    code, out = lc.run()
    assert code == 0, out
    ph, kh = _hashes(out)
    assert ph and kh == _sha(keep.read_bytes()) and victim.is_file()
    code, out = lc.run("-Apply")                                          # no hashes: the script itself refuses (exit 2 goes through)
    assert code == 2 and "APPLY REFUSED" in out and victim.is_file(), out
    code, out = lc.run("-Apply", "-PlanHash", ph, "-KeepListHash", kh)
    assert code == 0, out
    assert not victim.parent.exists()


# ------------------------------------------------------------------ T13, H3: a folder written during the run is not deleted


def _inject_touch(w: World) -> None:
    """Technique (as _set_tree_max): the COPY of the script in the fake tool folder writes the files named in
    $env:DF_TEST_TOUCH right after the hash check and before anything is deleted, i.e. a real write after the start of the
    run and after the plan."""
    p = w.tool / CLEANUP.name
    src = p.read_bytes()
    marker = b"if ($Apply -and -not $Refused.Count) {"
    assert src.count(marker) == 1
    p.write_bytes(src.replace(marker, b"if ($Apply -and $env:DF_TEST_TOUCH) { foreach ($tp in $env:DF_TEST_TOUCH.Split('|')) "
                                      b"{ Set-Content -LiteralPath $tp -Value 'late' } }\n" + marker))


def _h3_world(w: World, group: str, nested: bool) -> tuple[Path, Path, Path]:
    """(victim folder, control folder, file to write late): both folders are candidates of the group."""
    sub = "sub" if nested else ""
    if group == "exports":
        victim, control = _old_export_days(w)
        _file(victim / "sub" / "a.xlsx")
    elif group == "deploy_temp":
        victim, control = (w.temp / f"DemandForecast-deploy-2026110{i}-000000" for i in (1, 2))
        for d in (victim, control):
            _file(d / "pkg.zip")
            _file(d / "sub" / "a.zip")
        w.age(3, victim, control)
    elif group == "dist_versions":
        victim, control = w.p("dist") / "DemandForecast-1.4.5", w.p("dist") / "DemandForecast-1.4.4"
        for d in (victim, control):
            _file(d / "VERSION", b"x")
            _file(d / "sub" / "a.txt")
    else:                                                                # tmp
        victim, control = w.tmproot / "victim", w.tmproot / "control"
        for d in (victim, control):
            _file(d / "f.txt")
            _file(d / "sub" / "a.txt")
        w.age(3, victim, control)
    w.write_keep(["# unrelated", r"reports\no_such_folder"])
    return victim, control, (victim / sub / "late.txt")


@pytest.mark.parametrize("group,nested", [("exports", False), ("exports", True), ("deploy_temp", False), ("dist_versions", False),
                                          ("tmp", False), ("tmp", True)])
def test_t13_a_candidate_folder_written_after_the_plan_is_skipped_the_others_go(w: World, group: str, nested: bool):
    _inject_touch(w)
    victim, control, late = _h3_world(w, group, nested)
    code, out, rep = w.run(group, apply=True, env_extra={"DF_TEST_TOUCH": str(late)})
    assert code == 0, out
    assert rep["mode"] == "APPLY" and rep["apply_gate"] == "MATCHED"        # the plan itself matched: the write came later
    g = _groups(rep)[group]
    assert {_n(victim), _n(control)} <= _cands(rep, group)
    assert late.is_file() and victim.is_dir(), "the folder written to must stay"
    assert not control.exists(), "an untouched candidate folder is still deleted"
    assert rep["totals"]["deleted_count"] == 1 and g["deleted_count"] == 1
    sk = {_n(s["path"]): s["reason"] for s in _list(g["skipped"])}
    assert "changed after the plan" in sk[_n(victim)], sk
    if group != "tmp":                                                    # tmp has an older age check with the same words first
        assert str(late).lower() in sk[_n(victim)].lower() or str(victim).lower() in sk[_n(victim)].lower()
    lines = _txt_report(out)
    assert any(ln.startswith(f"NOT deleted {group} ") and str(victim).lower() in ln.lower() and "changed after the plan" in ln for ln in lines), lines


def test_t13_an_item_dated_in_the_future_blocks_the_folder_as_well_fail_safe(w: World):
    victim, control = _old_export_days(w)
    ok = _file(victim / "sub" / "a.xlsx")
    _set_times(w.root, [(ok, NOW + timedelta(hours=2))])                 # 'at or after the start of the run' includes the future
    w.write_keep(["# unrelated", r"reports\no_such_folder"])
    code, out, rep = w.run("exports", apply=True)
    assert code == 0, out
    assert rep["totals"]["deleted_count"] == 1 and ok.is_file() and not control.exists()
    sk = {_n(s["path"]): s["reason"] for s in _list(_groups(rep)["exports"]["skipped"])}
    assert "changed after the plan" in sk[_n(victim)] and str(ok).lower() in sk[_n(victim)].lower()


def test_t13_folders_untouched_during_the_run_are_deleted_even_when_written_just_before_it(w: World):
    _inject_touch(w)                                                      # nothing is touched here: DF_TEST_TOUCH is not set
    victim, control = _old_export_days(w)
    w.write_keep(["# unrelated", r"reports\no_such_folder"])
    code, out, rep = w.run("exports", apply=True)
    assert code == 0, out
    assert rep["totals"]["deleted_count"] == 2 and not victim.exists() and not control.exists()


# ------------------------------------------------------------------ T14, H1: prune-artifacts.ps1 -Apply only for the planned entries

_DIST_ARGS = ["-IncludeDist", "-DistKeep", "1.4.14"]
# Calls of the stub in the tests below (every case runs w.run(..., apply=True): a dry run first, then the -Apply run):
#   dry call 1 = the dry run of the helper, 2 = the plan of the -Apply run (Get-DistGroup), 3 = the check right before
#   prune-artifacts.ps1 -Apply (Invoke-DistApply), then the -Apply call.


def test_t14_i_dry_run_equal_to_the_plan_runs_prune_apply_and_it_deletes_exactly_the_plan(w: World):
    a, b = _dist_world(w)
    kept = _file(w.p("dist") / "listed_by_nobody.zip")
    w.write_keep([r"dist\other.zip"])
    code, out, rep = w.run("dist", apply=True, extra=_DIST_ARGS)
    assert code == 0, out
    assert _prune_calls(w) == ["apply=False", "apply=False", "apply=False", "apply=True"], _prune_calls(w)
    g = _groups(rep)["dist"]
    chk = g["apply_check"]
    assert chk["planned_existing"] == 2 and chk["dry_run_delete"] == 2 and not _list(chk["not_planned"]) and not _list(chk["planned_not_listed"]), chk
    assert not _list(g["errors"]) and g["deleted_count"] == 2 and all(c.get("deleted") for c in _list(g["candidates"]))
    _gone(a, b)
    _alive(kept)


def test_t14_i_without_include_dist_prune_never_runs_apply(w: World):
    a, b = _dist_world(w)
    w.write_keep([r"dist\other.zip"])
    code, out, rep = w.run("dist", apply=True, extra=["-DistKeep", "1.4.14"])
    assert code == 0, out
    assert "apply=True" not in _prune_calls(w) and _prune_calls(w)
    _alive(a, b)
    assert any("dist: deleted only with -IncludeDist" in ln for ln in _txt_report(out))


def test_t14_ii_a_dry_run_that_lists_something_not_in_the_plan_stops_prune_apply(w: World):
    a, b = _dist_world(w)
    extra = _file(w.p("dist") / "c.zip")
    (w.proj / "prune_mode.txt").write_text("extra_from_dry=3\nextra_row=dist\\c.zip\n", encoding="ascii")
    w.write_keep([r"dist\other.zip"])
    code, out, rep = w.run("dist", apply=True, extra=_DIST_ARGS)
    assert code == 1, out
    assert _prune_calls(w) == ["apply=False", "apply=False", "apply=False"], _prune_calls(w)      # prune -Apply was NOT run
    g = _groups(rep)["dist"]
    assert any("-Apply not run: its dry run differs from the plan" in e and "not planned:" in e and "c.zip" in e for e in _list(g["errors"])), g["errors"]
    assert [x.lower() for x in _list(g["apply_check"]["not_planned"])] == [str(extra).lower()]
    assert g["deleted_count"] == 0
    _alive(a, b, extra)


def test_t14_ii_a_planned_entry_missing_from_the_dry_run_stops_prune_apply_too(w: World):
    a, b = _dist_world(w)
    (w.proj / "prune_mode.txt").write_text("omit_from_dry=3\nomit_row=dist\\a.zip\n", encoding="ascii")
    w.write_keep([r"dist\other.zip"])
    code, out, rep = w.run("dist", apply=True, extra=_DIST_ARGS)
    assert code == 1, out
    assert "apply=True" not in _prune_calls(w)
    errs = " | ".join(_list(_groups(rep)["dist"]["errors"]))
    assert "its dry run differs from the plan" in errs and "planned, not listed:" in errs and "a.zip" in errs, errs
    _alive(a, b)


def test_t14_iii_an_entry_that_disappears_while_prune_apply_runs_and_is_not_planned_is_an_error(w: World):
    a, b = _dist_world(w)
    other = _file(w.p("dist") / "x.zip")
    (w.proj / "prune_mode.txt").write_text("apply_also_deletes=dist\\x.zip\n", encoding="ascii")
    w.write_keep([r"dist\other.zip"])
    code, out, rep = w.run("dist", apply=True, extra=_DIST_ARGS)
    assert code == 1, out
    g = _groups(rep)["dist"]
    assert any("x.zip: disappeared while prune-artifacts.ps1 -Apply ran, not in the plan" in e for e in _list(g["errors"])), g["errors"]
    assert not any("a.zip: disappeared" in e or "b.zip: disappeared" in e for e in _list(g["errors"]))      # the planned ones are fine
    assert rep["exit_code"] == 1 and rep["groups"] is not None
    _gone(a, b, other)                                                    # what the stub did: the report says so


def test_t14_iv_a_dry_run_without_the_final_line_is_not_trusted(w: World):
    a, b = _dist_world(w)
    (w.proj / "prune_mode.txt").write_text("no_dry_line=1\n", encoding="ascii")
    w.write_keep([r"dist\other.zip"])
    code, out, rep = w.run("dist", apply=True, extra=_DIST_ARGS)
    assert code == 1, out
    assert "apply=True" not in _prune_calls(w)
    assert any("cannot be compared with the plan" in e and "Dry run: nothing deleted." in e for e in _list(_groups(rep)["dist"]["errors"]))
    _alive(a, b)


def test_t14_iv_a_dry_run_row_in_another_format_is_not_trusted(w: World):
    a, b = _dist_world(w)
    (w.proj / "prune_mode.txt").write_text("bad_row_from_dry=3\n", encoding="ascii")
    w.write_keep([r"dist\other.zip"])
    code, out, rep = w.run("dist", apply=True, extra=_DIST_ARGS)
    assert code == 1, out
    assert "apply=True" not in _prune_calls(w)
    assert any("DELETE row not understood" in e for e in _list(_groups(rep)["dist"]["errors"]))
    _alive(a, b)


def test_t14_vi_an_entry_dist_versions_already_deleted_is_not_expected_from_the_dry_run(w: World):
    a, b = _dist_world(w)
    pkg = _file(w.p("dist") / "DemandForecast-1.4.5-win64-portable.zip")  # a package of an old version: dist_versions deletes it first
    w.write_keep([r"dist\other.zip"])
    code, out, rep = w.run("dist_versions,dist", apply=True, extra=_DIST_ARGS)
    assert code == 0, out
    groups = _groups(rep)
    assert _cands(rep, "dist_versions") == {_n(pkg)} and groups["dist_versions"]["deleted_count"] == 1
    chk = groups["dist"]["apply_check"]
    assert chk["planned_existing"] == 2 and chk["dry_run_delete"] == 2, chk       # pkg is gone: neither expected nor listed
    _gone(a, b, pkg)
    assert _prune_calls(w)[-1] == "apply=True"
