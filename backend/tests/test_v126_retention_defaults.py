"""1.2.6 blocker resolution: 90-day retention of the end-of-day forecast backup (migration 0006, eod_retention.py, CLI
eod-retention), the two day-end flows OFF by default (also for a stored 1.2.5 schedule without their keys) and the real
behaviour of EOD_SNAPSHOT_VERIFY_FAILED (FAILED, ERROR alert, no automatic retry, nothing stored).

Kind of evidence: integration on an isolated database (conftest: temporary DF_DATA_DIR per test + process-wide
fallback; the first fixture asserts the database is not the live one). Retention tests run on the REAL clock: the
database computes its own 90-day floor from date('now'), so a Python clock frozen ahead of the real one would be refused
by the triggers (as designed). Snapshots are made by forecast_backup.create from synthetic published runs."""
import hashlib
import json
import sqlite3
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import cli, data_checks, db, eod_retention as er, forecast_backup as fb, forecast_history as fh, paths, timeutil
from app import messages, settings_service as ss
from app.jobs import runner
from app.jobs.scheduler import Scheduler, plan
from app.messages import AppError

import test_v125_forecast_history as t125

SCOPE = "BIGQUERY:test-project-1.d.t"          # = bigquery_scope_key of the settings made by _bq_active()
OTHER = "BIGQUERY:test-project-1.d.other"
LIVE_DATA = Path(r"D:\Buymed\Lightgbm AI\data")
KEYS = (("S1", "HN"), ("S2", "HN"), ("S1", "BD"))       # 3 series -> a COMPLETE snapshot holds 7 x 3 = 21 values
VN = timeutil.VN_TZ
DAY_END = ("EOD_FORECAST_SNAPSHOT", "ACTUAL_CLOSE")
# schedule as saved by 1.2.5 on production (18/10/2026): no eod_* / close_* key
STORED_125 = {"enabled": True, "d1_enabled": True, "d0_enabled": True, "train_enabled": True,
              "d1_enabled_at": "2026-10-17T23:06:00+07:00", "d0_enabled_at": "2026-10-17T23:06:00+07:00",
              "train_enabled_at": None, "d0_times": ["08:00", "10:00", "12:00", "14:00", "16:00", "18:00"],
              "d1_signal_poll_start": "03:00", "d1_poll_interval_minutes": 30, "d1_fallback_time": "05:00",
              "train_time": "09:00", "slot_grace_minutes": 20, "d0_catchup_policy": "LATEST_ONCE",
              "train_catchup_policy": "SKIP", "max_attempts": 4, "retry_base_seconds": 60, "retry_max_seconds": 1800,
              "timeout_seconds": 3600, "max_catchup_jobs_per_tick": 1}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    p = paths.db_path().resolve()
    assert not p.is_relative_to(LIVE_DATA.resolve()) and ("pytest-" in str(p) or "df-tests-" in str(p)), p
    timeutil.set_now_override(None)       # real clock (module docstring)
    # cli --apply configures the process-wide console log on the CURRENT stdout (pytest's capture of this test, closed
    # afterwards): not here, so later tests do not log into a closed stream
    from app import logging_setup
    monkeypatch.setattr(logging_setup, "setup_logging", lambda *a, **k: None)
    yield
    timeutil.set_now_override(None)


def _at(vn: datetime):
    timeutil.set_now_override(lambda: vn.astimezone(timezone.utc))


def _d(days_back: int) -> str:
    return str(timeutil.today_vn() - timedelta(days=days_back))


def _source(back: int = 130, horizon: int = 150) -> str:
    """One published run created `back` days ago, covering the next `horizon` days, recorded in the history."""
    rid = t125._run(f"{_d(back)} 09:00", origin=_d(back), horizon=horizon, keys=KEYS, scope=SCOPE)
    fh.capture(rid)
    return rid


def _snap(days_back: int, scope: str = SCOPE) -> dict:
    return fb.create(scope, "BIGQUERY", _d(days_back))


NEW_0007 = {"open_hours", "open_hours_status"}     # 1.2.9: additive nullable columns of demand_daily (NULL checked apart)


def _fp_all() -> dict:
    """Row count + sha256 of every table of the database (the columns that existed before 0007)."""
    out = {}
    with db.read() as c:
        for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
            cols = [r[1] for r in c.execute(f'PRAGMA table_info("{t}")') if not (t == "demand_daily" and r[1] in NEW_0007)]
            sel = ", ".join(f'"{x}"' for x in cols)
            lines = sorted(repr(tuple(r)) for r in c.execute(f'SELECT {sel} FROM "{t}"'))
            out[t] = (len(lines), hashlib.sha256("\n".join(lines).encode()).hexdigest())
    return out


