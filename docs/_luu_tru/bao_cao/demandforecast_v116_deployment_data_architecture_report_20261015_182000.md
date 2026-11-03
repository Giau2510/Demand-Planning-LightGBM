# Demand Forecasting - 1.1.6 deployment, OAuth/BigQuery, data architecture and engineering foundation

Date: 2026-10-15 (Vietnam time). Machine: LOG-PC, Windows user `LOG-PC\Giau Vo`. Working folder `D:\Buymed\Lightgbm AI`
(not a Git repository: no branch, no commits, nothing committed or pushed).

## Final status: **READY_FOR_EXTERNAL_SETUP**

1.1.6 is deployed and verified on the real installation; data, models, configuration and rollback are preserved; all
internal checks pass. Real Google OAuth and BigQuery could not be verified: the app's real access check stops at the
first gate (`auth` -> `BQ_AUTH_MISSING`) because no OAuth client has been issued and the Windows user has no Google
credentials. That is an external setup dependency, not a defect. Production BigQuery and the D0 BigQuery schedule
remain **OFF**.

## 1. Phases

| Phase | Result |
|---|---|
| A Inventory | 1.1.5 running (pid 17220, port 8765); `current.txt` 1.1.5; `storage.json` SHA-256 `8D79DBDD...E047` -> data `D:\Buymed\Lightgbm AI\data\runtime` (storage id `6cff0821634b0447`); schema 3; 20 backups; package `dist\DemandForecast-1.1.6-win64-portable.zip` SHA-256 `A2E0345CEB654A281557BA1DA825E31E4DFD0A1DCA6C851166B9C144B3A19561` = expected; package files == source (0 drift); no credentials / user data / `__pycache__` in the package; required scripts present |
| B Backup + deploy safety | real `deploy-upgrade.ps1 -CheckOnly`: PRECHECK OK; new backup verified by an isolated restore (below); 74 GB free on D:; scripts reviewed (behaviour, not comments) |
| C Data architecture | `docs/data/DATA-MODEL.md` (ER, lifecycle, keys, timezone, implicit rules, contract check, A-E assessment) and `docs/data/DATA-DICTIONARY.md` (generated from PRAGMA of a DB copy) |
| D Validation + safe fixes | read-only `app.cli data-check` (13 invariants); deterministic newest-first ordering; new tests. Source only, not in the 1.1.6 package |
| E Engineering foundation | `AGENTS.md`, `CLAUDE.md`, `CHANGELOG.md`, `docs/agents/GOVERNANCE.md`, `.claude/settings.json`, `.claude/agents/` |
| F Deploy 1.1.6 | done 18:01:39-18:05:42, exit 0 |
| G OAuth / BigQuery real | **BLOCKED_EXTERNAL_SETUP** (real evidence below) |
| H D0 SQL | v1 kept verbatim, v2 still a proposal, none active, schedule OFF; real comparison **BLOCKED_EXTERNAL_SETUP**; logic tests only |
| I Regression / rollback | all pass (section 6) |

## 2. Deployment of 1.1.6

Gate checks, in order: scheduler slot 18:00 finished (`JOB-20261015110028-364BC7` SUCCEEDED) and no job in flight;
next slot 01:00. Pre-deploy facts from a fresh read-only DB copy: integrity ok, 0 FK violations, `demand_daily`
38,533 rows / 1,015,057 units = `order_lines` 93,157 lines / 1,015,057 units, 3 forecast runs / 4,368 values,
model `MV-20261014-150621-DF32.txt` SHA-256 `EC507FD6...6C26`.

Backups (all in `D:\Buymed\Lightgbm AI\backups`):

| File | Bytes | SHA-256 | Taken by | Verification |
|---|---|---|---|---|
| backup-20261015-180114-manual.zip | 9,102,362 | 32ADB5F3F9E79058051E6C107950337DCD6A2782DE629DB5EDFA916E7D21E5BC | official API, before deploy | restored with the app's own `restore_backup()` into an isolated scratch folder: integrity ok, 0 FK, schema 3, no migration needed, both model files with identical SHA-256, only difference vs live = 1 audit row (the backup itself) |
| backup-20261015-180141-manual.zip | 9,102,362 | 646330CE9669EECF0B313AA827028A91FCA3D59E2A4219A78BE6BB3006B1D76D | `deploy-upgrade.ps1` | `db/app.db` present (script check) |
| backup-20261015-180424-cli.zip | 9,102,361 | 1EB0AA33075E70DE4428D0AD4AF151B790A8576DDFA3E1EF6D5A57C810313A4B | `install.ps1` (integrity-checked by `backup.py`) | integrity_check in `backup_database` |

