# Data dictionary (SQLite, schema version 5 since 1.2.6; tables of version 4 unchanged)

Generated from `PRAGMA table_info / index_list / foreign_key_list` of a read-only **copy** of the live database (integrity `ok`, foreign-key violations 0) and annotated from the code. Row counts are from that copy on 2026-10-15 and only indicate scale. Empty *Meaning* = the column name is self-describing; nothing has been invented. See [DATA-MODEL.md](DATA-MODEL.md) for relationships, lifecycle and rules.

Conventions: timestamps are UTC ISO-8601 strings with offset (`timeutil.iso`); business dates are Vietnam calendar dates `YYYY-MM-DD` (Asia/Ho_Chi_Minh); `*_json` columns hold JSON text; SQLite types are affinities (TEXT/INTEGER/REAL), not enforced types.

## `actual_closes` (1.2.6, migration 0005)

Close of a business day's actual at 23:59 (revision 1, `kind` CLOSE) and the later revisions recorded when the actual
changed (`kind` RECONCILIATION). Immutable; revisions consecutive (triggers). Code: `actual_close.py`.

| Column | Type | Null | Key | Default | Meaning / rule |
|---|---|---|---|---|---|
| `id` | TEXT | no | PK |  | ACL-... |
| `scope_key`, `data_source` | TEXT | no | UNIQUE(1) |  | active scope at the close |
| `business_date` | TEXT | no | UNIQUE(2) |  | Vietnam day closed (date of the slot, never the UTC date) |
| `revision` | INTEGER | no | UNIQUE(3) |  | 1 = close, n > 1 follows n - 1 (`previous_id`) |
| `kind`, `reason` | TEXT | no |  |  | CLOSE / RECONCILIATION; SCHEDULED_CLOSE, CATCH_UP_CLOSE, MANUAL_CLOSE, D1_LOADED, D1_RELOADED, D0_LATE_READ, COMPLETION_SIGNAL_CONFIRMED, SOURCE_HAS_NO_DATA |
| `source`, `source_ref`, `source_as_of`, `source_reason` | TEXT | yes |  |  | D1 (ref = load time) / D0 (ref = snapshot id) / NULL (no data); read time; actual_context reason |
| `n_rows`, `total_qty`, `values_sha256` | INTEGER / REAL / TEXT | no / yes / yes |  |  | SKU x FC rows present in the source (absent rows are not stored); total NULL when no data |
| `status`, `status_reason` | TEXT | no / yes |  |  | CLOSED_VERIFIED (completion signal) / CLOSED_UNVERIFIED / CLOSED_NO_DATA (CHECK) |
| `previous_id`, `previous_total`, `n_changed`, `n_added`, `n_removed` | TEXT / REAL / INTEGER | yes |  |  | before / after of a revision |
| `cutoff_at`, `closed_at`, `timezone`, `job_id` | TEXT | no / no / no / yes |  |  | business_date close time (UTC); time written (UTC); Asia/Ho_Chi_Minh |

## `actual_close_values` (1.2.6, migration 0005)

SKU x FC quantities of one close revision (WITHOUT ROWID). Immutable.

| Column | Type | Null | Key | Default | Meaning / rule |
|---|---|---|---|---|---|
| `close_id` | TEXT | no | PK(1) FK -> actual_closes |  |  |
| `sku_id`, `fc_id` | TEXT | no | PK(2), PK(3) |  |  |
| `qty` | REAL | no |  |  | as read from the source (D-1 qty or D0 cumulative) |

## `alerts`

User-visible alerts (INFO/WARNING/ERROR) with a message code and parameters.  
Code: `db.py` - rows in copy: 5

| Column | Type | Null | Key | Default | Meaning / rule |
|---|---|---|---|---|---|
| `id` | INTEGER | no | PK |  |  |
| `created_at` | TEXT | no |  |  | UTC ISO-8601 timestamp of row creation (app time), unless stated otherwise |
| `level` | TEXT | no |  |  | INFO / WARNING / ERROR (CHECK) |
| `code` | TEXT | no |  |  |  |
| `params_json` | TEXT | yes |  |  |  |
| `entity_type` | TEXT | yes |  |  |  |
| `entity_id` | TEXT | yes |  |  |  |
| `acknowledged_at` | TEXT | yes |  |  |  |

## `app_settings`

Current value of each settings section (Pydantic models in settings_service.py). A row exists only for sections that were saved at least once; every other section - and every key missing from a stored section - takes the default from the CODE of the running version (see DATA-MODEL.md, data that lives only in code).  
Code: `settings_service.py` - rows in copy: 4

