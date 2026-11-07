"""Archive and remove one release worktree safely (owner 07/11/2026 item C3).
usage: archive_worktree.py <worktree path> [--archive-dir DIR] [--apply]
Without --apply only checks and prints the plan. Refuses (exit 2) when the worktree: is not a git worktree of this
repository, has uncommitted changes, has commits not on its remote branch (origin/<branch>), or is the junction target
of other worktrees (e.g. ban-1.4 holds .venv / node_modules / fixtures for the others).
With --apply:
  1. zip the folder to <archive dir>\\<name>_<YYYYMMDD>.zip WITHOUT following junctions / symlinks (their content
     belongs elsewhere), verify the zip (testzip + file count);
  2. remove the junction LINKS only (os.rmdir on a junction removes the link, never the target);
  3. `git worktree remove <path>` (no --force: git refuses if anything is left that it would lose).
Never deletes recursively by itself."""
import argparse
import os
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent


def git(*a, cwd=None):
    r = subprocess.run(["git", *a], cwd=str(cwd or REPO), capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def is_link(p: Path) -> bool:
    try:
        return p.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(p))
    except OSError:
        return False


def junctions(root: Path):
    out = []
    for dp, dn, fn in os.walk(root):
        keep = []
        for d in dn:
            p = Path(dp) / d
            if is_link(p):
                out.append(p)
            elif d != ".git":
                keep.append(d)
        dn[:] = keep
    return out


def main(argv=None):
    a = argparse.ArgumentParser()
    a.add_argument("path")
    a.add_argument("--archive-dir", default=str(REPO / "archive" / "worktrees"))
    a.add_argument("--apply", action="store_true")
    o = a.parse_args(argv)
    wt = Path(o.path).resolve()
    rc, out, _ = git("worktree", "list", "--porcelain")
    paths = [Path(l[9:]).resolve() for l in out.splitlines() if l.startswith("worktree ")]
    if wt not in paths or wt == REPO.resolve():
        print(f"REFUSED: {wt} is not a secondary worktree of {REPO}")
        return 2
    others = [p for p in paths if p != wt]
    for p in others:
        for j in junctions(p) if p.exists() else []:
            try:
                t = os.readlink(j)
                tgt = Path(t[4:] if t.startswith("\\\\?\\") else t).resolve()   # junctions read as \\?\D:\...
            except OSError:
                continue
            if wt == tgt or wt in tgt.parents:
                print(f"REFUSED: {wt} is the junction target of {j}")
                return 2
    _, branch, _ = git("rev-parse", "--abbrev-ref", "HEAD", cwd=wt)
    _, dirty, _ = git("status", "--porcelain", cwd=wt)
    if dirty:
        print(f"REFUSED: {wt} has uncommitted changes ({len(dirty.splitlines())} entries)")
        return 2
    rc, ahead, err = git("rev-list", "--count", f"origin/{branch}..HEAD", cwd=wt)
    if rc != 0 or ahead != "0":
        print(f"REFUSED: {wt} branch {branch} not fully on origin ({ahead or err})")
        return 2
    links = junctions(wt)
    dest = Path(o.archive_dir) / f"{wt.name}_{date.today():%Y%m%d}.zip"
    print(f"PLAN: {wt} ({branch}, clean, pushed); zip -> {dest}; junction links to remove: {[str(j) for j in links]}")
    if not o.apply:
        return 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        print(f"REFUSED: {dest} already exists")
        return 2
    n = 0
    tmp = dest.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        for dp, dn, fn in os.walk(wt):
            dn[:] = [d for d in dn if not is_link(Path(dp) / d)]
            for f in fn:
                p = Path(dp) / f
                if is_link(p):
                    continue
                z.write(p, p.relative_to(wt.parent))
                n += 1
    with zipfile.ZipFile(tmp) as z:
        bad = z.testzip()
        cnt = len(z.namelist())
    if bad or cnt != n:
        print(f"FAILED: zip check (bad {bad}, {cnt} != {n}); nothing removed")
        return 1
    os.replace(tmp, dest)
    for j in links:
        os.rmdir(j)
    rc, out, err = git("worktree", "remove", str(wt))
    if rc != 0:
        print(f"FAILED: git worktree remove: {err}; zip kept at {dest}")
        return 1
    print(f"DONE: {wt.name} archived ({n} files, {dest.stat().st_size // 2**20} MB) and removed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
