"""Small synthetic tests of scripts/ops/excel20.py (every rule case + detection flow). Run: python test_x20.py"""
import json
import math
import os
import shutil
import sys
import time
from datetime import date, timedelta
from pathlib import Path

SP = Path(__file__).resolve().parent
sys.path.insert(0, str(SP))
from ops_test_env import REPO, isolate  # noqa: E402

T = isolate("ops_x20_")
(T / "notify_config.json").write_text(json.dumps({"toast": False, "ntfy": False, "ntfy_topic": ""}), encoding="utf-8")
os.environ["DF_NOTIFY_CONFIG"] = str(T / "notify_config.json")
os.environ["DF_OPS_LOCK"] = str(T / "OPS_LOCK")
sys.dont_write_bytecode = True
import gen  # noqa: E402
import excel20 as X  # noqa: E402
import notify  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

SENT = []
notify.send = lambda title, text, priority="default", log=None, **k: SENT.append((title, text, priority)) or {}
D = date(2026, 11, 5)
YMD = "20261105"
DATA, WORK = T / "data", T / "work"
DB = DATA / "db" / "app.db"
FOLDER = DATA / "exports" / "du_bao" / YMD
LATEST = FOLDER / f"du_bao_{YMD}.xlsx"
APP = os.environ.get("DF_X20_APP_BACKEND") or str(REPO / "backend")   # the app's xlsx_stream (this repository)
RES = []


def run(*extra, now="2026-11-05 10:00"):
    sys.argv = ["excel20.py", "--data-dir", str(DATA), "--db", str(DB), "--work-dir", str(WORK), "--app-backend", APP,
                "--since", "2026-11-01", "--now", now, *extra]
    return X.main()


def check(name, cond):
    RES.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


# raw values per horizon of K1 and the expected roundup
RAW1 = [0.1, 0.2, 1.0000004, 2.5, 0.0, 3.0, 0.19999999]
EXP1 = [0, 1, 1, 3, 0, 3, 1]


def small_rows(d, layout="143"):
    r = gen.row
    rows = []
    for h in range(1, 8):
        x = RAW1[h - 1]
        rows.append(r(d, "A.X1", "BD", h, x, 1.0, "LIGHTGBM", 0 if x < .2 else math.ceil(round(x, 6)), None, x, None, layout))
    for h in range(1, 8):
        rows += [r(d, "A.X2", "BD", h, 4.2, None, "LIGHTGBM", 5, "DUNG_SO_LAN_CHAY_TRUOC", 4.2,
                   "LAN_CHAY_TRUOC:2026-11-04", layout),
                 r(d, "A.X3", "BD", h, None, None, "LIGHTGBM", 0, "NGOAI_PHAM_VI_GAN_0", 6.6 if h == 1 else None, None, layout),
                 r(d, "A.X4", "BD", h, None, 6.3, "LIGHTGBM", 7, "STALE", None, "AVG_Y", layout),
                 r(d, "A.X5", "BD", h, None, None, "LIGHTGBM", 0, "KHONG_CO_SO_NAO", None, None, layout),
                 r(d, "B.Y6", "HN", h, 9.9, 3.4, "AVG_DEMAND", 4, None, 9.9, None, layout),
                 r(d, "B.Y7", "HN", h, 2.1, None, "AVG_DEMAND", 3, "KHONG_CO_AVG_DUNG_LIGHTGBM", 2.1, None, layout),
                 r(d, "B.Y8", "HN", h, None, None, "AVG_DEMAND", 0, "KHONG_CO_AVG_DUNG_LIGHTGBM", None, None, layout),
                 r(d, "NODOT9", "HN", h, None, None, "AVG_DEMAND", 0, "KHONG_CO_SO_NAO", None, None, layout)]
    rows.sort(key=lambda x: (x[0], x[-12] if layout == "143" else x[-12]))
    return rows


def add_version(v, layout="143", rows=None, rid=None, ts=None):
    rel = f"exports/du_bao/{YMD}/du_bao_{YMD}_v{v}.xlsx"
    rows = rows or small_rows(D, layout)
    sha = gen.write_file(DATA / rel, D, rows, layout)
    gen.make_db(DB, [(rid or f"E{v}", D.isoformat(), v, rel, sha, len(rows), ts or gen.old_ts())])
    shutil.copyfile(DATA / rel, LATEST)          # what the app does
    return sha


def read_out(p=LATEST):
    bk = X.Book(p)
    out = {n: list(bk.rows(n)) for n in bk.sheetnames()}
    bk.close()
    return out