Upgrade: `scripts\deploy-upgrade.ps1 -Package ... -ExpectedSha256 A2E0345C... -ConfirmToken UPGRADE-1.1.6`. The token is
the script's documented non-interactive form of its typed confirmation; it was used because this batch explicitly
authorised the controlled upgrade. The app was stopped about 1.5 minutes (18:04 to 18:05:38). Transcript:
`D:\Buymed\Lightgbm AI\logs\runtime\deploy-20261015-180140.log`.

Post-deploy evidence:

* `/api/health` 1.1.6; process pid 36892 runs `...\Programs\DemandForecast\1.1.6\python\python.exe -m app.cli serve
  --port 8765`; `current.txt` 1.1.6; Desktop and Start-menu shortcuts -> 1.1.6 `Start.bat`; no autostart task existed
  (none created).
* `storage.json` SHA-256 unchanged; data dir unchanged; active source DEMO (unchanged); schema 3 (no migration);
  `check-env` OK; startup log without warnings or errors.
* Fresh DB copy after deploy: every table count identical except `audit_log` +2 (BACKUP_CREATED x2); demand and
  order-line sums identical; forecast runs and values identical; settings rows untouched; `data-check` same result as
  before (WARN only for the pre-0003 forecast run, see section 4).
* 1.1.6 state: BigQuery production disabled; OAuth not configured; SQL D0 = 2 versions, none active,
  `schedule_enabled=false`; history source TABLE mode; scheduler running.
* Read-only browser E2E against the real 1.1.6 (`e2e_readonly.py`, any non-GET request counts as a failure):
  **90 passed, 0 failed**; no new job created.
* Rollback available: `rollback-version.ps1 -To 1.1.5 -CheckOnly` -> "database schema 3; 1.1.5 supports up to 3 /
  rollback possible without restoring the database". 1.1.5 and older program folders are kept.

## 3. Google OAuth and BigQuery (real checks, no mocks)

| Check | Result |
|---|---|
| Windows identity of the app | `Giau Vo` on LOG-PC (from `/api/bigquery/identity`) |
| OAuth client configured | no (`configured=false`, `client_secret_set=false`) |
| Credential Manager entries of the app | 0 |
| ADC for this Windows user | absent (`%APPDATA%\gcloud\application_default_credentials.json` missing); `GOOGLE_APPLICATION_CREDENTIALS` not set; gcloud not installed |
| Network to `bigquery.googleapis.com` | reachable (HTTPS answered) |
| App access check (run on an isolated copy of the live DB, same Windows user) | `auth` **FAIL `BQ_AUTH_MISSING`**; `api_and_dataset`, `location`, `table_metadata`, `query_job`, `schema_mapping` NOT_RUN |
| OAuth scopes requested by the app | `openid`, `email`, `https://www.googleapis.com/auth/bigquery` |

Not verified (BLOCKED_EXTERNAL_SETUP): BigQuery API enabled, IAM (`roles/bigquery.jobUser` on `lakehouse-prod-394907`,
`roles/bigquery.dataViewer` on `gold_buymed_vn2`), location `asia-southeast1`, table schema and column types, partition
`created_date`, row counts, key uniqueness, any real query. Unit tests of OAuth/BigQuery use fakes and are not counted as
real verification. Configuration read from the DB (no secrets): project `lakehouse-prod-394907`, location
`asia-southeast1`, dataset `gold_buymed_vn2`, table `demand_planing_lightgbm`, `created_at_is_utc=true`, field mapping
**not yet set** (all columns empty).

## 4. Data architecture findings

Full detail: `docs/data/DATA-MODEL.md`. Main points:

1. **No data defect found.** On a copy of the live DB all invariants hold: integrity, FKs, one ACTIVE DEMO batch, closed
   batches hold no rows, demand = order lines, scope ownership, active-dataset setting, valid dates and quantities,
   no order-grain duplicates, every forecast run complete (n_series x max_horizon), model file hash matches, no stuck
   job. One expected WARN: `FCR-20261014080621-8D88F1` (published before migration 0003) has no per-series explanation
   rows; it is immutable and stays as is.
