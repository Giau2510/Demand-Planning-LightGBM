# Changelog

Versions of the portable package `DemandForecast-<version>-win64-portable.zip`. Details and evidence for each version
are in the report named in brackets (folder `reports/`). "Changed defaults" lists settings whose code default changed:
they take effect without any data change for every section/key that was never saved (see
[docs/data/DATA-MODEL.md](docs/data/DATA-MODEL.md) section 9).

## 1.2.11 - 2026-10-21 (duplicate rule by order status; item_code never a uniqueness criterion) [reports/release-1.2.11-20261021/FINAL_REPORT.md]

No migration (schema 9, as 1.2.10), no settings change, no change of any default. Rollback to 1.2.10 =
`rollback-version.ps1 -To 1.2.10` without a restore (same schema).

* **Pending orders are exempt from the exact-duplicate rule** (owner rule 21/10/2026; supersedes fix 7.1 of 1.2.10):
  rows of status `WAIT_TO_CONFIRM` (`connector.PENDING_STATUSES`, compared after `UPPER(TRIM())`, **with or without**
  `so_code`) are never a duplicate - the gate, the full-period validation and the D-1 control rows do not count them,
  `DROP_EXACT` keeps all of them; no order code is required or invented, rows are never merged, a repeated
  `customer_id` or other matching columns are no reason to reject them. They are counted apart (`pending_orders`: rows,
  quantity, rows without order code, rows identical in every compared column, rows identical in EVERY source column -
  informative, the sign of a possible join fan-out; BigQuery page, duplicate report Summary). Fix 7.1 blocked pending
  rows identical in every source column; they are now exempt by the owner's rule.
* **item_code is never a uniqueness criterion**: rows of every other status keep the exact-duplicate protection on the
  compared columns = the mapped columns except `item_code` (`connector.DUP_NOT_COMPARED_FIELDS`); two order lines that
  differ only in their item code (e.g. one line fanned out over the SKU's listings by a join) are duplicates. The
  status is a compared column, so a group never mixes pending and other statuses. `DROP_EXACT` keeps one row per group
  (`ROW_NUMBER` over the compared columns, deterministic) and every pending row. The D-1 aggregation and the validation
  no longer read the whole source row (1.35 GB instead of 1.70 GB on the 21/10 table); the gate still does (1.70 GB).
  Real table 01/01-20/10 (21/10 07:10 snapshot): 0 duplicate groups; 904 pending rows / 12,933 units exempt (46 groups /
  136 rows identical in the compared columns, 0 identical in every source column); comparing item_code too also gives 0
  non-pending groups.
* Tests: `test_v129h_pending_orders_grain.py` rewritten for the rule (+ proof that whether an open-hours key blocks never
  depends on its item codes), `test_v129h_real_bq_pending_grain.py` (+2 real BigQuery: an order line fanned out over item
  codes blocks; mixed statuses / status spelling; pending rows identical in every source column, with an order code and
  with a repeated customer are exempt; DROP_EXACT), `test_bq_real_semantics.py`, `test_v118_bq_ingest.py`,
  `test_bigquery.py`, `v129h-pending.test.tsx`.
* **The 6 `MULTI_ITEM` keys stay blocked (owner decision 21/10/2026).** Read-only check of the 21/10 07:10 source: each
  key = two items of the SKU that are its listings in two sales regions (source column `sales_region_code`, never the
  suffix), fulfilled by the same FC; an item's `total_open_hours` = time in status `NORMAL` or `LIMIT` that day (rebuilt
  from the item status log on 2,190 / 2,191 item-days). No JOIN fan-out, no inconsistent value, no mapping error; no
  aggregation rule exists in the source or the repository, so none is applied: the BIGQUERY training keeps stopping with
  `OPEN_HOURS_INVALID`. New regression tests `test_v1210_multi_item_open_hours.py` (the six real patterns, the other-FC
  keys, one value for valid keys, inconsistent hours detected, demand kept, training gate) and
  `test_v1210_real_bq_multi_item_regions.py` (real BigQuery on inline rows: FC from `fc_code`, statuses, quantities, the
  customer-count join changes nothing). Docs: [docs/BIGQUERY.md](docs/BIGQUERY.md) 11f, DATA-MODEL, `open_hours.py` note.

## 1.2.10 - 2026-10-21 (restore D-1: pending orders without order code compared on the whole source row; faster whole-scope reads) [reports/master-audit-20261021/FINAL_REPORT.md, release: reports/fix71-restore-d1-20261021/FINAL_REPORT.md]

Contains everything of 1.2.9 (never installed) plus the master audit of 21/10/2026 and fix 7.1. No migration beyond
1.2.9 (schema 9; upgrade from 1.2.8 runs 0007-0009), no settings change, no change of any default. Rollback to 1.2.8 =
restore the pre-upgrade backup (1.2.8 refuses schema 9), as for 1.2.9.

* **Fix 7.1 - a pending order is a duplicate only when identical in EVERY source column** (`connector._pending_raw_expr`,
  `_src_cte` column `_praw`): the 21/10 rule below exempted every pending row without order code from the exact-duplicate
  check, so a real duplicate or a join fan-out among them (rows identical in every source column) could never be found.
  Such rows are now compared on their whole source row (every column of the table / user SQL, mapped or not; the row
  never leaves BigQuery): rows that differ in any source column (e.g. another `customer_id`) are separate orders, kept and
  counted apart as before; rows identical in every source column stay exact duplicates (BLOCK stops, `DROP_EXACT` drops,
  report column `compared_on = whole source row`, `pending_no_order_code.duplicate_groups / duplicate_rows`, BigQuery page
  line). No column is used as an order key; non-pending rows keep the mapped-column rule unchanged. Cost: when both
  `order_id` and `order_status` are mapped, the gate and the aggregation read every column (production table 21/10:
  1.70 GB instead of 1.35 GB per query). Real source 21/10 07:10 (01/01-20/10, 8,979,752 rows): 0 duplicate groups;
  904 pending rows, 46 groups / 136 rows identical in the 15 mapped columns, every row a different customer, 0 identical
  in every source column. Tests: `test_v129h_pending_orders_grain.py` (+2), `test_v129h_real_bq_pending_grain.py` (+2:
  whole-row duplicates block; the customer-count join never multiplies demand), `test_bq_real_semantics.py` (inline rows
  carry a customer column), `test_v118_bq_ingest.py` (GROUP BY ends with `_praw`), `v129h-pending.test.tsx` (+1).
* **Pending orders without order code are never exact duplicates** (owner rule 21/10/2026, `connector.PENDING_STATUSES`;
  refined by fix 7.1 above):
  an order `WAIT_TO_CONFIRM` has no `so_code` yet. Rows with a NULL order reference and that status were compared like
  any row (NULL = NULL), so pending orders of different customers for the same day x SKU x FC x quantity x price looked
  like exact duplicates and the BLOCK policy stopped every D-1 / backfill read that contains them (source rebuilt 20/10
  22:18: 18 groups / 67 rows on 16/10 and 19/10, every row of a group from a different customer). The duplicate gate
  (`_dup_sql`), the full-period validation summary and the D-1 control rows now leave these rows out of the duplicate
  count; `DROP_EXACT` keeps them; they are counted apart (`pending_no_order_code`: rows, qty, identical groups / rows) on
  the BigQuery page and in the Summary sheet of the duplicate report. Every other row keeps the exact-duplicate rule
  (a NULL `so_code` with another status still compares equal). Only when both `order_id` and `order_status` are mapped.
  The expectations of the opt-in real-BigQuery test `test_bq_real_semantics.py` changed accordingly (its WAIT_TO_CONFIRM
  pair is now kept; a new non-pending NULL pair keeps the NULL = NULL check).
* **Regression tests** for the grain rules (FC only from `fc_code`, item suffixes never create or merge a key, full SKU
  codes never merged, no quantity duplicated or lost) and the pending rule: `test_v129h_pending_orders_grain.py`
  (offline), `test_v129h_real_bq_pending_grain.py` (opt-in, inline rows, 0 bytes), `v129h-pending.test.tsx`.
* **Faster whole-scope reads** (same results, measured on a copy of production with 1.36 M demand rows): three reads now
  run as ONE sequential scan (`NOT INDEXED`, as `ops_routes` 1.2.7 and `demand.fingerprint` 1.2.8) instead of the key
  index that fetched every row again: `feature_registry.coverage` 8.3 s -> 0.47 s (Feature registry page
  `GET /api/features/registry` 9.0 s -> 1.5 s on the same copy, identical response; 13.5 s median on the production PC),
  `pipeline.data_lineage` 8.6 s -> 1.0 s, `demand.load_demand` 15.3 s -> 6.2 s (now sorted in the key order: identical
  DataFrame). Test: `test_v129h_perf_scans.py`.

## 1.2.9 - 2026-10-20 (day of week 1-7, SKU open hours as a mandatory BigQuery input, roles of every D-1 column, weekday names, controlled backfill, finalized actual on the history page; migrations 0007-0009, schema 9) [reports/weekday_total_open_hours_mapping_fix.md ... reports/demandforecast_upgrade_backfill_rehearsal_20261020.md, release: reports/demandforecast_release_20261020_final_report.md]