| Column | Type | Null | Key | Default | Meaning / rule |
|---|---|---|---|---|---|
| `section` | TEXT | no | PK |  | settings section name (general, horizons, quality, model, import, data_policy, schedule, bigquery, sql_sources, ...) |
| `value_json` | TEXT | no |  |  | full section JSON; validated by its Pydantic model on read and write; never contains secrets |
| `updated_at` | TEXT | no |  |  |  |

## `audit_log`

Append-only audit trail of user and system actions.  
Code: `db.py` - rows in copy: 46

| Column | Type | Null | Key | Default | Meaning / rule |
|---|---|---|---|---|---|
| `id` | INTEGER | no | PK |  |  |
| `at` | TEXT | no |  |  |  |
| `action` | TEXT | no |  |  |  |
| `entity_type` | TEXT | yes |  |  |  |
| `entity_id` | TEXT | yes |  |  |  |
| `details_json` | TEXT | yes |  |  |  |

## `backtest_runs`

Walk-forward backtest of a training run (folds + pooled metrics).  
Code: `ml/pipeline.py, ml/model.py` - rows in copy: 1

| Column | Type | Null | Key | Default | Meaning / rule |
|---|---|---|---|---|---|
| `id` | TEXT | no | PK |  |  |
| `training_run_id` | TEXT | no | FK -> training_runs.id |  |  |
| `created_at` | TEXT | no |  |  | UTC ISO-8601 timestamp of row creation (app time), unless stated otherwise |
| `config_json` | TEXT | no |  |  |  |
| `folds_json` | TEXT | no |  |  |  |
| `metrics_json` | TEXT | no |  |  |  |
| `reliable` | INTEGER | no |  |  |  |
| `notes_json` | TEXT | yes |  |  |  |

## `d0_snapshot_values`

Cumulative quantity per SKU x FC in a D0 snapshot. UPDATE blocked by trigger.  
Code: `sync.py` - rows in copy: 602

| Column | Type | Null | Key | Default | Meaning / rule |
|---|---|---|---|---|---|
| `snapshot_id` | TEXT | no | PK(1) FK -> d0_snapshots.id |  |  |
| `sku_id` | TEXT | no | PK(2) |  | SKU code as text (leading zeros kept) |
| `fc_id` | TEXT | no | PK(3) |  | fulfilment centre / warehouse code as text |
| `cumulative_qty` | REAL | no |  |  | cumulative quantity of the day up to snapshot_at |
| `source_updated_at` | TEXT | yes |  |  |  |

## `d0_snapshots`

Header of one successful intraday (D0) read of today's cumulative demand. Written only on success.  
Code: `sync.py` - rows in copy: 10

| Column | Type | Null | Key | Default | Meaning / rule |
|---|---|---|---|---|---|
| `id` | TEXT | no | PK |  |  |
| `data_source` | TEXT | no |  |  | DEMO / MANUAL_IMPORT / BIGQUERY |
| `scope_key` | TEXT | no |  |  | dataset key: DEMO/MANUAL_IMPORT batch id or BIGQUERY:<project>.<dataset>.<table> |
| `order_date` | TEXT | no |  |  | VN business date of the intraday read |
| `snapshot_at` | TEXT | no |  |  | UTC time the source was read |
| `scheduled_slot` | TEXT | yes |  |  | VN slot the run belongs to (ISO with +07:00), NULL for manual runs |
| `is_catch_up` | INTEGER | no |  | `0` |  |
| `sync_status` | TEXT | no |  |  |  |
| `rows_read` | INTEGER | no |  |  |  |
| `rows_valid` | INTEGER | no |  |  |  |
| `rows_error` | INTEGER | no |  |  |  |
| `source_updated_max` | TEXT | yes |  |  |  |
| `source_batch_id` | TEXT | yes |  |  |  |
| `job_id` | TEXT | yes |  |  | job_runs.id that produced the row (logical reference, no FK) |
| `created_at` | TEXT | no |  |  | UTC ISO-8601 timestamp of row creation (app time), unless stated otherwise |

Indexes: `ix_d0_snapshots_date`(order_date, snapshot_at)

## `demand_daily`

Daily demand per scope = exactly one dataset (DEMO batch id, MANUAL_IMPORT batch id, or BIGQUERY:<project>.<dataset>.<table>). Grain: scope x order_date x SKU x FC. Training input.  
Code: `data/demand.py, sync.py` - rows in copy: 38533