def _cli(capsys, *args):
    code = cli.main(["eod-retention", *args])
    out = capsys.readouterr().out          # --apply logs one-line JSON first; a result is indented, a refusal one line
    i = out.find("{\n")
    body = out[i:] if i >= 0 else out.strip().splitlines()[-1]
    return code, json.loads(body[:body.rindex("}") + 1])


def _rows(sql, p=()):
    with db.read() as c:
        return db.rows(c, sql, p)


def _checks(target=None) -> dict:
    return {x["check"]: x for x in data_checks.run(target or paths.db_path())["checks"]}


def _db_at(target: Path, version: int):
    """A database built by the migrations up to `version` only (what an older release left behind)."""
    conn = db.connect(target, create=True)
    db.current_version(conn)
    for v, p in db.available_migrations():
        if v > version:
            break
        for stmt in db._split_sql(p.read_text(encoding="utf-8")):
            conn.execute(stmt)
        conn.execute("INSERT INTO schema_migrations(version, name, applied_at) VALUES (?,?,?)", (v, p.name, "x"))
    conn.close()


def _triggers() -> set[str]:
    return {r["name"] for r in _rows("SELECT name FROM sqlite_master WHERE type='trigger'")}


def _store_125_schedule():
    with db.tx() as c:
        c.execute("INSERT INTO app_settings(section, value_json, updated_at) VALUES ('schedule', ?, 'x') "
                  "ON CONFLICT(section) DO UPDATE SET value_json=excluded.value_json", (json.dumps(STORED_125),))


def _bq_active():
    ss.update("bigquery", {"project_id": "test-project-1", "dataset_id": "d", "source_table": "t"})
    ss.update("general", {"active_source": "BIGQUERY"})


# ------------------------------------------------------------------ A. migration 0006
def test_migration_0006_from_v4_and_from_v5_keeps_every_row_and_deletes_nothing(tmp_path, monkeypatch):
    for start in (4, 5):
        target = tmp_path / f"v{start}.db"
        _db_at(target, start)
        with monkeypatch.context() as m:          # never monkeypatch.undo(): conftest's isolation must stay in place
            m.setattr(paths, "db_path", lambda: target)
            _source()
            if start == 5:                         # a 1.2.6 database: one snapshot already older than 90 days
                assert [_snap(k)["status"] for k in (100, 3)] == ["COMPLETE", "COMPLETE"]
            before = _fp_all()
            res = db.migrate(target)
            assert (res["from"], res["to"]) == (start, 9)                        # 1.2.9: + 0007, 0008, 0009 (additive)
            assert res["applied"] == ["0005_eod_backup_actual_close.sql", "0006_eod_snapshot_retention.sql",
                                      "0007_open_hours.sql", "0008_customer_aggregates.sql",
                                      "0009_actual_finalization.sql"][start - 4:]
            assert _rows("SELECT COUNT(*) AS n FROM demand_daily WHERE open_hours IS NOT NULL OR "
                         "open_hours_status IS NOT NULL")[0]["n"] == 0                     # nothing invented
            assert db.migrate(target)["applied"] == []                          # running it again changes nothing
            after = _fp_all()
            assert {t: v for t, v in after.items() if t in before and t != "schema_migrations"} == \
                   {t: v for t, v in before.items() if t != "schema_migrations"}
            assert all(after[t][0] == 0 for t in set(after) - set(before))       # new tables start empty
            trig = _triggers()
            assert not {"trg_fes_no_delete", "trg_fes_values_no_delete"} & trig
            assert {"trg_fes_delete_retention_only", "trg_fes_values_delete_retention_only", "trg_fesr_insert_checked",
                    "trg_fesr_keys_fixed", "trg_fesr_finish_only", "trg_fesr_no_delete", "trg_fes_complete_fixed",
                    "trg_fes_keys_fixed", "trg_fes_values_no_update", "trg_fes_values_complete_only"} <= trig
            chk = _checks(target)
            assert chk["eod_snapshot_retention_records"]["status"] == "OK"
            # the expired snapshot is reported, not deleted: deletion is a separate operator step
            assert chk["eod_snapshot_retention_due"]["count"] == (1 if start == 5 else 0)


