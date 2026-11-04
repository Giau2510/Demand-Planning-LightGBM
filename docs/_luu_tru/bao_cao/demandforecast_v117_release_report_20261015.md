# Demand Forecasting 1.1.7 — final hardening, 2026 data window, BigQuery login completion

Date: 2026-10-15 (Vietnam time). Machine LOG-PC, Windows user `LOG-PC\Giau Vo`. Repository `D:\Buymed\Lightgbm AI`
(not a Git repository: nothing committed or pushed). The installed version stays **1.1.6** (not touched by this batch).

## Final status: **CODE READY — GOOGLE ACCESS BLOCKED**

All code and tests in scope are complete and the 1.1.7 package is built and verified in isolation. Google OAuth and
BigQuery could not be verified for real: no OAuth Desktop client has been issued and the Windows account has no Google
credentials, so the real access check stops at the `auth` gate (`BQ_AUTH_MISSING`). No real BigQuery query has run.

## 1. Summary of changes (1.1.7)

| Area | Change |
|---|---|
| Data window | Model input = complete Vietnam days from `data_policy.window_start_date` (**2026-01-01**) to **yesterday**; today = D0 only; future never used; stored older data kept and counted, not used. Applied to training, backtest, forecast panel, data-quality report, BigQuery read range, D-1 full reload, status API, Dashboard. Existing runs are rebuilt from their own stored `train_start..train_end`. |
| Newest-first | `rowid DESC` tie-break on every "latest" query, reviewed table by table (append-only tables, no VACUUM, backup API preserves rowids); one remaining ascending query fixed; regression tests. |
| Backtest | Defaults 12 folds × 30 days, step 30 (up to ~12 months), shortened to the data; measured span stored and shown; note `BACKTEST_SPAN_BELOW_6_MONTHS`. |
| Incumbent protection | With a model in use, a new model is a candidate (`PROMOTION_REVIEW_REQUIRED`), never published automatically; same-fold comparison stored; explicit promotion endpoint + UI button; first model of a scope still published. |
| OAuth / BigQuery | Real token request at the `auth` gate; error classes for client / scope / expired / network / IAM; client JSON import (Desktop app only); client change revokes the old sign-in; `verified_at`; actionable messages; admin checklist; `app.cli bq-check`. |
| Other | `app.cli data-check`; tests isolate Credential Manager; docs (release notes `docs/TRIEN-KHAI-1.1.7.md`, CHANGELOG, data model, BigQuery, operations, model). No schema change (schema 3). |

## 2. Defects found and fixed

| # | Defect | Evidence | Fix |
|---|---|---|---|
| 1 | Access check `auth` gate passed without contacting Google: a revoked/expired token was reported at the *dataset* gate, mixing sign-in and permission errors | code review of `access_check` (client creation never refreshes credentials) | `verify_auth()` obtains an access token; test with revoked / invalid client / network errors at the auth gate |
| 2 | "Insufficient authentication scopes" (user unticked BigQuery on the consent page) reported as missing IAM permission | `_map_error` order | new `OAUTH_SCOPE_NOT_GRANTED` before the permission rule; test |
| 3 | `invalid_client` / deleted client reported as "expired sign-in" | `_map_error` | `OAUTH_CLIENT_INVALID`; test |
| 4 | A token of an old OAuth client stayed "signed in" after the client was changed (unusable) | `save_client` | revoke + remove, status `OAUTH_CLIENT_CHANGED`; `credentials()` refuses a foreign-client token; test |
| 5 | OAuth error codes (cancelled, blocked, timeout, network, state mismatch, …) had no message/next action; `BQ_AUTH_*` told users to install gcloud | message catalogue | bilingual messages with actions for every emitted OAuth/BQ code; catalogue completeness test |
| 6 | Explanations / forecast extension / backtest-point export rebuilt a run's panel from **current** settings (`max_train_days`, data end), so a settings change could break or alter old runs | `explain._reproduce`, `extend_forecast`, `training_explain` | `panel_for_run()` uses the run's stored range; test changes the window after training and reproduces exactly |
| 7 | Training could use today's partial day and dates after it (MANUAL_IMPORT accepts today; injected future rows) | `build_panel` used the max date of the data | window end = yesterday (VN); test with today + future rows |
| 8 | BigQuery fell back to a 730-day look-back when `history_start_date` was empty; D-1 full reload deleted all stored rows of the scope | `read_range`, `run_d1_sync` | read floor = window start; full reload replaces only from the window start; tests |
| 9 | Newest-first ties at one-second resolution returned arbitrary rows (found by a flaky test) | intermittent `test_v111` failure | `rowid DESC`; tests for jobs, training runs, forecast runs (incumbent), validation reports |
| 10 | Backtest covered ~5 weeks; 30-day horizon never backtested at full length | defaults 3 × 14 days | 12 × 30-day folds, adaptive; test of span and leakage |
| 11 | Second model replaced the model in use automatically (no comparison) | pipeline | candidate + same-fold comparison + explicit promotion; tests better/worse/equal/insufficient, refusal when data changed |
| 12 | Client JSON could not be imported (manual copy of secrets on every PC); `File.text()` unavailable in older browsers | UI | JSON import with FileReader fallback; frontend test |