| Column | Type | Null | Key | Default | Meaning / rule |
|---|---|---|---|---|---|
| `scope_key` | TEXT | no | PK(1) |  | dataset key: DEMO/MANUAL_IMPORT batch id or BIGQUERY:<project>.<dataset>.<table> |
| `data_source` | TEXT | no |  |  | DEMO / MANUAL_IMPORT / BIGQUERY |
| `order_date` | TEXT | no | PK(2) |  | VN business date |
| `sku_id` | TEXT | no | PK(3) |  | SKU code as text (leading zeros kept) |
| `fc_id` | TEXT | no | PK(4) |  | fulfilment centre / warehouse code as text |
| `qty` | REAL | no |  |  | SUM(order_qty) of the day; absent row = no recorded demand (the model panel fills 0 for active series) |
| `n_orders` | INTEGER | no |  | `0` | distinct orders (order_id, else one per line) |
| `avg_unit_price` | REAL | yes |  |  |  |
| `avg_discount_rate` | REAL | yes |  |  |  |
| `promo_share` | REAL | yes |  |  |  |
| `voucher_share` | REAL | yes |  |  |  |
| `loaded_at` | TEXT | no |  |  | UTC time the row was (re)built |

## `forecast_eod_snapshots` (1.2.6, migration 0005)

End-of-day forecast backup per scope and business day S: the next 7 forecast days (S+1..S+7) of the official session of
the newest run date <= S. One row per (scope, day) (UNIQUE). A COMPLETE row never changes; an INCOMPLETE / NO_SOURCE row
may only be completed by a later attempt of the same day. Code: `forecast_backup.py`. Deletion (1.2.6, migration 0006):
only by the 90-day retention (`eod_retention.py`): a permit row in `forecast_eod_snapshot_retention` inserted by the same
connection, business date older than its cutoff and than `date('now', '+7 hours', '-90 days')`, values first (triggers
`trg_fes_delete_retention_only`, `trg_fes_values_delete_retention_only`); every other DELETE is refused.

| Column | Type | Null | Key | Default | Meaning / rule |
|---|---|---|---|---|---|
| `id` | TEXT | no | PK |  | FES-... |
| `scope_key`, `data_source` | TEXT | no | UNIQUE(1) |  |  |
| `business_date` | TEXT | no | UNIQUE(2) |  | Vietnam day the snapshot stands for |
| `first_target_date`, `last_target_date`, `n_days` | TEXT / TEXT / INTEGER | no |  |  | S+1, S+7, 7 |
| `source_run_id` | TEXT | yes | FK -> forecast_runs |  | NULL when no valid session existed |
| `source_run_date`, `source_session_started_at`, `source_published_at`, `source_model_version`, `source_training_run_id`, `source_data_as_of`, `source_n_series` | TEXT / INTEGER | yes |  |  | trace of the source session |
| `n_rows`, `days_covered`, `missing_dates_json`, `total_yhat`, `values_sha256` | INTEGER / TEXT / REAL | no / no / yes / yes / yes |  |  | n_rows = 7 x series when COMPLETE, else 0 |
| `status`, `status_reason` | TEXT | no / yes |  |  | COMPLETE / INCOMPLETE / NO_SOURCE (CHECK); e.g. SOURCE_COVERS_4_OF_7_DAYS |
| `timezone`, `job_id`, `attempts`, `created_at`, `updated_at` | TEXT / INTEGER | no / yes / no / no / no |  | attempts 1 | first and last attempt (UTC) |

Index: `ix_fes_scope_day`(scope_key, status, business_date)

## `forecast_eod_snapshot_values` (1.2.6, migration 0005)

Values of a COMPLETE end-of-day snapshot, copied from `forecast_values` (WITHOUT ROWID). Insert allowed only for a
COMPLETE snapshot; never updated; deleted only with their snapshot by the 90-day retention (triggers, migration 0006).
About 7 x 17,127 = 119,889 rows (~11.8 MB) per day on production data (measured on a copy, 18/10/2026).

## `forecast_eod_snapshot_retention` (1.2.6, migration 0006)

Permit and permanent record of each end-of-day snapshot deleted by the 90-day retention (`eod_retention.py`, CLI
`eod-retention`, LICH-SU-FORECAST.md section 14). Insert only for an existing snapshot (same id, scope, day, status,
n_rows) older than the database's 90-day floor, and only when no other permit is DELETING; keys never change;
DELETING -> DELETED once, only after the snapshot and its values are gone; never deleted (triggers `trg_fesr_*`).