def test_a_failed_0006_leaves_schema_5_with_the_0005_protection(tmp_path, monkeypatch):
    target = tmp_path / "v5.db"
    _db_at(target, 5)
    broken = tmp_path / "migrations"
    broken.mkdir()
    for v, p in db.available_migrations():
        txt = p.read_text(encoding="utf-8")
        if v == 6:      # fails at its LAST statement, after the two 0005 triggers were dropped and replaced
            txt += "\nCREATE TABLE forecast_runs (x INTEGER);\n"
        (broken / p.name).write_text(txt, encoding="utf-8")
    with monkeypatch.context() as m:
        m.setattr(paths, "db_path", lambda: target)
        _source()
        snap = _snap(100)
        before, trig0 = _fp_all(), _triggers()
        m.setattr(db, "MIGRATIONS_DIR", broken)
        with pytest.raises(db.MigrationError, match="0006_eod_snapshot_retention.sql failed"):
            db.migrate(target)
        assert _rows("SELECT MAX(version) AS v FROM schema_migrations")[0]["v"] == 5
        assert _fp_all() == before and _triggers() == trig0                   # the whole migration rolled back
        with pytest.raises(sqlite3.IntegrityError, match="never deleted"):    # 0005 still refuses every delete
            with db.tx() as c:
                c.execute("DELETE FROM forecast_eod_snapshots WHERE id=?", (snap["id"],))
    with monkeypatch.context() as m:
        m.setattr(paths, "db_path", lambda: target)
        assert db.migrate(target)["applied"] == ["0006_eod_snapshot_retention.sql", "0007_open_hours.sql",
                                                 "0008_customer_aggregates.sql", "0009_actual_finalization.sql"]
        assert _rows("SELECT COUNT(*) AS n FROM forecast_eod_snapshot_values")[0]["n"] == 21


# ------------------------------------------------------------------ B. retention: dry run, apply, holds, triggers
def test_the_dry_run_is_the_default_reads_only_and_keeps_a_snapshot_exactly_90_days_old(capsys):
    _source()
    assert [_snap(k)["status"] for k in (100, 91, 90, 89, 5)] == ["COMPLETE"] * 5
    before = _fp_all()
    code, out = _cli(capsys)                       # no flag at all = dry run on the configured database
    assert code == 0 and out["mode"] == "DRY_RUN" and out["written"] is False and out["apply_ready"] is True
    assert (out["today"], out["cutoff_date"], out["policy_days"], out["timezone"]) == (
        _d(0), _d(90), 90, "Asia/Ho_Chi_Minh")
    assert [i["business_date"] for i in out["delete"]["items"]] == [_d(100), _d(91)]
    assert out["delete"]["rows"] == 42 and out["delete"]["by_status"] == {"COMPLETE": 2}
    assert (out["delete"]["first_business_date"], out["delete"]["last_business_date"]) == (_d(100), _d(91))
    assert out["kept"] == {"snapshots": 3, "rows": 63, "first_business_date": _d(90)}     # 90 days old: kept
    assert out["held"] == [] and out["refused"] is None and len(out["plan_id"]) == 16
    code, again = _cli(capsys, "--db", str(paths.db_path()))
    assert code == 0 and again["plan_id"] == out["plan_id"]                  # same plan, same id
    assert _fp_all() == before                                               # neither dry run wrote anything


