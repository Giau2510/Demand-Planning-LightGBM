-- 0012 (v1.4.0): per-SKU model selection "SEL2" - the trainings of the LightGBM candidates, the daily runs and values
-- of the 6 candidate forecasts per SKU x FC (MOC, V33_L112, V36_two_stage@0.6, TSB, DOW4, AVG7), the forecast source
-- chosen per SKU x FC (AVG_DEMAND / LIGHTGBM) with its append-only history, the AVG_DEMAND rows read from BigQuery and
-- the daily Excel exports. Settings section "sel2_pipeline" (ON by default; enabled = False is the emergency return to
-- the exact 1.3.1 behaviour, where nothing is written into these tables). The forecast runs, values, refresh log,
-- day-end backup and actual close of 1.3.1 are untouched.
--
-- Additive only: new tables, indexes and triggers. Nothing is written into them by the migration; no existing row or
-- table is changed. Dates are Vietnam calendar days (YYYY-MM-DD); timestamps are UTC ISO-8601.
--   candidate_train_runs            one record per training of a LightGBM candidate (MOC, V33_L112, V36_two_stage:
--                                   classifier + regressor) for an origin day (training data < origin_date)
--   candidate_runs                  one record per candidate forecast of a forecast day (one of the 6 names)
--   candidate_forecasts             every candidate value, LONG format: forecast day x SKU x FC x candidate x horizon
--                                   (about 75 M rows at 120 days of retention: kept narrow, WITHOUT ROWID, the primary
--                                   key prefix (forecast_date, sku_code, fc_code) is the lookup index and the
--                                   retention range, one forecast day per transaction). No scope and no run column:
--                                   the provenance of a day is its candidate_runs (one SUCCEEDED run per scope_key x
--                                   forecast_date x model); a whole day is written in ONE transaction (the day's rows
--                                   of its models deleted, then inserted sorted by the key) and a day that has
--                                   candidate_runs of another scope is refused by the code
--   forecast_source_config          current forecast source of a SKU x FC (a missing row = AVG_DEMAND, the default)
--   forecast_source_config_history  every change of the source (append-only: UPDATE and DELETE refused)
--   avg_demand_daily                AVG_DEMAND rows of the BigQuery table per day x SKU x FC x seller, raw (the seller
--                                   rule sel2_pipeline.avg_seller_rule is applied by the code)
--   avg_demand_reads                one record per COMPLETED read of an AVG_DEMAND table for a day (written only
--                                   after the read committed)
--   export_runs                     one record per daily Excel written (version 1, 2, ... per forecast day)
--
-- SEL2 runs published into the 1.3.1 tables forecast_refresh_runs / forecast_refresh_values are marked by
-- config_version = 'SEL2:' + 12-character hash of the selection settings; method = the model used of the series
-- ('MOC+DOW4', 'FALLBACK:V33_L112', ...); lgb_raw = the SEL2 raw value (mean of the two chosen candidates, or the
-- fallback candidate's value); final_qty = the published integer; model_version names the three training runs.
--
-- Rollback: the application refuses a database newer than it knows, so going back means restoring the pre-upgrade
-- backup (as for 0004-0011). Reverse statements, for a copy only: DROP TABLE export_runs, avg_demand_reads, avg_demand_daily,
-- forecast_source_config_history, forecast_source_config, candidate_forecasts, candidate_runs, candidate_train_runs
-- (their indexes and triggers go with them); DELETE FROM schema_migrations WHERE version = 12.

CREATE TABLE IF NOT EXISTS candidate_train_runs (
    id                TEXT PRIMARY KEY,
    scope_key         TEXT NOT NULL,      -- data scope of the demand (demand_daily.scope_key)
    model             TEXT NOT NULL CHECK (model IN ('MOC', 'V33_L112', 'V36_two_stage')),
    origin_date       TEXT NOT NULL,      -- the training uses the data before this day
    data_as_of        TEXT,               -- last demand day used
    status            TEXT NOT NULL CHECK (status IN ('RUNNING', 'SUCCEEDED', 'FAILED')),
    config_json       TEXT,
    fingerprint       TEXT,
    model_files_json  TEXT,               -- model file paths + sha256 (two-stage: classifier and regressor)
    n_rows            INTEGER,
    n_series          INTEGER,
    n_features        INTEGER,
    train_seconds     REAL,
    peak_ram_mb       REAL,
    job_id            TEXT,
    created_at        TEXT NOT NULL,      -- UTC
    finished_at       TEXT,               -- UTC
    detail_json       TEXT
);
CREATE INDEX IF NOT EXISTS idx_ctr_model_origin ON candidate_train_runs(scope_key, model, origin_date);

CREATE TABLE IF NOT EXISTS candidate_runs (
    id                TEXT PRIMARY KEY,
    scope_key         TEXT NOT NULL,
    forecast_date     TEXT NOT NULL,      -- Vietnam day the forecast is made on (horizon 1)
    data_as_of        TEXT NOT NULL,      -- last data day used (before forecast_date)
    model             TEXT NOT NULL CHECK (model IN ('MOC', 'V33_L112', 'V36_two_stage@0.6', 'TSB', 'DOW4', 'AVG7')),
    train_run_id      TEXT REFERENCES candidate_train_runs(id),   -- LightGBM candidates only (NULL otherwise)
    status            TEXT NOT NULL CHECK (status IN ('SUCCEEDED', 'FAILED')),
    n_series          INTEGER,
    flags             TEXT,
    created_at        TEXT NOT NULL,      -- UTC
    job_id            TEXT,
    detail_json       TEXT
);
CREATE INDEX IF NOT EXISTS idx_cr_date_model ON candidate_runs(scope_key, forecast_date, model);

CREATE TABLE IF NOT EXISTS candidate_forecasts (
    forecast_date  TEXT NOT NULL,
    sku_code       TEXT NOT NULL,
    fc_code        TEXT NOT NULL,
    model          TEXT NOT NULL CHECK (model IN ('MOC', 'V33_L112', 'V36_two_stage@0.6', 'TSB', 'DOW4', 'AVG7')),
    horizon        INTEGER NOT NULL CHECK (horizon BETWEEN 1 AND 7),   -- 1 = forecast_date
    target_date    TEXT NOT NULL,         -- forecast_date + horizon - 1
    value          REAL NOT NULL CHECK (value >= 0),                    -- as computed (float); no value = no row
    PRIMARY KEY (forecast_date, sku_code, fc_code, model, horizon)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS forecast_source_config (
    sku_code         TEXT NOT NULL,
    fc_code          TEXT NOT NULL,
    forecast_source  TEXT NOT NULL CHECK (forecast_source IN ('AVG_DEMAND', 'LIGHTGBM')),
    ghi_chu          TEXT,
    updated_by       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,       -- UTC
    PRIMARY KEY (sku_code, fc_code)
);

CREATE TABLE IF NOT EXISTS forecast_source_config_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sku_code    TEXT NOT NULL,
    fc_code     TEXT NOT NULL,
    old_source  TEXT CHECK (old_source IN ('AVG_DEMAND', 'LIGHTGBM')),     -- NULL = no row before (AVG_DEMAND)
    new_source  TEXT NOT NULL CHECK (new_source IN ('AVG_DEMAND', 'LIGHTGBM')),
    ghi_chu     TEXT,
    changed_by  TEXT NOT NULL,
    changed_at  TEXT NOT NULL,            -- UTC
    channel     TEXT NOT NULL CHECK (channel IN ('UI', 'UPLOAD', 'API')),
    batch_id    TEXT                      -- upload batch (NULL = single change)
);

CREATE TABLE IF NOT EXISTS avg_demand_daily (
    business_date    TEXT NOT NULL,
    sku_code         TEXT NOT NULL,
    fc_code          TEXT NOT NULL,
    seller_code      TEXT NOT NULL,
    avg_demand       REAL,                -- as read (NULL kept as NULL)
    product_name     TEXT,
    source_table     TEXT NOT NULL,       -- sel2_pipeline.avg_demand_table / avg_demand_hist_table
    source_modified  TEXT,                -- UTC, last-modified time of the source table seen by the read
    loaded_at        TEXT NOT NULL,       -- UTC
    PRIMARY KEY (business_date, sku_code, fc_code, seller_code, source_table)
);

CREATE TABLE IF NOT EXISTS avg_demand_reads (
    id               TEXT PRIMARY KEY,
    source_table     TEXT NOT NULL,
    business_date    TEXT NOT NULL,
    kind             TEXT NOT NULL CHECK (kind IN ('CURRENT', 'HISTORICAL')),
    n_rows           INTEGER NOT NULL,
    source_modified  TEXT,               -- UTC, last-modified time of the source table seen by the read
    completed_at     TEXT NOT NULL       -- UTC
);

CREATE TABLE IF NOT EXISTS export_runs (
    id              TEXT PRIMARY KEY,
    forecast_date   TEXT NOT NULL,
    version         INTEGER NOT NULL,     -- 1, 2, ... per forecast_date
    path            TEXT NOT NULL,
    sha256          TEXT,
    n_rows          INTEGER,
    is_stale        INTEGER NOT NULL DEFAULT 0,
    flags           TEXT,
    refresh_run_id  TEXT,
    trigger         TEXT,
    job_id          TEXT,
    created_at      TEXT NOT NULL,        -- UTC
    summary_json    TEXT,
    UNIQUE (forecast_date, version)
);

-- the history of the forecast source is append-only
CREATE TRIGGER IF NOT EXISTS trg_fsch_no_update BEFORE UPDATE ON forecast_source_config_history
BEGIN SELECT RAISE(ABORT, 'forecast_source_config_history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_fsch_no_delete BEFORE DELETE ON forecast_source_config_history
BEGIN SELECT RAISE(ABORT, 'forecast_source_config_history is append-only'); END;