## 3. Remaining issues (not fixed here)

| Issue | Reason | Impact |
|---|---|---|
| Real Google OAuth + BigQuery unverified | no OAuth Desktop client, no IAM grant (external) | BigQuery cannot be enabled yet; DEMO/Excel unaffected |
| D0 SQL v1/v2 not run on BigQuery; `created_at` type unknown; master SKU may duplicate rows when a SKU has several statuses; `fact_order` has no partition filter (cost); cancelled-order rule vs target | needs real schema + business decision | D0 BigQuery schedule stays OFF |
| Promotion is manual only | no approved promotion rule / WAPE-bias thresholds | after new data, forecasts change only when a user promotes the candidate |
| Backtest span < 12 months | data window starts 2026-01-01 (≈ 9.5 months of history) | 7 folds = 210 days with today's data; 12 months possible from early 2027 |
| No automatic retention of backups/logs | needs a policy decision | disk use grows slowly (~9 MB per backup) |
| Lint not configured | — | reported as not configured |

## 4. Data window from 2026-01-01 (confirmed)

`data_window()` = {start: `data_policy.window_start_date` = 2026-01-01, end: yesterday in Asia/Ho_Chi_Minh}. The rule
is used by training, backtest, forecast, quality report, status API and BigQuery reads (see section 1). Stored rows are
never deleted because of the window.

Measurement on a read-only copy of the live DB (active dataset = DEMO `DEMO-20261014080556-5342EB`, synthetic data
generated by the app; no BigQuery data is accessible, so **no BigQuery row counts are reported**), window
2026-01-01 .. 2026-10-14:

| Part of the stored daily demand | Rows | Quantity | Series | Dates | Used by the model |
|---|---|---|---|---|---|
| All stored | 38,533 | 1,015,057 | 84 | 2024-10-14 .. 2026-10-13 | — |
| Before the window | 23,401 | 576,448 | 68 | 2024-10-14 .. 2025-12-31 | no (kept untouched) |
| In the window | 15,132 | 438,609 | 84 | 2026-01-01 .. 2026-10-13 | **yes** |
| After the window end (today/future) | 0 | 0 | 0 | — | no |

## 5. Date boundary and timezone evidence (tests, all passing)

* `2026-01-01` included, 2025-12-31 excluded: `test_window_is_2026_01_01_to_yesterday_and_stored_history_is_kept`
  (train_start = 2026-01-01; 61 days × 6 series before the window counted, not used; data unchanged).
* UTC+7 boundary: `test_vietnam_day_boundary_decides_window_membership` — `2025-12-31 23:30` (VN) → excluded;
  `2025-12-31T17:30:00+00:00` (= 00:30 VN 01/01) → included; `2026-01-01 00:00` → included.
* Day closing: `test_today_closes_at_midnight_vietnam_time` — 16:59:59 UTC (23:59:59 VN) → window ends the day before;
  17:00:00 UTC (00:00 VN) → the previous day becomes complete.