def test_apply_deletes_exactly_the_reviewed_plan_after_a_verified_backup(capsys, tmp_path):
    _source()
    for k in (100, 91, 90, 5):
        _snap(k)
    assert fb.create(OTHER, "BIGQUERY", _d(120))["status"] == "NO_SOURCE"      # header only, no value
    with db.read() as c:
        p = er.plan(c)
    assert [i["business_date"] for i in p["delete"]["items"]] == [_d(120), _d(100), _d(91)]
    assert p["delete"]["by_status"] == {"NO_SOURCE": 1, "COMPLETE": 2} and p["delete"]["rows"] == 42
    untouched = {t: v for t, v in _fp_all().items() if t not in (
        "forecast_eod_snapshots", "forecast_eod_snapshot_values", "forecast_eod_snapshot_retention", "audit_log")}
    with pytest.raises(AppError) as e:                                       # not the reviewed plan: refused
        er.apply("0" * 16)
    assert e.value.code == "EOD_RETENTION_PLAN_CHANGED"
    assert _cli(capsys, "--apply")[0] == 2                                   # --apply without --plan: refused
    assert _cli(capsys, "--apply", "--plan", p["plan_id"], "--db", str(paths.db_path()))[0] == 2
    assert len(_rows("SELECT id FROM forecast_eod_snapshots")) == 5 and not list(paths.backups_dir().glob("*retention*"))

    code, out = _cli(capsys, "--apply", "--plan", p["plan_id"])
    assert code == 0 and out["mode"] == "APPLY" and out["error"] is None
    assert [(x["business_date"], x["result"], x["rows"]) for x in out["deleted"]] == [
        (_d(120), "DELETED", 0), (_d(100), "DELETED", 21), (_d(91), "DELETED", 21)]
    bk = Path(out["backup_file"])
    assert bk.is_file() and bk.parent == paths.backups_dir() and "pre-eod-retention" in bk.name
    with zipfile.ZipFile(bk) as z:                                           # the backup holds the state before
        z.extract("db/app.db", tmp_path)
    b = sqlite3.connect(tmp_path / "db" / "app.db")
    assert b.execute("SELECT COUNT(*), (SELECT COUNT(*) FROM forecast_eod_snapshot_values) FROM "
                     "forecast_eod_snapshots").fetchone() == (5, 84)
    b.close()
    assert [r["business_date"] for r in _rows("SELECT business_date FROM forecast_eod_snapshots "
                                              "ORDER BY business_date")] == [_d(90), _d(5)]
    recs = _rows("SELECT * FROM forecast_eod_snapshot_retention ORDER BY business_date")
    assert all(r["seq"] >= 1 << 61 for r in recs)                           # random 62-bit permit identities
    assert [(r["business_date"], r["state"], r["rows_deleted"], r["cutoff_date"], r["policy_days"]) for r in recs] == [
        (_d(120), "DELETED", 0, _d(90), 90), (_d(100), "DELETED", 21, _d(90), 90), (_d(91), "DELETED", 21, _d(90), 90)]
    assert {(r["run_id"], r["backup_file"], r["requested_by"]) for r in recs} == {(out["run_id"], str(bk), "CLI")}
    aud = json.loads(_rows("SELECT details_json FROM audit_log WHERE action='EOD_SNAPSHOT_RETENTION'")[0]["details_json"])
    assert (aud["planned_snapshots"], aud["deleted_snapshots"], aud["deleted_rows"], aud["error"]) == (3, 3, 42, None)
    assert (aud["first_business_date"], aud["last_business_date"], aud["cutoff_date"]) == (_d(120), _d(91), _d(90))
    st = json.loads(_rows("SELECT details_json FROM audit_log WHERE action='EOD_SNAPSHOT_RETENTION_STARTED'")[0]
                    ["details_json"])
    assert (st["planned_snapshots"], st["planned_rows"], st["backup_file"]) == (3, 42, str(bk))
    assert {t: v for t, v in _fp_all().items() if t in untouched} == untouched   # forecasts, history, closes, jobs
    chk = _checks()
    assert chk["eod_snapshot_retention_records"]["status"] == "OK" and chk["eod_snapshot_retention_due"]["count"] == 0
    # again: an empty plan deletes nothing and takes no backup; the old plan id is refused
    code, again = _cli(capsys)
    assert code == 0 and again["delete"]["snapshots"] == 0
    with pytest.raises(AppError):
        er.apply(p["plan_id"])
    res = er.apply(again["plan_id"])
    assert res["deleted"] == [] and res["backup_file"] is None and len(list(paths.backups_dir().glob("*retention*"))) == 1


def test_a_snapshot_still_shown_as_backup_inside_the_window_is_held():
    _source()
    old, new = _snap(95), _snap(85)        # gap: run dates T-90 and T-89 still show the snapshot of T-95
    with db.read() as c:
        p = er.plan(c)
        shown = {d["run_date"]: d["snapshot_id"] for d in fh.fallback_days(c, SCOPE)}
    assert [(h["id"], h["code"], h["run_dates"]) for h in p["held"]] == [
        (old["id"], "SERVES_BACKUP_INSIDE_WINDOW", [_d(90), _d(89)])]
    assert shown[_d(90)] == shown[_d(89)] == old["id"] and shown[_d(85)] == new["id"]
    assert p["delete"]["snapshots"] == 0
    assert _checks()["eod_snapshot_retention_due"]["count"] == 0             # held: nothing waits for deletion
    res = er.apply(p["plan_id"])
    assert res["deleted"] == [] and len(_rows("SELECT id FROM forecast_eod_snapshots")) == 2


