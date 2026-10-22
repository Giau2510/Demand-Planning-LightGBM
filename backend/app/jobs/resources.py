"""Resource readings of this process and of the machine for the job records (1.2.13): memory (private bytes = commit
charge, working set), CPU time, I/O, page faults and the machine's available memory / commit headroom. Windows reads the
Win32 API through ctypes (no extra package in the portable build); Linux reads /proc. Every reading is best effort: an
unavailable value is None and a failure never reaches the job.

The server runs every job in a thread of its single process (one uvicorn worker), so the figures of a job are those of
the whole process while it ran; `other_jobs` in the record says when another job ran at the same time (the figures then
cover both)."""
from __future__ import annotations

import gc
import os
import sys
import threading
import time

MB = 1024 * 1024


# ---------------------------------------------------------------- platform readings
if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes as wt

    class _PMC(ctypes.Structure):
        _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t), ("PrivateUsage", ctypes.c_size_t)]

    class _IOC(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                     "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _MSX(ctypes.Structure):
        _fields_ = [("dwLength", wt.DWORD), ("dwMemoryLoad", wt.DWORD)] + [
            (n, ctypes.c_uint64) for n in ("ullTotalPhys", "ullAvailPhys", "ullTotalPageFile", "ullAvailPageFile",
                                           "ullTotalVirtual", "ullAvailVirtual", "ullAvailExtendedVirtual")]

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _psapi = ctypes.WinDLL("psapi", use_last_error=True)
    _k32.GetCurrentProcess.restype = wt.HANDLE
    _psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(_PMC), wt.DWORD]
    _psapi.GetProcessMemoryInfo.restype = wt.BOOL
    _k32.GetProcessTimes.argtypes = [wt.HANDLE] + [ctypes.POINTER(wt.FILETIME)] * 4
    _k32.GetProcessTimes.restype = wt.BOOL
    _k32.GetProcessIoCounters.argtypes = [wt.HANDLE, ctypes.POINTER(_IOC)]
    _k32.GetProcessIoCounters.restype = wt.BOOL
    _k32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(_MSX)]
    _k32.GlobalMemoryStatusEx.restype = wt.BOOL
    _k32.GetProcessHeaps.argtypes = [wt.DWORD, ctypes.POINTER(wt.HANDLE)]
    _k32.GetProcessHeaps.restype = wt.DWORD
    _k32.HeapCompact.argtypes = [wt.HANDLE, wt.DWORD]
    _k32.HeapCompact.restype = ctypes.c_size_t

    def _read() -> dict:
        h = _k32.GetCurrentProcess()
        out: dict = {}
        p = _PMC()
        p.cb = ctypes.sizeof(_PMC)
        if _psapi.GetProcessMemoryInfo(h, ctypes.byref(p), p.cb):
            out.update(private=p.PrivateUsage, ws=p.WorkingSetSize, ws_peak_lifetime=p.PeakWorkingSetSize,
                       page_faults=p.PageFaultCount)
        t = [wt.FILETIME() for _ in range(4)]
        if _k32.GetProcessTimes(h, *(ctypes.byref(x) for x in t)):
            f = lambda x: ((x.dwHighDateTime << 32) | x.dwLowDateTime) / 1e7  # noqa: E731
            out.update(cpu_kernel=f(t[2]), cpu_user=f(t[3]))
        io = _IOC()
        if _k32.GetProcessIoCounters(h, ctypes.byref(io)):
            out.update(io_read=io.ReadTransferCount, io_write=io.WriteTransferCount)
        m = _MSX()
        m.dwLength = ctypes.sizeof(_MSX)
        if _k32.GlobalMemoryStatusEx(ctypes.byref(m)):
            out.update(phys_total=m.ullTotalPhys, phys_avail=m.ullAvailPhys, commit_limit=m.ullTotalPageFile,
                       commit_avail=m.ullAvailPageFile)
        return out

    def _trim_heaps() -> None:
        n = _k32.GetProcessHeaps(0, None)
        if n:
            arr = (wt.HANDLE * n)()
            for i in range(_k32.GetProcessHeaps(n, arr)):
                _k32.HeapCompact(arr[i], 0)
        try:
            ctypes.CDLL("ucrtbase")._heapmin()
        except (OSError, AttributeError):
            pass

elif sys.platform.startswith("linux"):
    def _kb(path: str, names: tuple) -> dict:
        out = {}
        with open(path, encoding="ascii", errors="replace") as fh:
            for line in fh:
                k, _, v = line.partition(":")
                if k in names:
                    out[k] = int(v.split()[0]) * 1024
        return out

    def _read() -> dict:
        out: dict = {}
        st = _kb("/proc/self/status", ("VmRSS", "VmHWM", "RssAnon"))
        out.update(private=st.get("RssAnon", st.get("VmRSS")), ws=st.get("VmRSS"), ws_peak_lifetime=st.get("VmHWM"))
        t = os.times()
        out.update(cpu_user=t.user, cpu_kernel=t.system)
        try:
            with open("/proc/self/io", encoding="ascii") as fh:
                io = dict(line.split(":") for line in fh if ":" in line)
            out.update(io_read=int(io.get("read_bytes", 0)), io_write=int(io.get("write_bytes", 0)))
        except OSError:
            pass
        mi = _kb("/proc/meminfo", ("MemTotal", "MemAvailable", "CommitLimit", "Committed_AS"))
        out.update(phys_total=mi.get("MemTotal"), phys_avail=mi.get("MemAvailable"), commit_limit=mi.get("CommitLimit"))
        if "CommitLimit" in mi and "Committed_AS" in mi:
            out["commit_avail"] = max(mi["CommitLimit"] - mi["Committed_AS"], 0)
        return out

    def _trim_heaps() -> None:
        try:
            import ctypes
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except (OSError, AttributeError):
            pass