def by_key(sheet):
    head = sheet[0]
    rows = [dict(zip(head, r + [None] * (len(head) - len(r)))) for r in sheet[1:]]
    return head, {(r["sku_code"], r["horizon"]): r for r in rows}


# ---------------------------------------------------------------- 1. rule cases (1.4.3 layout)
add_version(3)
rc = run()
check("pass1 rc 0", rc == 0)
o = read_out()
check("sheets", list(o) == ["DU_BAO_BD", "DU_BAO_HN", "TOM_TAT", "CONFIG"])
hb, bd = by_key(o["DU_BAO_BD"])
hh, hn = by_key(o["DU_BAO_HN"])
check("header = app columns + cach_tinh", hb == gen.COLS + ["cach_tinh"] and hh == hb)
check("rows BD = 5 x 20", len(o["DU_BAO_BD"]) - 1 == 100)
check("rows HN = 4 x 20", len(o["DU_BAO_HN"]) - 1 == 80)
src = {(r[0], r[8]): r for r in small_rows(D)}
ok = all([bd.get((k[0], k[1])) or hn.get((k[0], k[1]))][0]["cach_tinh"] == "SEL2" and
         [bd.get(k) or hn.get(k)][0]["forecast_used"] == v[12] and [bd.get(k) or hn.get(k)][0]["raw_value"] == v[15]
         for k, v in src.items())
check("h1..7 unchanged + SEL2", ok)
allr = {**bd, **hn}
check("h8..20 targets D+h-1, weekday = template, cach_tinh",
      all(r["target_date"] == D + timedelta(days=h - 1) and r["cach_tinh"] == "UOC_TINH_THEO_TUAN" and
          r["target_date"].weekday() == allr[(s, (h - 1) % 7 + 1)]["target_date"].weekday()
          for (s, h), r in allr.items() if h > 7))
check("forecast_used int >= 0 everywhere", all(type(r["forecast_used"]) is int and r["forecast_used"] >= 0
                                               for r in allr.values()))
check("K1 LIGHTGBM raw -> roundup(raw), reason empty, lgbm = raw",
      all(bd[("A.X1", h)]["forecast_used"] == EXP1[(h - 1) % 7] and bd[("A.X1", h)]["fallback_reason"] is None
          and bd[("A.X1", h)]["lightgbm_forecast"] == RAW1[(h - 1) % 7] for h in range(8, 21)))
check("K2 previous-run reason + flag kept",
      all(bd[("A.X2", h)]["forecast_used"] == 5 and bd[("A.X2", h)]["fallback_reason"] == "DUNG_SO_LAN_CHAY_TRUOC"
          and bd[("A.X2", h)]["flags"] == "LAN_CHAY_TRUOC:2026-11-04" for h in range(8, 21)))
check("K3 out of scope -> 0 (raw on template ignored)",
      all(bd[("A.X3", h)]["forecast_used"] == 0 and bd[("A.X3", h)]["fallback_reason"] == "NGOAI_PHAM_VI_GAN_0"
          for h in range(8, 21)) and bd[("A.X3", 8)]["lightgbm_forecast"] == 6.6)
check("K4 LIGHTGBM no raw -> template Avg + STALE, lgbm empty",
      all(bd[("A.X4", h)]["forecast_used"] == 7 and bd[("A.X4", h)]["fallback_reason"] == "STALE"
          and bd[("A.X4", h)]["lightgbm_forecast"] is None and bd[("A.X4", h)]["avg_demand"] == 6.3
          for h in range(8, 21)))
check("K5 LIGHTGBM KHONG_CO_SO_NAO -> 0", all(bd[("A.X5", h)]["forecast_used"] == 0 and
                                             bd[("A.X5", h)]["fallback_reason"] == "KHONG_CO_SO_NAO" for h in range(8, 21)))
check("K6 AVG_DEMAND -> template used, lgbm = raw",
      all(hn[("B.Y6", h)]["forecast_used"] == 4 and hn[("B.Y6", h)]["lightgbm_forecast"] == 9.9 for h in range(8, 21)))
check("K7 AVG missing -> roundup(raw)", all(hn[("B.Y7", h)]["forecast_used"] == 3 and hn[("B.Y7", h)]["fallback_reason"]
                                            == "KHONG_CO_AVG_DUNG_LIGHTGBM" for h in range(8, 21)))
check("K8 AVG missing, no raw -> template", all(hn[("B.Y8", h)]["forecast_used"] == 0 for h in range(8, 21)))
check("K9 no number -> 0 + seller empty for no-dot sku",
      all(hn[("NODOT9", h)]["forecast_used"] == 0 and hn[("NODOT9", h)]["seller_code"] is None and
          hn[("NODOT9", h)]["product_code"] == "NODOT9" for h in range(1, 21)))