def test_the_database_refuses_every_delete_outside_the_retention_path():
    _source()
    old, other, spare, young = _snap(100), _snap(101), _snap(102), _snap(5)
    permit = ("INSERT INTO forecast_eod_snapshot_retention(run_id, snapshot_id, scope_key, data_source, business_date, "
              "first_target_date, last_target_date, snapshot_status, n_rows, snapshot_created_at, policy_days, "
              "cutoff_date, state, requested_by, started_at) VALUES ('T',?,?,?,?,?,?,?,?,?,90,?,'DELETING','TEST','x')")

    def p(s, cutoff):
        return permit, (s["id"], s["scope_key"], s["data_source"], s["business_date"], s["first_target_date"],
                        s["last_target_date"], s["status"], s["n_rows"], s["created_at"], cutoff)

    def refused(*stmts):
        with pytest.raises(sqlite3.IntegrityError):
            with db.tx() as c:
                for sql, prm in stmts:
                    c.execute(sql, prm)

    def values(s):
        return ("DELETE FROM forecast_eod_snapshot_values WHERE snapshot_id=?", (s["id"],))

    def header(s):
        return ("DELETE FROM forecast_eod_snapshots WHERE id=?", (s["id"],))

    refused(values(old))                                       # a plain delete, even of an expired snapshot
    refused(header(old))
    refused(p(young, str(timeutil.today_vn() + timedelta(days=1))))      # younger than 90 days: no permit, any cutoff
    refused(p(old, _d(80)))                                    # a cutoff later than the database's 90-day floor
    refused(p(other, _d(90)), values(old))                     # a permit for one snapshot deletes no other
    refused(p(old, _d(90)), ("INSERT INTO audit_log(at, action, details_json) VALUES ('x', 'TEST', '{}')", ()),
            values(old))                                       # any other insert after the permit voids it
    refused(p(old, _d(90)), header(old))                       # the header only after its values
    with db.tx() as c:                                         # the retention path itself: values, header, DELETED
        c.execute(*p(old, _d(90)))
        c.execute(*values(old))
        c.execute(*header(old))
        c.execute("UPDATE forecast_eod_snapshot_retention SET state='DELETED', rows_deleted=21, finished_at='y' "
                  "WHERE snapshot_id=?", (old["id"],))
    refused(("DELETE FROM forecast_eod_snapshot_retention", ()))                       # records are permanent
    refused(("UPDATE forecast_eod_snapshot_retention SET cutoff_date='2099-01-01'", ()))
    refused(("UPDATE forecast_eod_snapshot_retention SET state='DELETING'", ()))
    # a permit left open by mistake (committed) is useless to any other connection, blocks new permits, is reported
    with db.tx() as c:
        c.execute(*p(other, _d(90)))
    refused(values(other))
    refused(p(spare, _d(90)))
    refused(("UPDATE forecast_eod_snapshot_retention SET state='DELETED' WHERE snapshot_id=?", (other["id"],)))
    assert _checks()["eod_snapshot_retention_records"]["status"] == "FAIL"
    left = {r["snapshot_id"]: r["n"] for r in _rows("SELECT snapshot_id, COUNT(*) AS n FROM forecast_eod_snapshot_values "
                                                    "GROUP BY snapshot_id")}
    assert left == {other["id"]: 21, spare["id"]: 21, young["id"]: 21}


def test_insert_or_replace_can_neither_overwrite_nor_delete_a_protected_row(tmp_path):
    # REPLACE deletes the colliding row without firing delete triggers (no PRAGMA recursive_triggers): refused up front
    _source()
    gone, other, keep = _snap(100), _snap(101), _snap(5)
    with db.read() as c:
        p = er.plan(c)
    assert {i["id"] for i in p["delete"]["items"]} == {gone["id"], other["id"]}
    # only `gone` is deleted through the real path (one tombstone); `other` stays expired and present
    er._delete_one(next(i for i in p["delete"]["items"] if i["id"] == gone["id"]), timeutil.today_vn(),
                   er.cutoff(), "RET-T", "none", "TEST")
    tomb = _rows("SELECT * FROM forecast_eod_snapshot_retention")[0]
    hdr = _rows("SELECT * FROM forecast_eod_snapshots WHERE id=?", (keep["id"],))[0]
    val = _rows("SELECT * FROM forecast_eod_snapshot_values WHERE snapshot_id=? LIMIT 1", (keep["id"],))[0]
    with db.tx() as c:
        c.execute("INSERT INTO actual_closes(id, scope_key, data_source, business_date, revision, kind, reason, n_rows, "
                  "status, cutoff_at, closed_at, timezone) VALUES ('ACL-T', ?, 'BIGQUERY', ?, 1, 'CLOSE', 'TEST', 1, "
                  "'CLOSED_UNVERIFIED', 'x', 'x', 'Asia/Ho_Chi_Minh')", (SCOPE, _d(2)))
        c.execute("INSERT INTO actual_close_values(close_id, sku_id, fc_id, qty) VALUES ('ACL-T', 'S1', 'HN', 3)")
    before = _fp_all()

    def replace(table, row):
        with pytest.raises(sqlite3.IntegrityError, match="never replaced"):
            with db.tx() as c:
                c.execute(f"INSERT OR REPLACE INTO {table}({', '.join(row)}) VALUES ({','.join('?' * len(row))})",
                          tuple(row.values()))

    replace("forecast_eod_snapshots", {**hdr, "total_yhat": 0.0})                         # same id
    replace("forecast_eod_snapshots", {**hdr, "id": "FES-OTHER", "total_yhat": 0.0})      # same scope + day
    replace("forecast_eod_snapshot_values", {**val, "yhat": 0.0})
    replace("forecast_eod_snapshot_retention", {**tomb, "snapshot_id": other["id"], "business_date": other["business_date"],
                                                "state": "DELETING", "n_rows": other["n_rows"]})   # same seq
    replace("actual_closes", {"id": "ACL-T", "scope_key": SCOPE, "data_source": "BIGQUERY", "business_date": _d(2),
                              "revision": 1, "kind": "CLOSE", "reason": "X", "n_rows": 0, "status": "CLOSED_NO_DATA",
                              "cutoff_at": "x", "closed_at": "x", "timezone": "Asia/Ho_Chi_Minh"})
    replace("actual_close_values", {"close_id": "ACL-T", "sku_id": "S1", "fc_id": "HN", "qty": 0})
    assert _fp_all() == before                                                # nothing replaced, nothing deleted
    assert _checks()["eod_backup_protection_triggers"]["status"] == "OK"
    # a dropped protection trigger is reported by data-check
    target = tmp_path / "v6.db"
    _db_at(target, 6)
    c = sqlite3.connect(target)
    c.execute("DROP TRIGGER trg_fes_no_replace")
    c.commit()
    c.close()
    chk = _checks(target)["eod_backup_protection_triggers"]
    assert chk["status"] == "FAIL" and chk["count"] == 1


