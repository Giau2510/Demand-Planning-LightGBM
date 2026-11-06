"""Notifications of the step runner (owner 03/11): Windows toast (scripts\\ops\\toast.ps1) AND a phone push through
ntfy.sh (HTTP POST https://ntfy.sh/<topic>, Title + Priority headers). The topic "buymed-lgbm-" + 16 random [a-z0-9]
is generated once into notify_config.json next to this file (private, not a secret; kept out of Git by the .gitignore
here) and is never written to a log. Texts are status only (step id / title, state, x/y, times): never data values,
customer / SKU ids, paths of user files or credentials. A failed send is logged and never raised.
Offline (owner 05/11): a message whose ntfy send failed is kept in notify_queue.json next to notify_config.json (callers
that resend it themselves pass queue=False); the next successful ntfy send, or flush_queue() (runner loop, watchdog
check), posts ONE summary "N tin bi hoan khi mat mang:" (one line per queued time + title) and clears the queue. Toasts
are local and still go at once. The queue is changed only under notify_queue.lock; a writer that cannot get the lock
writes notify_queue.<pid>-<ns>.json instead (merged by the next flush), a flush that cannot get it does nothing.
usage: notify.py "<title>" "<text>" [--priority high|default] [--log <file>] [--no-toast] [--no-ntfy]"""
import argparse
import base64
import os
import secrets
import string
import subprocess
import time
import urllib.request
from pathlib import Path

from common import NO_WINDOW, append_log, load_json, read_json, stamp, write_json

HERE = Path(__file__).resolve().parent
CONFIG = Path(os.environ.get("DF_NOTIFY_CONFIG") or HERE / "notify_config.json")  # env override: tests only
TOAST = HERE.parent / "toast.ps1"
QUEUE = CONFIG.with_name("notify_queue.json")  # ntfy messages not sent while offline (one summary later)
QLOCK = CONFIG.with_name("notify_queue.lock")  # runner, watchdog and ops scripts can write the queue at the same time
QUEUE_MAX = 200


def config():
    """the topic is generated only when notify_config.json does not exist; an unreadable file raises (the caller skips
    ntfy and logs) and is never regenerated, so the phone subscription never changes silently"""
    if not CONFIG.exists():
        abc = string.ascii_lowercase + string.digits
        write_json(CONFIG, {"ntfy_server": "https://ntfy.sh", "toast": True, "ntfy": True,
                            "ntfy_topic": "buymed-lgbm-" + "".join(secrets.choice(abc) for _ in range(16))})
    return load_json(CONFIG)


def _header(s):
    # HTTP headers are latin-1: non-ASCII titles go RFC 2047 encoded (ntfy decodes them)
    return s if s.isascii() else "=?UTF-8?B?" + base64.b64encode(s.encode("utf-8")).decode("ascii") + "?="


