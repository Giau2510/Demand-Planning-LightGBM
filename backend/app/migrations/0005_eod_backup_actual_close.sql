-- 0005 (v1.2.6): additive only - new tables, no existing row is modified or deleted.
-- (1) End-of-day forecast backup: at the end of each business day (Vietnam time) a full copy of the next 7 forecast days
--     (business date + 1 .. + 7) of the newest official forecast session (forecast_history_days, run date <= that day).
--     It is a recovery copy: shown only for a run date that has no official session of its own; forecast_values and the
--     D+1 history stay the source of truth and are never written by it.
-- (2) Actual close at 23:59: per business day an independent copy of the actual read at the close (revision 1) and,
--     when data arrives or changes later, controlled revisions (2, 3, ...) with before/after figures. Nothing is ever
--     overwritten; the current figure on screen is still read from demand_daily / d0_snapshots (forecast_history.py).

CREATE TABLE forecast_eod_snapshots (
    id                         TEXT PRIMARY KEY,
    scope_key                  TEXT NOT NULL,
    data_source                TEXT NOT NULL,
    business_date              TEXT NOT NULL,   -- Vietnam day the snapshot represents (end of that day)
    first_target_date          TEXT NOT NULL,   -- business_date + 1
    last_target_date           TEXT NOT NULL,   -- business_date + n_days
    n_days                     INTEGER NOT NULL,
    source_run_id              TEXT REFERENCES forecast_runs(id),   -- NULL when no valid session existed
    source_run_date            TEXT,
    source_session_started_at  TEXT,
    source_published_at        TEXT,
    source_model_version       TEXT,
    source_training_run_id     TEXT,
    source_data_as_of          TEXT,
    source_n_series            INTEGER,         -- SKU x FC series of the source run
    n_rows                     INTEGER NOT NULL,   -- values stored (n_days x source_n_series when COMPLETE, else 0)
    days_covered               INTEGER NOT NULL,   -- target dates for which the source holds every series
    missing_dates_json         TEXT,
    total_yhat                 REAL,
    values_sha256              TEXT,
    status                     TEXT NOT NULL CHECK (status IN ('COMPLETE','INCOMPLETE','NO_SOURCE')),
    status_reason              TEXT,
    timezone                   TEXT NOT NULL,
    job_id                     TEXT,
    attempts                   INTEGER NOT NULL DEFAULT 1,
    created_at                 TEXT NOT NULL,   -- first attempt (UTC)
    updated_at                 TEXT NOT NULL,   -- last attempt (UTC); a COMPLETE snapshot is never updated
    UNIQUE (scope_key, business_date)
);
CREATE INDEX ix_fes_scope_day ON forecast_eod_snapshots(scope_key, status, business_date);

CREATE TABLE forecast_eod_snapshot_values (
    snapshot_id  TEXT NOT NULL REFERENCES forecast_eod_snapshots(id),
    target_date  TEXT NOT NULL,
    sku_id       TEXT NOT NULL,
    fc_id        TEXT NOT NULL,
    horizon_day  INTEGER NOT NULL,   -- horizon of the value in the source run
    yhat         REAL NOT NULL,
    method       TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, target_date, sku_id, fc_id)
) WITHOUT ROWID;

-- a COMPLETE snapshot never changes and no snapshot is ever deleted; only an INCOMPLETE / NO_SOURCE attempt of the same
-- business day may be completed by a later attempt (its keys never change)
CREATE TRIGGER trg_fes_no_delete BEFORE DELETE ON forecast_eod_snapshots
BEGIN SELECT RAISE(ABORT, 'forecast_eod_snapshots are never deleted'); END;
CREATE TRIGGER trg_fes_complete_fixed BEFORE UPDATE ON forecast_eod_snapshots WHEN OLD.status = 'COMPLETE'
BEGIN SELECT RAISE(ABORT, 'a COMPLETE forecast_eod_snapshot is immutable'); END;
CREATE TRIGGER trg_fes_keys_fixed BEFORE UPDATE OF id, scope_key, business_date, first_target_date, last_target_date,
    n_days, created_at ON forecast_eod_snapshots