def test_a_failure_rolls_back_that_snapshot_stops_the_run_and_is_recorded(capsys):
    _source()
    a, b, c3 = _snap(100), _snap(99), _snap(98)
    with db.tx() as c:          # test-only fault: the DELETED update of the 2nd snapshot fails, after its deletes
        c.execute(f"CREATE TRIGGER test_fault BEFORE UPDATE ON forecast_eod_snapshot_retention "
                  f"WHEN NEW.snapshot_id = '{b['id']}' BEGIN SELECT RAISE(ABORT, 'injected fault'); END")
    with db.read() as c:
        p = er.plan(c)
    code, out = _cli(capsys, "--apply", "--plan", p["plan_id"])
    assert code == 1 and out["error"]["snapshot_id"] == b["id"] and "injected fault" in out["error"]["error"]
    assert [x["id"] for x in out["deleted"]] == [a["id"]]                    # the run stopped at the failure
    left = {r["snapshot_id"]: r["n"] for r in _rows("SELECT snapshot_id, COUNT(*) AS n FROM forecast_eod_snapshot_values "
                                                    "GROUP BY snapshot_id")}
    assert left == {b["id"]: 21, c3["id"]: 21}                              # b rolled back completely
    assert [(r["snapshot_id"], r["state"]) for r in _rows("SELECT * FROM forecast_eod_snapshot_retention")] == [
        (a["id"], "DELETED")]                                                # no open permit left behind
    al = _rows("SELECT level, code FROM alerts WHERE code='EOD_RETENTION_FAILED'")
    aud = json.loads(_rows("SELECT details_json FROM audit_log WHERE action='EOD_SNAPSHOT_RETENTION'")[0]["details_json"])
    assert al == [{"level": "ERROR", "code": "EOD_RETENTION_FAILED"}]
    assert (aud["planned_snapshots"], aud["deleted_snapshots"], aud["error"]["snapshot_id"]) == (3, 1, b["id"])
    assert _checks()["eod_snapshot_retention_records"]["status"] == "OK"
    with db.tx() as c:
        c.execute("DROP TRIGGER test_fault")
    with db.read() as c:
        p2 = er.plan(c)
    assert [i["id"] for i in p2["delete"]["items"]] == [b["id"], c3["id"]]  # running again continues
    res = er.apply(p2["plan_id"])
    assert [x["result"] for x in res["deleted"]] == ["DELETED", "DELETED"] and res["error"] is None
    assert not _rows("SELECT * FROM forecast_eod_snapshots")


def test_the_cutoff_follows_the_vietnam_business_date():
    _at(datetime(2026, 10, 17, 18, 30, tzinfo=timezone.utc))     # already 18/10 01:30 in Vietnam
    assert er.cutoff() == date(2026, 7, 20)
    _at(datetime(2026, 10, 17, 16, 59, tzinfo=timezone.utc))     # still 17/10 23:59 in Vietnam
    assert er.cutoff() == date(2026, 7, 19)
    timeutil.set_now_override(None)
    with db.read() as c:                                          # the database floor uses the same Vietnam-date rule
        assert c.execute("SELECT date('now', '+7 hours', '-90 days')").fetchone()[0] == str(er.cutoff())