def _post(cfg, title, text, priority, timeout=15):
    """one ntfy POST; True when accepted. Raises on a network error (the caller logs only the error type: the message
    of the error can hold the URL = topic)"""
    req = urllib.request.Request(f"{cfg.get('ntfy_server', 'https://ntfy.sh').rstrip('/')}/{cfg['ntfy_topic']}",
                                 data=text[:1000].encode("utf-8"), method="POST",
                                 headers={"Title": _header(title[:120]), "Priority": priority,
                                          "Tags": "warning" if priority == "high" else "information_source"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return 200 <= r.status < 300


class _QueueLock:
    """exclusive lock file, tried for about 5 s; a lock older than 60 s is stale (its holder died). .acquired tells
    whether the caller holds it"""
    def __enter__(self):
        self.fd, self.acquired = None, False
        for _ in range(25):
            try:
                self.fd = os.open(QLOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                self.acquired = True
                return self
            except FileExistsError:
                try:
                    if time.time() - QLOCK.stat().st_mtime > 60:
                        QLOCK.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
            except OSError:
                pass
            time.sleep(0.2)
        return self

    def __exit__(self, *exc):
        if self.fd is not None:
            os.close(self.fd)
            QLOCK.unlink(missing_ok=True)


def _side_files():
    """notify_queue.<pid>-<ns>.json files of writers that did not get the lock"""
    return sorted(QUEUE.parent.glob(QUEUE.stem + ".*.json"))


def queued():
    """True when messages wait for the summary (cheap: file existence only)"""
    return QUEUE.exists() or bool(_side_files())


def _enqueue(title, priority, log):
    item = {"title": title[:120], "priority": priority, "at": stamp()}
    try:
        with _QueueLock() as lk:
            # no lock: a new file of its own (merged by the next flush, never rewritten), never a lost message
            f = QUEUE if lk.acquired else QUEUE.with_name(f"{QUEUE.stem}.{os.getpid()}-{time.time_ns()}.json")
            q = (((read_json(f).get("items") or []) if f.exists() else []) + [item])[-QUEUE_MAX:]
            write_json(f, {"items": q})
        log and append_log(log, f"NOTIFY ntfy queued ({len(q)} waiting{'' if lk.acquired else ', side file'})")
    except Exception as e:  # noqa: BLE001
        log and append_log(log, f"NOTIFY queue write error: {type(e).__name__}")


def flush_queue(log=None, cfg=None):
    """the queued messages (queue + side files) as ONE ntfy summary, then they are cleared; cheap when nothing is
    queued. Returns the number of messages summarised (0 = nothing queued, -1 = not sent / lock busy: all kept). A
    failed flush is not logged (the runner tries every minute while offline)"""
    if not queued():
        return 0
    try:
        cfg = cfg or config()
        if not (cfg.get("ntfy", True) and cfg.get("ntfy_topic")):
            return -1
        with _QueueLock() as lk:
            if not lk.acquired:
                return -1
            files = [f for f in [QUEUE, *_side_files()] if f.exists()]
            q = sorted((m for f in files for m in (read_json(f).get("items") or [])), key=lambda m: str(m.get("at", "")))
            if q:
                head = f"{len(q)} tin bi hoan khi mat mang:"
                lines, size = [], len(head)
                for i, m in enumerate(q):
                    line = f"{str(m.get('at', ''))[5:16]} {m.get('title', '')}"[:150]
                    if size + len(line) + 1 > 950:
                        lines.append(f"... (+{len(q) - i})")
                        break
                    lines.append(line)
                    size += len(line) + 1
                high = any(m.get("priority") == "high" for m in q)
                if not _post(cfg, f"Demand Forecast: {len(q)} tin bi hoan / delayed", "\n".join([head, *lines]),
                             "high" if high else "default", timeout=10):
                    return -1
            for f in files:
                f.unlink(missing_ok=True)
        if q:
            log and append_log(log, f"NOTIFY queue flushed: {len(q)} delayed messages in one summary")
        return len(q)
    except Exception:  # noqa: BLE001 - offline: the queue stays
        return -1


def send(title, text, priority="default", log=None, toast=True, ntfy=True, queue=True):
    """returns {"toast": ok, "ntfy": ok} for the channels used; never raises. queue=True: a failed ntfy send is queued
    for the offline summary (flush_queue)"""
    res = {}
    try:
        cfg = config()
    except Exception as e:  # noqa: BLE001 - a notification never stops the caller; toast still goes, ntfy is skipped
        cfg = {"ntfy": False}
        log and append_log(log, f"NOTIFY config unreadable ({type(e).__name__}): ntfy skipped, notify_config.json kept")
    if toast and cfg.get("toast", True):
        try:
            rc = subprocess.call(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(TOAST), "-Title",
                                  title[:120], "-Text", text[:220]], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL,
                                 creationflags=NO_WINDOW, timeout=60)
            res["toast"] = rc == 0
        except Exception as e:  # noqa: BLE001
            res["toast"] = False
            log and append_log(log, f"NOTIFY toast error: {type(e).__name__}")
    if ntfy and cfg.get("ntfy", True) and cfg.get("ntfy_topic"):
        try:
            res["ntfy"] = _post(cfg, title, text, priority)
        except Exception as e:  # noqa: BLE001 - the message of e can hold the URL (= topic): only the type is logged
            res["ntfy"] = False
            log and append_log(log, f"NOTIFY ntfy error: {type(e).__name__}")
    log and append_log(log, f"NOTIFY [{priority}] {title}: {text} -> {res}")
    if res.get("ntfy") is False and queue:
        _enqueue(title, priority, log)
    elif res.get("ntfy"):
        flush_queue(log, cfg)  # back online: the summary of what was missed
    return res


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("title")
    a.add_argument("text")
    a.add_argument("--priority", default="default", choices=["high", "default"])
    a.add_argument("--log")
    a.add_argument("--no-toast", action="store_true")
    a.add_argument("--no-ntfy", action="store_true")
    o = a.parse_args()
    r = send(o.title, o.text, o.priority, o.log, toast=not o.no_toast, ntfy=not o.no_ntfy)
    print(r)
    raise SystemExit(0 if all(r.values()) else 1)
