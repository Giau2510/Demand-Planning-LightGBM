-- 0009 (v1.2.9, seventh batch): finalized (frozen) actual of a business day - the owner's rule of 20/10/2026: the
-- actual of a completed day is finalized from the successful D-1 load that wrote it and never changes afterwards
-- (rules in app/actual_final.py, docs/LICH-SU-FORECAST.md section 15).
--
-- Additive only: two new tables and their protection triggers. Nothing is written into them by the migration; no
-- existing row or table is changed. A day is finalized later by the application (after a successful D-1 load, or
-- `python -m app.cli actual-finalize --apply`) only when its stored rows can be traced to a verified D-1 load.
--   actual_finals         one header per scope x business day: FINALIZED (sealed = 1: values complete, immutable) or
--                         BLOCKED (why the day could not be finalized yet; may later become FINALIZED, never the reverse)
--   actual_final_values   the frozen SKU x FC quantities of a FINALIZED day (only rows present in the source; an absent
--                         SKU x FC is not stored)
--
-- Rollback: the application refuses a database newer than it knows, so going back means restoring the pre-upgrade
-- backup (as for 0004-0008). Reverse statements, for a copy only: DROP the ten triggers trg_afn_* / trg_afv_*, DROP
-- TABLE actual_final_values; DROP TABLE actual_finals; DELETE FROM schema_migrations WHERE version = 9.

CREATE TABLE actual_finals (
    id               TEXT PRIMARY KEY,
    scope_key        TEXT NOT NULL,
    data_source      TEXT NOT NULL,
    business_date    TEXT NOT NULL,      -- Vietnam day of the demand (= demand_daily.order_date)
    status           TEXT NOT NULL CHECK (status IN ('FINALIZED','BLOCKED')),
    reason           TEXT NOT NULL,      -- FINALIZED: D1_LOAD; BLOCKED: why (NO_VERIFIED_D1_LOAD, MIXED_LOADS, ...)
    sealed           INTEGER NOT NULL DEFAULT 0 CHECK (sealed IN (0, 1)),   -- 1 = every value written and checked
    d1_load_id       TEXT,               -- the D-1 load that wrote the frozen rows (sync_state / audit D1_SYNC)
    d1_job_id        TEXT,
    d1_synced_at     TEXT,               -- = demand_daily.loaded_at of the frozen rows (UTC)
    d1_mode          TEXT,               -- SIGNAL | FALLBACK_TIME_VERIFIED | BACKFILL
    d1_backfill      INTEGER,
    d1_full_reload   INTEGER,
    d1_window_start  TEXT,
    d1_window_end    TEXT,
    d1_watermark     TEXT,
    d1_mapping_hash  TEXT,
    d1_preview_id    TEXT,
    n_rows           INTEGER,            -- SKU x FC rows frozen
    total_qty        REAL,
    total_orders     INTEGER,
    values_sha256    TEXT,
    timezone         TEXT NOT NULL,
    finalized_by     TEXT,               -- AFTER_D1 | CLI | ...
    job_id           TEXT,               -- job that ran the finalization (the D-1 job when AFTER_D1)
    attempts         INTEGER NOT NULL DEFAULT 1,
    first_attempt_at TEXT NOT NULL,
    last_attempt_at  TEXT NOT NULL,
    finalized_at     TEXT,               -- when the day became FINALIZED (UTC)
    CHECK (status != 'FINALIZED' OR (d1_synced_at IS NOT NULL AND n_rows > 0 AND total_qty IS NOT NULL
                                     AND values_sha256 IS NOT NULL AND finalized_at IS NOT NULL)),
    UNIQUE (scope_key, business_date)
);

CREATE TABLE actual_final_values (
    final_id  TEXT NOT NULL REFERENCES actual_finals(id),
    sku_id    TEXT NOT NULL,
    fc_id     TEXT NOT NULL,
    qty       REAL NOT NULL CHECK (qty >= 0),
    n_orders  INTEGER,
    PRIMARY KEY (final_id, sku_id, fc_id)
) WITHOUT ROWID;

