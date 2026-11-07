"""Exit 0 when tonight's production run of the business day is completely done, else 1 (owner 06/11/2026: heavy jobs
that do NOT write production run again as soon as the night run is finished, without waiting until 03:45).
Read-only (live DB opened mode=ro). "Done" for the Vietnam business day D (today):
  1. a D1_SYNC job SUCCEEDED, started on day D (Vietnam time), watermark = D - 1;
  2. a FORECAST_REFRESH job SUCCEEDED for business_date D with result status PUBLISHED (the SEL2 run);
  3. the daily Excel of D is exported and checked: newest export_runs row of D exists, its file exists with the
     recorded sha256, and the latest copy du_bao_YYYYMMDD.xlsx exists;
  4. Monday only: the weekly training of the candidates (CANDIDATE_TRAIN) of origin D SUCCEEDED.
usage: night_done.py [--date YYYY-MM-DD]   (prints one line: DONE ... / NOT YET: <reason>)
The DB: env DF_OPS_LIVE_DB, else ops_config (repo copy), else <data_dir of storage.json>\\db\\app.db."""
import hashlib
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

VN = timezone(timedelta(hours=7))


def _db_and_data():
    if os.environ.get("DF_OPS_LIVE_DB"):
        db = Path(os.environ["DF_OPS_LIVE_DB"])
        return db, db.parent.parent
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import ops_config  # noqa: E402  (repo copy)
        d = ops_config.data_dir()
        return Path(ops_config.live_db_uri()[5:].split("?")[0]), d
    except ImportError:
        st = Path(os.environ.get("LOCALAPPDATA", "")) / "DemandForecast" / "storage.json"
        d = Path(json.loads(st.read_text(encoding="utf-8-sig"))["data_dir"])
        return d / "db" / "app.db", d


def _res(row_json):
    o = json.loads(row_json or "{}")
    return o.get("result") if isinstance(o.get("result"), dict) else o


def check(d: date, db: Path, data: Path):
    c = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=30)
    try:
        start_utc = datetime(d.year, d.month, d.day, tzinfo=VN).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        d1 = [r for r in c.execute("SELECT result_json FROM job_runs WHERE job_type='D1_SYNC' AND status='SUCCEEDED' "
                                   "AND started_at >= ? ORDER BY started_at DESC, rowid DESC", (start_utc,))
              if _res(r[0]).get("watermark") == (d - timedelta(days=1)).isoformat()]
        if not d1:
            return False, f"D-1 of {d} not succeeded yet"
        ref = [r for r in c.execute("SELECT result_json FROM job_runs WHERE job_type='FORECAST_REFRESH' AND "
                                    "status='SUCCEEDED' AND started_at >= ? ORDER BY started_at DESC, rowid DESC",
                                    (start_utc,))
               if _res(r[0]).get("business_date") == d.isoformat() and _res(r[0]).get("status") == "PUBLISHED"]
        if not ref:
            return False, f"SEL2 refresh of {d} not published yet"
        ex = c.execute("SELECT version, path, sha256, n_rows FROM export_runs WHERE forecast_date=? "
                       "ORDER BY created_at DESC, rowid DESC LIMIT 1", (d.isoformat(),)).fetchone()
        if not ex:
            return False, f"daily Excel of {d} not exported yet"
        f = data / ex[1]
        if not f.is_file() and f.with_name(f.stem + "_bo" + f.suffix).is_file():
            f = f.with_name(f.stem + "_bo" + f.suffix)   # 1.4.5: renamed by a newer export killed before its record
        if not f.is_file():
            return False, f"Excel file v{ex[0]} missing"
        h = hashlib.sha256()
        with open(f, "rb") as fh:
            for b in iter(lambda: fh.read(1 << 20), b""):
                h.update(b)
        if h.hexdigest().upper() != (ex[2] or "").upper():
            return False, f"Excel v{ex[0]} sha256 differs from export_runs (still being written?)"
        if not (f.parent / f"du_bao_{d:%Y%m%d}.xlsx").is_file():
            return False, "latest copy of the daily Excel missing"
        if d.weekday() == 0:
            tr = [r for r in c.execute("SELECT result_json FROM job_runs WHERE job_type='CANDIDATE_TRAIN' AND "
                                       "status='SUCCEEDED' AND started_at >= ?", (start_utc,))
                  if (json.loads(r[0] or "{}").get("params") or {}).get("origin") == d.isoformat()]
            if not tr:
                return False, f"Monday: weekly training of origin {d} not finished yet"
        return True, f"DONE {d}: D-1 ok, SEL2 published, Excel v{ex[0]} ({ex[3]} rows) checked" + \
            (", weekly training done" if d.weekday() == 0 else "")
    finally:
        c.close()


def main(argv):
    d = date.fromisoformat(argv[argv.index("--date") + 1]) if "--date" in argv else datetime.now(VN).date()
    db, data = _db_and_data()
    ok, why = check(d, db, data)
    print(why if ok else f"NOT YET: {why}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