def test_after_retention_the_history_shows_the_day_as_missing_never_as_zero():
    _source()
    s = _snap(100)                          # serves run dates T-100 .. T-94 (no session, no other snapshot)
    with db.read() as c:
        q = fh.Query(c, SCOPE, run_from=_d(100), run_to=_d(95))
        before = q.daily()
    assert {x["forecast_source"] for x in before} == {fh.SNAPSHOT} and all(x["forecast"] > 0 for x in before)
    with db.read() as c:
        assert er.apply(er.plan(c)["plan_id"])["deleted"][0]["id"] == s["id"]
    with db.read() as c:
        q = fh.Query(c, SCOPE, run_from=_d(100), run_to=_d(95))
        daily = q.daily()
        k = q.kpi(daily)
    assert len(daily) == len(before)
    assert all(x["has_history"] is False and x["forecast"] is None and x["forecast_source"] is None for x in daily)
    assert k["forecast_total"] is None and k["n_rows"] == 0                  # missing, never 0


# ------------------------------------------------------------------ C. day-end flows OFF by default
def test_the_new_flows_are_off_by_default_and_for_a_stored_125_schedule(client, small_demo):
    assert (ss.ScheduleSettings().eod_enabled, ss.ScheduleSettings().close_enabled) == (False, False)
    _store_125_schedule()
    s = ss.get("schedule")
    assert (s.eod_enabled, s.close_enabled, s.eod_enabled_at, s.close_enabled_at) == (False, False, None, None)
    assert (s.eod_time, s.close_time) == ("23:55", "23:59")
    assert {k: getattr(s, k) for k in STORED_125} == STORED_125              # every saved choice kept as it was
    ov = client.get("/api/schedules").json()
    assert (ov["flows"]["eod"]["enabled"], ov["flows"]["close"]["enabled"]) == (False, False)
    assert ov["flows"]["d1"]["enabled"] and ov["flows"]["d0"]["enabled"] and ov["flows"]["train"]["enabled"]
    assert client.get("/api/system/status").status_code == 200
    seen = {"eod": "2026-10-01T00:00:00+07:00", "close": "2026-10-01T00:00:00+07:00"}
    on = s.model_copy(update={"eod_enabled": True, "close_enabled": True})
    for t in (datetime(2026, 10, 18, 3, 5, tzinfo=VN), datetime(2026, 10, 18, 9, 5, tzinfo=VN),
              datetime(2026, 10, 18, 16, 5, tzinfo=VN), datetime(2026, 10, 18, 23, 56, tzinfo=VN),
              datetime(2026, 10, 19, 0, 5, tzinfo=VN)):
        _at(t)
        with db.read() as c:
            off_acts = plan(t, s, "BIGQUERY", t - timedelta(minutes=1), c, seen)
            on_acts = plan(t, on, "BIGQUERY", t - timedelta(minutes=1), c, seen)
        assert not [a for a in off_acts if a["job_type"] in DAY_END]
        # D-1, D-0 and training plan exactly the same whether the day-end flows are on or off
        assert off_acts == [a for a in on_acts if a["job_type"] not in DAY_END]
    assert [a["key"] for a in on_acts if a["job_type"] in DAY_END] == ["EOD_FORECAST_SNAPSHOT:2026-10-18",
                                                                        "ACTUAL_CLOSE:2026-10-18"]


def test_restarts_with_the_flows_off_register_no_day_end_job(small_demo):
    ss.update("schedule", {"train_enabled": False})          # only the day-end slots are due at these times
    for t in (datetime(2026, 10, 18, 23, 56, tzinfo=VN), datetime(2026, 10, 19, 0, 5, tzinfo=VN),
              datetime(2026, 10, 19, 0, 5, 30, tzinfo=VN), datetime(2026, 10, 19, 23, 57, tzinfo=VN)):
        _at(t)
        Scheduler().tick(t, wait=True)                       # a new process each time (restart)
    assert not _rows("SELECT id FROM job_runs WHERE job_type IN ('EOD_FORECAST_SNAPSHOT','ACTUAL_CLOSE')")
    assert not _rows("SELECT id FROM forecast_eod_snapshots") and not _rows("SELECT id FROM actual_closes")
    assert (ss.get("schedule").eod_enabled, ss.get("schedule").close_enabled) == (False, False)


