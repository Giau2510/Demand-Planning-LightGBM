"""Watchdog of the Claude Code orchestrator session (owner 07/11/2026: a session stood still 7 hours on an "Allow"
prompt). Read-only on the transcripts; run every 5 minutes by the task DemandForecastSessionWatchdog.
For every transcript <projects dir>\\*.jsonl written in the last ACTIVE_H hours:
  * a tool call without its result for >= IDLE_MIN minutes  -> high alert "phien co the dang cho Allow"
  * otherwise no new line for >= IDLE_MIN minutes            -> high alert "phien khong hoat dong"
One alert per idle episode (state file per transcript), reminded every REMIND_MIN minutes while it lasts; a new line
ends the episode. Texts carry the session id prefix and minutes only (no content of the conversation).
usage: session_watchdog.py [--projects DIR] [--state DIR] [--idle-min 15] [--dry-run]"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "runner"))

IDLE_MIN, REMIND_MIN, ACTIVE_H, TAIL_BYTES = 15, 60, 6, 400_000
DEFAULT_PROJECTS = Path.home() / ".claude" / "projects" / "d--Buymed-Lightgbm-AI"


def tail_lines(p: Path):
    with open(p, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - TAIL_BYTES))
        data = f.read().decode("utf-8", errors="replace")
    lines = data.splitlines()
    return lines[1:] if size > TAIL_BYTES else lines


def pending_tool(lines):
    """name of the LAST tool call of the main thread (not a subagent) when it has no result yet, else None (an earlier
    call without a recorded result, e.g. one refused by a safety check, is ignored once a later call exists)"""
    last, done = None, set()
    for ln in lines:
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if d.get("isSidechain"):
            continue
        content = (d.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                last = (c.get("id"), c.get("name"))
            elif isinstance(c, dict) and c.get("type") == "tool_result":
                done.add(c.get("tool_use_id"))
    return last[1] if last and last[0] not in done else None


def check(projects: Path, state_dir: Path, idle_min: float, dry: bool, now=None):
    now = now or time.time()
    state_dir.mkdir(parents=True, exist_ok=True)
    sent = []
    for p in sorted(projects.glob("*.jsonl")):
        age_min = (now - p.stat().st_mtime) / 60
        if age_min > ACTIVE_H * 60:
            continue
        sf = state_dir / (p.stem + ".json")
        st = json.loads(sf.read_text(encoding="utf-8")) if sf.exists() else {}
        if age_min < idle_min:
            if st:
                sf.unlink()
            continue
        if st.get("mtime") == p.stat().st_mtime and now - st.get("alerted_at", 0) < REMIND_MIN * 60:
            continue
        tool = pending_tool(tail_lines(p))
        title = f"[Phien {p.stem[:8]}] " + ("PHIEN CO THE DANG CHO ALLOW" if tool else "PHIEN KHONG HOAT DONG")
        text = (f"khong co hoat dong {age_min:.0f} phut" + (f"; lenh {tool} chua co ket qua (co the dang cho bam Allow)"
                                                            if tool else "; kiem tra phien Claude Code"))
        if not dry:
            import notify
            notify.send(title, text, "high")
        sent.append((p.stem, title, text))
        sf.write_text(json.dumps({"mtime": p.stat().st_mtime, "alerted_at": now}), encoding="utf-8")
    return sent


def main(argv=None):
    a = argparse.ArgumentParser()
    a.add_argument("--projects", default=os.environ.get("DF_SESSION_PROJECTS") or str(DEFAULT_PROJECTS))
    a.add_argument("--state")
    a.add_argument("--idle-min", type=float, default=IDLE_MIN)
    a.add_argument("--dry-run", action="store_true")
    o = a.parse_args(argv)
    state = Path(o.state) if o.state else HERE.parent.parent / "reports" / "session-watchdog"
    for s in check(Path(o.projects), state, o.idle_min, o.dry_run):
        print(" | ".join(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