Released 2026-10-20 from the eight source batches below (first batch text kept as written). Upgrade from 1.2.8 runs
migrations 0007, 0008 and 0009 (schema 6 -> 9, additive); rollback to 1.2.8 = restore the pre-upgrade backup (1.2.8
refuses schema 9; rehearsed). **Migration 0007** (schema 7, additive: two nullable columns of `demand_daily`); going back to
1.2.8 needs the pre-upgrade backup (1.2.8 refuses a schema newer than 6), as for 0004-0006.

* **Day of week: one convention** (`backend/app/weekday.py`): Monday = 1 ... Sunday = 7, from the calendar date itself.
  Models trained from 1.2.9 store `weekday_encoding = "ISO"` (`dow` 1-7); older models keep the 0-6 code they were trained
  with (same function, ISO - 1), so no model changes behaviour. The explanation's history days carry the ISO weekday.
  The switch `model.feature_weekday` (1.2.8) is now also on the **Field mapping** page (card "Day of week", label
  "Sử dụng thứ trong tuần khi dự báo", says "not saved" until saved; same setting as the Model configuration page).
  Root cause of "not saved": production ran 1.2.6 until 19/10 20:08 - that version has no such key and Pydantic ignored it;
  after the 1.2.8 deploy it was never saved (settings history of `model`: one save, 17/10).
* **SKU open hours (`total_open_hours`) - mandatory model input of the BigQuery D-1 source** (`backend/app/data/open_hours.py`):
  D-1 reads, per day x SKU x FC, lines without a value + MIN / MAX; stored value only when every line has one, they agree
  and lie within 0-24 (status OK); otherwise no value and status MISSING / OUT_OF_RANGE / CONFLICT - never 0, never a carried
  or averaged value; the demand itself is written as before. Features `open_hours_last` (day before the target / origin) and
  `open_hours_mean_7` (known days of the 7 before); the target day's own hours are never used. Training of the BIGQUERY source
  stops with `OPEN_HOURS_INVALID` (rows and day range per status) while any demand row of the data window is not OK; DEMO /
  Excel: not applicable. Not a user switch (`PUT /api/settings/model` refuses `feature_open_hours`: `OPEN_HOURS_MANDATORY`);
  the resolved value is stored with each training run, older models keep their list. Data identity of a run that used open
  hours also hashes them; identities recorded before keep their own column list (a D-1 reload that adds open hours does not
  make older runs "data changed"). Full-period validation reports `OPEN_HOURS_MISSING` / `OPEN_HOURS_OUT_OF_RANGE` as warnings.
* **Roles of every D-1 field and column**: key / target / mandatory input / optional input / reference (`FIELD_ROLES`); the
  mapping page lists every source column with its role, "not classified" until marked reference
  (`bigquery.extra_reference_columns`, never read, never an input, not part of the mapping hash); `REQUIRED_NOT_MAPPED` for
  open hours, `COLUMN_ROLE_CONFLICT` when one column feeds two of key / target / input. `open_hours` stays in
  `reference_mapping`, so the saved production mapping and its hash are unchanged (no re-validation caused by the upgrade).
* **Daily forecast table: weekday names** ("Thứ 2" ... "Chủ nhật") of each target date in place of the number. That number was
  `horizon_day` (position in the forecast period, 1 = first forecast day - not a weekday); it stays as the cell's tooltip.
  `/values` rows carry `weekday` (1-7). Excel export **format 6**: column "Thứ trong tuần" / "Weekday" after the date; the
  numeric "Ngày thứ" / "Day #" column is unchanged.
* Real-data facts (read-only BigQuery profile 01/01-18/10/2026): `total_open_hours` NULL for every line before 2026-03-19
  and none after; min 0, max 24; 2 day x SKU x FC keys in August with differing values. After deploying this version the
  BigQuery training stays blocked until a D-1 full reload AND an owner decision on the missing period / the 2 conflicting
  keys (or a later `window_start_date`).
* Tests: backend `test_v129_weekday_open_hours.py`, real BigQuery (opt-in) `test_v129_real_bq_open_hours.py`, frontend
  `v129.test.tsx`; earlier fixtures that simulate D-1 data now carry the open hours a 1.2.9 D-1 writes.

Second batch (19/10/2026 evening) [reports/demandforecast_comprehensive_upgrade_review.md]:

* **Controlled history backfill: preview, preview id, backup.** `POST /api/sync/backfill/preview` (button "Preview (no
  write)") runs the checks and the BigQuery read of the load. The read is read-only, dry run first, capped, with the
  exact-duplicate gate. It reports new / changed / unchanged / removed day x SKU x FC rows, the quantity before and after,
  the open-hours status each row would get and the 23:59-closed days whose actual would change. It writes no demand; the
  result is kept in `sync_state bq_backfill_preview` and audited `D1_BACKFILL_PREVIEW`.
  `POST /api/sync/backfill` now needs the `preview_id` of a READY preview of the same window, mapping and SQL. The preview
  must be at most 6 h old and is used once; otherwise `BACKFILL_PREVIEW_REQUIRED` (checked by the API and again by the
  job). The job makes a verified online backup (`backup-...-pre-backfill.zip`) right before it replaces the window; a
  failed backup gives `BACKFILL_BACKUP_FAILED` and nothing is written. The job result names the preview and the backup.
  The page enables "Re-read this window" only for the previewed dates and asks for confirmation with the counts.
  Inside the write transaction, before the DELETE, the job checks again that the preview is still READY, that no D-1
  load ran since and that the new / updated / removed counts are the previewed ones. An empty read is BLOCKED already in
  the preview. A window ending yesterday without a completion signal gets the warning `YESTERDAY_NOT_CONFIRMED`.
* **Backups are written atomically**: zip under a temporary name, `testzip`, then renamed. A failed write leaves no
  `backup-*.zip`. Backtest groups are stored as small integer codes; an error in them never stops a training.
* **Forecast & actual history: whole numbers.** The page shows, sums, sorts and exports the forecast quantity of
  `app/qty.py` (round half up, never below 0, zero allowed) - the number of the Results page. Its deviation and WAPE
  compare that number with the actual. The stored `yhat` is unchanged and still returned; the hover shows it. Model accuracy
  (backtest, quality gate, Results accuracy card) still uses `yhat`. History Excel **format H3** (same columns).
  This closes A5 of 1.2.8 (owner instruction of 19/10: integers consistently across details, totals, exports and history).
