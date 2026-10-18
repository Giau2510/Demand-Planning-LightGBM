# AGENTS.md - engineering instructions (shared entry point)

Applies to every engineer and coding agent (Claude Code, Codex, others) working in this repository. Tool-specific
additions live in `CLAUDE.md`; detail lives in the documents linked below. If two documents disagree, this file wins for
process rules and the code + database win for facts; fix the document that is wrong.

## 1. What this is

Demand Forecasting: a single-user web app for one Windows PC that forecasts daily customer order quantity per
**SKU x FC/warehouse** with **LightGBM** (horizons 7/15/30 by default). FastAPI + SQLite (WAL) backend, React/TypeScript
frontend, embedded Python in a portable ZIP (no Python/Node needed on the target PC). Data sources, never mixed:
`DEMO`, `MANUAL_IMPORT` (`.xlsx`, one independent batch per import) and `BIGQUERY` (intended primary source,
read-only).

| Topic | Document |
|---|---|
| Architecture, modules | [docs/KIEN-TRUC.md](docs/KIEN-TRUC.md) |
| Data model, lifecycle, invariants, timezone | [docs/data/DATA-MODEL.md](docs/data/DATA-MODEL.md), [docs/data/DATA-DICTIONARY.md](docs/data/DATA-DICTIONARY.md) |
| Storage locations, storage.json | [docs/LUU-TRU.md](docs/LUU-TRU.md) |
| BigQuery, OAuth, SQL sources, D0 | [docs/BIGQUERY.md](docs/BIGQUERY.md) |
| Operations, backup, upgrade, rollback | [docs/VAN-HANH.md](docs/VAN-HANH.md), [docs/TRIEN-KHAI-1.1.6.md](docs/TRIEN-KHAI-1.1.6.md) |
| Scheduler | [docs/SCHEDULER.md](docs/SCHEDULER.md) |
| Model and metrics | [docs/MO-HINH-VA-CHI-SO.md](docs/MO-HINH-VA-CHI-SO.md) |
| Agents, model routing, budgets, checkpoints | [docs/agents/GOVERNANCE.md](docs/agents/GOVERNANCE.md) |
| Resume state of the current batch | [docs/CHECKPOINT.md](docs/CHECKPOINT.md) |
| Git / GitHub: what is versioned, commit, push, sync | [docs/GITHUB_WORKFLOW.md](docs/GITHUB_WORKFLOW.md) |
| Development, QA, release, artifact and backup retention | [docs/PHAT-TRIEN-QA-PHAT-HANH.md](docs/PHAT-TRIEN-QA-PHAT-HANH.md) |
| VPS deployment (Linux, prepared, not deployed) | [docs/TRIEN-KHAI-VPS.md](docs/TRIEN-KHAI-VPS.md) |
| Web UI design system (tokens, icons, components) | [docs/UI-DESIGN-SYSTEM.md](docs/UI-DESIGN-SYSTEM.md) |
| Forecast & actual history (D+1 storage, session choice, actual status, KPI) | [docs/LICH-SU-FORECAST.md](docs/LICH-SU-FORECAST.md) |
| Version history | [CHANGELOG.md](CHANGELOG.md) |

## 2. Inspect before changing

1. Read the relevant code, tests, migrations and the latest report in `reports/` before editing. Verify any value
   given in a prompt (paths, versions, hashes, table names) against the machine; prompts can be stale.
2. The source is a Git repository (private GitHub `Giau2510/Demand-Planning-LightGBM`, branch `main`; no CI). Commit and
   push only as described in [docs/GITHUB_WORKFLOW.md](docs/GITHUB_WORKFLOW.md); runtime data, backups, checkpoints,
   reports and packages stay outside Git. Before a large change, still save a checkpoint ZIP of the touched source under
   `checkpoints/` and record it in `docs/CHECKPOINT.md`.
3. Live state to check before any operational step: running process (`app.cli serve` command line) and
   `GET http://127.0.0.1:8765/api/health`; `%LOCALAPPDATA%\Programs\DemandForecast\current.txt`;
   `%LOCALAPPDATA%\DemandForecast\storage.json` (hash); active jobs (`/api/jobs`); next scheduler slot
   (D0 08:00-18:00 every 2 h, D-1 from 01:00, training 07:00, 1.2.6 end-of-day forecast backup 23:55 and actual close
   23:59, Vietnam time; defaults - the installation may have saved other times).

## 3. Coding conventions

* Match the surrounding code: comment density, naming, idiom. Minimal, evidence-based changes; no rewrites to fit a
  template.
* Python 3.14, FastAPI, Pydantic v2. User-facing errors are `AppError(<CODE>)` with bilingual texts in
  `backend/app/messages.py`. Settings changes go through `settings_service` (validated, history kept).
* Business dates are Vietnam calendar dates (Asia/Ho_Chi_Minh); stored timestamps are UTC ISO-8601 (`timeutil`).
  "Newest first" SQL must add `rowid DESC` as tie-breaker (timestamps have one-second resolution).
* PowerShell scripts (`scripts/*.ps1`) must be **ASCII only** (Windows PowerShell 5.1 reads them as ANSI).
* Python text-mode writes on Windows turn LF into CRLF; preserve each file's line endings when patching.
* New scripts that must ship in the package are added to the explicit list in `scripts/build-package.ps1`.

## 4. Data integrity (highest priority)

* The live DB (`<data>\db\app.db`), models, backups, `storage.json` and the user's settings/batches/forecasts are user
  data. Never delete, reset, replace, truncate or "fix" them to make something pass.
