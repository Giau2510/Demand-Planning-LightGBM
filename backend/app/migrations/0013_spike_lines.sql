-- 0013 (v1.4.8): spike cleaning of the SEL2 training data - the SO lines (customer_id, order code) read from the
-- BigQuery source, the spike flags of those lines (logic v3, ml/sel2/spike.py) and the spike excess per SKU x FC x day.
-- Settings: sel2_pipeline.spike_cleaning (OFF by default; OFF = SEL2 does not use these tables and the forecast numbers
-- are those of 1.4.7; the nightly job SPIKE_LINES fills them in either state) and sel2_pipeline.spike_e4_n (E4 rule, 4).
--
-- Additive only: new tables and an index. Nothing is written into them by the migration; no existing row or table is
-- changed (order_lines / demand_daily of the Excel and DEMO batches are not touched). Dates are Vietnam calendar days
-- (YYYY-MM-DD); timestamps are UTC ISO-8601.
--   so_lines_cache      SO lines of a BIGQUERY scope: one row = order day x FC x SKU x so_code x customer_id, the source
--                       rows of that line summed (n_rows). A re-readable working cache of the source (the only table
--                       of this migration that is pruned, to its last 210 days); customer_id '' = unknown customer
--   spike_flag_lines    the flagged lines (n_signals_raw >= 1) of the runs, with every value the excess as of a day
--                       needs (T7 is recomputed as of the day); computed_for = the run day (data up to the day before).
--                       Training data: never pruned; a run replaces the rows of the days it recomputed
--   demand_excess_daily the excess per SKU x FC x day as of the latest run (level, E4 days N), derived: for checks and
--                       reports; only rows with excess > 0
--
-- Rollback: the application refuses a database newer than it knows, so going back means restoring the pre-upgrade
-- backup (as for 0004-0012). Reverse statements, for a copy only: DROP TABLE demand_excess_daily, spike_flag_lines,
-- so_lines_cache (their indexes go with them); DELETE FROM schema_migrations WHERE version = 13.

CREATE TABLE IF NOT EXISTS so_lines_cache (
    scope_key    TEXT NOT NULL,                       -- data scope of the demand (demand_daily.scope_key, BIGQUERY)
    order_date   TEXT NOT NULL,                       -- Vietnam order day
    fc_code      TEXT NOT NULL,
    sku_code     TEXT NOT NULL,
    so_code      TEXT NOT NULL,                       -- '' = no order code in the source
    customer_id  TEXT NOT NULL,                       -- '' = unknown customer (its own customer per order)
    qty          REAL NOT NULL CHECK (qty >= 0),      -- sum of the source rows of the line (0 = not a purchase)
    n_rows       INTEGER NOT NULL DEFAULT 1 CHECK (n_rows >= 1),
    loaded_at    TEXT NOT NULL,                       -- UTC
    PRIMARY KEY (scope_key, order_date, fc_code, sku_code, so_code, customer_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_slc_series ON so_lines_cache(scope_key, fc_code, sku_code, order_date);

CREATE TABLE IF NOT EXISTS spike_flag_lines (
    scope_key      TEXT NOT NULL,
    logic          TEXT NOT NULL CHECK (logic IN ('v3')),
    history_days   INTEGER NOT NULL CHECK (history_days BETWEEN 1 AND 3650),
    d              TEXT NOT NULL,                     -- order day of the line
    fc_code        TEXT NOT NULL,
    sku_code       TEXT NOT NULL,
    so_code        TEXT NOT NULL,
    customer_id    TEXT NOT NULL,                     -- '' = unknown customer
    qty            REAL NOT NULL CHECK (qty > 0),
    group_code     TEXT CHECK (group_code IN ('A', 'B', 'C')),   -- sku_group of the line's day, NULL = none
    min_qty        REAL NOT NULL,                     -- minimum quantity of a signal (5, group C: 3)
    n_prev         INTEGER NOT NULL,                  -- earlier lines of the customer x SKU x FC in the history window
    cust_med       REAL,                              -- median qty of those lines (NULL = none)
    gap_med        REAL,                              -- median gap in days between its purchase days (NULL = none)
    n_gaps         INTEGER NOT NULL,
    next_day       TEXT,                              -- next purchase day of the customer x SKU x FC (NULL = none seen)
    kept           REAL NOT NULL CHECK (kept >= 0),   -- normal part of the line; excess = qty - kept when > 0
    T1             INTEGER NOT NULL CHECK (T1 IN (0, 1)),
    T2             INTEGER NOT NULL CHECK (T2 IN (0, 1)),
    T4             INTEGER NOT NULL CHECK (T4 IN (0, 1)),
    T7             INTEGER NOT NULL CHECK (T7 IN (0, 1)),   -- as of computed_for (recomputed as of each day)
    n_signals_raw  INTEGER NOT NULL CHECK (n_signals_raw >= 1),
    exc_wholesale  INTEGER NOT NULL CHECK (exc_wholesale IN (0, 1)),
    exc_periodic   INTEGER NOT NULL CHECK (exc_periodic IN (0, 1)),
    exc_demand     INTEGER NOT NULL CHECK (exc_demand IN (0, 1)),
    is_regular     INTEGER NOT NULL CHECK (is_regular IN (0, 1)),
    computed_for   TEXT NOT NULL,                     -- run day: data up to the day before
    computed_at    TEXT NOT NULL,                     -- UTC
    PRIMARY KEY (scope_key, logic, history_days, d, fc_code, sku_code, so_code, customer_id),
    CHECK (d < computed_for)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS demand_excess_daily (
    scope_key    TEXT NOT NULL,
    d            TEXT NOT NULL,                       -- demand day
    fc_code      TEXT NOT NULL,
    sku_code     TEXT NOT NULL,
    level        INTEGER NOT NULL CHECK (level BETWEEN 1 AND 3),
    e4_n         INTEGER NOT NULL CHECK (e4_n BETWEEN 1 AND 30),
    excess       REAL NOT NULL CHECK (excess > 0),
    asof         TEXT NOT NULL,                       -- the excess uses the lines before this day only
    computed_at  TEXT NOT NULL,                       -- UTC
    PRIMARY KEY (scope_key, d, fc_code, sku_code, level, e4_n),
    CHECK (d < asof)
) WITHOUT ROWID;
