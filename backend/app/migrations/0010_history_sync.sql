-- 0010 (v1.2.13): history sync - the owner's rule of 22/10/2026: the target is the order quantity of the orders placed
-- (gross demand); a stored day is never reduced only because the source later dropped an order line (cancellation,
-- unconfirmed WAIT_TO_CONFIRM, scope change), while late lines and proven re-attributions are taken (rules in
-- app/data/history_sync.py, docs/BIGQUERY.md section 11g).
--
-- Additive only: new tables and their protection triggers. Nothing is written into them by the migration; no existing
-- row or table is changed.
--   demand_held_lines     order lines seen in the source and later removed by it without a proven move: kept in the
--                         stored demand (ACTIVE) until they reappear, a rollback or an explicit owner decision (RELEASED)
--   demand_change_log     every change of a stored demand row (insert / update / delete) with the full row before and
--                         after: never updated or deleted (audit trail, rollback, reconstruction of an older state)
--   demand_sync_runs      one record per load / backfill / preview / rollback / release (source version, window,
--                         counts, backup); only COMMITTED -> ROLLED_BACK may change afterwards
--   demand_sync_run_keys  the per-key decisions of a run or preview (report)
--   source_day_checks     latest daily check of each stored history day against the source (outside the D-1 window)
--
-- Rollback: the application refuses a database newer than it knows, so going back means restoring the pre-upgrade
-- backup (as for 0004-0009). Reverse statements, for a copy only: DROP the triggers trg_dhl_*, trg_dcl_*, trg_dsr_*,
-- trg_dsk_*, DROP TABLE source_day_checks, demand_sync_run_keys, demand_sync_runs, demand_change_log,
-- demand_held_lines; DELETE FROM schema_migrations WHERE version = 10.

CREATE TABLE demand_held_lines (
    id              TEXT PRIMARY KEY,
    scope_key       TEXT NOT NULL,
    order_date      TEXT NOT NULL,          -- the day x SKU x FC the line belongs to (= demand_daily key)
    sku_id          TEXT NOT NULL,
    fc_id           TEXT NOT NULL,
    order_id        TEXT,                   -- source order code; NULL for a pending order without code or NO_EVIDENCE
    product_id      TEXT,
    item_code       TEXT,
    order_status    TEXT,                   -- last status the line had in the source
    qty             REAL NOT NULL CHECK (qty > 0),
    cause           TEXT NOT NULL CHECK (cause IN ('ORDER_GONE', 'LINE_GONE', 'PENDING_GONE', 'QTY_REDUCED', 'NO_EVIDENCE')),
    status          TEXT NOT NULL CHECK (status IN ('ACTIVE', 'RELEASED')),
    detected_run    TEXT NOT NULL,          -- load / backfill / rollback that recorded it
    detected_at     TEXT NOT NULL,
    base_asof       TEXT,                   -- source version (time travel timestamp, UTC) in which the line was seen
    evidence_json   TEXT,
    released_run    TEXT,
    released_at     TEXT,
    release_reason  TEXT CHECK (release_reason IS NULL OR release_reason IN ('REAPPEARED', 'ROLLBACK', 'OWNER_DECISION')),
    restored_from   TEXT,                   -- a line held again by a rollback copies the released hold (its id)
    CHECK ((status = 'ACTIVE' AND released_at IS NULL AND released_run IS NULL AND release_reason IS NULL)
           OR (status = 'RELEASED' AND released_at IS NOT NULL AND released_run IS NOT NULL AND release_reason IS NOT NULL))
);
CREATE INDEX idx_dhl_active ON demand_held_lines(scope_key, order_date, sku_id, fc_id) WHERE status = 'ACTIVE';
CREATE INDEX idx_dhl_run ON demand_held_lines(detected_run);

CREATE TRIGGER trg_dhl_no_delete BEFORE DELETE ON demand_held_lines
BEGIN SELECT RAISE(ABORT, 'demand_held_lines are never deleted'); END;
-- what was held never changes; the only update is ACTIVE -> RELEASED (with when / by which run / why)
CREATE TRIGGER trg_dhl_fixed BEFORE UPDATE ON demand_held_lines
WHEN OLD.status = 'RELEASED' OR NEW.status IS NOT 'RELEASED'
     OR NEW.id IS NOT OLD.id OR NEW.scope_key IS NOT OLD.scope_key OR NEW.order_date IS NOT OLD.order_date
     OR NEW.sku_id IS NOT OLD.sku_id OR NEW.fc_id IS NOT OLD.fc_id OR NEW.order_id IS NOT OLD.order_id
     OR NEW.product_id IS NOT OLD.product_id OR NEW.item_code IS NOT OLD.item_code OR NEW.qty IS NOT OLD.qty
     OR NEW.cause IS NOT OLD.cause OR NEW.detected_run IS NOT OLD.detected_run OR NEW.detected_at IS NOT OLD.detected_at
     OR NEW.base_asof IS NOT OLD.base_asof OR NEW.evidence_json IS NOT OLD.evidence_json
     OR NEW.restored_from IS NOT OLD.restored_from
BEGIN SELECT RAISE(ABORT, 'a held line only goes from ACTIVE to RELEASED once'); END;

