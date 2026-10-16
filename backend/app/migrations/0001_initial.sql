-- 0001_initial: core schema for the Demand Forecasting app.
-- All timestamps are ISO-8601 strings with offset (UTC unless stated). Business dates are
-- Vietnam calendar dates (YYYY-MM-DD).

CREATE TABLE app_settings (
    section     TEXT PRIMARY KEY,
    value_json  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE settings_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    section     TEXT NOT NULL,
    value_json  TEXT NOT NULL,
    changed_at  TEXT NOT NULL,
    note        TEXT
);
CREATE INDEX ix_settings_history_section ON settings_history(section, id);

-- Every load of order-line data (DEMO generation or a MANUAL_IMPORT Excel file) is one batch.
CREATE TABLE import_batches (
    id                  TEXT PRIMARY KEY,
    data_source         TEXT NOT NULL CHECK (data_source IN ('DEMO','MANUAL_IMPORT')),
    status              TEXT NOT NULL CHECK (status IN ('PENDING_REVIEW','ACTIVE','REPLACED','DELETED','CANCELLED','FAILED')),
    file_name           TEXT,
    file_sha256         TEXT,
    sheet_name          TEXT,
    column_mapping_json TEXT,
    replaces_batch_id   TEXT REFERENCES import_batches(id),
    replaced_by_batch_id TEXT REFERENCES import_batches(id),
    total_rows          INTEGER NOT NULL DEFAULT 0,
    valid_rows          INTEGER NOT NULL DEFAULT 0,
    error_rows          INTEGER NOT NULL DEFAULT 0,
    duplicate_rows      INTEGER NOT NULL DEFAULT 0,
    min_order_date      TEXT,
    max_order_date      TEXT,
    validation_json     TEXT,
    created_at          TEXT NOT NULL,
    confirmed_at        TEXT,
    closed_at           TEXT,
    note                TEXT
);
CREATE INDEX ix_import_batches_status ON import_batches(data_source, status);

-- Normalised order lines belonging to a batch. Only lines of ACTIVE batches are used.
CREATE TABLE order_lines (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id          TEXT NOT NULL REFERENCES import_batches(id),
    row_number        INTEGER,
    order_id          TEXT,
    created_at        TEXT,
    order_date        TEXT NOT NULL,
    sku_id            TEXT NOT NULL,
    fc_id             TEXT NOT NULL,
    order_qty         REAL NOT NULL CHECK (order_qty >= 0),
    unit_price        REAL,
    discount_amount   REAL,
    promotion_flag    INTEGER,
    promotion_id      TEXT,
    voucher_flag      INTEGER,
    voucher_amount    REAL,
    source_updated_at TEXT,
    source_batch_id   TEXT
);
CREATE INDEX ix_order_lines_batch ON order_lines(batch_id, order_date);

-- Rows rejected during validation of a pending batch (kept for the Excel error report).
CREATE TABLE import_row_errors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id    TEXT NOT NULL REFERENCES import_batches(id),
    row_number  INTEGER,
    field       TEXT,
    code        TEXT NOT NULL,
    severity    TEXT NOT NULL,
    raw_value   TEXT
);
CREATE INDEX ix_import_row_errors_batch ON import_row_errors(batch_id);

-- Daily demand per scope (= one dataset: a DEMO batch, a MANUAL_IMPORT batch, or the BIGQUERY sync).
CREATE TABLE demand_daily (
    scope_key       TEXT NOT NULL,
    data_source     TEXT NOT NULL CHECK (data_source IN ('DEMO','MANUAL_IMPORT','BIGQUERY')),
    order_date      TEXT NOT NULL,
    sku_id          TEXT NOT NULL,
    fc_id           TEXT NOT NULL,
    qty             REAL NOT NULL,
    n_orders        INTEGER NOT NULL DEFAULT 0,
    avg_unit_price  REAL,
    avg_discount_rate REAL,
    promo_share     REAL,
    voucher_share   REAL,
    loaded_at       TEXT NOT NULL,
    PRIMARY KEY (scope_key, order_date, sku_id, fc_id)
);

-- Data-quality / validation reports per scope.
CREATE TABLE validation_reports (
    id          TEXT PRIMARY KEY,
    scope_key   TEXT NOT NULL,
    data_source TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    can_train   INTEGER NOT NULL,
    report_json TEXT NOT NULL
);
CREATE INDEX ix_validation_reports_scope ON validation_reports(scope_key, created_at);

CREATE TABLE training_runs (
    id                  TEXT PRIMARY KEY,
    model_version       TEXT UNIQUE,
    scope_key           TEXT NOT NULL,
    data_source         TEXT NOT NULL,
    data_fingerprint    TEXT,
    status              TEXT NOT NULL CHECK (status IN ('RUNNING','ACCEPTED','REJECTED','FAILED')),
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    train_start         TEXT,
    train_end           TEXT,
    n_series            INTEGER,
    n_rows              INTEGER,
    feature_config_json TEXT,
    params_json         TEXT,
    metrics_json        TEXT,
    baseline_metrics_json TEXT,
    quality_gate_json   TEXT,
    feature_importance_json TEXT,
    reject_reason       TEXT,
    error               TEXT,
    model_path          TEXT,
    model_sha256        TEXT,
    job_id              TEXT
);
CREATE INDEX ix_training_runs_scope ON training_runs(scope_key, started_at);

