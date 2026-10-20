-- 0007 (v1.2.9): SKU open hours of the day on the daily demand rows - the BigQuery D-1 column total_open_hours, a
-- mandatory model input of the BIGQUERY source (owner request 19/10/2026; rules in app/data/open_hours.py).
--
-- Additive only: two nullable columns, no default value written into existing rows, no constraint, no trigger. Every
-- existing row keeps its values and gets NULL / NULL = "not loaded with this column" (NOT_LOADED): nothing is invented.
-- D-1 fills them for the days it (re)loads; DEMO / Excel-import rows keep NULL (their sources have no such column).
--   open_hours         hours (0..24) of the day the SKU was open for sale; only when open_hours_status = 'OK'
--   open_hours_status  OK | MISSING | OUT_OF_RANGE | CONFLICT (NULL = not loaded / not applicable)
--
-- Rollback: the application refuses a database newer than it knows, so going back to 1.2.8 means restoring the
-- pre-upgrade backup (as for 0004-0006). Reverse statements, for a copy only, after checking that nothing else uses
-- the columns:  ALTER TABLE demand_daily DROP COLUMN open_hours_status; ALTER TABLE demand_daily DROP COLUMN open_hours;
--               DELETE FROM schema_migrations WHERE version = 7;
-- WARNING: only on a database WITHOUT any training run made by 1.2.9 or later. 1.2.8 ignores the stored
-- weekday_encoding / feature_open_hours of such a run: it would feed dow 0..6 to a model trained on 1..7 (a silent
-- one-day shift) and leave the open-hours columns out of its feature matrix. After 1.2.9 has trained, go back by
-- restoring the pre-upgrade backup only.

ALTER TABLE demand_daily ADD COLUMN open_hours REAL;
ALTER TABLE demand_daily ADD COLUMN open_hours_status TEXT;
