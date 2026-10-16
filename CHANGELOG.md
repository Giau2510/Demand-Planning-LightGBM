# Changelog

Versions of the portable package `DemandForecast-<version>-win64-portable.zip`. Details and evidence for each version
are in the report named in brackets (folder `reports/`). "Changed defaults" lists settings whose code default changed:
they take effect without any data change for every section/key that was never saved (see
[docs/data/DATA-MODEL.md](docs/data/DATA-MODEL.md) section 9).

## 1.1.9 - 2026-10-16 (audit + BigQuery ingest + storage/release) [demandforecast_audit_v118_20261016.md, demandforecast_bq_ingest_20261016.md, demandforecast_storage_release_20261016.md]

Package `DemandForecast-1.1.9-win64-portable.zip`, built from the release commit (tag `v1.1.9`). Database schema unchanged (3): rollback to 1.1.8 / 1.1.6 needs no restore.

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