CREATE TRIGGER trg_afn_no_delete BEFORE DELETE ON actual_finals
BEGIN SELECT RAISE(ABORT, 'actual_finals are never deleted'); END;
CREATE TRIGGER trg_afn_keys_fixed BEFORE UPDATE OF id, scope_key, data_source, business_date ON actual_finals
BEGIN SELECT RAISE(ABORT, 'actual_finals keys never change'); END;
CREATE TRIGGER trg_afn_born_unsealed BEFORE INSERT ON actual_finals WHEN NEW.sealed IS NOT 0
BEGIN SELECT RAISE(ABORT, 'an actual_finals row is sealed only by the checked update'); END;
CREATE TRIGGER trg_afn_no_replace BEFORE INSERT ON actual_finals
WHEN EXISTS (SELECT 1 FROM actual_finals f WHERE f.id = NEW.id)
  OR EXISTS (SELECT 1 FROM actual_finals f WHERE f.scope_key = NEW.scope_key AND f.business_date = NEW.business_date)
BEGIN SELECT RAISE(ABORT, 'actual_finals: key exists (never replaced)'); END;
-- a FINALIZED day is immutable; the only change ever allowed is sealing it once, inside the transaction that wrote it
CREATE TRIGGER trg_afn_final_fixed BEFORE UPDATE ON actual_finals
WHEN OLD.status = 'FINALIZED' AND (OLD.sealed = 1 OR NEW.sealed IS NOT 1 OR NEW.status IS NOT 'FINALIZED'
     OR NEW.reason IS NOT OLD.reason OR NEW.n_rows IS NOT OLD.n_rows OR NEW.total_qty IS NOT OLD.total_qty
     OR NEW.total_orders IS NOT OLD.total_orders OR NEW.values_sha256 IS NOT OLD.values_sha256
     OR NEW.d1_load_id IS NOT OLD.d1_load_id OR NEW.d1_synced_at IS NOT OLD.d1_synced_at
     OR NEW.d1_mode IS NOT OLD.d1_mode OR NEW.finalized_at IS NOT OLD.finalized_at)
BEGIN SELECT RAISE(ABORT, 'a FINALIZED actual is immutable'); END;
CREATE TRIGGER trg_afn_seal_checked BEFORE UPDATE OF sealed ON actual_finals
WHEN NEW.sealed = 1 AND (NEW.status IS NOT 'FINALIZED'
     OR (SELECT COUNT(*) FROM actual_final_values v WHERE v.final_id = NEW.id) IS NOT NEW.n_rows
     OR ABS((SELECT TOTAL(v.qty) FROM actual_final_values v WHERE v.final_id = NEW.id) - NEW.total_qty)
        > 1e-6 * MAX(1.0, ABS(NEW.total_qty)))
BEGIN SELECT RAISE(ABORT, 'actual_finals: values do not match the header (not sealed)'); END;

CREATE TRIGGER trg_afv_no_update BEFORE UPDATE ON actual_final_values
BEGIN SELECT RAISE(ABORT, 'actual_final_values are immutable'); END;
CREATE TRIGGER trg_afv_no_delete BEFORE DELETE ON actual_final_values
BEGIN SELECT RAISE(ABORT, 'actual_final_values are immutable'); END;
CREATE TRIGGER trg_afv_open_only BEFORE INSERT ON actual_final_values
WHEN (SELECT status FROM actual_finals WHERE id = NEW.final_id) IS NOT 'FINALIZED'
  OR (SELECT sealed FROM actual_finals WHERE id = NEW.final_id) IS NOT 0
BEGIN SELECT RAISE(ABORT, 'values belong to a FINALIZED actual that is not sealed yet'); END;
CREATE TRIGGER trg_afv_no_replace BEFORE INSERT ON actual_final_values
WHEN EXISTS (SELECT 1 FROM actual_final_values v WHERE v.final_id = NEW.final_id AND v.sku_id = NEW.sku_id
             AND v.fc_id = NEW.fc_id)
BEGIN SELECT RAISE(ABORT, 'actual_final_values: key exists (never replaced)'); END;
