-- 0012 (v1.3.2): extended history and deals for the same-period-last-year and deal features of the LightGBM chot model
-- (design in docs/hoc_lai_2025_deal_20261030.md sections 1.2 to 1.4). OFF by default (bigquery.deal_code_column and
-- bigquery.deal_table_id empty, model.feature_set CHOT): nothing is written into these tables or the new column until
-- the deal source is configured; demand_daily and every table of 1.3.1 keep their rows and meaning.
--
-- Additive only: new tables, indexes and one nullable column. Nothing is written by the migration; no existing row is
-- changed (the added column reads NULL on every existing row).
--   demand_deal_daily               order-line quantity per data scope x Vietnam day x SKU x FC x deal code, lines with
--                                   a deal code only (same valid lines as the demand: SKU, FC, quantity not NULL and
--                                   >= 0, the app's duplicate rule); each load replaces exactly its own window
--   deal_line_loads                 one record per load of demand_deal_daily (D-1, backfill, manual run)
--   deal_snapshots                  one record per refresh of the deal table: time taken, last-modified time of the
--                                   source table, row count, SHA-256 of the content; the rows are kept gzip-compressed,
--                                   or same_as points to the earlier snapshot with the same content (stored once)
--   deals                           current state of the deal table = rows of the latest snapshot
--   forecast_refresh_values.deal_active  new column: 1 = a valid deal of the deal table covers the target day, 0 = none,
--                                   NULL = deals not configured (every row before 1.3.2)
--
-- Rollback: the application refuses a database newer than it knows, so going back means restoring the pre-upgrade
-- backup (as for 0004-0011). Reverse statements, for a copy only: DROP TABLE deals, deal_snapshots, deal_line_loads,
-- demand_deal_daily (their indexes go with them); ALTER TABLE forecast_refresh_values DROP COLUMN deal_active (SQLite
-- 3.35+, rewrites the table; the 1.3.1 code ignores the column, so a restored backup is the simpler way back);
-- DELETE FROM schema_migrations WHERE version = 12.

CREATE TABLE IF NOT EXISTS demand_deal_daily (
    scope_key   TEXT NOT NULL,            -- data scope of the demand (demand_daily.scope_key)
    order_date  TEXT NOT NULL,            -- Vietnam calendar day (YYYY-MM-DD)
    sku_id      TEXT NOT NULL,
    fc_id       TEXT NOT NULL,
    deal_code   TEXT NOT NULL,            -- value of bigquery.deal_code_column on the order line
    qty         REAL NOT NULL,            -- sum of the order-line quantities of the key
    n_rows      INTEGER NOT NULL,         -- order lines summed
    load_id     TEXT NOT NULL,            -- deal_line_loads.load_id of the load that wrote the row
    loaded_at   TEXT NOT NULL,            -- UTC
    PRIMARY KEY (scope_key, order_date, sku_id, fc_id, deal_code)
);
CREATE INDEX IF NOT EXISTS idx_ddd_deal ON demand_deal_daily(scope_key, deal_code, sku_id, fc_id);

CREATE TABLE IF NOT EXISTS deal_line_loads (
    load_id           TEXT PRIMARY KEY,
    scope_key         TEXT NOT NULL,
    range_start       TEXT NOT NULL,      -- Vietnam days of the window replaced by the load
    range_end         TEXT NOT NULL,
    trigger           TEXT NOT NULL CHECK (trigger IN ('D1_SYNC', 'BACKFILL', 'MANUAL')),
    deal_code_column  TEXT NOT NULL,      -- bigquery.deal_code_column used by the read
    source_version    TEXT,               -- source version / snapshot time read (NULL = current)
    rows_written      INTEGER NOT NULL,
    rows_removed      INTEGER NOT NULL,   -- rows of the window deleted before the write
    qty               REAL NOT NULL,
    lines             INTEGER NOT NULL,   -- order lines read
    estimated_bytes   INTEGER,            -- BigQuery dry-run estimate (NULL = unknown)
    job_id            TEXT,
    started_at        TEXT NOT NULL,      -- UTC
    completed_at      TEXT NOT NULL       -- UTC, after the write committed
);
CREATE INDEX IF NOT EXISTS idx_dll_latest ON deal_line_loads(scope_key, completed_at);

CREATE TABLE IF NOT EXISTS deal_snapshots (
    id               TEXT PRIMARY KEY,
    source_table     TEXT NOT NULL,       -- bigquery.deal_table_id read (project.dataset.table)
    taken_at         TEXT NOT NULL,       -- UTC
    source_modified  TEXT,                -- UTC, last-modified time of the source table (NULL = unknown)
    n_rows           INTEGER NOT NULL,
    content_sha256   TEXT NOT NULL,       -- SHA-256 of the rows (same content = same hash)
    rows_gz          BLOB,                -- gzip-compressed rows (NULL when same_as is set)
    same_as          TEXT REFERENCES deal_snapshots(id),   -- earlier snapshot with the same content
    checks_json      TEXT,                -- checks of the read (duplicate keys, ...)
    estimated_bytes  INTEGER,             -- BigQuery dry-run estimate (NULL = unknown)
    trigger          TEXT,
    job_id           TEXT,
    CHECK ((rows_gz IS NULL) <> (same_as IS NULL))     -- exactly one of the two
);
CREATE INDEX IF NOT EXISTS idx_dsnap_taken ON deal_snapshots(source_table, taken_at);

-- ready_time / end_time are the Vietnam wall clock 'YYYY-MM-DD HH:MM:SS': the source stores Vietnam time in a UTC
-- TIMESTAMP (owner-verified), so the value is kept as written, never shifted by 7 hours
CREATE TABLE IF NOT EXISTS deals (
    source_table   TEXT NOT NULL,         -- bigquery.deal_table_id of the snapshot
    row_no         INTEGER NOT NULL,      -- row number inside the snapshot
    deal_code      TEXT,
    sku_code       TEXT,
    fc_code        TEXT,
    ready_time     TEXT,                  -- Vietnam wall clock
    end_time       TEXT,                  -- Vietnam wall clock
    status         TEXT,
    quantity_used  REAL,
    max_quantity   REAL,
    reason         TEXT,
    snapshot_id    TEXT NOT NULL REFERENCES deal_snapshots(id),
    PRIMARY KEY (source_table, row_no)
);
CREATE INDEX IF NOT EXISTS idx_deals_sku ON deals(source_table, sku_code, fc_code);
CREATE INDEX IF NOT EXISTS idx_deals_code ON deals(source_table, deal_code);

-- a nullable column without default: SQLite adds it without rewriting the table, and the immutability triggers of 0011
-- (BEFORE UPDATE / DELETE) do not fire; existing rows read NULL
ALTER TABLE forecast_refresh_values ADD COLUMN deal_active INTEGER;