* **Backtest accuracy per group** (`ml/demand_patterns.py`, `backtest_runs.metrics_json.segments`, training explanation
  `backtest.segments`). The same walk-forward points are split by demand pattern (Syntetos-Boylan: smooth / erratic /
  intermittent / lumpy / inactive / short history, from the 91 days before each fold origin), volume tier, spike day
  (relative to the series' own history before the origin) and horizon days 1-7 / 8-15 / 16-30. Each group has model and
  baseline metrics, and the 7 / 15 / 30-day per-series total WAPE is reported. Evaluation only: no value is removed,
  clipped or re-weighted, nothing is a model input, and pooled metrics / quality gate are unchanged.

Third batch (20/10/2026) [reports/demandforecast_dq_spike_customer_20261020.md]. **Migration 0008** (schema 8, additive:
three nullable columns of `demand_daily`); same rollback rule as 0007. Every new behaviour is OFF by default.

* **Open hours are measured per item** (read-only check of the real source, 20/10): the same item has the same hours in
  every FC on a day; an item (`<sku_code>.<n>`) belongs to one SKU. (Corrected in the fifth batch: the suffix `<n>` is
  the order in which the SKU was opened for sale in the regions, not a region code; nothing is inferred from it.)
  New status **`MULTI_ITEM`**: the values of a day x SKU x FC differ only BETWEEN items (each item one value,
  item_code mapped) - still no value at the SKU x FC grain (no aggregation rule approved), so it still
  stops the BigQuery training like the other non-OK statuses. `CONFLICT` now means a disagreement not explained by the items
  (the same item with two values, or lines without item code). D-1 reads three counts more (items, item / value pairs,
  lines without item code); without the item_code mapping it behaves as before.
* **Open hours a reload would lose**: the source keeps open hours for about its last 7 months (first day with a value moved
  from 19/03 to 20/03 between the refreshes of 19/10 and 20/10). The backfill preview warns `OPEN_HOURS_WOULD_BE_LOST`
  (rows, first / last day, now missing / removed) and every D-1 / backfill result counts `open_hours_lost`.
* **Model-input start rule** `data_policy.training_start_rule` (Configuration > Data policy, default `WINDOW_START` = as
  before). `OPEN_HOURS_COVERAGE` (BigQuery source only): training, backtest, forecast panel, open-hours check, data-quality
  report and data-check start at the first STORED day with open hours, recomputed at each use (no date in the code); the
  earlier days stay stored and are still read by D-1 / backfill (read floor = `window_start_date`, mapping hash unchanged).
  Each training stores `data_window.excluded_summary` (days, rows, series, series only in the excluded days, quantity and
  its share). Status pages show the rule without scanning.
* **customer_id (OFF by default)**: optional source column `bigquery.customer_id_column` (mapping page, "" = none; part of
  the mapping hash only when set, so an unmapped installation keeps its validated state). D-1 reduces it INSIDE BigQuery to
  `customer_count`, `repeat_customer_count` (ordered the same SKU x FC in the 90 days before) and
  `repeat_interval_days_sum` per day x SKU x FC; no identifier is fetched, stored, logged or exported; NULL = unknown.
  Model switch `model.feature_customer` (default false) adds `cust_mean_28`, `cust_repeat_share_28`,
  `cust_repeat_interval_28` (known days of the 28 before the target / origin) only when the stored rows carry the counts
  (coverage rule of the optional groups). Output grain stays SKU x FC. data-check `customer_counts_consistent`.
* **Spike-aware training weights - experiment code only** (`ml/spike_weights.py`, `model.train(weights=...)`,
  `training_matrix(..., with_index=True)`): the owner's one-day / two-day / third-day hypothesis as loss weights computed
  from the days before the cutoff only; targets, features and stored data unchanged. The application's training never
  passes weights (test). Results of the bounded experiments in the report.
* Tests: backend `test_v129c_window_spike_customer.py`, real BigQuery (opt-in, inline rows, 0 bytes)
  `test_v129c_real_bq_items_customers.py`, frontend `v129c.test.tsx`; expectations of `test_v129_weekday_open_hours.py`
  (D-1 query width 17 -> 20, status counts with `MULTI_ITEM`, migration to 8) and `test_v129_backfill_history_patterns.py`
  updated.

Fourth batch (20/10/2026) [reports/demandforecast_multi_item_overforecast_20261020.md]. No migration, no change of
settings or stored demand data; one fix of the backfill preview re-check (below), otherwise evaluation code only.

* **MULTI_ITEM review workbook** (report output, not versioned): `reports/demandforecast_multi_item_review_20261020.xlsx`,
  built from read-only BigQuery rows - the two keys of 26/08 at FC BD are one FC, two item codes (`.1` with lines only
  at FC BD, `.2` with almost all lines at FC HN) and different orders; both `.2` lines are one order. The aggregation
  rule stays an owner decision. (The workbook's hypothesis "`.2` = a listing of the HN region" is withdrawn in the fifth
  batch; the original file is kept unchanged.)
* **Over / under-forecast metrics - evaluation and experiment code only** (`ml/overforecast.py`): bias, over-only,
  under-only, WAPE and forecast / actual ratio on one set of observations (undefined when the actual total is 0), the
  published whole-number rule, the normal-day label (not a spike day of `demand_patterns`; needs the day's actual, never
  a model input) and walk-forward calibration factors from earlier evaluation windows only, with a shrunk segment factor
  and a fallback to the global factor. Not used by training, forecast or publication (test).
* **Fix (backfill preview re-check, second batch code):** a regular D-1 load after the preview was recognised only by its
  one-second `synced_at`; two loads in the same second let a stale preview through (seen once in a fast full-suite run of
  `test_the_preview_is_checked_again_under_the_write_lock`). Each D-1 load now stores a unique `load_id`, the preview
  keeps it and the re-check compares both (loads stored before the change have none: same result as before).
* Tests: backend `test_v129d_overforecast.py`; deterministic same-second case in `test_v129_backfill_history_patterns.py`.

Fifth batch (20/10/2026) [reports/demandforecast_data_recovery_learning_readiness_20261020.md]. No migration, no change of
settings, behaviour or stored data; text corrections and tests only.

* **Owner rule on item codes:** the suffix of `<sku_code>.<n>` is the order in which the SKU was opened for sale in the
  regions, not a region code. The earlier wording "an item is a listing of one sales region" (open_hours.py docstring,
  the open-hours text of the feature catalog, docs, CHANGELOG of the third / fourth batch) is corrected; the code never
  parsed the suffix (now covered by tests). The 20/10 MULTI_ITEM workbook is kept unchanged; a corrected
  `reports/demandforecast_multi_item_review_20261020_v2.xlsx` (not versioned) withdraws the region hypothesis.
* **Open hours after the owner's fix** (read-only, source refresh 20/10 15:05): a value on every line 01/01-19/10/2026;
  6 day x SKU x FC keys `MULTI_ITEM` (rule pending), 0 missing / conflicting / out of range. The open_hours.py note on
  the source keeping only its last ~7 months is updated accordingly.
* Tests: backend `test_v129e_item_suffix.py` (the D-1 query only counts item codes; status independent of the item
  names; feature text), real BigQuery opt-in `test_v129e_real_bq_item_suffix.py` (inline rows, 0 bytes).

Sixth batch (20/10/2026) [reports/demandforecast_zero_hours_followup_audit_20261020.md]. No migration, no change of code,
settings, behaviour or stored data; one test file.

* **Zero open hours with orders** (931 day x SKU x FC keys of the 15:05 refresh, 25,542 units): exported for the owner's
  review (`reports/demandforecast_zero_open_hours_with_orders_20261020.xlsx`, not versioned). They stay a value: stored
  `0` / `OK`, no training stop, `0` in `open_hours_last` / `open_hours_mean_7`, never carried to a day without a value -
  now covered by `test_v129f_zero_open_hours.py`.
* Read-only facts (docs/BIGQUERY.md §11e): the 71,834-unit line of 28/08 has 19.25 open hours (not 0); `open_date` /
  `total_open_days` say nothing about days without orders; candidate availability tables of the same dataset are listed
  (meaning not confirmed, not used).

Seventh batch (20/10/2026) [reports/demandforecast_actual_finalization_20261020.md]. **Migration 0009** (schema 9,
additive: two tables + protection triggers, nothing written by the migration).

* **Finalized (frozen) actual - owner rule 20/10/2026** (`backend/app/actual_final.py`): after each successful D-1 load
  (after its commit, never failing it) every completed Vietnam business day whose stored rows trace to ONE verified D-1
  load (same loaded_at = the load's synced_at in audit `D1_SYNC`; mode SIGNAL / FALLBACK_TIME_VERIFIED / BACKFILL; the
  load's window covers the day; the load ran after the day ended) is copied SKU x FC into `actual_finals` /
  `actual_final_values` with the load's provenance, row count, total and sha256, one immediate transaction per day,
  checked then sealed. A sealed day never changes (triggers): a later reload, correction, cancellation or missing key
  leaves it as it is, and it never goes back to provisional. Days that cannot be finalized are BLOCKED with a reason and
  keep their live figure. Idempotent; a failed day rolls back alone (alert `ACTUAL_FINALIZE_FAILED`) and is retried by
  the next run. `python -m app.cli actual-finalize` = read-only dry run (also on a database before 0009); `--apply`
  finalizes. BIGQUERY only.
* **Forecast history page** (root cause: "complete" required a completion-signal D-1 that production never has, and
  the figure was always re-read from the mutable demand_daily): COMPLETE now means finalized and its figure comes from
  the frozen copy; actual total, deviation, WAPE and bias of the main cards use the finalized rows only (formulas
  unchanged); provisional and end-of-day closed rows are reported apart (`kpi.provisional` / `kpi.closed`, card "Actual
  not finalized", not model quality); `kpi.coverage` and `n_zero_absent` show the evaluation base; "No finalized actual
  yet" when there is none. Excel format **H4** (Info sheet rows appended). The 23:59 close keeps its own rule.
* `data-check`: `actual_final_sealed`, `actual_final_protection_triggers`. Tests: backend `test_v129g_actual_final.py`,
  frontend `v129g-final.test.tsx`; earlier history / migration tests updated to the new rule and schema 9.

## 1.2.8 - 2026-10-19 (explanation never loads endlessly, Results page accuracy, whole-number forecasts, day-of-week switch; includes 1.2.7; no migration, schema 6 unchanged) [reports/demandforecast_fix_and_deploy_20261019.md]

No migration and no change to stored data: going back to 1.2.6 / 1.2.7 needs no restore. Contains every 1.2.7 change
(1.2.7 was packaged but never deployed).

* **"How is this calculated" never waits endlessly.** Root causes measured on a copy of the production database:
  (1) every request first computed the data fingerprint through the key index (SQLite fetched every row again for
  `qty` / `loaded_at`): about 30-42 s per request, even for a cached explanation; (2) requests arriving while the run's
  input panel was being built (modal opened again, previous / next day) each built the same ~40 s panel and ran the
  model again in parallel - with several of them the production PC ran out of memory (> 30 min). Now the fingerprint
  is one sequential scan (`NOT INDEXED`, same hash: stored training fingerprints keep matching; a scope with
  fractional quantities keeps the original key-order statement), and one reproduction runs at a time - the others
  wait and reuse it. First explanation 125 s -> 70 s, three at once 77.6 s each -> 3.3 s, cached 30.7 s -> 2.5 s.
  The modal stops waiting after 180 s with `REQUEST_TIMEOUT` and "Try again"; closing it or choosing another day
  cancels the request and ignores its late answer. Nothing is recomputed or published by opening it.
* **Results page: accuracy card in milliseconds.** `/api/forecast-runs/{id}/accuracy` joined `demand_daily` as the
  outer loop (every row of the scope before today): 4.6-26 s; now the run's own rows are the outer loop (`CROSS JOIN`,
  same rows for every run): about 50 ms. WAPE / bias still computed from the stored values.
* **An older answer never replaces a newer one** (`useAsync`): changing the horizon or the day quickly always shows the
  figures of the last choice; the page keeps loading until that answer arrives.
* **Forecast quantities are whole numbers** (Results, Dashboard, explanation headline, `/values` `forecast_qty`,
  `/summary`, Excel export of a run): round half up of the stored value, never below 0 (`backend/app/qty.py`); every
  total is the sum of the rounded daily values. The stored `yhat` and every accuracy figure are unchanged. Not changed
  yet: the "Forecast & actual history" page (its deviation and row WAPE are computed from the stored value; showing a
  rounded forecast next to them needs an owner decision).
* **Day-of-week feature switch** `model.feature_weekday` (Configuration > model): `dow` + `is_weekend` of the TARGET
  day, separately from the other calendar features. Not saved (every configuration before 1.2.8) = as before, so the
  model in use and older models keep their exact feature list; a change applies from the next training. Training,
  backtest and forecast (RECURSIVE and DIRECT) share one definition (`calendar_names`).
* Not done (blocked, see the report): `total_open_hours` as a required model feature (no approved aggregation /
  future-value rule; `demand_daily` has no such column - needs a migration and a full D-1 reload) and free mapping
  of every D-1 column with roles (needs a storage decision, a D-1 query change and a reload).
* Tests: backend `test_v128_fixes.py` (29), frontend `v128.test.tsx` (10); `test_v111.py` export check now expects the
  whole number shown on the page.

## 1.2.7 - 2026-10-19 (dashboard load hotfix; no migration, schema 6 unchanged; not deployed, owner approval pending) [reports/demandforecast_v126_post_deployment_operations.md, reports/demandforecast_v127_readiness_review.md]

No migration and no settings change: going back to 1.2.6 needs no restore.

* **System status no longer reads `demand_daily` row by row.** The freshness aggregate of `system_status()` (every page
  through `/api/system/status`, and `/api/dashboard`) used the primary-key index, which does not hold `loaded_at`, so
  SQLite fetched every row of the scope again: 1.5 M page reads (6.2 GB through the OS cache) per call, 7.5 s on a warm
  copy of the production database and 45-66 s on the production PC. It is now one sequential scan (`NOT INDEXED`) that
  also gives the model-window figures: 55 k page reads (225 MB). Same values (old statements kept as the reference in
  `test_v126_status_perf.py`); no schema, API or business-rule change.
* **Dashboard page loads part by part and computes the status once.** The page no longer calls `/api/dashboard` (which
  computed the status a second time, in parallel with the shell's `/api/system/status`): it uses the shell's status,
  asked again when the page opens and shared with a request already running, and loads the forecast card from
  `/api/forecast-runs/{id}/summary?horizon=min(h, run max)&limit=10` (same figures; already allowed by the read-only
  proxy). Header at once; each card shows its own loading state or error; nothing shows 0 or "needs configuration"
  in place of data. `/api/dashboard` is unchanged for other callers.
* Measured on an isolated copy of the production database (same PC, before and after measured back to back): dashboard
  content 60.6 s -> 3.5 s (median), page complete 60.6 s -> 5.3 s, server CPU per page open 83 s -> 5.3 s, read
  operations per page open 3.1 M -> 0.11 M (12.1 GB -> 0.42 GB). The first open after a server start (cold cache) still
  takes about 20 s.

## 1.2.6 - 2026-10-18 (end-of-day forecast backup + 23:59 actual close + 90-day backup retention; new flows OFF by default; not deployed, owner approval pending) [reports/demandforecast_v125_eod_backup_actual_finalization.md, reports/demandforecast_v126_blocker_resolution_release_rehearsal.md]

Rules in [docs/LICH-SU-FORECAST.md](docs/LICH-SU-FORECAST.md) sections 10-14.

* Migration **0005** (additive, schema 4 -> 5): `forecast_eod_snapshots` / `forecast_eod_snapshot_values` and
  `actual_closes` / `actual_close_values`, with immutability triggers. No existing table or row changed (verified on a
  copy of the production database: 8 table fingerprints identical before / after).
* Migration **0006** (schema 5 -> 6): table `forecast_eod_snapshot_retention` and the two 0005 triggers that refused
  every DELETE on the backup tables replaced, in the same transaction, by triggers that refuse every DELETE except the
  90-day retention path (owner-approved trigger change, B1). Also refuses `INSERT OR REPLACE` over an existing key on
  the five 1.2.6 tables (REPLACE deletes without firing delete triggers). No row is changed or deleted by the
  migration.
* **90-day retention of the end-of-day backup** (owner decision 18/10/2026; `eod_retention.py`, CLI `eod-retention`,
  `scripts\eod-retention.ps1`, packaged).
  - Expired = business date (Vietnam) < today - 90 days; a snapshot exactly 90 days old is kept. A snapshot still
    shown as backup for a run date inside the 90 days is held.
  - Dry run by default (read-only plan with `plan_id`); deletion only with `--apply --plan <plan_id>` of the reviewed
    plan, after a verified backup; one transaction per snapshot; permanent record per deleted snapshot + audit; a
    failure rolls that snapshot back and stops the run (ERROR alert `EOD_RETENTION_FAILED`).
  - The database refuses any deletion younger than 90 days or without a permit of the same connection. Never touches
    forecasts, the D+1 history or actual closes. Not scheduled: an operator step.
  - After a snapshot is deleted, a run date that only had that backup shows no forecast (never 0).
* **Schedule configuration of the two day-end flows** (owner request 18/10/2026 15:4x; schedules page, one card each).
  - Persistent switch, time and timezone (`eod_timezone` / `close_timezone`, only `Asia/Ho_Chi_Minh` accepted),
    defaults defined once in `ScheduleSettings` (OFF, 23:55 / 23:59) and returned as `defaults`; last configuration
    change (`config_updated`) and scheduler runtime state (`REGISTERED` / `NOT_REGISTERED` / active job).
  - Validation (422, nothing saved): HH:MM between 20:00 and 23:59, Vietnam timezone only, the two flows never at the
    same minute (also refused in the UI before sending).
  - Switching `eod` / `close` ON is kept only when the running scheduler confirms it (`Scheduler.reload()`); otherwise
    it is switched back OFF with an audit entry and the API answers 409 `SCHEDULE_NOT_REGISTERED`: no false ON.
  - Dry run `GET /api/schedules/{eod|close}/preview` (button "Chạy thử (không ghi)"): what the next run would record
    today, computed read-only with the job's rules (no job, no write, no BigQuery). Not reachable through the remote
    link (proxy unchanged: 403).
  - No time is hard-coded in the logic any more (`actual_close.close_day` takes `close_time`); texts say "cuối ngày" /
    "end of the day" instead of "23:59".
* **End-of-day forecast backup** (job `EOD_FORECAST_SNAPSHOT`, flow `eod`, 23:55 Vietnam time, **OFF by default**).
  - Copies the next 7 forecast days (S+1..S+7) of the official session of the newest run date <= S.
  - COMPLETE only when every series has all 7 days, verified in the same transaction. Otherwise the snapshot is
    INCOMPLETE / NO_SOURCE without any value, with a WARNING alert.
  - A failed verification (`EOD_SNAPSHOT_VERIFY_FAILED`) rolls back, stores nothing and ends the job FAILED with an
    ERROR alert; it is **not retried automatically** (earlier text of this entry said it retried: corrected).
  - One snapshot per scope and day. A complete one is never changed.
  - Waits for a running training / forecast job. Never trains, forecasts, publishes or reads BigQuery.
* **Backup in the history**: a run date WITHOUT an official session shows the D+1 of the newest COMPLETE snapshot that
  covers it.
  - Labelled "Dự phòng" with the snapshot day, time made and source run. Chart: dashed segment.
  - New filter `forecast_source`; new columns at the end of the Excel sheets (format H2).
  - The official forecast always wins. No covering snapshot = an empty day, never 0.
* **Actual close at 23:59** (job `ACTUAL_CLOSE`, flow `close`, 23:59 Vietnam time, **OFF by default**).
  - Revision 1 is an independent copy of the actual shown at the close (D-1 if loaded, else the last D0 snapshot). It
    covers only the SKU x FC rows present in the source; a day without data is CLOSED_NO_DATA, never 0.
  - Without the source's completion signal the day is "Đã chốt – cần xác minh" (CLOSED), never "Đã hoàn tất".
  - Late data (after each D-1 load and in each close job, last 14 days) appends a revision with before / after totals
    and changed / added / removed counts. Revisions are immutable and consecutive.
  - The figure shown, the deviation and the WAPE formula are unchanged: the close only adds the status and the trace.
* **WAPE during the day:** unchanged, still recomputed after each D-0 read (owner accepted cumulative vs full-day).
  Pinned by a regression test against `ml/metrics.py`.
* **Schedule:** the two day-end jobs carry the business date of their slot (Vietnam date).
  - Yesterday's missed slot is caught up once; older days are recorded as missed.
  - Slots before this version first ran are never run (`sync_state` `flows_first_seen`).
  - Times must be 20:00-23:59.
  - D-0 / D-1 / training schedules unchanged.
  - Both day-end flows are **OFF by default** (owner decision 18/10/2026): switched on on the Schedules page only after
    the post-deployment check. A stored schedule without their keys (every installation upgraded from 1.2.5) reads OFF;
    the migrations write no setting; a saved choice is kept.
* `data-check`: 6 new checks (`eod_snapshot_complete`, `eod_snapshot_values_match_source`, `actual_close_revisions`,
  `eod_snapshot_retention_due` (WARN), `eod_snapshot_retention_records`, `eod_backup_protection_triggers`).
* Changed defaults: new schedule keys `eod_enabled` / `close_enabled` = **false**, `eod_time` = 23:55,
  `close_time` = 23:59.
* Storage: about 11.8 MB per day for the backup with the current 17,127 series; about 1.1 GB with the 90-day retention
  run regularly.
* Rollback to 1.2.5 = restore the pre-upgrade backup (schema 6) with **1.2.5's** `restore.ps1`, then
  `rollback-version.ps1 -To 1.2.5`; everything written after that backup is lost (kept in the automatic `pre-restore`
  backup).

## 1.2.5 - 2026-10-18 (Forecast & actual history D+1 + UI redesign, released together) [reports/demandforecast_v125_history_ui_20261018.md]

### A. Forecast & actual history (new page `/forecast-history`, rules in [docs/LICH-SU-FORECAST.md](docs/LICH-SU-FORECAST.md))

* Migration **0004** (additive, schema 3 -> 4): `forecast_history_sessions` / `forecast_history_values` (immutable) and
  `forecast_history_days` (official session per scope and run date; only the pointer moves, audited). No existing table
  or row changed; forecast, model, snapshot, job, settings and scheduler unchanged.
* Each published forecast run is recorded right after its commit (never inside it: a history failure cannot undo a
  forecast; alert `FORECAST_HISTORY_CAPTURE_FAILED`), only its D+1 values (target = run date + 1, Vietnam date of the
  job start / publish). The newest valid session of a run date is official; a session that started earlier never
  replaces a newer one; a run without D+1 values replaces nothing. Idempotent retry from the immutable runs at the
  next publish, at app start and with `python -m app.cli history-reconcile`. Runs published before 1.2.5 are recorded
  from their stored values (`RECOVERED`), nothing is invented for days without a run.
* Actual is read when shown (never stored with the forecast, never changes it): loaded D-1 day (no row = 0 on a loaded
  day, as in the training panel), else the latest D0 snapshot, else "no actual data yet" (never 0). "Complete" only when
  the D-1 load of that day ran on the configured completion signal; otherwise "Provisional" - on production no signal
  is configured, so every actual is provisional and the page says why.
* Page: own menu entry; run date and forecast date shown apart; filters (run date / range, FC, SKU or name without
  accents, actual status) shared by KPI (stored forecast, actual available, deviation, WAPE = sum|F-A| / sum A on the
  rows that have an actual, "Tạm tính" marks), chart (`CompareChart`: blue forecast, orange actual, gaps never joined,
  hollow provisional points), sessions (official + traced others), paged SKU x FC table (11 columns, server sort) and
  Excel (format H1, all filtered rows, refused - never cut - above 1,000,000 rows).
* API (GET only): `/api/history/overview|summary|rows|export.xlsx`; the read-only remote proxy (1.2.5) allows exactly
  these. `data-check`: 5 new `forecast_history_*` checks.
* Tests: backend `test_v125_forecast_history.py` (20), frontend `v125-history.test.tsx` (8).

### B. UI redesign (scope D)

No API, SQL, forecast formula, scheduler condition, permission or data change. Design system in
[docs/UI-DESIGN-SYSTEM.md](docs/UI-DESIGN-SYSTEM.md).

* New dependency **lucide-react 1.48.0** (ISC, pinned; the project had no icon library): one semantic icon set
  (`components/icons.tsx`), notice in [docs/THIRD-PARTY-NOTICES.md](docs/THIRD-PARTY-NOTICES.md). Emoji / bare tick
  glyphs used as controls replaced (calendar button, close buttons, yes / no marks).
* Tokens for colour (fixed meanings: blue primary + forecast, orange actual, green / amber / red / blue states, purple
  DEMO; text pairs >= 4.5:1), type scale, spacing, radius, shadow, icon sizes; every status badge, alert and banner
  carries an icon next to its text.
* Shell: sidebar with icons and a clear current page, collapsible on desktop (per-browser choice), drawer below 900 px;
  sticky top bar; skip link; visible keyboard focus.
* Shared components: `PageHeader` on all 16 pages (title, purpose, actions; kept while loading / failing), `Card` /
  `Stat` icons, `FilterBar` (filters in effect + clear), `SearchInput`, `Pager`, `IconButton`, `YesNo`, `Empty` with
  guidance, spinner `Loading`, `Confirm` labelled + Escape; production-affecting buttons marked with a shield icon and
  tooltip (confirmations unchanged).
* Tables: sticky distinct header, row hover, tabular numbers, SKU on one line, wrapping product names, frames that
  scroll; Results no longer cuts off the "how it was computed" column. Chart drawn in real pixels: dates never overlap,
  the last date is always labelled, value labels sized to the largest total, tooltip box, a dot per day.
* Small fixes found in the review: `.alert.error` (not usable model, empty feature groups) had no style; the Features
  page coverage line was Vietnamese only; SQL source column headers and "line" were not translated.
* Tests: `v125.test.tsx` (11): all routes render with header + active sidebar item, every button named, icons hidden
  from screen readers, contrast of token pairs, no emoji icons, filter count / clear, sidebar collapse with and without
  storage, drawer, dialog, chart labels. Existing tests unchanged (86 -> 97 passed).

## 1.2.4 - 2026-10-17 (explanation survives a reload of identical data, product names + search, D-1 / D-0 switches) [reports/demandforecast_v124_history_names_schedules_20261017.md]

Database schema unchanged (3); settings: new keys `bigquery.product_names_table / _key_column / _name_column` (defaults
`dim_sku` / `sku_code` / `product_name`, ignored by 1.2.3: rollback needs no restore). Cause of the empty "How was the
forecast produced?" and "Demand history and Excel export" areas: the manual D-1 of 17/10 19:58 rewrote every row with
identical values; the data fingerprint includes `MAX(loaded_at)`, so the published run was declared "data changed".
Package built 2026-10-17 22:30 from local commit 1750f8d (SHA-256 030418A5...1F2D; QA 418 + 7 real BigQuery + 86 vitest
+ build; the first 1.2.4 build from addbfb9 was only rehearsed and is kept as `...-superseded-20261017-223024`).
Rehearsal with its own Quick Tunnel 34/34. Deployed 22:52-22:59 (backups backup-20261017-225247-manual.zip +
-225648-cli.zip): shared link, proxy (pid 13024) and cloudflared (pid 31076) kept; the link answered 502 for ~130 s
(22:56:47-22:58:58). Then on production: TRN-20261017101340-EEDA47 attested from backup-20261017-193147-manual.zip
(SAME_CONTENT, 1,349,388 rows), product names read (9,657 / 9,657 SKUs, 22.9 MB), D-1 and D-0 switched ON
(owner request; times unchanged). Demand data unchanged; no job, training or forecast was started.

* Data identity (`data/identity.py`): SHA-256 of the values the model reads, per day and per window, never loaded_at.
  Stored with each training run; explanations (calculation, history + Excel, TreeSHAP trace) and the model page's
  backtest points accept a reload with identical values (`SAME_CONTENT`), name the changed days otherwise. Older runs:
  `app.cli attest-training-data --training-run <id> --backup <zip>` (only from a backup whose fingerprint equals the
  run's). The cache of explanations includes the verdict.
* Explanation speed (the remote link cuts a request after 100 s): the run's panel / classification / model are built
  once per run and content version (not once per series; ~40 s on the real data), the fingerprint is computed once per
  check; a D-1 that only adds days after the window keeps them. Measured on a production copy: first explanation
  ~90 s (cold, copy on C:), next series ~19 s.
* Product names: `bq/product_names.py`, one name per SKU from `dim_sku` (ambiguous / missing -> "Chưa có tên sản phẩm"),
  refreshed after each D-1 or by hand (`POST /api/bigquery/product-names/refresh`, `app.cli product-names-refresh`).
  Results: name column, keyword search (`q`: parts of SKU / name, case- and accent-insensitive, all words, combined
  with the FC / SKU filters; totals and pages follow it). Excel export (format 5): "Product name" after the SKU,
  source + read time on the Info sheet; rows and numbers unchanged.
* Jobs page: D-1 and D-0 switches (existing `PUT /api/schedules/{flow}`, readiness checked), showing only the saved
  state; disabled on the read-only remote link.
* Tests: `test_v124_history_names_schedules.py` (13), `v124.test.tsx` (6); export column positions in test_v111 /
  test_v112 shifted by one (product name inserted after the SKU, format 5).

## 1.2.3 - 2026-10-17 (P0: SOURCE_NOT_READY explained, effective flow state, manual training not tied to schedules) [reports/demandforecast_v123_p0_source_not_ready_20261017.md]

Database schema unchanged (3); no new setting (rollback to 1.2.2 needs no restore). Root cause of the skipped manual
trainings JOB-20261017121625-661B96 / -121820-57FB9B / -122150-90EEDA (19:16-19:22 VN): the BigQuery field mapping was
saved at 17:32 (unit_price OPTIONAL -> REQUIRED); a mapping save always switches production mode off and changes the
mapping hash (new full-period validation + activation needed). The job reported a bare code after ~35 s of data
fingerprint, and the Jobs page showed "On - loaded by the scheduler" for the training flow from its switch alone.
Package built 2026-10-17 20:21 from local commit 87f6fce (SHA-256 39C1DA4A...3410; QA 405 + 7 real BigQuery + 80 vitest
+ build). Rehearsal with its own Quick Tunnel 22/22 (one check re-run with Python to read the 409 body). Deployed to
production 20:32-20:37 (deploy-upgrade.ps1, backups backup-20261017-203230-manual.zip + -203501-cli.zip): shared link,
proxy (pid 13024) and cloudflared (pid 31076) kept; the link answered 502 for ~87 s (20:35:00-20:36:28). Data and
settings unchanged by the deploy; rollback to 1.2.2 needs no restore.

* `SOURCE_NOT_READY` now says since when and by which saved change production mode is off and how to fix it (settings
  history); `BQ_VALIDATION_REQUIRED` names the mapping hash. The training checks the BigQuery source BEFORE the data
  fingerprint.
* A manual training (Overview, Model performance, Jobs) on a BigQuery source that is not ready is refused at once
  (409 + reason), no skipped job is created. The schedule switches never block a manual run: "Run once now" of the
  training flow ignores the schedule-only condition "waits for today's D-1" (`manual_readiness` in `/api/schedules`).
* Jobs page and `/api/scheduler/status` (`flow_states`): the EFFECTIVE state per flow (ON / ON_NOT_READY / ...) with
  the reason, never the switch alone.
* Mapping page: confirmation before a save that switches production off, message after it, permanent note of the
  production state (`production_switched_off` in the save response).
* "Disable production mode" keeps the active source (it used to switch to DEMO silently) and asks for confirmation.
* Tests: conftest keeps process-wide temporary `DF_DATA_DIR` / `DF_STORAGE_CONFIG`, so a test that calls
  `monkeypatch.undo()` can never resolve the real installation (incident 17/10 19:49: one settings write reached the
  live database, see the report).

## 1.2.2 - 2026-10-17 (P0: BigQuery end to end, quality gate = assessment, best evaluated candidate) [reports/demandforecast_v122_p0_bigquery_20261017.md]

Database schema unchanged (3); settings: new key `quality.below_threshold_policy` (ignored by 1.2.1: rollback needs no
restore, checked). Root cause of "DEMO on the dashboard": the quality gate was a publish switch, so no BIGQUERY run was
ever published (WAPE 0.807 > 0.60), and the Results page opened the newest run of ANY source (an old DEMO run).
Package built 2026-10-17 18:30 from local commit 7053999 (SHA-256 7AA7D910...0F95; QA 405 incl. real BigQuery + 75
vitest + build). Deployed to production 18:53-18:57 (deploy-upgrade.ps1, backup backup-20261017-185319-manual.zip) after
an isolated rehearsal with its own Quick Tunnel (17/17 checks): the shared link, the read-only proxy and cloudflared kept
running (same PIDs, same URL); the link answered 502 "app down" for ~82 s during the restart. Data and settings
unchanged. Publishing the waiting BIGQUERY run (TRN-20261017101340-EEDA47) is left to the owner ("Use this model").

* Quality policy `quality.below_threshold_policy` = `PUBLISH_WITH_WARNING` (owner decision 17/10/2026; changed default)
  or `BLOCK` (behaviour before 1.2.2). Thresholds and gate results unchanged and shown honestly. A technically sound run
  is used with a warning (`FORECAST_PUBLISHED_WITH_WARNING`, WARNING alert + audit); blocking only for technical reasons
  (no data / too short history, stale data policy, forecast not computable, BigQuery not ready). Never a DEMO fallback.
* Candidate selection on the SAME backtest points: LightGBM (+ fallback rules) vs the 28-day baseline, lower pooled WAPE
  wins (tie / undefined WAPE keeps LightGBM). A selected baseline is published as `BASELINE_MOVING_AVERAGE` (version
  `BL28-...`, no model file; explanation and extension supported). Selection, rejected candidate and reason are stored.
* Assessment stored per run (`quality_gate.assessment`): technical / quality (PASS, BELOW_THRESHOLD, NOT_EVALUATED) /
  confidence (NORMAL, LOW) / usage (USABLE, USABLE_WITH_WARNING, NOT_USABLE); APIs `/api/training-runs*`,
  `/api/forecast-runs*`, `/api/system/status` (`forecast_state`) carry it; lineage of the data used on the forecast run.
* A model in use is still never replaced automatically (review + "Use this model"); "Use this model" also publishes a run
  rejected before 1.2.2 / under BLOCK only for thresholds or confidence, without retraining, when the data is unchanged.
* UI: Results opens on the newest run of the ACTIVE source (other sources labelled "other source", never the default);
  Overview says "No forecast from BIGQUERY yet" with the cause; D-0 snapshot history opens on the active source;
  assessment box (Overview, Results, Model performance); policy selector in Configuration.
* Changed defaults: `quality.below_threshold_policy="PUBLISH_WITH_WARNING"` (new key; production never saved the
  `quality` section, so the new default applies there as soon as 1.2.2 runs).

## 1.2.1 - 2026-10-17 (D-0 own mapping + real BigQuery validation, training follows today's D-1, read-only remote link) [reports/demandforecast_v121_d0_d1_remote_20261017.md]

Database schema unchanged (3); settings: new key `bigquery.d0_mapping` (ignored by 1.2.0: rollback to 1.2.0 needs no
restore, checked). Package built 2026-10-17 16:46 from local commit 94fd17b (SHA-256 1BE9E270...4DC7; QA 391 incl. real
BigQuery + 69 vitest). Deployed to production 2026-10-17 16:48-16:52 (deploy-upgrade.ps1, backup
backup-20261017-164813-manual.zip); data and every settings section unchanged. Before the deploy the training catch-up
policy was set to SKIP (owner's instruction), so today's missed 09:00 slot was recorded SKIPPED, no training ran. D-0
SQL / key policy / schedule untouched (D-0 still OFF, SQL_NOT_VALIDATED until a version is validated).

* D-0 feed: its own mapping `bigquery.d0_mapping` (SKU, FC, quantity, day; optional order id / update time), edited on
  *SQL sources -> D-0 -> D-0 mapping* (`GET/PUT /api/bigquery/d0-mapping`, suggestion from the real schema
  `POST /api/bigquery/d0-mapping/suggest`). The D-0 SQL output / table no longer needs the D-1 columns, names or partition
  column. Saving it never touches the D-1 mapping, hash or production mode.
* D-0 validation = dry run + output check against the D-0 mapping + a REAL execution of today's aggregate (nothing
  written); the validation records the SQL sha256 and the D-0 mapping hash. A mapping / key change makes the version
  stale (`D0_REVALIDATE_REQUIRED`, job SKIPPED with that reason); validations recorded by 1.2.0 must be redone.
* D-0 job: only rows of today (Vietnam, `@day`) count; rows of another day / without day / SKU / FC / quantity are counted
  by reason; duplicates measured on today's rows; `forecast_match` (series and quantity without a forecast for today) in the
  job result. Never writes `demand_daily`; never falls back to the D-1 table. Changed: in SQL mode rows of another day were
  summed with a warning before; now they are excluded (OTHER_DAY).
* Daily training on BIGQUERY follows today's successful D-1 - scheduled OR manual (not a backfill) ending yesterday. Before,
  only the scheduled D-1 counted, so a successful manual D-1 still left the training "waiting for D-1". Readiness shows the
  D-1 of today (`D1_TODAY_SUCCEEDED`, `TRAIN_WAITING_FOR_TODAY_D1`, `TRAIN_WAITS_FOR_D1`); quality gate unchanged.
* Readiness reasons and notes show their detail in the UI; `SQL_NOT_VALIDATED` lists the status of each version.
* BigQuery error "Not found: Table ... in location X" is `BQ_NOT_FOUND` (was misreported as `BQ_LOCATION_MISMATCH`).
* Remote read-only link (no app change needed, works with 1.2.0): `Start-DemandForecast-Remote.bat` /
  `Stop-DemandForecast-Remote.bat`, `scripts/remote/remote-access.ps1` (Cloudflare Quick Tunnel, cloudflared downloaded from
  the official release with SHA-256 + signature check) and `scripts/remote/readonly_proxy.py` (GET/HEAD only, allow-list,
  local paths removed, rate limit). Guide: `REMOTE_ACCESS_GUIDE.md`.

## 1.2.0 - 2026-10-17 (L7_direct strategy, quality-gate exception record, D-1 / D-0 source tables, feature groups) [experiments/final_release_20261017/]

Database schema unchanged (3): rollback to 1.1.9 / 1.1.8 needs no restore. A DIRECT model published with 1.2.0 is
displayed by older versions but cannot be explained or extended by them (they refuse it; see docs/VAN-HANH.md).
Package built 2026-10-17 01:56 from commit 577b925 (SHA-256 2343261C...F666; QA 324 + 66 passed); isolated rehearsal on a
copy of the real DB with prices passed (upgrade, price training, exception release, restart, rollback, restore).
Deployed to production 2026-10-17 08:16 (deploy-upgrade.ps1, backup backup-20261017-081320-manual.zip); price mapping
saved and D-1 full reload 01/01-16/10 with prices (coverage 99.98%). Production training / model release not done yet
(training on production not authorised in that session); no model in use for the BigQuery scope.

* Forecast strategy `model.forecast_strategy`: RECURSIVE (default, every earlier model, DEMO) | DIRECT (experiment
  L7_direct, 16/10/2026). DIRECT = one LightGBM model for every horizon day: features at the forecast origin (data before
  it only), calendar of the target day and the horizon; trained on `direct_origins` (12) origins every
  `direct_origin_step_days` (7) days. Horizons above the backtest horizon are refused (DIRECT_HORIZON_EXCEEDS_TRAINING).
  Production implementation reproduces the experiment harness exactly (0 difference, 7 folds, real data).
* Quality gate: a run rejected only on the metric thresholds keeps its model file for review. One such run can be
  published with `POST /api/training-runs/{id}/release-with-exception` (approver, business reason, review date, restated
  WAPE / bias, `EXCEPTION-<run id>`); recorded in `quality_gate.exception`, the audit log and a WARNING alert. The
  standard thresholds are never changed; every later run goes through the normal gate.
* BigQuery: separate D-1 / D-0 source tables (`bigquery.d0_table_id`, new), metadata-only checks, saved only after a
  passed check; the D-1 table cannot change while production mode is on. The D-0 feed in TABLE mode now reads the D-0
  table (before: the D-1 table, which never has today's rows). D-0 readiness needs a passed D-0 table check.
* Feature groups in Configuration: Historical demand (lags + rolling) and Price (quantity-weighted unit price); at least
  one on (FEATURE_GROUPS_EMPTY). Each training run records the groups (switch / used), the strategy and a configuration
  fingerprint.
* Price group: owner decision 17/10/2026, ON for the release model (`model.feature_price = true`, saved explicitly). A
  group that is on but has no data in the scope is still left out of a training (recorded `used: false`, reason
  `NO_DATA`); for BigQuery the price exists only after mapping `unit_price <- sales_price` and a full reload. Tests
  `test_v120_price.py`: mapped price -> demand_daily (missing price stays NULL) -> registry -> DIRECT training (trees
  split on the price) -> published forecast and explanation read the last known price; the switch survives a restart,
  a BigQuery load, other settings saves and a 1.1.9 settings row. Backtest on real data (7 folds): demand only WAPE
  0.805953 / bias +0.068976, demand + price WAPE 0.808117 / bias +0.071829 (no gain from these two price features).
* Scheduler: a tick blocked by a long write transaction is deferred with a WARNING (SCHEDULER_TICK_DEFERRED) instead of
  an ERROR "database is locked".
* Changed defaults: `bigquery.d0_table_id` (new key) = `lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm_D0`.

## 1.1.9 - built and deployed 2026-10-16 16:31 (Vietnam time) (audit + BigQuery ingest + storage/release) [demandforecast_v119_production_ingest_training_20261016_171500.md, demandforecast_audit_v118_20261016.md, demandforecast_bq_ingest_20261016.md, demandforecast_storage_release_20261016.md]

Package `DemandForecast-1.1.9-win64-portable.zip`, built from the release commit (tag `v1.1.9`). Database schema unchanged (3): rollback to 1.1.8 / 1.1.6 needs no restore.
First BigQuery production load 16/10/2026 16:43-16:49 (source BIGQUERY, 01/01-15/10: 1,347,346 day x SKU x FC rows, 41,722,635); first training on real data REJECTED by the quality gate (WAPE 1.017, bias +0.399), no model in use for the BigQuery scope.

Storage / release / VPS preparation (late afternoon; tooling and docs, no change to forecasting, BigQuery or schedules):
* `scripts\release.ps1`: clean commit -> QA (`run-tests.ps1`) -> package -> verification (SHA-256, `VERSION`,
  `BUILD-INFO.json`) -> retention plan. A failed QA builds nothing.
* `scripts\build-package.ps1`: records version, git commit, dirty flag and a source fingerprint (`BUILD-INFO.json` in the
  package, manifest); refuses a dirty tree unless `-AllowDirty`; the same sources are not rebuilt ("Up to date"); an
  existing package of the same version is never silently replaced (`-Force` renames it `...-superseded-<time>`); the
  staging folder `dist\DemandForecast-<version>\` is removed after zipping (`-KeepFolder`).
* `scripts\prune-artifacts.ps1`: retention of `dist\` / `release\` (keeps the running version, the `-Keep` rollback
  version and the newest one); a folder is removed only when every file is identical (SHA-256) in its package; dry run
  unless `-Apply`; never touches installed versions, data or backups.
* Cleanup 16/10/2026: project 6,876 MB -> 988 MB; `dist\` keeps 1.1.8 (running) and 1.1.6 (rollback) packages.
* `scripts\vps\`: Linux VPS kit (artifact build, `install-server.sh`, `deploy.sh` with SHA-256 / schema guard / online
  backup / health check / automatic switch-back, `rollback.sh`, systemd unit, Caddy example, `app.env.example`).
  Prepared, NOT run on Linux yet.
* `app.cli` "is the app running" check also works off Windows (signal 0), so a second `serve` / a `restore` on the
  running app is refused on Linux too.
* Docs: `docs/PHAT-TRIEN-QA-PHAT-HANH.md`, `docs/TRIEN-KHAI-VPS.md`; `.gitignore` ignores `*.tar.gz` artifacts.

BigQuery ingest (afternoon):
* Exact-duplicate gate on the RAW source rows, BEFORE aggregation, in the D-1 sync, the full-period validation and the
  new dry run: rows equal in every mapped column (BigQuery GROUP BY on native values: NULL = NULL, no text
  serialisation). Counts `duplicate_groups` / `duplicate_rows` / `extra_duplicate_rows`. With the default policy BLOCK
  the load stops with `BQ_DATA_DUPLICATES` and nothing is written.
* Downloadable duplicate report `<reports_dir>/bigquery-duplicates/bq-trung-lap_<start>_<end>_<time>.xlsx` (sheets
  Summary, Duplicate_Rows with every row + `duplicate_group_id` / `duplicate_occurrence`, Duplicate_Groups); never
  overwritten; CSV fallback when the workbook cannot be written. API: `GET /api/bigquery/duplicate-reports[/{name}]`.
* Mapping is checked against the live source before any data query (`BQ_MAPPING_INVALID` with the field list); the
  aggregated day x SKU x FC rows are checked before writing (`BQ_AGGREGATE_INVALID`, nothing turned into zero).
* New "Kiểm tra trùng & thử tổng hợp (không ghi)" on the BigQuery page (`POST /api/bigquery/ingest-check`): every
  step of the next D-1 load, read-only comparison with the stored days, nothing written.
* Changed default: history feed `sql_sources.history.key_duplicate_policy` BLOCK -> **SUM_ALL** (several lines of one
  order x SKU x FC x day are summed; business rule confirmed 16/10/2026). D0 feed unchanged. Takes effect only where
  `sql_sources` was never saved (true on the real DB on 16/10/2026).
* Opt-in real-BigQuery test on inline rows (`backend/tests/test_bq_real_semantics.py`, `DF_REAL_BQ=1`, 0 bytes).

Audit (morning):

* D-1 sync: a read that returns no rows while the app holds rows for that window no longer deletes them; the job
  stops before any write with `SOURCE_INCOMPLETE` (reason `EMPTY_READ`), retries, then fails with an alert.
* Data schedules page: a job that SUCCEEDED while its result was REJECTED / FAILED (e.g. training rejected by the
  quality gate) shows that outcome; "Run once now" follows the job until it ends, blocks a second click meanwhile,
  re-reads the page afterwards and says when a job of the flow was already running. API: each job row of
  `/api/schedules` carries `result_status`.
* Docs corrected against the code: full reload scope, `BQ_AUTH_MISSING` retry, D-1 cost on an unpartitioned table,
  training outcome vs job status, D-1 missed days, `NO_NEW_DATA` with BigQuery, cancelled-order rule for BigQuery,
  broken `STORAGE_NOT_FOUND` row; verified facts of the real source table (docs/BIGQUERY.md section 12).

## 1.1.8 - built 2026-10-16, deployed 2026-10-16 08:34 (Vietnam time) [demandforecast_v118_schedules_report_20261016.md, docs/TRIEN-KHAI-1.1.8.md]

Package SHA-256 `0DFDEC86042767AB5E8A8545C990BEF5D2E8B87AB465A970F1642D4DB9F15EE0`. After the deployment the user switched
D-0 back on (DEMO, every 2 h 08:00-18:00); see Part II of the report.

* Separate schedules for the automatic flows, each with its OWN switch: D-1 closed days (`schedule.d1_enabled`),
  D-0 today (`schedule.d0_enabled`) and daily training (`schedule.train_enabled`). The single global switch
  `schedule.enabled` is no longer used for planning (kept only for rollback compatibility).
* New page **Lịch chạy dữ liệu / Data schedules** (`/schedules`): one card per flow with switch, times, time zone,
  readiness and reasons, last run / result, next runs, log, *save times*, *switch on/off*, *run once now*. Config page,
  Jobs page and Source SQL page now link to it (no duplicated controls; the old D0 toggle on the SQL page is gone).
* API: `GET /api/schedules`, `GET|PUT /api/schedules/{d1|d0|train}`, `POST /api/schedules/{flow}/run`. Switching ON
  requires readiness (409 `FLOW_NOT_READY` with reasons); saving never runs a job; the generic settings editor and the
  schedule *reset* cannot change switches (`SCHEDULE_SWITCH_VIA_FLOW_API`); `PUT /api/sql-sources/d0/options
  {schedule_enabled}` maps to the same D-0 switch.
* Scheduler: plans only flows that are ON; slots before the switch-on time (`*_enabled_at`) are neither run nor "missed";
  scheduled / catch-up / retry runs of a flow that is OFF are skipped (`D1|D0|TRAIN_SCHEDULE_DISABLED`); `reload()` lets
  the UI confirm the running scheduler loaded the new state; state per flow (`ON`, `ON_NOT_READY`, `ON_NOT_LOADED`,
  `ON_SCHEDULER_STOPPED`, `OFF`).
* Audit `SCHEDULE_CHANGED` per flow; settings history as before.
* Changed defaults / upgrade: D-1 and D-0 OFF; training takes the old global switch. Nothing turns from OFF to ON.
  On DEMO, the synthetic D0 snapshots that ran under the old global switch stop until D-0 is switched on.
* No schema change (still schema 3).

## 1.1.7 - 2026-10-15 [demandforecast_v117_release_report_20261015.md, docs/TRIEN-KHAI-1.1.7.md]

* Data window: model input (training, backtest, forecast panel, data-quality report) = complete Vietnam days from
  `data_policy.window_start_date` (2026-01-01) to yesterday; today is D0-only, future dates never used; stored history
  outside the window is kept, counted and reported. BigQuery reads start at the window (no 730-day look-back); a D-1 full
  reload keeps rows stored before the window. Panels of existing runs are rebuilt from their own stored
  train_start..train_end (explanations, extension, backtest points no longer depend on current settings).
* Backtest: up to 12 consecutive 30-day folds (~12 months), shortened to the longest span the data allows; measured
  span reported (`span_days`, first/last day) with note `BACKTEST_SPAN_BELOW_6_MONTHS`.
* Incumbent protection: with a model in use, a new model that passes the gate is kept as a candidate
  (`PROMOTION_REVIEW_REQUIRED`) with a same-fold comparison (incumbent configuration re-fitted walk-forward on the same
  folds; BETTER / WORSE / EQUAL / INSUFFICIENT_DATA); publication only through `POST /api/training-runs/{id}/promote`
  (UI button). The first model of a scope is published as before.
* OAuth / BigQuery: the `auth` gate obtains a real access token (revoked/expired token no longer reported at the dataset
  gate); new codes `OAUTH_CLIENT_INVALID`, `OAUTH_SCOPE_NOT_GRANTED` (vs IAM), `OAUTH_CLIENT_CHANGED`,
  `OAUTH_CLIENT_WRONG_TYPE`; OAuth client JSON import (Desktop app only); changing the client revokes and removes the
  old sign-in; `verified_at`; actionable messages for every OAuth code; administrator checklist in the UI;
  `python -m app.cli bq-check`.
* Fix: every "newest first" query adds `rowid DESC` as tie-breaker (one-second timestamps; rowid = insertion order,
  tables involved are append-only and never VACUUMed); found through an intermittent failure of
  `test_v111.py::test_publish_failure_after_training_keeps_previous_forecast`.
* New: `python -m app.cli data-check [--db FILE] [--models-dir DIR]` - read-only data invariants.
* Tests isolate Windows Credential Manager (memory store) by default.
* Engineering documentation: `AGENTS.md`, `CLAUDE.md`, `docs/data/`, `docs/agents/GOVERNANCE.md`, `.claude/`.
* No schema change (still schema 3). Changed defaults: `data_policy.window_start_date="2026-01-01"` (new),
  `model.backtest_folds` 3 -> 12, `model.backtest_horizon_days` 14 -> 30, `model.backtest_step_days` 7 -> 30;
  `bigquery.initial_history_days` is no longer used.

## 1.1.6 - built 2026-10-15, deployed 2026-10-15 18:05 (Vietnam time)

Package SHA-256 `A2E0345CEB654A281557BA1DA825E31E4DFD0A1DCA6C851166B9C144B3A19561`
[demandforecast_v116_production_readiness_report_20261015_171500.md, demandforecast_v116_oauth_sql_scheduler_report_20261015_145500.md].

* In-app "Sign in with Google" (OAuth installed-app flow: loopback, state, PKCE); client secret and refresh token in
  Windows Credential Manager only.
* SQL sources: versioned history / D0 SQL with validation, preview, test, restore; activation only after a successful
  BigQuery validation; jobs capture the SQL snapshot they use. D0 SQL of 15/10/2026 stored verbatim as v1; corrected
  proposal stored as v2 (not active).
* BigQuery access check by gates (auth, API + dataset, location, table metadata, query job, schema mapping).
* D-1 sync: bounded backfill, new/updated/unchanged/removed counts; key gate `BQ_KEY_NOT_UNIQUE`.
* Installer: restarts the previous version if the upgrade stops after it was stopped; `current.txt` written only after
  a successful migration; refuses when a data folder is inside the program folder.
* New scripts `deploy-upgrade.ps1` and `rollback-version.ps1`; package manifest + `.sha256`.
* Schema 3 (no migration). Changed defaults: `bigquery.oauth_enabled=false`, `bigquery.oauth_client_id=""`, new section
  `sql_sources` (history TABLE mode; D0 v1 + v2, no active version, `schedule_enabled=false`).

## 1.1.5 - installed 2026-10-15 12:18 [demandforecast_v115_bigquery_feature_registry_report_20261015_122500.md]

* BigQuery table `gold_buymed_vn2.demand_planing_lightgbm`: suggested mapping, full-period validation bound to a
  mapping hash, sync reconciliation, exact-duplicate policy.
* Feature registry (ACTIVE / DISABLED / PLANNED / UNAVAILABLE), `feature_set_version` and lineage stored per training
  run; price/discount/promotion groups used only with enough coverage.
* Changed defaults (new keys): `bigquery.history_start_date="2026-01-01"`, `exact_duplicate_policy="BLOCK"`,
  `max_retries=2`, `max_null_share=0.05`, `reference_mapping`; `model.feature_min_coverage=0.5`.

## 1.1.4 - installed 2026-10-15 01:22 [demandforecast_v114_treeshap_audit_report_20261015_013000.md]

* Auditable TreeSHAP trace (exact port of LightGBM 4.7.0 TreeSHAP, identical to `pred_contrib`), "Why?" per feature,
  trace export to Excel/CSV.

## 1.1.3 - installed 2026-10-15 00:11 [demandforecast_v113_explainability_report_20261015_001500.md]

* Three-level forecast explanation, feature catalogue, history by weekday + Excel, WAPE/bias/points explained, training
  explanation page, backtest points export.

## 1.1.2 - installed 2026-10-14 22:36 [demandforecast_v112_fix_report_20261014_224500.md]

* Dates shown as DD/MM/YYYY everywhere; compact number format.

## 1.1.1 - installed 2026-10-14 17:35 [demandforecast_v111_report_20261014_162031.md, demandforecast_v111_acceptance_20261014_174000.md]

* Migration 0003 (additive): job stages + stage history, `forecast_runs.derived_from_run_id` (forecast extension to a
  longer horizon from an accepted model), immutable `forecast_series_meta`. After this migration versions 1.1.0 and
  older cannot open the database (rollback below 1.1.1 = restore `backup-20261014-173454-pre-migration-v2.zip`).

## 1.1.0 - 2026-10-14 [upgrade_storage_fix_report_20261014_144908.md, demandforecast_fix_storage_report_20261014_102811.md]

* Configurable storage location (`storage.json`, storage id, verify / migrate / rollback / repair commands); the app
  refuses to create an empty database when the configured one is missing. Database schema 2.

## 1.0.0 - 2026-10-14

* First portable release: DEMO data, Excel import batches, LightGBM training with backtest and quality gate, immutable
  published forecasts, D0 snapshots, scheduler, backups.
