-- 0006 (v1.2.6): 90-day retention of the end-of-day forecast backup (owner decision 18/10/2026). No existing row is
-- modified or deleted by this migration; nothing is cleaned up when it runs (deletion is a separate, explicit operator
-- step: app.cli eod-retention, dry run unless --apply, see eod_retention.py and docs/LICH-SU-FORECAST.md section 14).
--
-- 0005 forbade every DELETE on the backup tables. Two of its triggers are replaced (in this one transaction, so the
-- tables are never unprotected) by triggers that still refuse every DELETE EXCEPT the retention path:
--   * a permit row in forecast_eod_snapshot_retention, state DELETING, for exactly that snapshot (id, scope, day),
--     that is the most recent insert of the deleting connection (seq = last_insert_rowid()). eod_retention.py gives
--     each permit a random 62-bit seq, so no insert into another table matches it in practice: the permit is usable
--     only by the connection that wrote it, and any other insert on that connection voids it;
--   * the snapshot's business date is older than the permit's cutoff AND older than today (Vietnam, UTC+7 without
--     daylight saving) minus 90 days, computed by the database itself: a snapshot younger than 90 days can never be
--     deleted, whatever the application computes;
--   * values first, then the header (a header with values left is refused).
-- The permit row stays as the record of the deletion (tombstone: what was deleted, when, by which run) and is never
-- deleted; it ends DELETED only when the snapshot and its values are really gone. Retention never touches
-- forecast_values, the D+1 history, actual_closes or any other table.

CREATE TABLE forecast_eod_snapshot_retention (
    seq                  INTEGER PRIMARY KEY AUTOINCREMENT,   -- permit identity (never reused: rows are never deleted)
    run_id               TEXT NOT NULL,          -- one cleanup run (several snapshots, one transaction each)
    snapshot_id          TEXT NOT NULL UNIQUE,   -- the deleted snapshot (no foreign key: this row outlives it)
    scope_key            TEXT NOT NULL,
    data_source          TEXT NOT NULL,
    business_date        TEXT NOT NULL,
    first_target_date    TEXT NOT NULL,
    last_target_date     TEXT NOT NULL,
    snapshot_status      TEXT NOT NULL,          -- COMPLETE | INCOMPLETE | NO_SOURCE (copied from the snapshot)
    source_run_id        TEXT,
    source_run_date      TEXT,
    n_rows               INTEGER NOT NULL,       -- values recorded by the snapshot header
    values_sha256        TEXT,
    total_yhat           REAL,
    snapshot_created_at  TEXT NOT NULL,
    policy_days          INTEGER NOT NULL CHECK (policy_days >= 90),
    cutoff_date          TEXT NOT NULL,          -- deleted because business_date < cutoff_date = today (Vietnam) - policy_days
    state                TEXT NOT NULL CHECK (state IN ('DELETING','DELETED')),
    rows_deleted         INTEGER,                -- values actually deleted (= n_rows)
    requested_by         TEXT NOT NULL,          -- CLI
    backup_file          TEXT,                   -- verified backup taken before the run
    started_at           TEXT NOT NULL,          -- UTC
    finished_at          TEXT                    -- UTC
);
CREATE INDEX ix_fesr_scope_day ON forecast_eod_snapshot_retention(scope_key, business_date);

-- a permit names an existing snapshot exactly, is older than the database's own 90-day floor, and is the only open one
CREATE TRIGGER trg_fesr_insert_checked BEFORE INSERT ON forecast_eod_snapshot_retention
WHEN NEW.state IS NOT 'DELETING'
  OR NOT EXISTS (SELECT 1 FROM forecast_eod_snapshots s WHERE s.id = NEW.snapshot_id AND s.scope_key = NEW.scope_key
                 AND s.business_date = NEW.business_date AND s.status = NEW.snapshot_status AND s.n_rows = NEW.n_rows)
  OR NOT (NEW.business_date < NEW.cutoff_date)
  OR NOT (NEW.cutoff_date <= date('now', '+7 hours', '-90 days'))
  OR EXISTS (SELECT 1 FROM forecast_eod_snapshot_retention r WHERE r.state = 'DELETING')
BEGIN SELECT RAISE(ABORT, 'retention permit refused: unknown snapshot, younger than 90 days or another permit open'); END;
CREATE TRIGGER trg_fesr_keys_fixed BEFORE UPDATE OF seq, run_id, snapshot_id, scope_key, data_source, business_date,
    first_target_date, last_target_date, snapshot_status, source_run_id, source_run_date, n_rows, values_sha256,
    total_yhat, snapshot_created_at, policy_days, cutoff_date, requested_by, backup_file, started_at
    ON forecast_eod_snapshot_retention
BEGIN SELECT RAISE(ABORT, 'forecast_eod_snapshot_retention records never change'); END;
-- DELETING -> DELETED only, and only once the snapshot and every value are gone
CREATE TRIGGER trg_fesr_finish_only BEFORE UPDATE ON forecast_eod_snapshot_retention
WHEN NOT (OLD.state = 'DELETING' AND NEW.state = 'DELETED')
  OR EXISTS (SELECT 1 FROM forecast_eod_snapshots s WHERE s.id = OLD.snapshot_id)
  OR EXISTS (SELECT 1 FROM forecast_eod_snapshot_values v WHERE v.snapshot_id = OLD.snapshot_id)
