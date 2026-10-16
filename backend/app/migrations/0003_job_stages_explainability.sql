-- 0003 (v1.1.1): additive only - no existing row is modified or deleted.
-- Job progress: current pipeline stage + history of stage transitions (real stages only, no percentages).
ALTER TABLE job_runs ADD COLUMN stage TEXT;
ALTER TABLE job_runs ADD COLUMN stage_updated_at TEXT;
ALTER TABLE job_runs ADD COLUMN stage_history_json TEXT;

-- A forecast run produced later from an already accepted model (e.g. to add a longer horizon) points at the
-- run it extends. The original run is never changed.
ALTER TABLE forecast_runs ADD COLUMN derived_from_run_id TEXT;

-- Why each SKU x FC got its method and how a fallback value was computed, captured at publish time
-- (one small row per series; immutable like forecast_values).
CREATE TABLE forecast_series_meta (
    run_id       TEXT NOT NULL REFERENCES forecast_runs(id),
    sku_id       TEXT NOT NULL,
    fc_id        TEXT NOT NULL,
    method       TEXT NOT NULL,
    reason_code  TEXT NOT NULL,
    details_json TEXT NOT NULL,
    PRIMARY KEY (run_id, sku_id, fc_id)
);
CREATE TRIGGER trg_series_meta_no_update BEFORE UPDATE ON forecast_series_meta
BEGIN SELECT RAISE(ABORT, 'forecast_series_meta is immutable'); END;
CREATE TRIGGER trg_series_meta_no_delete BEFORE DELETE ON forecast_series_meta
BEGIN SELECT RAISE(ABORT, 'forecast_series_meta is immutable'); END;