check("dates are dates", isinstance(bd[("A.X1", 9)]["forecast_date"], date) and
      bd[("A.X1", 9)]["data_cutoff_date"] == D - timedelta(days=1))
tt = dict((r[0], r[1] if len(r) > 1 else None) for r in o["TOM_TAT"][1:])
check("TOM_TAT app rows + additions", tt.get("export_version") == 3 and tt.get("layout") == "20 ngay, tach sheet theo kho"
      and tt.get("rows:DU_BAO_BD") == 100 and tt.get("sku_fc:DU_BAO_HN") == 4 and tt.get("source_file") ==
      f"du_bao_{YMD}_v3.xlsx" and len(tt.get("source_sha256") or "") == 64 and "UOC_TINH_THEO_TUAN" in tt["horizon_8_20"]
      and tt.get("generated_at", "").startswith("2026-11-05 10:00"))
check("CONFIG copied", o["CONFIG"][0] == gen.CCOLS and len(o["CONFIG"]) == 2)
wb = load_workbook(LATEST, read_only=True)
ws = wb["DU_BAO_BD"]
check("openpyxl opens (read-only)", wb.sheetnames == list(o) and ws.max_row == 101)
wb.close()
wb = load_workbook(LATEST)
check("autofilter on DU_BAO_*/CONFIG/TOM_TAT + bold header",
      wb["DU_BAO_HN"].auto_filter.ref == "A1:U81" and wb["CONFIG"].auto_filter.ref and wb["TOM_TAT"].auto_filter.ref
      and wb["DU_BAO_BD"]["A1"].font.b and wb["DU_BAO_BD"].freeze_panes == "A2" and wb["CONFIG"].freeze_panes == "A2")
wb.close()
check("version file untouched", (FOLDER / f"du_bao_{YMD}_v3.xlsx").stat().st_size > 0 and
      "cach_tinh" not in str(read_out(FOLDER / f"du_bao_{YMD}_v3.xlsx")["DU_BAO"][0]))
check("done notification (relative path, no data)", SENT and "Da tao file 20 ngay" in SENT[-1][0] and
      SENT[-1][2] == "default")

# ---------------------------------------------------------------- 2. detection flow
m1 = LATEST.stat().st_mtime_ns
n = len(SENT)
rc = run()
check("pass2 up to date: no rewrite, no notification", rc == 0 and LATEST.stat().st_mtime_ns == m1 and len(SENT) == n)
shutil.copyfile(FOLDER / f"du_bao_{YMD}_v3.xlsx", LATEST)       # app copies the version again
time.sleep(0.05)
run()
check("app re-copy -> rewritten", "DU_BAO_BD" in read_out())
add_version(4, ts=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(timespec="seconds"))
run()
check("fresh version (< 60 s): waits", "DU_BAO" in read_out())
run("--force")
st = json.loads((WORK / "state.json").read_text(encoding="utf-8"))
check("v4 written (force) + state", "DU_BAO_BD" in read_out() and st["days"][YMD]["version"] == 4)

# locked latest copy
add_version(5)
h = open(LATEST, "rb")
n = len(SENT)
rc = run()
tmp = FOLDER / f".x20_du_bao_{YMD}.tmp"
check("locked: rc 0, temp kept, notified once", rc == 0 and tmp.exists() and len(SENT) == n + 1 and
      "dang mo" in SENT[-1][1])
run()
check("still locked: no second notification", len(SENT) == n + 1)
h.close()
t0 = time.time()
run()
check("closed: pending temp replaced", not tmp.exists() and "DU_BAO_BD" in read_out() and
      json.loads((WORK / "state.json").read_text(encoding="utf-8"))["days"][YMD]["version"] == 5)

# ops lock of another session: warning only
(T / "OPS_LOCK").write_text(json.dumps({"session": "other", "job": "x", "run": "R"}), encoding="utf-8")
add_version(6)
run()
(T / "OPS_LOCK").unlink()
check("OPS_LOCK -> warning, still written", "OPS_LOCK held by other" in (WORK / "excel20.log").read_text(encoding="utf-8")
      and json.loads((WORK / "state.json").read_text(encoding="utf-8"))["days"][YMD]["version"] == 6)

# too many SKU x FC per warehouse
add_version(7)
X.MAX_SKU_FC = 4
n = len(SENT)
rc = run()
X.MAX_SKU_FC = 50_000
check(">limit: rc 1, latest = app copy, high notification", rc == 1 and "DU_BAO" in read_out() and
      SENT[-1][2] == "high" and "TOO_MANY_SKU_FC" in SENT[-1][1])