BEGIN SELECT RAISE(ABORT, 'forecast_eod_snapshots keys never change'); END;
CREATE TRIGGER trg_fes_values_no_update BEFORE UPDATE ON forecast_eod_snapshot_values
BEGIN SELECT RAISE(ABORT, 'forecast_eod_snapshot_values are immutable'); END;
CREATE TRIGGER trg_fes_values_no_delete BEFORE DELETE ON forecast_eod_snapshot_values
BEGIN SELECT RAISE(ABORT, 'forecast_eod_snapshot_values are immutable'); END;
-- values exist only for a COMPLETE snapshot (an incomplete attempt stores none, so it can never be read as complete)
CREATE TRIGGER trg_fes_values_complete_only BEFORE INSERT ON forecast_eod_snapshot_values
WHEN (SELECT status FROM forecast_eod_snapshots WHERE id = NEW.snapshot_id) IS NOT 'COMPLETE'
BEGIN SELECT RAISE(ABORT, 'values belong to a COMPLETE forecast_eod_snapshot only'); END;

CREATE TABLE actual_closes (
    id              TEXT PRIMARY KEY,
    scope_key       TEXT NOT NULL,
    data_source     TEXT NOT NULL,
    business_date   TEXT NOT NULL,   -- Vietnam day closed
    revision        INTEGER NOT NULL CHECK (revision >= 1),
    kind            TEXT NOT NULL CHECK (kind IN ('CLOSE','RECONCILIATION')),   -- revision 1 = CLOSE
    reason          TEXT NOT NULL,   -- SCHEDULED_CLOSE | MANUAL_CLOSE | D1_LOADED | D1_RELOADED | D0_LATE_READ | ...
    source          TEXT,            -- D1 | D0 | NULL (no actual data)
    source_ref      TEXT,            -- D0 snapshot id, or the D-1 load time of that day
    source_as_of    TEXT,            -- when the source was read (UTC)
    source_reason   TEXT,            -- forecast_history.actual_context reason at that moment
    n_rows          INTEGER NOT NULL,   -- SKU x FC rows present in the source (an absent row is not stored as 0)
    total_qty       REAL,            -- NULL when there is no actual data
    values_sha256   TEXT,
    status          TEXT NOT NULL CHECK (status IN ('CLOSED_VERIFIED','CLOSED_UNVERIFIED','CLOSED_NO_DATA')),
    status_reason   TEXT,
    previous_id     TEXT REFERENCES actual_closes(id),
    previous_total  REAL,
    n_changed       INTEGER,
    n_added         INTEGER,
    n_removed       INTEGER,
    cutoff_at       TEXT NOT NULL,   -- business_date 23:59 Vietnam time (UTC)
    closed_at       TEXT NOT NULL,   -- when this revision was written (UTC)
    timezone        TEXT NOT NULL,
    job_id          TEXT,
    UNIQUE (scope_key, business_date, revision)      -- also the lookup index of a day's revisions
);

CREATE TABLE actual_close_values (
    close_id  TEXT NOT NULL REFERENCES actual_closes(id),
    sku_id    TEXT NOT NULL,
    fc_id     TEXT NOT NULL,
    qty       REAL NOT NULL,
    PRIMARY KEY (close_id, sku_id, fc_id)
) WITHOUT ROWID;

CREATE TRIGGER trg_actual_closes_no_update BEFORE UPDATE ON actual_closes
BEGIN SELECT RAISE(ABORT, 'actual_closes are immutable (a change is a new revision)'); END;
CREATE TRIGGER trg_actual_closes_no_delete BEFORE DELETE ON actual_closes
BEGIN SELECT RAISE(ABORT, 'actual_closes are immutable (a change is a new revision)'); END;
CREATE TRIGGER trg_actual_close_values_no_update BEFORE UPDATE ON actual_close_values
BEGIN SELECT RAISE(ABORT, 'actual_close_values are immutable'); END;
CREATE TRIGGER trg_actual_close_values_no_delete BEFORE DELETE ON actual_close_values
BEGIN SELECT RAISE(ABORT, 'actual_close_values are immutable'); END;
-- revisions are consecutive: revision n > 1 follows revision n - 1 of the same scope and day
CREATE TRIGGER trg_actual_closes_consecutive BEFORE INSERT ON actual_closes
WHEN NEW.revision > 1 AND NOT EXISTS (SELECT 1 FROM actual_closes p WHERE p.id = NEW.previous_id
     AND p.scope_key = NEW.scope_key AND p.business_date = NEW.business_date AND p.revision = NEW.revision - 1)
BEGIN SELECT RAISE(ABORT, 'actual_closes revision must follow the previous revision of the same day'); END;