| Column | Type | Null | Key | Default | Meaning / rule |
|---|---|---|---|---|---|
| `seq` | INTEGER | no | PK AUTOINCREMENT |  | permit identity, random 62-bit value set by `eod_retention.py`: a DELETE is allowed only while `seq = last_insert_rowid()` of the deleting connection |
| `run_id` | TEXT | no |  |  | RET-... one retention run (several snapshots, one transaction each) |
| `snapshot_id` | TEXT | no | UNIQUE |  | the deleted snapshot (no FK: the row outlives it) |
| `scope_key`, `data_source`, `business_date`, `first_target_date`, `last_target_date`, `snapshot_status` | TEXT | no |  |  | copied from the snapshot |
| `source_run_id`, `source_run_date`, `values_sha256`, `total_yhat` | TEXT / REAL | yes |  |  | copied from the snapshot (trace after deletion) |
| `n_rows`, `snapshot_created_at` | INTEGER / TEXT | no |  |  | values recorded by the header; snapshot creation time (UTC) |
| `policy_days`, `cutoff_date` | INTEGER / TEXT | no |  |  | 90 (CHECK >= 90); business_date < cutoff_date = today (Vietnam) - 90 |
| `state`, `rows_deleted` | TEXT / INTEGER | no / yes |  |  | DELETING (inside the transaction only) / DELETED; values actually deleted |
| `requested_by`, `backup_file` | TEXT | no / yes |  |  | CLI; verified backup taken before the run |
| `started_at`, `finished_at` | TEXT | no / yes |  |  | UTC |

Index: `ix_fesr_scope_day`(scope_key, business_date)

Migration 0006 also refuses an `INSERT OR REPLACE` that collides with an existing key on `forecast_eod_snapshots`,
`forecast_eod_snapshot_values`, `actual_closes`, `actual_close_values` and this table (`*_no_replace` triggers): REPLACE
deletes the colliding row without firing delete triggers (the app does not set `PRAGMA recursive_triggers`).
`data-check` `eod_backup_protection_triggers` fails when one of these triggers is missing.

| Column | Type | Null | Key | Default | Meaning / rule |
|---|---|---|---|---|---|
| `snapshot_id` | TEXT | no | PK(1) FK -> forecast_eod_snapshots |  |  |
| `target_date`, `sku_id`, `fc_id` | TEXT | no | PK(2..4) |  | grain SKU x FC x forecast date |
| `horizon_day`, `yhat`, `method` | INTEGER / REAL / TEXT | no |  |  | exactly the source value (data-check, last 14 days) |

## `forecast_history_days` (1.2.5, migration 0004)

Official forecast session per scope and run date (Vietnam date). The only mutable history table: a newer valid session of
the SAME run date moves `forecast_run_id` (audit `FORECAST_HISTORY_SELECTED`); rows are never deleted, keys never change,
the pointer must be an eligible session of the same scope and run date (triggers). Code: `forecast_history.py`.

| Column | Type | Null | Key | Default | Meaning / rule |
|---|---|---|---|---|---|
| `scope_key` | TEXT | no | PK(1) |  | dataset (same rule as `demand_daily`) |
| `run_date` | TEXT | no | PK(2) |  | VN date of the session time |
| `data_source` | TEXT | no |  |  | DEMO / MANUAL_IMPORT / BIGQUERY |
| `target_date` | TEXT | no |  |  | run_date + 1 |
| `forecast_run_id` | TEXT | no | FK -> forecast_history_sessions |  | official session |
| `selected_at` | TEXT | no |  |  | UTC time the pointer was last set |

## `forecast_history_sessions` (1.2.5, migration 0004)

Every published forecast run seen by the history and the decision taken when it was recorded. Immutable.

| Column | Type | Null | Key | Default | Meaning / rule |
|---|---|---|---|---|---|
| `forecast_run_id` | TEXT | no | PK, FK -> forecast_runs.id |  |  |
| `scope_key`, `data_source` | TEXT | no |  |  | from the run |
| `run_date`, `target_date` | TEXT | no |  |  | VN date of the session time; run_date + 1 |
| `session_started_at` | TEXT | no |  |  | start of the job that produced the run, else the publish time (UTC) |
| `published_at` | TEXT | no |  |  | forecast_runs.created_at |
| `training_run_id`, `model_version`, `data_as_of` | TEXT | no |  |  | from the run |
| `horizon_day` | INTEGER | yes |  |  | horizon of the D+1 values in the run |
| `n_rows`, `total_yhat` | INTEGER / REAL | no / yes |  |  | D+1 rows and total of the run |
| `usage_status` | TEXT | yes |  |  | usage assessment of the training run |
| `eligible` | INTEGER | no |  |  | 1 when the run has D+1 values |
| `decision`, `decision_reason` | TEXT | no / yes |  |  | SELECTED / OLDER_THAN_SELECTED / NOT_ELIGIBLE; e.g. REPLACES:&lt;run&gt; |
| `capture_mode` | TEXT | no |  |  | AT_PUBLISH / RECOVERED (CHECK) |
| `captured_at` | TEXT | no |  |  | UTC |

