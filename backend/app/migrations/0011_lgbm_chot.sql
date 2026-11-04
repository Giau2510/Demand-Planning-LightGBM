-- 0011 (v1.3.1): LightGBM chot - daily forecast refresh with the model in use (published quantity = ROUNDUP above the
-- rounding threshold), its log, the SKU open hours read from BigQuery, the SKU groups A / B / C, the actual of each day,
-- the accuracy report runs and the feature importance of each training run (design in docs/ke_hoach_lgbm_chot.md
-- sections 1 and 3). OFF by default (settings section "daily_forecast"): nothing is written into these tables until the
-- refresh is switched on; the forecast runs, values, history, day-end backup and actual close of 1.2.14 are untouched.
--
-- Additive only: new tables, indexes and triggers. Nothing is written into them by the migration; no existing row or
-- table is changed.
--   open_hours_daily             SKU open hours per FC x SKU x day read from the BigQuery open-hours table (keyed by
--                                the source table and the seller filter of the read)
--   aux_source_reads             one record per COMPLETED read of an auxiliary source (append-only watermark: written
--                                only after the last chunk of the read committed; a read that failed midway leaves none)
--   sku_group                    group A / B / C of each series of a data scope for a month (open days of the 90 days
--                                ending at D-1); used by the reports only, never to choose a formula
--   forecast_refresh_runs        one record per published forecast refresh of a forecast day and data scope (immutable)
--   forecast_refresh_values      every value of a run: LightGBM raw (float) and published integer quantity per horizon
--                                day x FC x SKU (never updated; deleted only by the retention of the log)
--   actual_daily                 demand and open hours of a closed day per data scope x FC x SKU
--   accuracy_report_runs         one record per accuracy report run of a data scope (scheduled or manual)
--   training_feature_importance  gain and split count of every feature of a training run, with their shares
--
-- Rollback: the application refuses a database newer than it knows, so going back means restoring the pre-upgrade
-- backup (as for 0004-0010). Reverse statements, for a copy only: DROP TABLE training_feature_importance,
-- accuracy_report_runs, actual_daily, forecast_refresh_values, forecast_refresh_runs, sku_group, aux_source_reads,
-- open_hours_daily (their indexes and triggers go with them); DELETE FROM schema_migrations WHERE version = 11.

CREATE TABLE IF NOT EXISTS open_hours_daily (
    source_table      TEXT NOT NULL,      -- daily_forecast.openhours_table the row was read from
    seller_code       TEXT NOT NULL,      -- daily_forecast.seller_code filter of the read
    fc_code           TEXT NOT NULL,
    sku_code          TEXT NOT NULL,
    open_date         TEXT NOT NULL,      -- Vietnam calendar day (YYYY-MM-DD)
    total_open_hours  REAL,
    n_items           INTEGER,
    loaded_at         TEXT NOT NULL,      -- UTC
    PRIMARY KEY (source_table, seller_code, fc_code, sku_code, open_date)
);
CREATE INDEX IF NOT EXISTS idx_ohd_date ON open_hours_daily(source_table, seller_code, open_date);

CREATE TABLE IF NOT EXISTS aux_source_reads (
    id               INTEGER PRIMARY KEY,
    source_table     TEXT NOT NULL,
    seller_code      TEXT NOT NULL,
    kind             TEXT NOT NULL CHECK (kind IN ('OPEN_HOURS')),
    range_start      TEXT NOT NULL,       -- Vietnam days requested
    range_end        TEXT NOT NULL,
    n_rows           INTEGER NOT NULL,    -- rows returned by the source
    last_day         TEXT,                -- last day returned (NULL = no row)
    source_modified  TEXT,                -- UTC, last-modified time of the source table seen by the read (NULL = unknown)
    completed_at     TEXT NOT NULL        -- UTC, after the last chunk committed
);
CREATE INDEX IF NOT EXISTS idx_asr_latest ON aux_source_reads(source_table, seller_code, kind, completed_at);

CREATE TABLE IF NOT EXISTS sku_group (
    scope_key         TEXT NOT NULL,      -- data scope of the demand (demand_daily.scope_key)
    fc_code           TEXT NOT NULL,
    sku_code          TEXT NOT NULL,
    group_code        TEXT NOT NULL CHECK (group_code IN ('A', 'B', 'C')),
    computed_for      TEXT NOT NULL,      -- Vietnam day of the computation (first refresh of a month / first refresh)
    window_start      TEXT NOT NULL,      -- effective start: WINDOW_DAYS before window_end, clipped to the data window
    window_end        TEXT NOT NULL,      -- D-1 of computed_for
    n_open_days       INTEGER NOT NULL,
    qty               REAL NOT NULL,
    avg_per_open_day  REAL,               -- NULL when n_open_days = 0
    zero_days         INTEGER NOT NULL,
    zero_share        REAL,               -- NULL when n_open_days = 0
    rule_version      TEXT NOT NULL,
    computed_at       TEXT NOT NULL,      -- UTC
    PRIMARY KEY (scope_key, fc_code, sku_code, computed_for)
);
CREATE INDEX IF NOT EXISTS idx_sku_group_for ON sku_group(scope_key, computed_for);