rc = run()
check("failed version not retried, not re-notified", rc == 0 and len(SENT) == n + 1)

# verification failure (a broken rule result)
add_version(8)
orig = X.derive_used
X.derive_used = lambda *a: (-1, None)
rc = run()
X.derive_used = orig
check("verify fail: rc 1, not replaced, temp removed", rc == 1 and "DU_BAO" in read_out() and not tmp.exists() and
      "VERIFY_FAILED" in SENT[-1][1])

# source sha mismatch
add_version(9)
p9 = FOLDER / f"du_bao_{YMD}_v9.xlsx"
with open(p9, "ab") as f:
    f.write(b"x")
rc = run()
check("source sha mismatch -> rc 1", rc == 1 and "SOURCE_SHA_MISMATCH" in SENT[-1][1])

# ---------------------------------------------------------------- 3. 1.4.2 layout, yesterday detection, since
shutil.rmtree(DATA)
shutil.rmtree(WORK)
add_version(2, layout="142")
rc = run(now="2026-11-06 08:00")                 # D = yesterday
o = read_out()
hb, bd = by_key(o["DU_BAO_BD"])
check("1.4.2 layout: seller/product inserted after ten_san_pham",
      rc == 0 and hb == gen.COLS + ["cach_tinh"] and bd[("A.X2", 9)]["seller_code"] == "A" and
      bd[("A.X2", 9)]["product_code"] == "X2" and o["CONFIG"][0] == gen.CCOLS and o["CONFIG"][1][3:5] == ["A", "X1"])
shutil.rmtree(WORK)
add_version(3)
sys.argv = ["excel20.py", "--data-dir", str(DATA), "--db", str(DB), "--work-dir", str(WORK), "--app-backend", APP,
            "--now", "2026-11-06 08:00"]          # default --since 2026-11-06: the 05/11 file is not converted
X.main()
check("default since 2026-11-06 skips the 05/11 file", "DU_BAO" in read_out())
run(now="2026-11-07 08:00")
check("day before yesterday not processed", "DU_BAO" in read_out())

# dry run
rc = run("--dry-run", "--forecast-date", "2026-11-05", "--force")
check("dry run: latest untouched, temp kept", rc == 0 and "DU_BAO" in read_out() and tmp.exists() and
      "DU_BAO_BD" in X.Book(tmp).sheetnames())

# openpyxl fallback writer
tmp.unlink()
shutil.rmtree(WORK)
sys.argv = ["excel20.py", "--data-dir", str(DATA), "--db", str(DB), "--work-dir", str(WORK), "--app-backend",
            str(T / "nope"), "--since", "2026-11-01", "--now", "2026-11-05 10:00"]
rc = X.main()
st = json.loads((WORK / "state.json").read_text(encoding="utf-8"))
check("openpyxl fallback writes + verifies", rc == 0 and st["days"][YMD]["info"]["writer"] == "openpyxl write_only"
      and "DU_BAO_HN" in read_out())

# reader vs openpyxl (LATEST = openpyxl fallback writer output; v3 = the app's xlsx_stream format)
from datetime import datetime as _dt  # noqa: E402


def norm(v):
    return v.date() if isinstance(v, _dt) and v.hour == v.minute == v.second == 0 else v


for label, path in (("openpyxl-format", LATEST), ("xlsx_stream-format", FOLDER / f"du_bao_{YMD}_v3.xlsx")):
    wb = load_workbook(path, read_only=True)
    same, bk = True, X.Book(path)
    for nm in wb.sheetnames:
        a = [[norm(c) for c in r] for r in wb[nm].iter_rows(values_only=True)]
        b = list(bk.rows(nm))
        w = max(len(r) for r in a + b)
        same = same and [list(r) + [None] * (w - len(r)) for r in a] == [r + [None] * (w - len(r)) for r in b]
    bk.close()
    wb.close()
    check(f"regex reader == openpyxl values ({label})", same)

# ---------------------------------------------------------------- 4. fix1: lock, per-day errors, state per day, cleanup
from common import proc_created  # noqa: E402

D6, D5 = date(2026, 11, 6), date(2026, 11, 5)


def add_day(d, v, rid):
    ymd = d.strftime("%Y%m%d")
    rel = f"exports/du_bao/{ymd}/du_bao_{ymd}_v{v}.xlsx"
    rows = small_rows(d)
    sha = gen.write_file(DATA / rel, d, rows)
    gen.make_db(DB, [(rid, d.isoformat(), v, rel, sha, len(rows), gen.old_ts())])
    shutil.copyfile(DATA / rel, DATA / "exports" / "du_bao" / ymd / f"du_bao_{ymd}.xlsx")


