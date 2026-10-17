# Changelog

Versions of the portable package `DemandForecast-<version>-win64-portable.zip`. Details and evidence for each version
are in the report named in brackets (folder `reports/`). "Changed defaults" lists settings whose code default changed:
they take effect without any data change for every section/key that was never saved (see
[docs/data/DATA-MODEL.md](docs/data/DATA-MODEL.md) section 9).

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