* Never run write tests, migrations, restores or E2E that writes against the live data. Use a **copy** made with the
  SQLite backup API (source opened `mode=ro`) and an isolated `LOCALAPPDATA` + `DF_DATA_DIR`; set
  `DF_DISABLE_SCHEDULER=1`. Read-only checks on the live DB: `python -m app.cli data-check`, `storage-verify`,
  `storage-inventory`, `/api/*` GET.
* Schema changes: new ordered file `backend/app/migrations/000N_<name>.sql`, additive only unless separately approved;
  tested on a copy of the real DB with before/after row counts, key counts and `data-check`; backup + rollback plan
  first. Never add a constraint before checking existing data for violations; report violations, never delete or merge
  silently.
* Each `.xlsx` import is an independent batch; replacing/deleting touches only the selected batch. CSV is not a
  substitute for the Excel workflow.
* Never convert missing values to zero without an established business rule; distinguish invalid rows from zero demand.
* Model input is the data window (`data_policy.window_start_date` .. yesterday, Vietnam time); never read data outside it
  for training/backtest/forecast, never delete stored data because it is outside it.
* A model in use is never replaced automatically: candidates wait for an explicit promotion until the business approves
  a promotion rule. Do not invent WAPE/bias thresholds or promotion criteria.
* BigQuery is read-only for this app: dry-run first, `maximum_bytes_billed` cap, no DML/DDL.
* Do not change `storage.json`, the storage id, the DB path or the active data source (the user changes it in the UI).
  Do not run `app.cli storage-repair --apply`.

## 5. Security and secrets

* Never create, fake, hardcode, print or log OAuth client secrets, refresh/access tokens, service-account keys or
  passwords - not in code, tests, logs, reports, configuration or chat. Never ask a user for them in conversation.
* Secrets live only in Windows Credential Manager (per Windows user) via `bq/secret_store.py`; settings hold the client
  ID only. Tests use `MemoryStore`.
* Do not change IAM, enable Google APIs, or use another person's credentials. Credentials of one Windows account are
  not available to another (the app runs as the logged-in user).
* Reports and diagnostics contain ids, counts and hashes only.

## 6. Verification (run what applies; record exact results)

```powershell
cd backend;  ..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider   # backend
cd frontend; npm test; npm run typecheck; npm run build                      # frontend
powershell -ExecutionPolicy Bypass -File scripts\run-tests.ps1               # both, logged
```

* Read-only checks of the installation: `python -m app.cli data-check` (data invariants) and `python -m app.cli bq-check`
  (Google sign-in + BigQuery gates for the Windows account that runs it; prints no secret).
* Lint is **not configured**: report it as "not configured", never as passed.
* Never weaken or delete a test to make it pass; a flaky test is a bug to explain.
* Label every result by kind: unit / integration with fakes / isolated install / DB copy / real external service.
  Mocked OAuth, fake BigQuery clients, DuckDB transpilation and synthetic data are **not** real integration evidence.
* Packages: `scripts\release.ps1` (clean commit -> QA -> `scripts\build-package.ps1` -> verification) ->
  `dist\<name>.zip` + `.sha256` + manifest; identity = version + commit + source fingerprint (`BUILD-INFO.json`); the
  same sources are never rebuilt and an existing package is never silently replaced. Linux VPS artifact:
  `scripts\vps\build-vps-artifact.ps1`. Old artifacts: `scripts\prune-artifacts.ps1` (dry run unless `-Apply`).
  Verify contents (no data, no credentials, no `__pycache__`), install in an isolated `LOCALAPPDATA` on a DB copy,
  test upgrade and rollback. Build artifacts only to release, test packaging or deploy.

## 7. Release and deployment

* Upgrades of the real installation use `scripts\deploy-upgrade.ps1 -Package <zip> -ExpectedSha256 <sha>` (prechecks,
  online backup, typed confirmation `UPGRADE-<version>`, install, post-checks, transcript). Run `-CheckOnly` first.
  Rollback: `scripts\rollback-version.ps1 -To <version>` (refuses when the DB schema is newer than the target).
* Deploy only with the user's explicit authorization for that batch, outside scheduler slots, with no active job, and
  never bypass the script's confirmation.
* Production BigQuery and the D0 BigQuery schedule stay OFF until real OAuth, IAM, schema, data quality, SQL
  correctness and job idempotency are verified with evidence.

## 8. Prohibited without explicit, specific approval

Deleting/replacing the live DB or backups; destructive or incompatible migrations; writing to BigQuery; changing IAM;
enabling D0/BigQuery production; committing/pushing (never force-push or rewrite history); installing over the running version outside
an authorized deployment; stopping the running app outside a deployment/rollback; editing files under
`%LOCALAPPDATA%\DemandForecast` or `<data>`.

## 9. Agents, models and budgets

Follow [docs/agents/GOVERNANCE.md](docs/agents/GOVERNANCE.md): one orchestrator, at most two specialists at a time,
read-only reconnaissance agents, module ownership for edits, tiered model routing with no silent escalation, bounded
retries, written task contracts and checkpoints.

## 10. Definition of Done

User data preserved (evidence: hashes/counts/`data-check` before and after); tests and builds run with recorded
results; new behaviour covered by tests; documentation and CHANGELOG updated; final diff reviewed (only intended
files changed, PS1 ASCII, no secrets); external verifications either done for real or explicitly marked BLOCKED.

## 11. Final report (in `reports/`)

One of `READY_FOR_PRODUCTION`, `READY_FOR_EXTERNAL_SETUP`, `BLOCKED_DATA_SAFETY`, `BLOCKED_EXTERNAL_SETUP`,
`BLOCKED_TEST_FAILURE`; work done; changed files; test results with counts and kind; deployment status with versions,
hashes and backup paths; data findings; external-integration status (real vs mocked); remaining blockers; the smallest
next action and who must take it. No secrets.