CREATE TABLE backtest_runs (
    id              TEXT PRIMARY KEY,
    training_run_id TEXT NOT NULL REFERENCES training_runs(id),
    created_at      TEXT NOT NULL,
    config_json     TEXT NOT NULL,
    folds_json      TEXT NOT NULL,
    metrics_json    TEXT NOT NULL,
    reliable        INTEGER NOT NULL,
    notes_json      TEXT
);

CREATE TABLE forecast_runs (
    id              TEXT PRIMARY KEY,
    training_run_id TEXT NOT NULL REFERENCES training_runs(id),
    model_version   TEXT NOT NULL,
    scope_key       TEXT NOT NULL,
    data_source     TEXT NOT NULL,
    forecast_origin TEXT NOT NULL,   -- first forecast date (VN date)
    data_as_of      TEXT NOT NULL,   -- last complete data date used
    horizons_json   TEXT NOT NULL,
    max_horizon     INTEGER NOT NULL,
    n_series        INTEGER NOT NULL,
    method_counts_json TEXT,
    status          TEXT NOT NULL CHECK (status IN ('PUBLISHED')),
    created_at      TEXT NOT NULL,
    job_id          TEXT
);
CREATE INDEX ix_forecast_runs_scope ON forecast_runs(scope_key, created_at);

CREATE TABLE forecast_values (
    run_id      TEXT NOT NULL REFERENCES forecast_runs(id),
    sku_id      TEXT NOT NULL,
    fc_id       TEXT NOT NULL,
    target_date TEXT NOT NULL,
    horizon_day INTEGER NOT NULL,
    yhat        REAL NOT NULL,
    method      TEXT NOT NULL,
    fallback_reason TEXT,
    PRIMARY KEY (run_id, sku_id, fc_id, target_date)
);

-- Published forecasts are immutable.
CREATE TRIGGER trg_forecast_values_no_update BEFORE UPDATE ON forecast_values
BEGIN SELECT RAISE(ABORT, 'forecast_values are immutable'); END;
CREATE TRIGGER trg_forecast_values_no_delete BEFORE DELETE ON forecast_values
BEGIN SELECT RAISE(ABORT, 'forecast_values are immutable'); END;
CREATE TRIGGER trg_forecast_runs_no_update BEFORE UPDATE ON forecast_runs
BEGIN SELECT RAISE(ABORT, 'forecast_runs are immutable'); END;
CREATE TRIGGER trg_forecast_runs_no_delete BEFORE DELETE ON forecast_runs
BEGIN SELECT RAISE(ABORT, 'forecast_runs are immutable'); END;

CREATE TABLE d0_snapshots (
    id              TEXT PRIMARY KEY,
    data_source     TEXT NOT NULL,
    scope_key       TEXT NOT NULL,
    order_date      TEXT NOT NULL,
    snapshot_at     TEXT NOT NULL,     -- real time the data was read
    scheduled_slot  TEXT,              -- slot (VN local) this sync belongs to, if any
    is_catch_up     INTEGER NOT NULL DEFAULT 0,
    sync_status     TEXT NOT NULL CHECK (sync_status IN ('SUCCEEDED')),
    rows_read       INTEGER NOT NULL,
    rows_valid      INTEGER NOT NULL,
    rows_error      INTEGER NOT NULL,
    source_updated_max TEXT,
    source_batch_id TEXT,
    job_id          TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX ix_d0_snapshots_date ON d0_snapshots(order_date, snapshot_at);

CREATE TABLE d0_snapshot_values (
    snapshot_id     TEXT NOT NULL REFERENCES d0_snapshots(id),
    sku_id          TEXT NOT NULL,
    fc_id           TEXT NOT NULL,
    cumulative_qty  REAL NOT NULL,
    source_updated_at TEXT,
    PRIMARY KEY (snapshot_id, sku_id, fc_id)
);
CREATE TRIGGER trg_d0_values_no_update BEFORE UPDATE ON d0_snapshot_values
BEGIN SELECT RAISE(ABORT, 'snapshot values are immutable'); END;

CREATE TABLE job_runs (
    id              TEXT PRIMARY KEY,
    job_type        TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    trigger         TEXT NOT NULL,     -- SCHEDULE | CATCH_UP | MANUAL | RETRY
    scheduled_for   TEXT,
    status          TEXT NOT NULL CHECK (status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','SKIPPED','RETRY_WAIT')),
    attempt         INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 1,
    next_attempt_at TEXT,
    created_at      TEXT NOT NULL,
    started_at      TEXT,
    finished_at     TEXT,
    reason_code     TEXT,
    error           TEXT,
    result_json     TEXT
);
CREATE INDEX ix_job_runs_type ON job_runs(job_type, created_at);
CREATE INDEX ix_job_runs_status ON job_runs(status);

CREATE TABLE job_locks (
    lock_name   TEXT PRIMARY KEY,
    owner       TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);

CREATE TABLE sync_state (
    name        TEXT PRIMARY KEY,
    value_json  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    level       TEXT NOT NULL CHECK (level IN ('INFO','WARNING','ERROR')),
    code        TEXT NOT NULL,
    params_json TEXT,
    entity_type TEXT,
    entity_id   TEXT,
    acknowledged_at TEXT
);

CREATE TABLE audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT NOT NULL,
    action      TEXT NOT NULL,
    entity_type TEXT,
    entity_id   TEXT,
    details_json TEXT
);
