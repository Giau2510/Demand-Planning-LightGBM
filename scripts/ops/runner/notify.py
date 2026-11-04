"""Notifications of the step runner (owner 03/11): Windows toast (scripts\\ops\\toast.ps1) AND a phone push through
ntfy.sh (HTTP POST https://ntfy.sh/<topic>, Title + Priority headers). The topic "buymed-lgbm-" + 16 random [a-z0-9]
is generated once into notify_config.json next to this file (private, not a secret; kept out of Git by the .gitignore
here) and is never written to a log. Texts are status only (step id / title, state, x/y, times): never data values,
customer / SKU ids, paths of user files or credentials. A failed send is logged and never raised.
usage: notify.py "<title>" "<text>" [--priority high|default] [--log <file>] [--no-toast] [--no-ntfy]"""
import argparse
import base64
import os
import secrets
import string
import subprocess
import urllib.request
from pathlib import Path

from common import NO_WINDOW, append_log, load_json, write_json

HERE = Path(__file__).resolve().parent
CONFIG = Path(os.environ.get("DF_NOTIFY_CONFIG") or HERE / "notify_config.json")  # env override: tests only
TOAST = HERE.parent / "toast.ps1"


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


def send(title, text, priority="default", log=None, toast=True, ntfy=True):
    """returns {"toast": ok, "ntfy": ok} for the channels used; never raises"""
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
            req = urllib.request.Request(f"{cfg.get('ntfy_server', 'https://ntfy.sh').rstrip('/')}/{cfg['ntfy_topic']}",
                                         data=text[:1000].encode("utf-8"), method="POST",
                                         headers={"Title": _header(title[:120]), "Priority": priority,
                                                  "Tags": "warning" if priority == "high" else "information_source"})
            with urllib.request.urlopen(req, timeout=15) as r:
                res["ntfy"] = 200 <= r.status < 300
        except Exception as e:  # noqa: BLE001 - the message of e can hold the URL (= topic): only the type is logged
            res["ntfy"] = False
            log and append_log(log, f"NOTIFY ntfy error: {type(e).__name__}")
    log and append_log(log, f"NOTIFY [{priority}] {title}: {text} -> {res}")
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
