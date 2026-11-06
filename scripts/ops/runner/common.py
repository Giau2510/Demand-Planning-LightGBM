"""Shared helpers of the step runner and its watchdog (owner 03/11): free memory (GlobalMemoryStatusEx), process alive
check by pid + creation time (a reused pid is not taken for the old process), the named mutex of one plan, atomic +
fsync'd JSON files, process tree kill; (05/11) operations lock, power state, keep awake, network check (net_up)."""
import ctypes
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts\ops: ops_config
import ops_config  # noqa: E402

K32 = ctypes.WinDLL("kernel32", use_last_error=True)
K32.CreateMutexW.restype = K32.OpenMutexW.restype = ctypes.c_void_p
K32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
K32.OpenMutexW.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_wchar_p]
K32.CloseHandle.argtypes = [ctypes.c_void_p]

NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW: the task runs pythonw, children must not open console windows
ACTIVE = ("RUNNING", "WAITING")  # run states in which a runner process must be alive
TERMINAL = ("DONE", "FAILED", "STOPPED")


class MS(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def mem():
    """(free RAM MB, free commit MB)"""
    m = MS()
    m.dwLength = ctypes.sizeof(MS)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return round(m.ullAvailPhys / 2 ** 20), round(m.ullAvailPageFile / 2 ** 20)


def proc_created(pid):
    """creation time (FILETIME as int) of a live process, None when it is gone"""
    if not pid:
        return None
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        code = ctypes.c_ulong()
        if not k.GetExitCodeProcess(h, ctypes.byref(code)) or code.value != 259:  # STILL_ACTIVE
            return None
        c, e, kt, ut = (ctypes.c_ulonglong() for _ in range(4))
        if not k.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(kt), ctypes.byref(ut)):
            return None
        return c.value
    finally:
        k.CloseHandle(h)


def alive(pid, created):
    return created is not None and proc_created(pid) == created


def kill_tree(pid):
    """taskkill /T /F; returns its exit code (0 = killed, 128 = already gone)"""
    return subprocess.call(["taskkill", "/PID", str(pid), "/T", "/F"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)


def mutex_name(plan_name):
    """one runner per PLAN NAME on the machine (Global namespace: also across sessions)"""
    return r"Global\DF-runner-" + re.sub(r"[^A-Za-z0-9_.-]", "_", str(plan_name))[:100]


def take_mutex(name):
    """handle when this process now owns the named mutex (kept open for the process lifetime; the OS releases it when
    the process ends, also on a kill), None when another runner holds it or it cannot be created"""
    h = K32.CreateMutexW(None, True, name)
    if h and ctypes.get_last_error() != 183:  # ERROR_ALREADY_EXISTS
        return h
    if h:
        K32.CloseHandle(h)
    return None


def mutex_held(name):
    """True when a process holds the named mutex (it exists only while a handle is open)"""
    h = K32.OpenMutexW(0x00100000, False, name)  # SYNCHRONIZE
    if h:
        K32.CloseHandle(h)
        return True
    return ctypes.get_last_error() == 5  # exists, opened by another security context


def read_json(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_json(p):
    """parsed JSON object; raises OSError / ValueError when the file is unreadable or not a JSON object"""
    obj = json.loads(Path(p).read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("not a JSON object")
    return obj


def write_json(p, obj, backup=False):
    """tmp file + flush + fsync, then os.replace (atomic on NTFS). backup=True first keeps the last 2 good copies:
    <name>.bak -> <name>.bak2, current file (it parsed when it was written) -> <name>.bak. A directory fsync is not
    possible on Windows."""
    p = Path(p)
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(obj, indent=1, ensure_ascii=False, default=str))
        f.flush()
        os.fsync(f.fileno())
    if backup and p.exists():
        bak = p.with_name(p.name + ".bak")
        if bak.exists():
            shutil.copyfile(bak, p.with_name(p.name + ".bak2"))
        shutil.copyfile(p, bak)
    for i in range(5):  # a reader (watchdog, editor) can hold the file for a moment
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            time.sleep(0.2 * (i + 1))
    os.replace(tmp, p)


def stamp(t=None):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))


# ------------------------------------------------------------------ operations lock, power (owner 05/11)
# one operation on production at a time: <project root>\run\OPS_LOCK (JSON: session, job, started_at, run) is
# created by the session that owns the operation; every runner / ops script checks it before it writes the DB, installs
# or stops the app, and goes on only when there is no lock or the lock names its own run
OPS_LOCK = ops_config.OPS_LOCK  # env DF_OPS_LOCK (tests) / ops_config.json "ops_lock" / <project root>\run\OPS_LOCK


def ops_lock_block(run_name):
    """None when this run may operate on production, else the reason (lock held by another session / run)"""
    if not OPS_LOCK.exists():
        return None
    lk = read_json(OPS_LOCK)
    lk = lk if isinstance(lk, dict) else {}  # valid JSON but not an object: a lock of an unknown holder
    runs = lk.get("runs") if isinstance(lk.get("runs"), list) else []   # one session, several runs in sequence
    if lk.get("run") == run_name or run_name in runs:
        return None
    return f"OPS_LOCK held by {lk.get('session') or '?'} ({lk.get('job') or '?'}, since {lk.get('started_at') or '?'})"


class SPS(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte), ("BatteryLifePercent", ctypes.c_ubyte),
                ("SystemStatusFlag", ctypes.c_ubyte), ("BatteryLifeTime", ctypes.c_ulong),
                ("BatteryFullLifeTime", ctypes.c_ulong)]


def power():
    """(on AC: True / False / None unknown, battery percent or None)"""
    s = SPS()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)):
        return None, None
    ac = {0: False, 1: True}.get(s.ACLineStatus)
    return ac, (None if s.BatteryLifePercent == 255 else s.BatteryLifePercent)


def keep_awake(on=True):
    """SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED) for THIS process only: no idle sleep while the runner
    lives; Windows drops the request when the process ends (no power setting is changed). Lid close / power button
    still sleep the PC."""
    return bool(ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | (0x00000001 if on else 0)))


NET_TARGETS = (("1.1.1.1", 443), ("ntfy.sh", 443))


def net_up(timeout=5):
    """(owner 05/11) True when one TCP connect to NET_TARGETS succeeds within timeout seconds; env DF_NET_CHECK_OVERRIDE
    = up / down replaces the check (tests only)"""
    o = (os.environ.get("DF_NET_CHECK_OVERRIDE") or "").strip().lower()
    if o in ("up", "down"):
        return o == "up"
    for host, port in NET_TARGETS:
        try:
            socket.create_connection((host, port), timeout=timeout).close()
            return True
        except OSError:
            continue
    return False


def append_log(p, msg):
    line = f"{stamp()} {msg}"
    print(line, flush=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(line + "\n")
