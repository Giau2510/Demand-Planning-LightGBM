-- 0008 (v1.2.9b): aggregate repeat-purchase counts per day x SKU x FC, prepared for an optional customer_id column of
-- the BigQuery D-1 source (owner request 20/10/2026; rules in app/data/customers.py). OFF by default: nothing fills
-- these columns until the owner maps a customer column, and no model uses them until the model switch is turned on.
--
-- Additive only: three nullable columns, no default value written into existing rows, no constraint, no trigger. Every
-- existing row keeps its values and gets NULL = "unknown" (never 0). No customer identifier is stored anywhere: D-1
-- reduces it to counts inside BigQuery.
--   customer_count            distinct customers of the day x SKU x FC
--   repeat_customer_count     customers of that day who had ordered the same SKU x FC in the 90 days before it
--   repeat_interval_days_sum  sum of the days since the previous order day of those repeat customers
--
-- Rollback: the application refuses a database newer than it knows, so going back means restoring the pre-upgrade
-- backup (as for 0004-0007). Reverse statements, for a copy only, after checking that nothing else uses the columns:
--   ALTER TABLE demand_daily DROP COLUMN repeat_interval_days_sum; ALTER TABLE demand_daily DROP COLUMN
--   repeat_customer_count; ALTER TABLE demand_daily DROP COLUMN customer_count; DELETE FROM schema_migrations WHERE
--   version = 8;

ALTER TABLE demand_daily ADD COLUMN customer_count INTEGER;
ALTER TABLE demand_daily ADD COLUMN repeat_customer_count INTEGER;
ALTER TABLE demand_daily ADD COLUMN repeat_interval_days_sum REAL;