Indexes: `ix_fh_sessions_day`(scope_key, run_date)

## `forecast_history_values` (1.2.5, migration 0004)

D+1 values of a session that was selected when recorded, copied from `forecast_values`. Immutable.

| Column | Type | Null | Key | Default | Meaning / rule |
|---|---|---|---|---|---|
| `forecast_run_id` | TEXT | no | PK(1) FK -> forecast_history_sessions |  |  |
| `sku_id`, `fc_id` | TEXT | no | PK(2), PK(3) |  |  |
| `scope_key`, `run_date`, `target_date` | TEXT | no |  |  | target_date = run_date + 1 (data-check) |
| `yhat`, `method` | REAL / TEXT | no |  |  | exactly the published value (data-check) |
| `product_name` | TEXT | yes |  |  | name known when recorded (display prefers the current mapping) |

Indexes: `ix_fh_values_target`(scope_key, target_date, sku_id, fc_id), `ix_fh_values_fc`(scope_key, fc_id, target_date)

## `forecast_runs`

Published forecast run. Immutable (triggers block UPDATE/DELETE).  
Code: `ml/pipeline.py` - rows in copy: 3

| Column | Type | Null | Key | Default | Meaning / rule |
|---|---|---|---|---|---|
| `id` | TEXT | no | PK |  |  |
| `training_run_id` | TEXT | no | FK -> training_runs.id |  |  |
| `model_version` | TEXT | no |  |  |  |
| `scope_key` | TEXT | no |  |  | dataset key: DEMO/MANUAL_IMPORT batch id or BIGQUERY:<project>.<dataset>.<table> |
| `data_source` | TEXT | no |  |  | DEMO / MANUAL_IMPORT / BIGQUERY |
| `forecast_origin` | TEXT | no |  |  | first forecast date (VN date) = data_as_of + 1 |
| `data_as_of` | TEXT | no |  |  | last complete VN business date used |
| `horizons_json` | TEXT | no |  |  |  |
| `max_horizon` | INTEGER | no |  |  |  |
| `n_series` | INTEGER | no |  |  |  |
| `method_counts_json` | TEXT | yes |  |  |  |
| `status` | TEXT | no |  |  | always PUBLISHED (CHECK); rejected candidates never produce a forecast run |
| `created_at` | TEXT | no |  |  | UTC ISO-8601 timestamp of row creation (app time), unless stated otherwise |
| `job_id` | TEXT | yes |  |  | job_runs.id that produced the row (logical reference, no FK) |
| `derived_from_run_id` | TEXT | yes |  |  | run this one extends (e.g. longer horizon from the same accepted model); 0003 |

Indexes: `ix_forecast_runs_scope`(scope_key, created_at)

## `forecast_series_meta`

Why each SKU x FC got its method (LightGBM or a fallback) at publish time. Immutable (0003).  
Code: `ml/pipeline.py, ml/model.py` - rows in copy: 168

| Column | Type | Null | Key | Default | Meaning / rule |
|---|---|---|---|---|---|
| `run_id` | TEXT | no | PK(1) FK -> forecast_runs.id |  |  |
| `sku_id` | TEXT | no | PK(2) |  | SKU code as text (leading zeros kept) |
| `fc_id` | TEXT | no | PK(3) |  | fulfilment centre / warehouse code as text |
| `method` | TEXT | no |  |  |  |
| `reason_code` | TEXT | no |  |  |  |
| `details_json` | TEXT | no |  |  |  |

## `forecast_values`

Forecast per run x SKU x FC x target date. Immutable.  
Code: `ml/pipeline.py` - rows in copy: 4368

| Column | Type | Null | Key | Default | Meaning / rule |
|---|---|---|---|---|---|
| `run_id` | TEXT | no | PK(1) FK -> forecast_runs.id |  |  |
| `sku_id` | TEXT | no | PK(2) |  | SKU code as text (leading zeros kept) |
| `fc_id` | TEXT | no | PK(3) |  | fulfilment centre / warehouse code as text |
| `target_date` | TEXT | no | PK(4) |  |  |
| `horizon_day` | INTEGER | no |  |  | 1..max_horizon days after data_as_of |
| `yhat` | REAL | no |  |  |  |
| `method` | TEXT | no |  |  | LIGHTGBM or a FALLBACK_* method |
| `fallback_reason` | TEXT | yes |  |  |  |