else:   # other platforms: CPU time only
    def _read() -> dict:
        t = os.times()
        return {"cpu_user": t.user, "cpu_kernel": t.system}

    def _trim_heaps() -> None:
        return None


def snapshot() -> dict:
    """Readings now (bytes / seconds); {} when the platform call fails."""
    try:
        return _read()
    except Exception:  # noqa: BLE001 - readings never fail a caller
        return {}


def release_memory() -> dict:
    """After a heavy job: collect cycles and give unused heap pages back to the system. Returns the private bytes before /
    after (MB) so the job record shows what the cleanup reclaimed; never raises."""
    before = snapshot().get("private")
    try:
        gc.collect()
        _trim_heaps()
    except Exception:  # noqa: BLE001
        pass
    after = snapshot().get("private")
    return {"private_before_mb": _mb(before), "private_after_mb": _mb(after),
            "released_mb": _mb(before - after) if before is not None and after is not None else None}


def _mb(v) -> float | None:
    return None if v is None else round(v / MB, 1)


class JobMeter:
    """Samples this process while a job runs: start / peak / mean / end of private bytes and working set, CPU time and
    utilisation, I/O, page faults and the machine's lowest available memory and commit headroom. start() before the job,
    stop() after it; result() is a JSON-ready dict in MB / seconds. The sampler is a daemon thread (default every 2 s)
    reading a few counters: negligible next to a job."""

    def __init__(self, interval: float = 2.0):
        self.interval = interval
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.start_s: dict = {}
        self.end_s: dict = {}
        self._t0 = 0.0
        self.wall = 0.0
        self._n = 0
        self._sum = {"private": 0, "ws": 0}
        self._peak = {"private": None, "ws": None}
        self._min = {"phys_avail": None, "commit_avail": None}

    def _take(self, s: dict) -> None:
        with self._lock:
            if s.get("private") is not None and s.get("ws") is not None:
                self._n += 1
                for k in ("private", "ws"):
                    self._sum[k] += s[k]
                    self._peak[k] = s[k] if self._peak[k] is None else max(self._peak[k], s[k])
            for k in ("phys_avail", "commit_avail"):
                if s.get(k) is not None:
                    self._min[k] = s[k] if self._min[k] is None else min(self._min[k], s[k])

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            self._take(snapshot())

    def start(self) -> "JobMeter":
        self._t0 = time.monotonic()
        self.start_s = snapshot()
        self._take(self.start_s)
        self._thread = threading.Thread(target=self._run, name="job-meter", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> "JobMeter":
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self.end_s = snapshot()
        self._take(self.end_s)
        self.wall = time.monotonic() - self._t0
        return self

    def result(self) -> dict:
        s, e = self.start_s, self.end_s
        d = lambda k: (e[k] - s[k]) if k in s and k in e else None  # noqa: E731
        cpu_u, cpu_k = d("cpu_user"), d("cpu_kernel")
        ncpu = os.cpu_count() or 1
        busy = (cpu_u or 0.0) + (cpu_k or 0.0)
        with self._lock:
            n = self._n
            out = {"pid": os.getpid(), "wall_s": round(self.wall, 1),
                   "cpu_user_s": None if cpu_u is None else round(cpu_u, 1),
                   "cpu_kernel_s": None if cpu_k is None else round(cpu_k, 1),
                   "cpu_util_pct": round(100 * busy / self.wall / ncpu, 1) if self.wall > 0 and cpu_u is not None else None,
                   "logical_cpus": ncpu,
                   "private_mb": {"start": _mb(s.get("private")), "peak": _mb(self._peak["private"]),
                                  "mean": _mb(self._sum["private"] / n) if n else None, "end": _mb(e.get("private"))},
                   "ws_mb": {"start": _mb(s.get("ws")), "peak": _mb(self._peak["ws"]),
                             "mean": _mb(self._sum["ws"] / n) if n else None, "end": _mb(e.get("ws"))},
                   "page_faults": d("page_faults"), "io_read_mb": _mb(d("io_read")), "io_write_mb": _mb(d("io_write")),
                   "machine_mb": {"phys_total": _mb(s.get("phys_total")), "phys_avail_start": _mb(s.get("phys_avail")),
                                  "phys_avail_min": _mb(self._min["phys_avail"]),
                                  "commit_limit": _mb(s.get("commit_limit")),
                                  "commit_avail_start": _mb(s.get("commit_avail")),
                                  "commit_avail_min": _mb(self._min["commit_avail"])},
                   "samples": n, "interval_s": self.interval}
        return out


def peak_growth_mb(res: dict | None) -> float | None:
    """Private memory a finished job needed above its start (MB), from a stored `resources` record."""
    try:
        pm = (res or {}).get("private_mb") or {}
        return round(max(pm["peak"] - pm["start"], 0.0), 1)
    except (KeyError, TypeError):
        return None