BEGIN SELECT RAISE(ABORT, 'a retention record ends DELETED once, after its snapshot is gone'); END;
CREATE TRIGGER trg_fesr_no_delete BEFORE DELETE ON forecast_eod_snapshot_retention
BEGIN SELECT RAISE(ABORT, 'forecast_eod_snapshot_retention records are never deleted'); END;

-- INSERT OR REPLACE deletes the row it collides with WITHOUT firing delete triggers (SQLite fires them during REPLACE
-- only under PRAGMA recursive_triggers, which the app does not set). So on every 1.2.6 table an insert whose key
-- already exists is refused before the conflict is resolved; a plain duplicate insert failed already (UNIQUE / PK).
CREATE TRIGGER trg_fesr_no_replace BEFORE INSERT ON forecast_eod_snapshot_retention
WHEN EXISTS (SELECT 1 FROM forecast_eod_snapshot_retention r WHERE r.seq = NEW.seq)
  OR EXISTS (SELECT 1 FROM forecast_eod_snapshot_retention r WHERE r.snapshot_id = NEW.snapshot_id)
BEGIN SELECT RAISE(ABORT, 'forecast_eod_snapshot_retention: key exists (never replaced)'); END;
CREATE TRIGGER trg_fes_no_replace BEFORE INSERT ON forecast_eod_snapshots
WHEN EXISTS (SELECT 1 FROM forecast_eod_snapshots s WHERE s.id = NEW.id)
  OR EXISTS (SELECT 1 FROM forecast_eod_snapshots s WHERE s.scope_key = NEW.scope_key AND s.business_date = NEW.business_date)
BEGIN SELECT RAISE(ABORT, 'forecast_eod_snapshots: key exists (never replaced)'); END;
CREATE TRIGGER trg_fes_values_no_replace BEFORE INSERT ON forecast_eod_snapshot_values
WHEN EXISTS (SELECT 1 FROM forecast_eod_snapshot_values v WHERE v.snapshot_id = NEW.snapshot_id
             AND v.target_date = NEW.target_date AND v.sku_id = NEW.sku_id AND v.fc_id = NEW.fc_id)
BEGIN SELECT RAISE(ABORT, 'forecast_eod_snapshot_values: key exists (never replaced)'); END;
CREATE TRIGGER trg_actual_closes_no_replace BEFORE INSERT ON actual_closes
WHEN EXISTS (SELECT 1 FROM actual_closes a WHERE a.id = NEW.id)
  OR EXISTS (SELECT 1 FROM actual_closes a WHERE a.scope_key = NEW.scope_key AND a.business_date = NEW.business_date
             AND a.revision = NEW.revision)
BEGIN SELECT RAISE(ABORT, 'actual_closes: key exists (never replaced)'); END;
CREATE TRIGGER trg_actual_close_values_no_replace BEFORE INSERT ON actual_close_values
WHEN EXISTS (SELECT 1 FROM actual_close_values v WHERE v.close_id = NEW.close_id AND v.sku_id = NEW.sku_id
             AND v.fc_id = NEW.fc_id)
BEGIN SELECT RAISE(ABORT, 'actual_close_values: key exists (never replaced)'); END;

DROP TRIGGER trg_fes_values_no_delete;
CREATE TRIGGER trg_fes_values_delete_retention_only BEFORE DELETE ON forecast_eod_snapshot_values
WHEN NOT EXISTS (SELECT 1 FROM forecast_eod_snapshot_retention r JOIN forecast_eod_snapshots s ON s.id = r.snapshot_id
                 WHERE r.seq = last_insert_rowid() AND r.state = 'DELETING' AND r.snapshot_id = OLD.snapshot_id
                   AND s.business_date < r.cutoff_date AND s.business_date < date('now', '+7 hours', '-90 days'))
BEGIN SELECT RAISE(ABORT, 'forecast_eod_snapshot_values are deleted only by the 90-day retention'); END;

DROP TRIGGER trg_fes_no_delete;
CREATE TRIGGER trg_fes_delete_retention_only BEFORE DELETE ON forecast_eod_snapshots
WHEN NOT EXISTS (SELECT 1 FROM forecast_eod_snapshot_retention r
                 WHERE r.seq = last_insert_rowid() AND r.state = 'DELETING' AND r.snapshot_id = OLD.id
                   AND r.scope_key = OLD.scope_key AND r.business_date = OLD.business_date
                   AND OLD.business_date < r.cutoff_date AND OLD.business_date < date('now', '+7 hours', '-90 days'))
  OR EXISTS (SELECT 1 FROM forecast_eod_snapshot_values v WHERE v.snapshot_id = OLD.id)
BEGIN SELECT RAISE(ABORT, 'forecast_eod_snapshots are deleted only by the 90-day retention, after their values'); END;
