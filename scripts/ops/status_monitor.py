"""Owner operating mode 03/11 (B, C): STATUS.md every 10 minutes + Windows toasts, read-only (live DB mode=ro).
Watches the steps listed in reports\\e2-20261103\\state\\plan.json (written by the orchestrator: current step, expected
end) and the E2 driver status; a toast when the driver state changes (DONE / STOPPED / FAILED / WAITING), and when a
RUNNING step shows no new progress for 15 minutes or its process is gone. Never changes anything else.
usage: status_monitor.py"""
import ctypes
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ops_config  # noqa: E402  (machine paths)

ROOT = ops_config.PROJECT_ROOT
STATUS = ops_config.STATUS_MD
E2 = ops_config.REPORTS / "e2-20261103"
PLAN = E2 / "state" / "plan.json"
DRV = E2 / "state" / "e2_status.json"
LIVE = ops_config.live_db_uri()          # storage.json data_dir \db\app.db, read-only
TOAST = ops_config.HERE / "toast.ps1"
MLOG = E2 / "status_monitor.log"
RUNNER = ops_config.REPORTS / "dong-bo-lich-su-20261102" / "run4" / "status.json"     # written by scripts\ops\runner (E3)


class MS(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def mem():
    m = MS()
    m.dwLength = ctypes.sizeof(MS)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return round(m.ullAvailPhys / 2 ** 20), round(m.ullAvailPageFile / 2 ** 20)


def toast(title, text):
    subprocess.call(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(TOAST), "-Title", title,
                     "-Text", text[:220]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(MLOG, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} TOAST {title}: {text}\n")


def read_json(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def db_progress():
    c = sqlite3.connect(LIVE, uri=True)
    try:
        q = lambda s: c.execute(s).fetchone()  # noqa: E731
        return {"open_hours": q("SELECT MIN(open_date), MAX(open_date), COUNT(*) FROM open_hours_daily"),
                "trainings_ok": q("SELECT COUNT(*) FROM candidate_train_runs WHERE status='SUCCEEDED'")[0],
                "trainings_last": q("SELECT origin_date || ' ' || model || ' ' || finished_at FROM candidate_train_runs "
                                    "WHERE status='SUCCEEDED' ORDER BY finished_at DESC LIMIT 1"),
                "candidate_days": q("SELECT COUNT(DISTINCT forecast_date) FROM candidate_runs WHERE status='SUCCEEDED'")[0],
                "sel2_runs": q("SELECT COUNT(*) FROM forecast_refresh_runs WHERE config_version LIKE 'SEL2:%'")[0],
                "exports": [list(r) for r in c.execute("SELECT forecast_date, version, n_rows, is_stale, created_at FROM "
                                                       "export_runs ORDER BY created_at DESC LIMIT 3")],
                "jobs_running": [list(r) for r in c.execute("SELECT id, job_type, stage FROM job_runs WHERE status IN "
                                                            "('RUNNING','QUEUED','RETRY_WAIT')")],
                "last_error": q("SELECT job_type || ' ' || status || ' ' || COALESCE(reason_code,'') || ' ' || created_at "
                                "FROM job_runs WHERE status='FAILED' ORDER BY created_at DESC LIMIT 1")}
    finally:
        c.close()


def proc_alive(pattern):
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "@(Get-CimInstance Win32_Process -Filter \"Name LIKE 'python%'\" | Where-Object { $_.CommandLine "
                          f"-like '*{pattern}*' }}).Count"], capture_output=True, text=True).stdout.strip()
    return out not in ("", "0")


last_write, last_sig, sig_since, last_drv, stall_told = 0.0, None, time.time(), None, False
while True:
    plan = read_json(PLAN)
    drv = read_json(DRV)
    try:
        prog = db_progress()
    except sqlite3.Error as e:
        prog = {"error": str(e)}
    ram, com = mem()
    sig = json.dumps({k: prog.get(k) for k in ("open_hours", "trainings_ok", "candidate_days", "sel2_runs", "exports")},
                     default=str)
    if sig != last_sig:
        last_sig, sig_since, stall_told = sig, time.time(), False
    step = plan.get("step", "?")
    running = plan.get("running", False)
    alive = proc_alive(plan["process"]) if running and plan.get("process") else None
    if running and (time.time() - sig_since > 15 * 60 or alive is False) and not stall_told:
        why = "tien trinh khong con chay" if alive is False else "15 phut khong co tien do moi"
        toast("Demand Forecast: CAN KIEM TRA", f"{step}: {why}")
        stall_told = True
    st = drv.get("state")
    if st and st != last_drv:
        if last_drv is not None or st in ("DONE", "STOPPED", "FAILED"):
            toast(f"Demand Forecast: E2 {st}", json.dumps(drv.get("progress") or drv.get("reason") or "", default=str)[:200])
        last_drv = st
    if time.time() - last_write >= 600 or (st and st != plan.get("_seen")):
        lines = [f"# Trang thai Demand Forecast 1.4.0", "",
                 f"* Cap nhat: {time.strftime('%Y-%m-%d %H:%M:%S')} (moi 10 phut, tu dong)",
                 f"* Buoc dang chay: {step}" + (" (dang chay)" if running else ""),
                 f"* Tien do: {plan.get('progress_note', '')}",
                 f"* Du kien xong: {plan.get('eta', '?')}",
                 f"* E2 driver: {st or '-'} {json.dumps(drv.get('progress'), default=str) if drv.get('progress') else ''}",
                 f"* Gio mo ban (open_hours_daily): {prog.get('open_hours')}",
                 f"* Hoc mo hinh xong: {prog.get('trainings_ok')} (gan nhat: {prog.get('trainings_last')})",
                 f"* Ngay ung vien da tinh: {prog.get('candidate_days')} / 28 (+ hom nay)",
                 f"* Lan chay SEL2 da cong bo: {prog.get('sel2_runs')}; file Excel gan nhat: {prog.get('exports')}",
                 f"* Job dang chay: {prog.get('jobs_running')}",
                 f"* RAM trong {ram} MB, commit trong {com} MB",
                 f"* Loi gan nhat: {prog.get('last_error') or '-'}",
                 f"* Tien trinh con song: {alive}" if alive is not None else "* Tien trinh con song: -",
                 f"* Lan co tien do moi gan nhat: {time.strftime('%H:%M:%S', time.localtime(sig_since))}", ""]
        rs = read_json(RUNNER)
        if rs:
            lines += ["## Runner (Scheduled Task, doc lap voi phien chat)", "",
                      f"* Trang thai: {rs.get('state')}; buoc {rs.get('x')}/{rs.get('y')}: "
                      f"{rs.get('step_id')} - {rs.get('step_title')}",
                      f"* Cap nhat runner: {rs.get('updated_at')}; du kien xong: {rs.get('expected_end')}",
                      f"* Loi gan nhat: {rs.get('last_error') or '-'}", ""]
        STATUS.write_text("\n".join(lines), encoding="utf-8")
        last_write = time.time()
    time.sleep(60)