CREATE TABLE demand_change_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT NOT NULL,             -- demand_sync_runs.id
    run_kind     TEXT NOT NULL CHECK (run_kind IN ('D1_SYNC', 'BACKFILL', 'ROLLBACK', 'HOLD_RELEASE')),
    scope_key    TEXT NOT NULL,
    order_date   TEXT NOT NULL,
    sku_id       TEXT NOT NULL,
    fc_id        TEXT NOT NULL,
    action       TEXT NOT NULL CHECK (action IN ('INSERT', 'UPDATE', 'DELETE')),
    qty_before   REAL,
    qty_after    REAL,
    held_after   REAL NOT NULL DEFAULT 0,   -- units of held lines inside qty_after
    before_json  TEXT,                      -- the whole stored row before (UPDATE / DELETE)
    after_json   TEXT,                      -- the whole stored row after (INSERT / UPDATE)
    finalized    INTEGER NOT NULL DEFAULT 0 CHECK (finalized IN (0, 1)),   -- the day had a FINALIZED actual (changed after)
    at           TEXT NOT NULL,
    CHECK ((action = 'INSERT' AND before_json IS NULL AND after_json IS NOT NULL)
           OR (action = 'UPDATE' AND before_json IS NOT NULL AND after_json IS NOT NULL)
           OR (action = 'DELETE' AND before_json IS NOT NULL AND after_json IS NULL))
);
CREATE INDEX idx_dcl_key ON demand_change_log(scope_key, order_date, sku_id, fc_id);
CREATE INDEX idx_dcl_run ON demand_change_log(run_id);

CREATE TRIGGER trg_dcl_no_update BEFORE UPDATE ON demand_change_log
BEGIN SELECT RAISE(ABORT, 'demand_change_log is append-only'); END;
CREATE TRIGGER trg_dcl_no_delete BEFORE DELETE ON demand_change_log
BEGIN SELECT RAISE(ABORT, 'demand_change_log is append-only'); END;

CREATE TABLE demand_sync_runs (
    id              TEXT PRIMARY KEY,       -- D1L-... load / BFP-... preview / RBK-... rollback / HRL-... release
    kind            TEXT NOT NULL CHECK (kind IN ('D1_SYNC', 'BACKFILL', 'PREVIEW', 'ROLLBACK', 'HOLD_RELEASE')),
    status          TEXT NOT NULL CHECK (status IN ('PREVIEW', 'COMMITTED', 'ROLLED_BACK')),
    scope_key       TEXT NOT NULL,
    window_start    TEXT,
    window_end      TEXT,
    policy          TEXT,
    source_version  TEXT,                   -- source table version (modified time, UTC) read, stable during the run
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    summary_json    TEXT NOT NULL,
    backup          TEXT,
    job_id          TEXT,
    preview_id      TEXT,
    rolled_back_by  TEXT,
    rolled_back_at  TEXT
);
CREATE INDEX idx_dsr_scope ON demand_sync_runs(scope_key, started_at);

CREATE TRIGGER trg_dsr_no_delete BEFORE DELETE ON demand_sync_runs
BEGIN SELECT RAISE(ABORT, 'demand_sync_runs are never deleted'); END;
CREATE TRIGGER trg_dsr_fixed BEFORE UPDATE ON demand_sync_runs
WHEN NOT (OLD.status = 'COMMITTED' AND NEW.status = 'ROLLED_BACK' AND NEW.rolled_back_by IS NOT NULL
          AND NEW.rolled_back_at IS NOT NULL AND NEW.id IS OLD.id AND NEW.kind IS OLD.kind
          AND NEW.scope_key IS OLD.scope_key AND NEW.summary_json IS OLD.summary_json
          AND NEW.started_at IS OLD.started_at AND NEW.finished_at IS OLD.finished_at
          AND NEW.window_start IS OLD.window_start AND NEW.window_end IS OLD.window_end AND NEW.policy IS OLD.policy
          AND NEW.source_version IS OLD.source_version AND NEW.backup IS OLD.backup AND NEW.job_id IS OLD.job_id
          AND NEW.preview_id IS OLD.preview_id)
BEGIN SELECT RAISE(ABORT, 'a sync run only goes from COMMITTED to ROLLED_BACK once'); END;

CREATE TABLE demand_sync_run_keys (
    run_id      TEXT NOT NULL,
    order_date  TEXT NOT NULL,
    sku_id      TEXT NOT NULL,
    fc_id       TEXT NOT NULL,
    kind        TEXT NOT NULL,              -- NEW | UPDATED | REMOVED | HELD | RELEASED
    stored_qty  REAL,
    source_qty  REAL,
    target_qty  REAL,
    held_qty    REAL NOT NULL DEFAULT 0,
    causes_json TEXT,
    PRIMARY KEY (run_id, order_date, sku_id, fc_id)
) WITHOUT ROWID;

CREATE TRIGGER trg_dsk_no_update BEFORE UPDATE ON demand_sync_run_keys
BEGIN SELECT RAISE(ABORT, 'demand_sync_run_keys are append-only'); END;
CREATE TRIGGER trg_dsk_no_delete BEFORE DELETE ON demand_sync_run_keys
BEGIN SELECT RAISE(ABORT, 'demand_sync_run_keys are append-only'); END;

CREATE TABLE source_day_checks (
    scope_key       TEXT NOT NULL,
    order_date      TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('MATCH', 'DIFF')),
    checked_at      TEXT NOT NULL,          -- latest check (UTC)
    verified_at     TEXT,                   -- latest check that matched: the stored day = the source + held lines
    source_version  TEXT,
    source_keys     INTEGER,
    source_qty      REAL,
    stored_keys     INTEGER,                -- stored keys minus keys kept only by held lines
    stored_qty      REAL,                   -- stored units minus held units
    run_id          TEXT,
    PRIMARY KEY (scope_key, order_date)
) WITHOUT ROWID;