2. **Batch isolation holds** even when batches share dates, SKU, FC and order ids (new test). Replacement/deletion purges
   only the selected batch; published forecasts survive.
3. **Implicit rules in code** (documented): settings defaults apply to every section/key never saved (only 4 of the
   sections exist in the live DB), so a new version can change behaviour without data change; `scope_key` ownership,
   closed-batch purge, demand aggregation and forecast completeness are code conventions, now checked by `data-check`.
4. **Ordering defect (fixed in source):** 23 "newest first" queries relied on second-resolution timestamps only; rows
   written in the same second came back in arbitrary order. Found through an intermittent failure of
   `test_v111.py::test_publish_failure_after_training_keeps_previous_forecast` (224 passed, 1 failed in the first run).
   Fixed with `rowid DESC` tie-break; new test fails on the old code and passes on the new.
5. **Contract deviations needing a business decision (not changed):**
   * History: BigQuery reads from `history_start_date` 2026-01-01 (~9.5 months) while the contract asks for about two
     years where available.
   * Backtest: default 3 folds x 14 days, step 7 (about 5 weeks), not 6-12 months; the 30-day horizon is not
     backtested at full length (configurable up to 12 folds x 90-day step).
   * Promotion: a candidate is gated by absolute thresholds (examples, not business-approved) and optionally a naive
     baseline; it is not compared with the current champion on the same folds.
   * Target semantics: the contract target is quantity at order creation (cancellations not subtracted) but the user's
     D0 SQL v1 excludes `order_status = 'CANCEL'`.
6. **Retention:** no automatic retention for backups (now 23 files, ~9 MB each), logs, reports or old model files.
   Not urgent (74 GB free); a policy needs a decision before automation.
7. **Restructuring:** class A and B done; class C/D/E none required (no schema change, no transformation; splitting
   the SQLite store or changing engine is not justified).

Timezone (verified): stored timestamps UTC; business dates Asia/Ho_Chi_Minh; Excel naive times = VN; BigQuery history
date from `created_at` uses `DATE(TIMESTAMP(col), 'Asia/Ho_Chi_Minh')` when `created_at_is_utc=true`; D0 v1 uses
`DATE(a.created_at)` (UTC day if the column is TIMESTAMP) and v2 `DATE(a.created_at, 'Asia/Ho_Chi_Minh')` (correct only
if TIMESTAMP). The real column type is UNKNOWN until BigQuery is readable.

## 5. D0 SQL

v1 (user SQL, stored verbatim) and v2 (proposal: master de-duplicated, explicit JOIN, VN date, trailing comma removed)
are both saved, neither active; scheduled BigQuery D0 runs are refused while `schedule_enabled=false`
(`D0_SCHEDULE_DISABLED`). Logic comparison on synthetic rows transpiled to DuckDB (not BigQuery): 10/10 and 5/5 checks
pass - v1's `LEFT JOIN` + `WHERE c.*` behaves as an inner join, a duplicated master row doubles demand in v1 but not
in v2, `DATE(created_at)` gives the UTC day for a 02:00 VN order, quantities otherwise identical, NULL quantities are
excluded with a reason (never 0), duplicate candidate keys block the write. Row counts, distinct keys, totals and
coverage on real data: **not measured** (BLOCKED_EXTERNAL_SETUP). v2 must not be activated only because it runs.

## 6. Tests and checks

| Check | Kind | Result |
|---|---|---|
| Backend pytest (final, all files) | unit + integration with fakes | **230 passed, 0 failed** (224 existing + 6 new; log `logs\development\pytest_final_20261015_181008.log`; wall time 3 h 47 min only because the PC was suspended during the run - CPU time about 2.5 min as usual) |
| Backend pytest before the ordering fix | same | 224 passed, 1 failed (ordering defect, section 4) |
| Frontend vitest | unit | 46 passed (7 files) |
| Frontend typecheck / build | static / build | OK / OK |
| Lint | - | not configured |
| `data-check` on live-DB copies (before and after deploy) | read-only, real data copy | 12 OK + 1 expected WARN |
| Package content + drift | deterministic | OK (0 drift at deploy time) |
| Isolated restore of the pre-deploy backup | real backup, isolated folder | OK |
| Real deploy | real installation | exit 0, post-checks OK |
| Read-only browser E2E on the real 1.1.6 | real app, GET only | 90 passed, 0 failed |
| Rollback check-only | real installation, read-only | OK |
| BigQuery access check | real Google endpoint path, real Windows user | BLOCKED at `auth` (BQ_AUTH_MISSING) |
| D0 SQL logic | DuckDB, synthetic | 10/10, 5/5 (logic only) |
| Secret scan of changed/new files; PS1 ASCII | deterministic | no hits; all ASCII |
| Claude Code deny rule | live tool check | Read of a dummy `client_secret*.json` refused |