## `import_batches`

One row per loaded dataset: a DEMO generation or one MANUAL_IMPORT .xlsx file. Never deleted; status moves PENDING_REVIEW -> ACTIVE -> REPLACED/DELETED, or -> CANCELLED.  
Code: `data/importer.py, data/demo.py` - rows in copy: 6

| Column | Type | Null | Key | Default | Meaning / rule |
|---|---|---|---|---|---|
| `id` | TEXT | no | PK |  | IMP-<utc yyyymmddHHMMSS>-<6 hex> or DEMO-...; also the scope_key of the batch |
| `data_source` | TEXT | no | UNIQUE |  | DEMO / MANUAL_IMPORT / BIGQUERY |
| `status` | TEXT | no |  |  | PENDING_REVIEW / ACTIVE / REPLACED / DELETED / CANCELLED / FAILED (CHECK) |
| `file_name` | TEXT | yes |  |  |  |
| `file_sha256` | TEXT | yes |  |  | SHA-256 of the uploaded file (re-importing the same file still creates a new batch) |
| `sheet_name` | TEXT | yes |  |  |  |
| `column_mapping_json` | TEXT | yes |  |  |  |
| `replaces_batch_id` | TEXT | yes | FK -> import_batches.id |  | batch this upload replaces on confirm (must be ACTIVE MANUAL_IMPORT) |
| `replaced_by_batch_id` | TEXT | yes | FK -> import_batches.id |  | set on the old batch when it is replaced |
| `total_rows` | INTEGER | no |  | `0` |  |
| `valid_rows` | INTEGER | no |  | `0` |  |
| `error_rows` | INTEGER | no |  | `0` |  |
| `duplicate_rows` | INTEGER | no |  | `0` |  |
| `min_order_date` | TEXT | yes |  |  | VN business date (YYYY-MM-DD) |
| `max_order_date` | TEXT | yes |  |  | VN business date (YYYY-MM-DD) |
| `validation_json` | TEXT | yes |  |  |  |
| `created_at` | TEXT | no |  |  | UTC ISO-8601 timestamp of row creation (app time), unless stated otherwise |
| `confirmed_at` | TEXT | yes |  |  |  |
| `closed_at` | TEXT | yes |  |  |  |
| `note` | TEXT | yes |  |  | for PENDING_REVIEW batches: the upload id (re-validation of the same upload cancels the older pending batch) |

Indexes: `ix_import_batches_status`(data_source, status)

## `import_row_errors`

Rows rejected or flagged while validating a pending batch (source of the Excel error report).  
Code: `data/importer.py` - rows in copy: 0

| Column | Type | Null | Key | Default | Meaning / rule |
|---|---|---|---|---|---|
| `id` | INTEGER | no | PK |  |  |
| `batch_id` | TEXT | no | FK -> import_batches.id |  |  |
| `row_number` | INTEGER | yes |  |  |  |
| `field` | TEXT | yes |  |  |  |
| `code` | TEXT | no |  |  |  |
| `severity` | TEXT | no |  |  |  |
| `raw_value` | TEXT | yes |  |  |  |

Indexes: `ix_import_row_errors_batch`(batch_id)

## `job_locks`

Short-lived named locks so two jobs of the same kind never run at once.  
Code: `jobs/runner.py` - rows in copy: 0

| Column | Type | Null | Key | Default | Meaning / rule |
|---|---|---|---|---|---|
| `lock_name` | TEXT | no | PK |  |  |
| `owner` | TEXT | no |  |  |  |
| `acquired_at` | TEXT | no |  |  |  |
| `expires_at` | TEXT | no |  |  |  |

## `job_runs`

Every scheduled/manual job (D0_SYNC, D1_SYNC, TRAIN_PUBLISH, FORECAST_EXTEND, ...) with idempotency key, retry state and stage history.  
Code: `jobs/runner.py, jobs/scheduler.py` - rows in copy: 22