CREATE TABLE IF NOT EXISTS forecast_refresh_runs (
    id                  TEXT PRIMARY KEY,
    scope_key           TEXT NOT NULL,    -- data scope the model in use and the panel belong to
    forecast_date       TEXT NOT NULL,    -- Vietnam day the forecast is made on (day 1 of the horizon)
    data_as_of          TEXT NOT NULL,    -- last demand day used (D-1)
    status              TEXT NOT NULL CHECK (status IN ('PUBLISHED')),   -- written only after success, never updated
    trigger             TEXT,             -- what started the run (schedule, manual, ...)
    training_run_id     TEXT,
    model_version       TEXT,
    model_fingerprint   TEXT,             -- fingerprint of the model in use
    config_version      TEXT NOT NULL,    -- version of the refresh configuration used
    trial_mode          INTEGER NOT NULL, -- 1 = trial mode on at the time of the run
    horizon             INTEGER NOT NULL, -- days forecast (H)
    n_series            INTEGER NOT NULL,
    n_lightgbm          INTEGER NOT NULL, -- series forecast by LightGBM
    n_fallback          INTEGER NOT NULL, -- series forecast by a fallback rule
    group_computed_for  TEXT,             -- sku_group.computed_for of the groups used (NULL = none)
    job_id              TEXT,
    created_at          TEXT NOT NULL,    -- UTC
    detail_json         TEXT
);
CREATE INDEX IF NOT EXISTS idx_frr_date ON forecast_refresh_runs(scope_key, forecast_date, created_at);

CREATE TABLE IF NOT EXISTS forecast_refresh_values (
    run_id       TEXT NOT NULL REFERENCES forecast_refresh_runs(id),
    horizon      INTEGER NOT NULL,        -- 1 = forecast_date
    target_date  TEXT NOT NULL,           -- forecast_date + horizon - 1 (Vietnam day)
    fc_code      TEXT NOT NULL,
    sku_code     TEXT NOT NULL,
    lgb_raw      REAL,                    -- value as computed (float); NULL = no LightGBM value
    final_qty    INTEGER NOT NULL CHECK (final_qty >= 0),   -- published quantity (integer)
    method       TEXT NOT NULL,
    group_code   TEXT,                    -- A / B / C (NULL = no group)
    flags        TEXT,                    -- CODE_UNKNOWN, GROUP_MISSING, ...
    PRIMARY KEY (run_id, horizon, fc_code, sku_code)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS actual_daily (
    scope_key         TEXT NOT NULL,      -- data scope of the demand
    date              TEXT NOT NULL,      -- Vietnam calendar day
    fc_code           TEXT NOT NULL,
    sku_code          TEXT NOT NULL,
    demand            REAL,
    total_open_hours  REAL,
    updated_at        TEXT NOT NULL,      -- UTC
    PRIMARY KEY (scope_key, date, fc_code, sku_code)     -- also the index by scope and date
);

CREATE TABLE IF NOT EXISTS accuracy_report_runs (
    id            TEXT PRIMARY KEY,
    scope_key     TEXT NOT NULL,
    run_kind      TEXT NOT NULL CHECK (run_kind IN ('SCHEDULED', 'MANUAL')),
    run_date      TEXT NOT NULL,          -- Vietnam day of the run
    period_start  TEXT,                   -- first and last target day of the report (NULL = no data)
    period_end    TEXT,
    n_cells       INTEGER,
    status        TEXT NOT NULL,
    summary_json  TEXT,
    report_path   TEXT,                   -- .xlsx written (NULL = not written)
    error         TEXT,
    job_id        TEXT,
    created_at    TEXT NOT NULL           -- UTC
);
CREATE INDEX IF NOT EXISTS idx_arr_run ON accuracy_report_runs(scope_key, run_kind, run_date);

CREATE TABLE IF NOT EXISTS training_feature_importance (
    training_run_id  TEXT NOT NULL,
    feature          TEXT NOT NULL,
    feature_group    TEXT,
    gain             REAL NOT NULL,
    split            INTEGER NOT NULL,    -- number of splits using the feature
    gain_share       REAL,                -- share of the total gain / split count (0 when the total is 0)
    split_share      REAL,
    rank             INTEGER,             -- by gain, descending
    PRIMARY KEY (training_run_id, feature)
);

-- the refresh runs and their values are immutable (a rerun of a day is a new run; values are deleted only by the log
-- retention), the read watermarks are append-only
CREATE TRIGGER IF NOT EXISTS trg_frr_no_update BEFORE UPDATE ON forecast_refresh_runs
BEGIN SELECT RAISE(ABORT, 'forecast_refresh_runs are immutable'); END;
CREATE TRIGGER IF NOT EXISTS trg_frr_no_delete BEFORE DELETE ON forecast_refresh_runs
BEGIN SELECT RAISE(ABORT, 'forecast_refresh_runs are immutable'); END;
CREATE TRIGGER IF NOT EXISTS trg_frv_no_update BEFORE UPDATE ON forecast_refresh_values
BEGIN SELECT RAISE(ABORT, 'forecast_refresh_values are immutable'); END;
CREATE TRIGGER IF NOT EXISTS trg_asr_no_update BEFORE UPDATE ON aux_source_reads
BEGIN SELECT RAISE(ABORT, 'aux_source_reads are append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_asr_no_delete BEFORE DELETE ON aux_source_reads
BEGIN SELECT RAISE(ABORT, 'aux_source_reads are append-only'); END;