Earlier isolated install/upgrade/rollback tests of this exact package (previous report): fresh 24+43, upgrade 26+4+7,
deploy scenario 12/12.

## 7. Files changed in this batch

Application source (Unreleased, not in the deployed package; checkpoint of the previous source:
`checkpoints\source-1.1.6-before-unreleased-20261015-175329.zip`):

* `backend/app/data_checks.py` (new), `backend/app/cli.py` (`data-check` command)
* `rowid DESC` tie-break: `backend/app/api/{background,bq_routes,data_routes,forecast_routes,ops_routes}.py`,
  `backend/app/data/{demand,importer,intraday}.py`, `backend/app/diagnostics.py`,
  `backend/app/ml/{feature_registry,pipeline,training_explain}.py`, `backend/app/sync.py`
* Tests: `backend/tests/test_data_checks.py`, `test_ordering.py` (new); `test_import.py` (+1 isolation test);
  `test_v111.py` (deterministic query, assertion unchanged)

Documentation and governance: `AGENTS.md`, `CLAUDE.md`, `CHANGELOG.md`, `docs/data/DATA-MODEL.md`,
`docs/data/DATA-DICTIONARY.md`, `docs/agents/GOVERNANCE.md`, `docs/KIEN-TRUC.md` (module table + links),
`docs/CHECKPOINT.md` (batch section), `.claude/settings.json`, `.claude/agents/repo-scout.md`,
`.claude/agents/data-reviewer.md`, this report.

Real installation (by the authorised deployment only): program folder `%LOCALAPPDATA%\Programs\DemandForecast\1.1.6`,
`current.txt`, two shortcuts, 3 backups, deploy transcript. No change to `storage.json`, the database content (except
2 audit rows), models, settings, batches or forecasts. No BigQuery, IAM or Google Cloud change.

## 8. Governance: enforced vs policy

* Enforced: `.claude/settings.json` deny rules (file-tool edits of live data, backups, per-user storage config and
  program folders; reads of Google credential files) - verified live; project subagents read-only by tool list, model
  tier pinned (`haiku` / `sonnet`) and `maxTurns` capped.
* Policy only: 50 % resource target (usage is not visible to the agent), max two concurrent specialists, retry limits,
  escalation rules, task contracts, checkpoints. Shell commands are not covered by the file-tool deny rules.
* Codex CLI is not installed; Codex reads `AGENTS.md` natively, no Codex configuration was invented.
* This batch used one documentation-lookup agent; everything else ran in the orchestrator with deterministic scripts.

## 9. Remaining blockers and next actions

1. **Google Cloud administrator** (external): create an OAuth client of type "Desktop app" (consent screen Internal,
   scopes `openid`, `email`, `https://www.googleapis.com/auth/bigquery`); confirm the BigQuery API is enabled on the
   project that owns the client; grant the user's Google account `roles/bigquery.jobUser` on `lakehouse-prod-394907`
   and `roles/bigquery.dataViewer` on `gold_buymed_vn2`. Hand over Client ID and Client secret through a secure channel
   (never in chat or e-mail text).
2. **User, in the app (1.1.6 already installed):** Google page -> enter the client -> Sign in with Google -> "Kiem tra
   quyen BigQuery" (all six gates must pass) -> set the field mapping -> full-period validation -> test SQL D0 v1 and v2
   and choose one with the business owner (cancelled-order rule, date column type).
3. **Business owner:** decide history start (2026-01-01 vs two years), backtest folds/step, champion/challenger rule,
   WAPE/bias thresholds, and the cancelled-order rule for the target.
4. Only after 1-3: enable BigQuery production and the D0 BigQuery schedule.
5. Engineering: package the Unreleased source changes as 1.1.7 (build, isolated install/upgrade/rollback tests) when
   convenient; nothing urgent.

Rollback if ever needed: `%LOCALAPPDATA%\Programs\DemandForecast\1.1.6\scripts\rollback-version.ps1 -To 1.1.5`
(no database restore needed).