| Column | Type | Null | Key | Default | Meaning / rule |
|---|---|---|---|---|---|
| `id` | TEXT | no | PK |  |  |
| `job_type` | TEXT | no |  |  |  |
| `idempotency_key` | TEXT | no | UNIQUE |  | UNIQUE, e.g. D0_SYNC:2026-10-15T16:00 (one run per slot) |
| `trigger` | TEXT | no |  |  | SCHEDULE / CATCH_UP / MANUAL / RETRY |
| `scheduled_for` | TEXT | yes |  |  | VN slot time with offset |
| `status` | TEXT | no |  |  | PENDING / RUNNING / SUCCEEDED / FAILED / SKIPPED / RETRY_WAIT (CHECK) |
| `attempt` | INTEGER | no |  | `0` |  |
| `max_attempts` | INTEGER | no |  | `1` |  |
| `next_attempt_at` | TEXT | yes |  |  |  |
| `created_at` | TEXT | no |  |  | UTC ISO-8601 timestamp of row creation (app time), unless stated otherwise |
| `started_at` | TEXT | yes |  |  |  |
| `finished_at` | TEXT | yes |  |  |  |
| `reason_code` | TEXT | yes |  |  |  |
| `error` | TEXT | yes |  |  |  |
| `result_json` | TEXT | yes |  |  |  |
| `stage` | TEXT | yes |  |  |  |
| `stage_updated_at` | TEXT | yes |  |  |  |
| `stage_history_json` | TEXT | yes |  |  | real stage transitions (0003); no percentages |

Indexes: `ix_job_runs_status`(status); `ix_job_runs_type`(job_type, created_at)

## `order_lines`

Normalised order lines of ONE batch (only ACTIVE / PENDING_REVIEW batches keep lines; replace, delete and cancel purge the lines of that batch only).  
Code: `data/importer.py, data/validation.py` - rows in copy: 93157

| Column | Type | Null | Key | Default | Meaning / rule |
|---|---|---|---|---|---|
| `id` | INTEGER | no | PK |  |  |
| `batch_id` | TEXT | no | FK -> import_batches.id |  | owning batch (FK import_batches.id); the ONLY ownership key |
| `row_number` | INTEGER | yes |  |  | row number in the source sheet |
| `order_id` | TEXT | yes |  |  |  |
| `created_at` | TEXT | yes |  |  | order creation time; naive Excel values are interpreted as Asia/Ho_Chi_Minh |
| `order_date` | TEXT | no |  |  | VN business date; given, or derived from created_at in Asia/Ho_Chi_Minh |
| `sku_id` | TEXT | no |  |  | SKU code as text (leading zeros kept) |
| `fc_id` | TEXT | no |  |  | fulfilment centre / warehouse code as text |
| `order_qty` | REAL | no |  |  | quantity ordered at order creation, cancellations NOT subtracted; CHECK >= 0 |
| `unit_price` | REAL | yes |  |  |  |
| `discount_amount` | REAL | yes |  |  |  |
| `promotion_flag` | INTEGER | yes |  |  |  |
| `promotion_id` | TEXT | yes |  |  |  |
| `voucher_flag` | INTEGER | yes |  |  |  |
| `voucher_amount` | REAL | yes |  |  |  |
| `source_updated_at` | TEXT | yes |  |  |  |
| `source_batch_id` | TEXT | yes |  |  | batch id of the source system, if supplied (mapped from the 'batch_id' field) |

Indexes: `ix_order_lines_batch`(batch_id, order_date)

## `schema_migrations`

