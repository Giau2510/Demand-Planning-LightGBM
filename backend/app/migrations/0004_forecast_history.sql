-- 0004 (v1.2.5): additive only - new tables, no existing row is modified or deleted.
-- Forecast & actual history: for each forecast session (= one published forecast run) the forecast of the day after
-- its run date (D+1) is kept, and per run date ONE session is the official one (the newest valid session of that day).
-- Source of truth stays forecast_values (immutable); these tables are the D+1 history taken from it. Actual demand is
-- NOT stored here: it is read from demand_daily (D-1 loads) and d0_snapshots (intraday) when the history is shown.

-- Every published forecast run seen by the history, with the decision taken when it was recorded (immutable).
CREATE TABLE forecast_history_sessions (
    forecast_run_id     TEXT PRIMARY KEY REFERENCES forecast_runs(id),
    scope_key           TEXT NOT NULL,
    data_source         TEXT NOT NULL,
    run_date            TEXT NOT NULL,   -- VN date of session_started_at
    target_date         TEXT NOT NULL,   -- run_date + 1 (the only forecast date kept)
    session_started_at  TEXT NOT NULL,   -- start of the job that produced the run, else the publish time (UTC)
    published_at        TEXT NOT NULL,   -- forecast_runs.created_at
    training_run_id     TEXT NOT NULL,
    model_version       TEXT NOT NULL,
    data_as_of          TEXT NOT NULL,
    horizon_day         INTEGER,         -- horizon of the D+1 values in that run (NULL when it has none)
    n_rows              INTEGER NOT NULL,
    total_yhat          REAL,
    usage_status        TEXT,            -- USABLE / USABLE_WITH_WARNING ... of the training run, when recorded
    eligible            INTEGER NOT NULL,
    decision            TEXT NOT NULL,   -- SELECTED | OLDER_THAN_SELECTED | NOT_ELIGIBLE
    decision_reason     TEXT,
    capture_mode        TEXT NOT NULL CHECK (capture_mode IN ('AT_PUBLISH','RECOVERED')),
    captured_at         TEXT NOT NULL
);
CREATE INDEX ix_fh_sessions_day ON forecast_history_sessions(scope_key, run_date);

-- D+1 values of the sessions that were selected when recorded (copied from forecast_values, immutable).
CREATE TABLE forecast_history_values (
    forecast_run_id TEXT NOT NULL REFERENCES forecast_history_sessions(forecast_run_id),
    sku_id          TEXT NOT NULL,
    fc_id           TEXT NOT NULL,
    scope_key       TEXT NOT NULL,
    run_date        TEXT NOT NULL,
    target_date     TEXT NOT NULL,
    yhat            REAL NOT NULL,
    method          TEXT NOT NULL,
    product_name    TEXT,            -- name known when recorded (display uses the current mapping first)
    PRIMARY KEY (forecast_run_id, sku_id, fc_id)
);
CREATE INDEX ix_fh_values_target ON forecast_history_values(scope_key, target_date, sku_id, fc_id);
CREATE INDEX ix_fh_values_fc ON forecast_history_values(scope_key, fc_id, target_date);

-- The official session per scope and run date (the only mutable table: a newer valid session of the SAME run date
-- replaces the pointer; every change is in audit_log as FORECAST_HISTORY_SELECTED).
CREATE TABLE forecast_history_days (
    scope_key        TEXT NOT NULL,
    run_date         TEXT NOT NULL,
    data_source      TEXT NOT NULL,
    target_date      TEXT NOT NULL,
    forecast_run_id  TEXT NOT NULL REFERENCES forecast_history_sessions(forecast_run_id),
    selected_at      TEXT NOT NULL,
    PRIMARY KEY (scope_key, run_date)
);

CREATE TRIGGER trg_fh_sessions_no_update BEFORE UPDATE ON forecast_history_sessions
BEGIN SELECT RAISE(ABORT, 'forecast_history_sessions are immutable'); END;
CREATE TRIGGER trg_fh_sessions_no_delete BEFORE DELETE ON forecast_history_sessions
BEGIN SELECT RAISE(ABORT, 'forecast_history_sessions are immutable'); END;
CREATE TRIGGER trg_fh_values_no_update BEFORE UPDATE ON forecast_history_values
BEGIN SELECT RAISE(ABORT, 'forecast_history_values are immutable'); END;
CREATE TRIGGER trg_fh_values_no_delete BEFORE DELETE ON forecast_history_values
BEGIN SELECT RAISE(ABORT, 'forecast_history_values are immutable'); END;
CREATE TRIGGER trg_fh_days_no_delete BEFORE DELETE ON forecast_history_days
BEGIN SELECT RAISE(ABORT, 'forecast_history_days rows are never deleted'); END;
CREATE TRIGGER trg_fh_days_keys_fixed BEFORE UPDATE OF scope_key, run_date, data_source, target_date ON forecast_history_days
BEGIN SELECT RAISE(ABORT, 'forecast_history_days keys never change'); END;
-- the official session of a run date is always a recorded, eligible session of that same scope and run date
CREATE TRIGGER trg_fh_days_same_day BEFORE UPDATE OF forecast_run_id ON forecast_history_days
WHEN NOT EXISTS (SELECT 1 FROM forecast_history_sessions s WHERE s.forecast_run_id = NEW.forecast_run_id
                 AND s.scope_key = NEW.scope_key AND s.run_date = NEW.run_date AND s.eligible = 1)
BEGIN SELECT RAISE(ABORT, 'forecast_history_days must point at an eligible session of the same run date'); END;
CREATE TRIGGER trg_fh_days_same_day_insert BEFORE INSERT ON forecast_history_days
WHEN NOT EXISTS (SELECT 1 FROM forecast_history_sessions s WHERE s.forecast_run_id = NEW.forecast_run_id
                 AND s.scope_key = NEW.scope_key AND s.run_date = NEW.run_date AND s.eligible = 1)
BEGIN SELECT RAISE(ABORT, 'forecast_history_days must point at an eligible session of the same run date'); END;