* No future/today data in training: same window test (today's rows + a future row exist, train_end = yesterday).
* Backtest without leakage: `test_backtest_span_is_the_longest_valid_one_and_never_sees_its_own_window` (each fold's
  training data ends the day before its first evaluated day; every evaluated point is on/after the origin).
* Re-running sync creates no duplicates: `test_d1_rerun_is_idempotent_and_full_reload_keeps_rows_before_the_window`.
* Existing forecasts/models still readable: `test_runs_trained_before_a_window_change_stay_explainable_and_extendable`
  and the read-only E2E on the real-data copy (section 12).
* Determinism: `test_same_input_gives_the_same_panel_and_metrics`; `EQUAL` verdict when the same data and configuration
  are trained twice (`test_a_model_in_use_is_never_replaced_automatically`).

## 6. Backtest results and data limits

Measured with the installed 1.1.7 package on an isolated copy of the live DB (DEMO data, synthetic; window
2026-01-01 .. 2026-10-13 = 286 days, 84 series):

* Configured: up to 12 folds × 30 days, step 30, ≥ 56 training days per fold. **Evaluated: 7 folds, 210 days
  (2026-03-18 .. 2026-10-13, ≈ 7 months)**; folds 1–5 skipped for short history (`FOLD_SKIPPED_SHORT_HISTORY`). Twelve
  months are not possible before about January 2027 because the window starts on 2026-01-01; the app reports the
  measured span and would add `BACKTEST_SPAN_BELOW_6_MONTHS` below 182 days.

| Fold | Evaluated days | Training days | WAPE | Bias | Points | Baseline WAPE |
|---|---|---|---|---|---|---|
| 6 | 2026-03-18 .. 04-16 | 76 | 0.1868 | +0.0293 | 2,040 | 0.2162 |
| 7 | 2026-04-17 .. 05-16 | 106 | 0.2053 | +0.0759 | 2,040 | 0.2279 |
| 8 | 2026-05-17 .. 06-15 | 136 | 0.1816 | +0.0118 | 2,040 | 0.2319 |
| 9 | 2026-06-16 .. 07-15 | 166 | 0.1968 | +0.0386 | 2,040 | 0.2469 |
| 10 | 2026-07-16 .. 08-14 | 196 | 0.3192 | +0.1450 | 2,040 | 0.3794 |
| 11 | 2026-08-15 .. 09-13 | 226 | 0.2475 | −0.0542 | 2,124 | 0.3098 |
| 12 | 2026-09-14 .. 10-13 | 256 | 0.2701 | −0.0059 | 2,338 | 0.2857 |
| **Pooled** | 210 days | — | **0.2237** | **+0.0354** | **14,662** | 0.2639 |

MAE 4.816, MAPE 0.2832. For reference only (different windows, not comparable): the model in use was evaluated at its
training on 3 × 14-day folds of two years of data: WAPE 0.2376, bias −0.0282, 3,274 points. Quality-gate thresholds are
still example values, not business-approved.

## 7. Incumbent model protection

* Incumbent = model of the latest published forecast run of the scope (`pipeline.incumbent`).
* Candidate passing the quality gate with an incumbent → status REJECTED + reason `PROMOTION_REVIEW_REQUIRED` (schema
  unchanged: no CHECK-constraint rebuild), model file + SHA-256 + metrics + comparison stored, alert
  `CANDIDATE_READY_FOR_REVIEW`; the published forecast is unchanged; the scheduled run skips identical data.
* Comparison `WALK_FORWARD_SAME_FOLDS`: the incumbent's stored configuration re-fitted walk-forward on exactly the
  candidate's folds, panel (SKU × FC × day) and target; identical evaluation points. Pooled WAPE = Σ|A−F| / ΣA
  (undefined when ΣA = 0 → no verdict), bias = (ΣF − ΣA) / ΣA (undefined when ΣA = 0), MAE, MAPE (only points with
  A ≥ 1). Verdict BETTER / WORSE / EQUAL (|ΔWAPE| ≤ 1e-9, numerical tie only) / INSUFFICIENT_DATA (< `min_backtest_points`,
  no fold, or incumbent configuration not rebuildable). No business threshold is applied or invented.
* Promotion only by `POST /api/training-runs/{id}/promote {"confirm": true}` (UI button with confirmation): refused if
  no longer a candidate, superseded, data changed, model file changed, or a training/extension job is running; one
  transaction (ACCEPTED + new forecast run); previous model and forecasts kept; audit `MODEL_PROMOTED`.
* Tests: better / worse / equal / insufficient (3 forms), integration (equal on identical data, skip of identical data,
  explicit promotion, second promotion refused), refusal after a data change, atomic failure (no ACCEPTED without its run).

## 8. OAuth and BigQuery — real vs mocked

| Kind | Result |
|---|---|
| **Real (this machine, no mock)** | Windows account `Giau Vo` on LOG-PC: no OAuth client configured, no app entry in Windows Credential Manager, no ADC file, `GOOGLE_APPLICATION_CREDENTIALS` not set, gcloud not installed. `python -m app.cli bq-check` of the **installed 1.1.7 package** (isolated DB copy, same Windows account): exit 1, first failure gate `auth`, code `BQ_AUTH_MISSING`; later gates NOT_RUN. **No real OAuth sign-in, token, identity or BigQuery query was obtained.** |
| Mocked / fake (unit + integration) | OAuth flow (state, PKCE S256, loopback, code exchange, refresh, revoke, logout), client JSON import, client change, error classification (expired, invalid client, network, missing scope vs IAM, API disabled, not found, location, timeout), access gates in order, CLI output without secrets, backup without secrets — all passing |
| Not verifiable (missing access) | Google consent, token issuance and refresh with a real client; account identity from Google; BigQuery API enablement; IAM `roles/bigquery.jobUser` (project) and `roles/bigquery.dataViewer` (dataset); dataset location; table metadata and schema (`created_at` type); real read-only query; real row counts before/after the window |

No secret was created, printed or stored in code, logs, reports or the package.

## 9. Missing Google permissions / configuration

1. OAuth client of type **Desktop app** (OAuth consent screen *Internal*; scopes `openid`, `email`,
   `https://www.googleapis.com/auth/bigquery`), delivered as the client JSON file through a secure channel.
2. BigQuery API enabled on `lakehouse-prod-394907` and on the project that owns the OAuth client.
3. For the user's Google account: `roles/bigquery.jobUser` on project `lakehouse-prod-394907`;
   `roles/bigquery.dataViewer` on dataset `lakehouse-prod-394907.gold_buymed_vn2` (location `asia-southeast1`).

The app shows the same list, filled with the real values, under *Xác thực Google → Nội dung gửi quản trị Google Cloud*.

## 10. D0 status

OFF. v1 (user SQL) kept verbatim, v2 still a proposal, none active, `schedule_enabled=false`, BigQuery production
disabled. Review of v2: trailing comma removed (whether BigQuery accepts it in v1 is decided by the dry-run); `LEFT JOIN`
+ `WHERE` on joined columns = inner join (v2 makes it explicit); `DISTINCT` master removes exact duplicates only — a
SKU with several statuses still multiplies rows and the key gate blocks the write; `DATE(a.created_at,
'Asia/Ho_Chi_Minh')` is right only if `created_at` is TIMESTAMP (unknown); `NOT IN ('CANCEL')` also drops NULL status;
`fact_order` has no date/partition filter (bytes capped by `maximum_bytes_billed`); excluding cancelled orders conflicts
with the target "ordered quantity at creation" — business decision needed. Logic re-checked on synthetic rows with DuckDB
(10/10, 5/5; not BigQuery).

## 11. Tests (pass / fail / skip)

| Check | Kind | Pass | Fail | Skip | Evidence |
|---|---|---|---|---|---|
| Backend pytest (all) | unit + integration, fakes for Google | **253** | 0 | 0 | `logs\development\pytest_117_final_20261015_225549.log` |
| — of which new in 1.1.7 | window, UTC+7, backtest, determinism, sync, old runs, promotion, OAuth, CLI, ordering | 23 | 0 | 0 | `tests/test_v117.py` (22), `test_v111.py` (+1) |
| Frontend vitest | unit (mocked API) | **48** | 0 | 0 | `logs\development\frontend_117_20261015_225559.log` (incl. `v117.test.tsx`: 2) |
| Frontend typecheck | static | OK | — | — | same log |
| Frontend production build | build (inside the package build) | OK | — | — | `logs\development\build_117_20261015_225827.log` |
| Lint / format | — | not configured | | | |
| Package content + drift vs source | deterministic | OK (0 drift, no data/credentials/caches, SHA matches `.sha256`) | 0 | — | `pkg_verify` |
| Isolated upgrade 1.1.6 → 1.1.7 → rollback 1.1.6 on a copy of the live DB | installed packages, real-shaped data | **20** | 0 | 0 | scratchpad `iso117d.ps1` |
| Read-only browser E2E on installed 1.1.7 (copy) | real app, GET only | 90 | 0 | 0 | inside the isolated scenario |
| `data-check` live-DB copies (start/end of batch) | read-only, real data | 12 OK + 1 expected WARN | 0 | — | `forecast_series_meta` of the pre-0003 run |
| Migration / schema compatibility | no new migration; 1.1.6 ↔ 1.1.7 on schema 3 | OK | 0 | — | isolated scenario |
| Real Google OAuth / BigQuery | real | — | blocked at `auth` | — | section 8 |
| Secret scan (changed files, package) | deterministic | no hit | 0 | — | final diff review |
| D0 SQL logic (DuckDB, synthetic) | logic only | 10 + 5 | 0 | — | SQL unchanged; last run 2026-10-15 ≈18:10 |

Notes: the existing Windows Credential Manager round-trip test writes and deletes a temporary `selftest-…` entry of the
current Windows user (since 1.1.6); every other test now uses an in-memory secret store.

## 12. Database, models, configuration — before / after

| Item | Batch start (22:19) | Batch end (23:22) |
|---|---|---|
| Installed / running | 1.1.6, pid 36892 since 18:05, `current.txt` 1.1.6 | identical (not stopped, not reinstalled) |
| `storage.json` SHA-256 | 8D79DBDD…E047 | identical |
| Database (read-only copies) | schema 3, integrity ok, 0 FK violations, 38,533 demand rows / 1,015,057 units, 3 forecast runs | identical counts in every table, same forecast runs |
| Model files | `MV-20261014-150621-DF32.txt` EC507FD6…, `.json` 62F11674… | identical |
| Backups | 23 | 23 (no backup needed: nothing on the real installation was changed) |
| Settings / active source | DEMO, BigQuery production off, D0 schedule off, no OAuth client | identical |
| Credential Manager (app entries) | 0 | 0 |
| 1.1.6 package | SHA-256 A2E0345C…9561 | identical (kept for rollback) |

All write tests ran on copies in the session scratchpad with an isolated `LOCALAPPDATA`.

## 13. Package, SHA-256, rollback

* Package: `D:\Buymed\Lightgbm AI\dist\DemandForecast-1.1.7-win64-portable.zip` — 92,017,287 bytes, 7,112 files
  (manifest `DemandForecast-1.1.7-win64-portable.manifest.json`).
* **SHA-256: `7D05CE491058BF8F26CB57627F7EDEC26285A8065B7582C7877AEE7A04C2F45B`** (also in the `.sha256` file).
* Contents: embedded Python 3.14.7 + locked wheels (LightGBM 4.7.0, google-cloud-bigquery 3.46.1, …), backend, built UI,
  scripts (install / deploy-upgrade / rollback-version / …), docs incl. `docs/TRIEN-KHAI-1.1.7.md`, README, CHANGELOG.
  No database, storage.json, model, credential, token or `__pycache__` of the app.
* Not installed on this machine (as required). Upgrade and rollback commands: `docs/TRIEN-KHAI-1.1.7.md`.
  Rollback: `%LOCALAPPDATA%\Programs\DemandForecast\1.1.7\scripts\rollback-version.ps1 -To 1.1.6` (type
  `ROLLBACK-1.1.6`), no database restore (schema 3) — verified in the isolated scenario.
* Source checkpoint before this batch: `checkpoints\source-1.1.6plus-before-1.1.7-20261015-222605.zip`.

## 14. Required actions

1. **Google Cloud administrator:** section 9 (OAuth Desktop client JSON, API, two IAM roles for the user's account).
2. **User (when convenient, outside scheduler slots):** install 1.1.7 with
   `scripts\deploy-upgrade.ps1 -Package dist\DemandForecast-1.1.7-win64-portable.zip -ExpectedSha256 7D05CE491058BF8F26CB57627F7EDEC26285A8065B7582C7877AEE7A04C2F45B`
   (type `UPGRADE-1.1.7`); then *Xác thực Google* → import the client JSON → *Đăng nhập Google* → *Kiểm tra quyền
   BigQuery* (all six gates pass) → mapping → full-period validation → test D0 v1/v2.
3. **Business owner:** cancelled-order rule for the target, promotion rule (keep manual or approve a criterion), WAPE/bias
   thresholds.