Applied schema migrations (version = numeric prefix of backend/app/migrations/*.sql).  
Code: `db.py` - rows in copy: 3

| Column | Type | Null | Key | Default | Meaning / rule |
|---|---|---|---|---|---|
| `version` | INTEGER | no | PK |  |  |
| `name` | TEXT | no |  |  |  |
| `applied_at` | TEXT | no |  |  |  |

## `settings_history`

Append-only history of every settings change (full section JSON + note).  
Code: `settings_service.py` - rows in copy: 14

| Column | Type | Null | Key | Default | Meaning / rule |
|---|---|---|---|---|---|
| `id` | INTEGER | no | PK |  |  |
| `section` | TEXT | no |  |  |  |
| `value_json` | TEXT | no |  |  |  |
| `changed_at` | TEXT | no |  |  |  |
| `note` | TEXT | yes |  |  |  |

Indexes: `ix_settings_history_section`(section, id)

## `sync_state`

Small key/value state: bq_status, bq_validation (full-period check bound to a mapping hash), oauth_status, scheduler_heartbeat, last_d1_sync:<scope> (D-1 watermark + mapping hash).  
Code: `sync.py, bq/connector.py, jobs/scheduler.py` - rows in copy: 2

| Column | Type | Null | Key | Default | Meaning / rule |
|---|---|---|---|---|---|
| `name` | TEXT | no | PK |  |  |
| `value_json` | TEXT | no |  |  |  |
| `updated_at` | TEXT | no |  |  |  |

## `training_runs`

One training attempt (ACCEPTED/REJECTED/FAILED/RUNNING) with metrics, quality gate, feature config (feature_set_version + lineage since 1.1.5) and the model file reference.  
Code: `ml/pipeline.py` - rows in copy: 1

| Column | Type | Null | Key | Default | Meaning / rule |
|---|---|---|---|---|---|
| `id` | TEXT | no | PK |  |  |
| `model_version` | TEXT | yes | UNIQUE |  | MV-<VN yyyymmdd-HHMMSS>-<4 hex>; UNIQUE; file <model_version>.txt in data/models |
| `scope_key` | TEXT | no |  |  | dataset key: DEMO/MANUAL_IMPORT batch id or BIGQUERY:<project>.<dataset>.<table> |
| `data_source` | TEXT | no |  |  | DEMO / MANUAL_IMPORT / BIGQUERY |
| `data_fingerprint` | TEXT | yes |  |  | hash of COUNT/SUM/MIN/MAX/loaded_at of the scope (no-new-data skip) |
| `status` | TEXT | no |  |  |  |
| `started_at` | TEXT | no |  |  |  |
| `finished_at` | TEXT | yes |  |  |  |
| `train_start` | TEXT | yes |  |  |  |
| `train_end` | TEXT | yes |  |  |  |
| `n_series` | INTEGER | yes |  |  |  |
| `n_rows` | INTEGER | yes |  |  |  |
| `feature_config_json` | TEXT | yes |  |  | resolved feature groups, feature_set_version and source lineage (mapping hash, SQL identity) |
| `params_json` | TEXT | yes |  |  |  |
| `metrics_json` | TEXT | yes |  |  |  |
| `baseline_metrics_json` | TEXT | yes |  |  |  |
| `quality_gate_json` | TEXT | yes |  |  | gate checks; thresholds_approved_by_business=false until the business approves |
| `feature_importance_json` | TEXT | yes |  |  |  |
| `reject_reason` | TEXT | yes |  |  |  |
| `error` | TEXT | yes |  |  |  |
| `model_path` | TEXT | yes |  |  | file name of the LightGBM model in the models folder (relative) |
| `model_sha256` | TEXT | yes |  |  | SHA-256 of the model file; the explanation / SHAP endpoints refuse a model file whose hash differs |
| `job_id` | TEXT | yes |  |  | job_runs.id that produced the row (logical reference, no FK) |

Indexes: `ix_training_runs_scope`(scope_key, started_at)

## `validation_reports`

Data-quality report of a scope before training (can_train + JSON details).  
Code: `data/quality.py` - rows in copy: 3

| Column | Type | Null | Key | Default | Meaning / rule |
|---|---|---|---|---|---|
| `id` | TEXT | no | PK |  |  |
| `scope_key` | TEXT | no |  |  | dataset key: DEMO/MANUAL_IMPORT batch id or BIGQUERY:<project>.<dataset>.<table> |
| `data_source` | TEXT | no |  |  | DEMO / MANUAL_IMPORT / BIGQUERY |
| `created_at` | TEXT | no |  |  | UTC ISO-8601 timestamp of row creation (app time), unless stated otherwise |
| `can_train` | INTEGER | no |  |  |  |
| `report_json` | TEXT | no |  |  |  |

Indexes: `ix_validation_reports_scope`(scope_key, created_at)

## Triggers

1.2.6: `trg_fes_no_delete`, `trg_fes_complete_fixed`, `trg_fes_keys_fixed`, `trg_fes_values_no_update/no_delete`,
`trg_fes_values_complete_only` (a COMPLETE backup never changes; values only for a COMPLETE snapshot);
`trg_actual_closes_no_update/no_delete`, `trg_actual_close_values_no_update/no_delete`, `trg_actual_closes_consecutive`
(closes are immutable, a change is a new consecutive revision).

1.2.5: `trg_fh_sessions_no_update/no_delete`, `trg_fh_values_no_update/no_delete`, `trg_fh_days_no_delete`,
`trg_fh_days_keys_fixed`, `trg_fh_days_same_day(_insert)` (history immutability; the official pointer is an eligible session
of the same run date).

`trg_forecast_values_no_update`, `trg_forecast_values_no_delete`, `trg_forecast_runs_no_update`, `trg_forecast_runs_no_delete`, `trg_d0_values_no_update`, `trg_series_meta_no_update`, `trg_series_meta_no_delete` - all block UPDATE/DELETE of published forecast data or UPDATE of D0 snapshot values (immutability).