def test_a_saved_choice_is_kept_and_switching_on_never_back_dates(client, small_demo, monkeypatch):
    from app.jobs import scheduler as sched_mod
    from test_v126_schedule_config import RunningScheduler
    monkeypatch.setattr(sched_mod, "SCHEDULER", RunningScheduler())   # switching ON needs a confirming scheduler
    _at(datetime(2026, 10, 18, 12, 0, tzinfo=VN))
    r = client.put("/api/schedules/eod", json={"enabled": True})
    assert r.status_code == 200 and r.json()["enabled"] is True
    s = ss.get("schedule")
    assert s.eod_enabled and s.eod_enabled_at == "2026-10-18T12:00:00+07:00" and s.close_enabled is False
    db.migrate()                                             # nothing pending: nothing reset
    assert ss.get("schedule") == s
    t = datetime(2026, 10, 18, 23, 56, tzinfo=VN)
    with db.read() as c:
        acts = plan(t, ss.get("schedule"), "DEMO", None, c, {"eod": "2026-10-01T00:00:00+07:00",
                                                              "close": "2026-10-01T00:00:00+07:00"})
    # 17/10 23:55 is before the switch-on moment: never run; 18/10 23:55 runs once; the close stays OFF
    assert [(a["key"], a["trigger"]) for a in acts if a["job_type"] in DAY_END] == [
        ("EOD_FORECAST_SNAPSHOT:2026-10-18", "SCHEDULE")]
    assert client.put("/api/schedules/eod", json={"enabled": False}).json()["enabled"] is False
    assert (ss.get("schedule").eod_enabled, ss.get("schedule").eod_enabled_at) == (False, None)


def test_upgrading_a_v4_database_with_a_saved_125_schedule_keeps_the_new_flows_off(tmp_path, monkeypatch):
    target = tmp_path / "v4.db"
    _db_at(target, 4)
    with monkeypatch.context() as m:
        m.setattr(paths, "db_path", lambda: target)
        _store_125_schedule()
        assert db.migrate(target)["to"] == 9                 # 1.2.9: up to 0009 (seventh batch)
        s = ss.get("schedule")
        raw = json.loads(_rows("SELECT value_json FROM app_settings WHERE section='schedule'")[0]["value_json"])
    assert raw == STORED_125                                 # the migrations write no setting
    assert (s.eod_enabled, s.close_enabled) == (False, False)
    assert {k: getattr(s, k) for k in STORED_125} == STORED_125


# ------------------------------------------------------------------ D. F1: EOD_SNAPSHOT_VERIFY_FAILED
def test_a_verify_failure_ends_failed_with_an_alert_no_retry_and_nothing_stored(monkeypatch):
    _at(datetime(2026, 10, 18, 23, 56, tzinfo=VN))
    _bq_active()
    ss.update("schedule", {"eod_enabled": True, "train_enabled": False})
    fh.capture(t125._run("2026-10-18 09:00", origin="2026-10-18", horizon=15, keys=KEYS, scope=SCOPE))
    with monkeypatch.context() as m:          # never monkeypatch.undo()
        m.setattr(fb, "sum", lambda xs: -1.0, raising=False)    # the stored copy no longer matches the computed total
        r = runner.execute("EOD_FORECAST_SNAPSHOT", "EOD_FORECAST_SNAPSHOT:2026-10-18", "SCHEDULE", None,
                           {"business_date": "2026-10-18"})
    assert (r["status"], r["reason_code"], r["attempt"], r["next_attempt_at"]) == (
        "FAILED", "EOD_SNAPSHOT_VERIFY_FAILED", 1, None)
    assert not _rows("SELECT id FROM forecast_eod_snapshots") and not _rows("SELECT * FROM forecast_eod_snapshot_values")
    assert not _rows("SELECT id FROM audit_log WHERE action='EOD_FORECAST_SNAPSHOT'")
    assert _rows("SELECT level, code FROM alerts WHERE entity_id=?", (r["id"],)) == [
        {"level": "ERROR", "code": "EOD_SNAPSHOT_VERIFY_FAILED"}]
    # no automatic retry: the scheduler never plans that slot again and a second call does not run it
    t = datetime(2026, 10, 18, 23, 58, tzinfo=VN)
    with db.read() as c:
        acts = plan(t, ss.get("schedule"), "BIGQUERY", None, c, {"eod": "2026-10-01T00:00:00+07:00",
                                                                  "close": "2026-10-01T00:00:00+07:00"})
    assert not [a for a in acts if a["key"] == "EOD_FORECAST_SNAPSHOT:2026-10-18"]
    again = runner.execute("EOD_FORECAST_SNAPSHOT", "EOD_FORECAST_SNAPSHOT:2026-10-18", "RETRY")
    assert (again["status"], again["attempt"], again["note"]) == ("FAILED", 1, "RETRIES_EXHAUSTED")
    # the operator runs it by hand after checking: it succeeds, nothing had to be undone
    ok = fb.run_job(None, {"business_date": "2026-10-18"})
    assert ok["status"] == "SUCCEEDED" and ok["rows"] == 21
    m = messages.msg("EOD_SNAPSHOT_VERIFY_FAILED")
    assert "not retried automatically" in m["en"] and "không tự thử lại" in m["vi"] and "the job retries" not in m["en"]