def latest_of(d):
    ymd = d.strftime("%Y%m%d")
    return read_out(DATA / "exports" / "du_bao" / ymd / f"du_bao_{ymd}.xlsx")


def reset():
    shutil.rmtree(DATA, ignore_errors=True)
    shutil.rmtree(WORK, ignore_errors=True)
    add_day(D6, 1, "A6")
    add_day(D5, 1, "A5")


NOW6 = "2026-11-06 08:00"
LOCK = WORK / "excel20.lock"
STATE = WORK / "state.json"
reset()
WORK.mkdir(parents=True)
LOCK.write_text(json.dumps({"pid": os.getpid(), "created": proc_created(os.getpid())}), encoding="utf-8")
rc = run(now=NOW6)
check("lock of a live pass (fresh): no work", rc == 0 and not STATE.exists() and LOCK.exists())
LOCK.write_text("", encoding="utf-8")
rc = run(now=NOW6)
check("fresh empty lock (being written): held", rc == 0 and not STATE.exists())
old = time.time() - 40 * 60
os.utime(LOCK, (old, old))
rc = run(now=NOW6)
check("lock older than 35 min: stale, pass runs, lock removed", rc == 0 and STATE.exists() and not LOCK.exists()
      and "older than 35 min" in (WORK / "excel20.log").read_text(encoding="utf-8"))
reset()
WORK.mkdir(parents=True)
LOCK.write_text(json.dumps({"pid": 999999, "created": 1}), encoding="utf-8")
rc = run(now=NOW6)
check("lock of a dead process: stale at once", rc == 0 and STATE.exists() and
      "process 999999 gone" in (WORK / "excel20.log").read_text(encoding="utf-8"))

# per-day exception: yesterday crashes (non-X20Error), today written, state saved, no repeats
reset()
calls = []
orig_rs = X.read_source


def boom(path, d):
    calls.append(d)
    if d == D5:
        raise RuntimeError("synthetic")
    return orig_rs(path, d)


X.read_source = boom
n = len(SENT)
rc = run(now=NOW6)
st = json.loads(STATE.read_text(encoding="utf-8"))
new = SENT[n:]
check("crash of one day: rc 1, other day written, failed recorded",
      rc == 1 and "DU_BAO_BD" in latest_of(D6) and "DU_BAO" in latest_of(D5) and st["days"]["20261106"]["version"] == 1
      and st["days"]["20261105"]["failed"]["code"] == "CRASH_RuntimeError")
check("notifications: 1 done + 1 high", [x[2] for x in new] == ["default", "high"] and "Da tao" in new[0][0])
check("notification path from export_runs folder", new[0][1].startswith("exports/du_bao/20261106/du_bao_20261106.xlsx"))
n, c = len(SENT), len(calls)
rc = run(now=NOW6)
check("next pass: no duplicate done, no re-notify, failed sha not retried",
      len(SENT) == n and len(calls) == c and rc == 0)
rc = run("--force", now=NOW6)
check("--force retries the failed version", len(calls) == c + 2)
X.read_source = orig_rs

# a BaseException after the first day: the first day's state is already on disk
reset()
orig_pd = X.process_day


def stop(conn, data_dir, d, state, writer):
    if d == D5:
        raise KeyboardInterrupt
    return orig_pd(conn, data_dir, d, state, writer)


X.process_day = stop
try:
    run(now=NOW6)
except KeyboardInterrupt:
    pass
X.process_day = orig_pd
st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
check("state saved after each day (interrupted pass keeps day 1)",
      (st.get("days") or {}).get("20261106", {}).get("version") == 1 and not LOCK.exists())
n = len(SENT)
run(now=NOW6)
check("no duplicate 'Da tao' for the saved day", not any("Da tao" in x[0] and "20261106" in x[1] for x in SENT[n:]))

# stale .x20 temp files (> 1 h) removed, recent ones kept
f6 = DATA / "exports" / "du_bao" / "20261106"
stale, fresh = f6 / ".x20_du_bao_20261099.tmp", f6 / ".x20_du_bao_20261098.tmp"
stale.write_bytes(b"x")
fresh.write_bytes(b"x")
old = time.time() - 2 * 3600
os.utime(stale, (old, old))
run(now=NOW6)
check("stale .x20 temp removed, recent kept", not stale.exists() and fresh.exists())

print(f"\n{sum(ok for _, ok in RES)} passed, {sum(not ok for _, ok in RES)} failed")
if all(ok for _, ok in RES):
    shutil.rmtree(T, ignore_errors=True)  # kept on failure for the diagnosis
sys.exit(0 if all(ok for _, ok in RES) else 1)
