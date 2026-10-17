# Batch checkpoint — Demand Forecasting Web App

Khi tiếp tục phiên mới: đọc file này → `scripts\check-env.ps1` → `scripts\run-tests.ps1` trước khi sửa tiếp.
Thư mục **không phải git repository** (chưa `git init`, không có commit nào).

| Checkpoint | Trạng thái | Ghi chú |
|---|---|---|
| A — Discovery & baseline | DONE | Repo trống lúc bắt đầu. Python 3.14.7, Node 24.18. LightGBM 4.7.0 (wheel pip). |
| B — Core data & import | DONE | SQLite + migration 0001, settings có lịch sử, validation dùng chung, Excel import/lô độc lập/thay thế/xóa, DEMO. |
| C — Forecast engine | DONE | Feature không rò rỉ, LightGBM đệ quy, dự phòng, backtest walk-forward, WAPE/MAE/bias/MAPE, quality gate, publish bất biến. |
| D — UI & admin | DONE | React + TS, 13 trang, song ngữ, glossary, nhãn nguồn. |
| E — Scheduler & BigQuery | DONE (BigQuery thật: BLOCKED_EXTERNAL_DEPENDENCY) | runner (lock/idempotency/retry/timeout), catch-up, D-1/D0; connector test bằng fake client. |
| F — Packaging & verification | DONE | Gói portable có Python nhúng: `dist\DemandForecast-1.0.0-win64-portable.zip`; install/upgrade/backup/restore đã chạy thử. |

## Kết quả kiểm thử gần nhất (2026-10-14)

| Bộ test | Lệnh | Kết quả |
|---|---|---|
| Backend pytest | `.venv\Scripts\python -m pytest -q backend\tests` | 72 passed |
| Frontend typecheck | `npx tsc -b` (frontend) | OK |
| Frontend vitest | `npx vitest run` | 7 passed |
| Frontend build | `npx vite build` | OK |
| E2E HTTP (venv, start.ps1) | `python scripts\smoke_test.py --base http://127.0.0.1:8799` | 19 passed |
| Sau restart | `... --phase after-restart` | 4 passed |
| E2E trên gói portable (Python nhúng) | như trên, cổng 8797/8798 | 19 + 4 passed |
| install.ps1 (nâng cấp trên dữ liệu có sẵn) | `scripts\install.ps1 -NoShortcuts -NoStart` | OK: backup trước, dữ liệu giữ nguyên (bản cài thử đã gỡ) |
| backup/restore, restore từ chối khi app chạy | `backup.ps1`, `restore.ps1` | OK |
| BigQuery thật | — | BLOCKED_EXTERNAL_DEPENDENCY (chưa có dataset/table/schema/credentials) |

## Còn lại / bước tiếp theo

1. Người dùng cung cấp Dataset ID, bảng, location, schema/grain, quyền (xem `docs\BIGQUERY.md`) → chạy quy trình kích hoạt.
2. Nghiệp vụ phê duyệt ngưỡng WAPE/bias (hiện là giá trị ví dụ).
3. (Tùy chọn) `git init` + commit đầu tiên; chưa làm vì repo chưa có quy ước git.

---

# Batch 2 (v1.1.0) — Fix Demo FK error + storage paths + safe migration

| Checkpoint | Trạng thái | Ghi chú |
|---|---|---|
| A — Inventory | DONE | Bản cài 1.0.0 tại %LOCALAPPDATA%\Programs\DemandForecast\1.0.0; DB thật %LOCALAPPDATA%\DemandForecast\db\app.db (27.8 MB, schema v1, integrity ok, fk_check rỗng, 1 lô DEMO ACTIVE, 93 157 dòng). App 1.0.0 thực tế ĐANG chạy (kiểm kê báo nhầm — xem INCIDENT). Nguyên nhân FK: demo.py UPDATE replaced_by_batch_id trước khi INSERT lô mới. NO_ACTIVE_DATASET: job catch-up khởi động lúc chưa có dữ liệu → FAILED + alert ERROR. |
| B — Fix database | DONE | demo.py: parent-first + invariant checks; migration 0002 (1 ACTIVE DEMO, unique index); runner: NO_ACTIVE_DATASET → SKIPPED; error codes/categories. Tests: test_demo_regression.py |
| C — Path config | DONE | paths.py + storage.json bootstrap, no silent empty DB, diagnostics, storage_migrate.py, scripts migrate/rollback/diagnose. Tests: test_storage.py. 93 backend tests pass. |
| INCIDENT (resolved) | DONE | 10:09: E2E test chạy nhầm trên DB thật (chỉ cô lập DF_STORAGE_CONFIG). Bản 1.0.0 cũng đang chạy (kiểm kê đầu phiên báo nhầm). Đã dừng 1.0.0, khôi phục backup tự động pre-migration-v1 (03:09:28Z) — mọi bảng giống hệt, thay đổi sau mốc này đều do test. Model test cách ly tại backups\quarantine-test-artifacts-20261014. Chặn tái diễn: smoke_test cần --test-data-dir; serve từ chối instance thứ 2 cùng thư mục dữ liệu. |
| D — Migration D:\ | DONE | Cài 1.1.0; storage-migrate SUCCEEDED 20261014_102304 → D:\Buymed\Lightgbm AI\data\runtime (logs\runtime, backups\, reports\). Backup xác minh: backups\backup-20261014-102304-pre-storage-migration.zip. Readonly smoke 7/7. DB cũ: %LOCALAPPDATA%\DemandForecast\db.migrated-20261014_102304. |
| E — UI/launcher/regression | DONE | ErrorBox theo category, DatasetGuide, trang Hệ thống (đường dẫn, chẩn đoán). Gói 1.1.0 build + E2E cô lập 24+4 pass. |
| F — Report | DONE | reports\demandforecast_fix_storage_report_20261014_102811.md |

## 2026-10-14 12:19 — storage.json investigation

storage.json KHÔNG bị mất (có tại %LOCALAPPDATA%\DemandForecast\storage.json, khớp storage-id.json và lịch sử). Đã sửa lỗ hổng tiềm ẩn khi mất file (STORAGE_CONFIG_MISSING, storage-verify, storage-repair, kiểm tra trước trong install.ps1). 99 backend tests pass. Gói dist 1.1.0 đã build lại; bản cài chưa cập nhật. Báo cáo: reports\storage_json_investigation_20261014_121904.md

## 2026-10-14 upgrade run (installed 1.1.0 -> rebuilt 1.1.0 with storage fixes)
- [x] CLI storage-repair: dry-run default, --apply to write (+test). install.ps1: abort if program files still in use. Package rebuilt, hash-verified vs source.
- [x] pre-upgrade checks + verified backup (backups/backup-20261014-135327-cli.zip, ...-142806, ...-144428)
- [x] upgrade via install.ps1 (3 cycles: initial, +BOM/marker fixes, +in-use guard fix); installed == package
- [x] post-upgrade checks (verify ok, readonly smoke 7/7, data identical) + isolated scenarios 20/20 + 102 backend / 9 frontend tests
- [x] report: reports/upgrade_storage_fix_report_20261014_144908.md

## 2026-10-14 batch v1.1.1 (explainability, job status, horizons, intraday, excel i18n, algorithm docs)
- [x] A inventory (root cause horizon: run 08:06Z has [7]; setting -> [7,15] at 08:10Z)
- [x] B backend (migration 0003, progress.py, pipeline stages+extend_forecast, explain.py, intraday.py, methods.py, export_i18n.py) — 102 old + 16 new tests pass
- [x] C frontend (ui.tsx components, Results, ExplainPanel, Dashboard, Jobs, Methodology + algorithms.ts, i18n, css) — tsc ok, 19 vitest pass
- [x] D docs (MO-HINH-VA-CHI-SO, SCHEDULER, HUONG-DAN-SU-DUNG, VAN-HANH upgrade 1.1.0->1.1.1)
- [x] E tests 118 backend + 19 frontend, tsc, build; package dist/DemandForecast-1.1.1 (sha256 52A79792…); isolated fresh 24+30, upgrade-on-copy 13, rollback 2, readonly real 7 — NOT installed on running app
- [x] F report reports/demandforecast_v111_report_20261014_162031.md (THANH CONG CO DIEU KIEN)

## 2026-10-14 batch nghiem thu 1.1.1 tren may that
- [x] Preflight read-only: 1.1.0 idle (no running job, scheduler inflight empty), storage.json sha256 8D79DBDD..., marker storage_id 6cff0821634b0447, real DB facts saved (schema 2, 1 run 588 rows sum 10395.456, ACTIVE DEMO-20261014080556-5342EB)
- [x] Pre-install acceptance on DB copy (source, port 8879, browser E2E via Chrome CDP): found + fixed: Excel times/dates not localised (format v3), job finish time missing, rounding rule missing in explain, tooltip closed immediately on touch, Results page reload loop after extension ("Dang tai..."), algorithm page groups/Tweedie/jobs entry/method examples
- [x] Tests: backend 119, frontend 21, tsc, build; E2E on copy 48/48
- [x] Rebuild package 1.1.1 sha256 9F53FF65...8C5B (old build1 zip renamed *-build1-superseded*, never installed); isolated fresh 24+30, upgrade 13
- [x] Backup backups/backup-20261014-173421-manual.zip verified -> installed 1.1.1 17:35 (schema 3, storage unchanged) -> E2E real 46/46 -> 5a no double count (real read-only 9/9, test, copy) -> report reports/demandforecast_v111_acceptance_20261014_174000.md
- [ ] Not yet observed: scheduler 1.1.1 automatic slot (D0 18:00) on the real machine

## 2026-10-14 batch fix 1.1.2 (number/date formats, dated history, method names in Excel)
- [x] Root causes + fixes (formatters, DateInput, explain history in_calc, export_i18n v4, snapshot/error-report i18n, method registry labels)
- [x] Tests: backend 126, frontend 31, tsc, build; E2E on DB copy 75/75 (1st run aborted: copy inherited MANUAL_IMPORT source set via UI at 18:29 VN; script fixed fail-fast)
- [x] Package dist/DemandForecast-1.1.2 sha256 1093BDA1...AB57; isolated fresh 24+30, upgrade 13
- [x] Installed 1.1.2 on real 22:36 (backup backups/backup-20261014-223619-manual.zip verified; no migration); read-only E2E real 50/50
- [x] Report reports/demandforecast_v112_fix_report_20261014_224500.md

## 2026-10-15 batch 1.1.3 (forecast explainability, history export, quality metrics, training explanation)
- [x] Verified from code: tweedie/log link, TreeSHAP pred_contrib, clip>=0, round 4 at publish; no validation/early stopping; one shared model
- [x] feature_catalog.py (33 features), explain chain + history weekday/used_by + quality sums, training_explain.py, history/backtest-points Excel
- [x] Tests: backend 137, frontend 36, tsc, build; E2E copy 86/86; package 1.1.3 sha256 5EA4A328...64BE; iso fresh 24+30, upgrade 13
- [x] Installed 1.1.3 on real 2026-10-15 00:11 (backup backups/backup-20261015-001048-manual.zip verified; no migration); read-only E2E real 60/60
- [x] Report reports/demandforecast_v113_explainability_report_20261015_001500.md

## 2026-10-15 batch 1.1.4 (auditable TreeSHAP trace)
- [x] Preflight: real 1.1.3, source DEMO, schema 3, no jobs; pre-change backup backups/backup-20261015-003833-manual.zip verified
- [x] Verified against LightGBM v4.7.0 source (tree.cpp/tree.h downloaded to scratchpad lgb_src): base value = sum of tree ExpectedValue (leaf_count/root count, bagged), not the plain training mean
- [x] ml/treeshap_trace.py (exact port, bit-identical to pred_contrib on the real model), ml/shap_audit.py (reconciliation, cache, limits), API shap-trace(+tree, xlsx, csv), UI ShapTrace.tsx (levels A/B/C)
- [x] Example traced: FCR-20261014111845-8B81D1 DEMO-SKU-001 FC-HCM 14/10/2026 zero_share_28 +0.8394 / roll_mean_14 +0.3276 / roll_mean_7 +0.2008 VERIFIED
- [x] Full tests (backend 151, frontend 39, tsc, build), E2E copy 99/0, iso fresh 24+33 / upgrade 16, all PASS
- [x] Package dist\DemandForecast-1.1.4-win64-portable.zip SHA256 D4E66387EACB867DAFFBD74C06B36F0F9F6494F91959FD81B0038E87DB4538F7, extracted release\DemandForecast-1.1.4
- [x] Backup backups\backup-20261015-012210-manual.zip (verified), installed 1.1.4 at 01:22 15/10 (pid 27956), no migration, storage.json/source/data unchanged
- [x] Read-only E2E on real 1.1.4: 73/0; report reports\demandforecast_v114_treeshap_audit_report_20261015_013000.md
- Rollback: 1.1.4\Stop.bat then %LOCALAPPDATA%\Programs\DemandForecast\1.1.3\Start.bat (schema 3, no DB restore)

## 2026-10-15 batch 1.1.5 (BigQuery demand_planing_lightgbm + feature registry)
- [x] Phase A (read-only): real app 1.1.4 pid 27956, source DEMO, schema 3, storage.json 8D79DBDD...E047, storage_id 6cff0821634b0447, no jobs; facts scratchpad facts115_start.json
- [x] BigQuery settings on real app (saved by user via UI 15/10 09:19/11:10 VN): gold_buymed_vn2.demand_planing_lightgbm, asia-southeast1, partition created_date, mapping EMPTY, production off
- [x] BLOCKER: no Google credentials on this machine (no ADC file, no gcloud, no GOOGLE_APPLICATION_CREDENTIALS); user's own auth check 14/10 23:16 -> BQ_AUTH_MISSING. Real BigQuery NOT verifiable here.
- Plan (no DB migration; new settings keys are top-level so 1.1.4 ignores them on rollback):
  - [x] settings: reference_mapping (product_id,item_code,outbound_qty,order_status,sales_price,price_after_discount,seller_code,sku_status,open_date,open_hours,open_days), history_start_date=2026-01-01, exact_duplicate_policy BLOCK|KEEP|DROP_EXACT, max_retries
  - [x] connector: suggested mapping preset (no auto-save), order_date must be DATE/DATETIME, full-range validate_source (reasons, sums reconciliation, duplicates, missing days, categories, reference completeness, outbound vs demand), error codes (AUTH_EXPIRED, TIMEOUT, QUOTA, UNAVAILABLE, SCHEMA_CHANGED, LOCATION), bounded retry, daily sql with reasons + duplicate policy + history floor; d1 sync reconciles inserted sum
  - [x] feature registry (ml/feature_registry.py) + data-availability gating of PRICE/DISCOUNT/PROMOTION (feature_discount None = legacy follows price), feature_set_version + lineage in training_runs.feature_config_json; BIGQUERY training requires validation for current mapping hash
  - [x] UI: BigQuery validation card, Mapping reference fields + suggestion, Features page, lineage card
  - [x] tests, docs, package 1.1.5, iso fresh/upgrade + rollback-to-1.1.4 test, backup, install, read-only E2E, report
- [x] SQL logic executed: scratchpad sqlh (sqlglot->DuckDB, synthetic rows) 27/27 + app post-processing 18/18
- [x] Tests: backend 183 (32 new test_v115_bigquery_features.py), frontend 42 (3 new v115.test.tsx), tsc, build; log logs/development/tests_20261015_114959.log
- [x] Docs: BIGQUERY.md rewritten, MO-HINH-VA-CHI-SO.md registry + lineage, HUONG-DAN; version 1.1.5
- [x] E2E copy 113/0; package dist/DemandForecast-1.1.5-win64-portable.zip SHA256 C122B0757654D8EEA19315BC4F30E2C9066016D70F3F5EBB378E35113076AA56
- [x] iso fresh 24+37, upgrade 20, rollback prep 3 + rollback-to-1.1.4 on same data 7 (no DB restore)
- [x] Backup backups/backup-20261015-121828-manual.zip verified; installed 1.1.5 12:18 15/10 (pid 17220), no migration, storage/source/data/model unchanged
- [x] Read-only E2E real 82/0; report reports/demandforecast_v115_bigquery_feature_registry_report_20261015_122500.md
- [ ] OPEN: real BigQuery verification needs Google credentials on this machine (gcloud auth application-default login), then: auth -> connection -> schema -> suggest mapping -> validate full period
- Rollback: 1.1.5\Stop.bat then %LOCALAPPDATA%\Programs\DemandForecast\1.1.4\Start.bat (schema 3, no DB restore)

## 2026-10-15 batch 1.1.6 (Google OAuth in app, SQL editor history/D0, independent sync jobs) - NOT installed on the real app (per request)
- [x] Preflight: real 1.1.5 pid 17220 (owner LOG-PC\Giau Vo), source DEMO, schema 3, storage.json 8D79DBDD...E047, storage_id 6cff0821634b0447; not a git repo
- [x] Root cause of "no Google credentials": backend runs as Giau Vo -> looks for ADC in C:\Users\Giau Vo\AppData\Roaming\gcloud (absent); ADC exists only in the Administrator profile (no access from Giau Vo); gcloud not on PATH
- [x] Backup backups/backup-20261015-121828-manual.zip restore drill with app restore_backup() into isolated folder: integrity ok, schema 3, no migration, model sha match, only audit_log differs
- [x] Source checkpoint checkpoints/source-1.1.5-before-1.1.6-20261015-133452.zip (+ manifest)
- [x] Code: bq/oauth.py (loopback + state + PKCE, Credential Manager), bq/secret_store.py, bq/sql_guard.py, bq/sql_sources.py, connector (table/SQL relation, key gate, D0 SQL path, dry-run validation), sync (snapshot, backfill, new/updated, D0 retry idempotent), api/bq_routes.py, UI GoogleAuth + SqlSources pages
- [x] Tests: backend 214, frontend 45, tsc, build (logs/development/tests_20261015_135912.log); D0 SQL DuckDB logic 10/10; E2E copy 122/0
- [x] Package dist/DemandForecast-1.1.6-win64-portable.zip SHA256 E2CFB67D3BBF3D0B7E4E873160A2295E21E0295FD8C40ED870504C5CAD66B3FF (first build interrupted at session end: orphan process stopped, outputs removed, clean rebuild); iso fresh 24+43, upgrade 26, rollback prep 4 + rollback-to-1.1.5 7
- [x] Report reports/demandforecast_v116_oauth_sql_scheduler_report_20261015_145500.md - status BLOCKED (no Google creds for Giau Vo, no OAuth client); diff checkpoints/diff-1.1.5-to-1.1.6.patch
- [ ] OPEN (user/IT): OAuth Desktop client + IAM, or gcloud ADC login as Giau Vo; then validate history + dry-run D0 v1; decide when to install 1.1.6


## 2026-10-15 batch "1.1.5 -> 1.1.6 production readiness" (no install, no stop of 1.1.5, no real-DB migration)
- [x] State: 1.1.5 pid 17220 (Giau Vo) healthy; no Git; still no Google creds for Giau Vo; 1.1.6 build1 zip E2CFB67D...B3FF
- [x] A: live DB copy ok (schema 3, 20 tables, fk 0, no missing migration); 20 backups verified (zip, sqlite, model load); new official backup backup-20261015-153315-manual.zip (SHA 59F18021...) restore drill ok; installer review: 3 issues (app left stopped on abort, current.txt before migrate, no guard data-inside-program-dir)
- [x] B: access gates (auth/API+dataset/location/table/query job/schema), BQ_API_DISABLED, UI gates + states, D0 schedule switch default OFF
- [x] C: real BigQuery BLOCKED_EXTERNAL_SETUP (no creds for Giau Vo, no OAuth client)
- [x] D: proposed D0 SQL v2 seeded inactive (DuckDB compare 5/5); installer fixes + deploy-upgrade.ps1 + rollback-version.ps1 + docs/TRIEN-KHAI-1.1.6.md
- [x] E: tests backend 224 / frontend 46 / tsc / build (logs/development/tests_20261015_154325.log); E2E copy 125/0; build script fixes (pycache after -B verification, deploy scripts packaged, manifest + .sha256); build1 kept as superseded; build2/3 discarded (missing/old deploy scripts)
- [x] iso build3: fresh 24+43, upgrade 26 + prep 4 + rollback 7; deploy scenario with source scripts 12/12 (found+fixed: Compress-Archive backslash entry names)
- [x] F: build4 dist/DemandForecast-1.1.6-win64-portable.zip SHA256 A2E0345CEB654A281557BA1DA825E31E4DFD0A1DCA6C851166B9C144B3A19561 (+manifest, .sha256); packaged deploy scenario 12/12; real deploy -CheckOnly PRECHECK OK (nothing changed)
- [x] Report reports/demandforecast_v116_production_readiness_report_20261015_171500.md - status READY_FOR_EXTERNAL_SETUP (real OAuth/BigQuery BLOCKED_EXTERNAL_SETUP); 1.1.6 NOT installed

---

# Batch 1.1.6 deployment + data architecture + engineering foundation (2026-10-15 17:47-18:20)

| Phase | Status | Evidence |
|---|---|---|
| A - Inventory | DONE | 1.1.5 running (pid 17220), storage.json 8D79DBDD...E047, 20 backups, package SHA A2E0345C...9561 = expected, package == source (drift 0) |
| B - Backup & deploy safety | DONE | real `deploy-upgrade.ps1 -CheckOnly` OK; backup-20261015-180114-manual.zip restored in isolation: integrity ok, schema 3, model hashes equal |
| C - Data architecture | DONE | docs/data/DATA-MODEL.md, docs/data/DATA-DICTIONARY.md (from PRAGMA of a DB copy) |
| D - Validation + non-breaking fixes | DONE (source only) | `app.cli data-check`; `rowid DESC` tie-break in 23 queries; checkpoint `checkpoints/source-1.1.6-before-unreleased-20261015-175329.zip` |
| E - Engineering foundation | DONE | AGENTS.md, CLAUDE.md, CHANGELOG.md, docs/agents/GOVERNANCE.md, .claude/settings.json (deny verified live), .claude/agents/* |
| F - Deploy 1.1.6 | DONE | 18:01:39-18:05:42, exit 0; log `logs/runtime/deploy-20261015-180140.log`; 1.1.6 pid 36892; DB unchanged except 2 audit rows (backups) |
| G - OAuth / BigQuery real | BLOCKED_EXTERNAL_SETUP | real access check on a DB copy: gate `auth` FAIL BQ_AUTH_MISSING (no OAuth client, no ADC for LOG-PC\Giau Vo) |
| H - D0 SQL | BLOCKED_EXTERNAL_SETUP (logic only) | v1 verbatim + v2 proposal, none active, schedule OFF; DuckDB logic 10/10 + 5/5 (synthetic) |
| I - Regression / rollback | DONE | see report; `rollback-version.ps1 -To 1.1.5 -CheckOnly` OK; read-only E2E on the real app 90/0 |
| J - Report | DONE | reports/demandforecast_v116_deployment_data_architecture_report_20261015_182000.md |

Next step: Google Cloud admin creates the OAuth Desktop client + IAM (see the report), then the user signs in and runs
"Kiem tra quyen BigQuery". Unreleased source changes go into the next package (1.1.7) after review.

---

# Batch 1.1.7 - 2026 data window, tie-break review, backtest span, incumbent protection, OAuth completion (started 2026-10-15 22:20)

Source checkpoint before any change: `checkpoints/source-1.1.6plus-before-1.1.7-20261015-222605.zip`
(backend/app, backend/tests, frontend/src, scripts, docs, root docs). Live install 1.1.6 is NOT touched by this batch.

| Work item | Status |
|---|---|
| W1 data window 2026-01-01 .. yesterday (VN) in pipeline, quality report, panel rebuild, BigQuery read range | DONE |
| W2 newest-first tie-break: per-table review + regression tests | DONE |
| W3 backtest span 6-12 months (adaptive folds) | DONE |
| W4 incumbent protection (candidate review, comparison, manual promotion) | DONE |
| W5 OAuth/BigQuery: real auth gate, error classes, client JSON import, bq-check CLI, in-app remediation | DONE (code); real Google access BLOCKED (no OAuth client/IAM) |
| W6 D0 v2 review (no activation) | DONE (no SQL change; review in report) |
| W7 version 1.1.7, package, isolated install/upgrade/rollback | DONE: dist\DemandForecast-1.1.7-win64-portable.zip SHA-256 7D05CE491058BF8F26CB57627F7EDEC26285A8065B7582C7877AEE7A04C2F45B; isolated 1.1.6->1.1.7->1.1.6 on a live-DB copy 20/20 |
| W8 docs, report | DONE: reports/demandforecast_v117_release_report_20261015.md (status CODE READY - GOOGLE ACCESS BLOCKED) |

Batch closed 2026-10-15 23:25. Tests: backend 253/0/0, frontend 48/0, typecheck+build OK. Live install still 1.1.6 (untouched). Next: Google admin (OAuth Desktop client + IAM), then the user installs 1.1.7 with deploy-upgrade.ps1.

---

# Batch 1.1.8 - separate D-1 / D-0 / training schedules (2026-10-15 23:59 - 2026-10-16 01:00)

Source checkpoint before any change: `checkpoints/source-1.1.7-before-1.1.8-20261016-000339.zip`. Live install 1.1.6 untouched.

| Step | Status | Evidence |
|---|---|---|
| Audit scheduler/UI/API (10 questions) | DONE | report section 1: jobs already separate, ONE global switch, UI scattered, enabling D0 mid-day caused a catch-up run |
| Backend: per-flow switches, flows.py, schedule API, runner/scheduler gates, enable time | DONE | backend 275/0/0 |
| Frontend: page /schedules (3 cards), links from Config/Jobs/SQL | DONE | frontend 52/0, typecheck + build OK |
| E2E on a DB copy with the scheduler running | DONE | 17/17, 0 jobs created, restart keeps the saved state |
| Package 1.1.8 + isolated 1.1.6 -> 1.1.8 -> 1.1.6 | DONE | SHA-256 0DFDEC86042767AB5E8A8545C990BEF5D2E8B87AB465A970F1642D4DB9F15EE0; 25/25 |
| Report | DONE | reports/demandforecast_v118_schedules_report_20261016.md |

Next: the user installs 1.1.8 when convenient (deploy-upgrade.ps1, UPGRADE-1.1.8); D-1 / D-0 stay OFF until switched on
on the Data schedules page.

---

# Deployment 1.1.8 + D-0 DEMO test (2026-10-16 08:29 - 10:05)

Authorized by the user (two pasted batches: controlled deployment; manual D-0 DEMO run on test data).

| Step | Status | Evidence |
|---|---|---|
| Prechecks (read-only), deploy-upgrade -CheckOnly | DONE | PRECHECK OK 08:31:15; no job in flight; next slot 10:00 |
| Deploy 1.1.6 -> 1.1.8 | DONE | exit 0, logs\runtime\deploy-20261016-083136.log; backups backup-20261016-083136-manual.zip, backup-20261016-083328-cli.zip (verified) |
| Post-checks: DB, storage, counts, models, backups, UI | DONE | only audit_log +1; UI 15/15 |
| D-0 DEMO switched on via the UI | DONE | 09:16:47, times 08-18 every 2 h unchanged, UI 14/14 |
| Restart keeps the configuration | DONE | pid 18608, no job at startup |
| Manual D-0 run via 'Run once now' | DONE | JOB-20261016022310-A7374B -> SNP-20261016022310-BE0AA7 (151 lines, 53 keys), source check 20/20 |
| Isolated dedupe + 1.1.8 tests | DONE | 26/26 |
| First scheduled D-0 slot after the upgrade (10:00) | DONE | JOB-20261016030003-935A2C -> SNP-20261016030004-13CC83 (209 lines, 59 keys), source check 20/20; next 12:00 |
| Report Part II | DONE | reports/demandforecast_v118_schedules_report_20261016.md (original kept in checkpoints/) |

Open: UI does not auto-refresh after 'Run once now' (display only). Rollback not needed (rollback-version -CheckOnly OK).

---

# Audit 1.1.8 + GitHub post-push (2026-10-16 11:14 - 11:45)

Read-only audit with two read-only reviewers (data/ML; API/UI/ops/security, T2). Source checkpoint before edits:
`checkpoints/source-1.1.8-before-audit-fixes-20261016-112638.zip`. Nothing committed or pushed; live DB, models,
settings, schedules and backups untouched (BigQuery checks ran on a DB copy in the scratchpad).

| Step | Status | Evidence |
|---|---|---|
| Git local/remote, ignore rules, eol, history secret scan | DONE | HEAD = origin/main d87c315; 31/31 ignored, 11/11 kept; 0 real secrets |
| Fresh clone (C:) -> npm ci/test/build, new venv + pytest | DONE | frontend 52/52; backend 274 + 1 drive-D test assumption (fixed) |
| Real BigQuery read-only (app code path, ADC) | DONE | 5/6 gates pass (mapping not saved); profile ~3.3 GB scanned |
| Safe fixes + tests | DONE | sync empty-read guard, schedules outcome/run follow-up, test_storage drive, docs |
| Regression | DONE | backend 279, vitest 55, typecheck + build OK |
| Report | DONE | reports/demandforecast_audit_v118_20261016.md |

Open: business decisions R1 (duplicate keys), R2 (complete day), R3 (D-1 completion/time), R5 (promotion with daily
data), R13 (gate thresholds); the fixes need a new release before BigQuery production.

# BigQuery ingest: exact-duplicate gate, report, dry run (2026-10-16 13:00 - 13:45)

Source checkpoint before edits: `checkpoints/source-1.1.8-before-bq-ingest-20261016-130203.zip`
(SHA-256 `1C39EB27DF7BB1C355F4863DE639DFDCB69F89977F14BC77D7B8DD453B08153F`). R1 decided by the business: key repeats
are summed, only exact duplicates block. Nothing committed/pushed/deployed; live DB, settings, schedules untouched.

| Step | Status | Evidence |
|---|---|---|
| Gate + report + dry run + output checks (backend), BigQuery page (frontend) | DONE | `bq/dup_report.py`, `connector.py`, `sync.py`, `BigQuery.tsx` |
| Tests | DONE | backend 298 passed + 2 opt-in skipped; vitest 61; typecheck + build OK; 4/4 mutants killed |
| Real BigQuery, inline rows (SQL semantics) | DONE | `test_bq_real_semantics.py` 2/2, 0 bytes |
| Real BigQuery, real table, DB copy | DONE | 433 groups / 878 rows / 445 extra -> BLOCKED + xlsx; measurement (KEEP, copy) 1,345,228 rows, 41,654,787 |
| Write on the DB copy (simulated run date 15/10) | DONE | full reload 1,345,228 rows / 41,654,787; re-run 13,120 unchanged, totals identical |
| Source freshness 16/10 13:30 | FINDING | no row for 15/10 yet: a D-1 now stops with SOURCE_INCOMPLETE |
| Production write | NOT RUN | needs a release with this code + user actions (docs/BIGQUERY.md section 13) |

# Storage cleanup, release flow, VPS preparation (2026-10-16 13:55 - 15:10)

No source/business change except the Linux branch of `app.cli._pid_alive`. Nothing committed/pushed/deployed.

| Step | Status | Evidence |
|---|---|---|
| Size survey | DONE | project 6,876 MB (dist 3,873, release 2,208, .venv 434, backups 209) |
| Staging / extracted folders vs ZIPs (path + size + CRC32) | DONE | 17 contained -> deleted (4,650 MB); release\1.1.0 = other build |
| Running 1.1.8 / rollback 1.1.6 recoverable | DONE | ZIP = installed (7,115 / 7,106 files); rollback-version -CheckOnly OK |
| Old / superseded / never-installed ZIPs + release\1.1.0 | DONE | list `reports\storage_cleanup_plan_20261016.md`, 1,239 MB deleted |
| After | DONE | 988 MB; DB, models, settings, storage.json, backups, checkpoints, Programs, git unchanged; app 1.1.8 healthy |
| Release tooling | DONE | release.ps1, build-package.ps1 (identity, no duplicate build, no overwrite), prune-artifacts.ps1 |
| VPS kit | PREPARED | scripts\vps\*, docs\TRIEN-KHAI-VPS.md; artifact tested on Windows only; Linux NOT tested |

# BigQuery ingest + local release attempt (2026-10-16 15:00 - 15:30)

User confirmed: 15/10 data added and duplicates fixed at the source. Nothing committed/pushed/deployed; live DB, settings,
schedules untouched (protected-state snapshot identical before/after).

| Step | Status | Evidence |
|---|---|---|
| Version | DONE | source bumped to 1.1.9 (`backend/app/__init__.py`, `frontend/package.json`, CHANGELOG heading) |
| Real BigQuery, fresh DB copy, policy BLOCK | READY | 01/01-15/10: 8,893,414 rows, 0 exact-duplicate groups; 15/10 = 18,992 rows (7-day avg 18,772) |
| Aggregation + reconciliation | DONE | 1,347,346 day x SKU x FC rows, 41,722,635 = source total, 0 excluded |
| Write on the DB copy | DONE | full reload 1,347,346 / 41,722,635; re-run 12/10-15/10 13,345 unchanged; 0 repeated keys |
| QA | DONE | backend 300 passed / 2 skipped; real BQ semantics 2/2; vitest 61/61; typecheck + build OK |
| Release (`scripts\release.ps1`) | BLOCKED | uncommitted tree; needs the user's commit permission |
| Local upgrade, production ingest | NOT RUN | need the 1.1.9 package |
| Pre-commit checkpoint (16:12) | DONE | `checkpoints\source-1.1.9-precommit-20261016-161233.zip` (status, diff, 17 untracked files), SHA-256 `0145A702...3871` |

# Release 1.1.9 + BigQuery production ingest + first real-data training (2026-10-16 16:10 - 17:15)

User authorized: commit/push, release 1.1.9, upgrade, source BIGQUERY, real write, training. Report `reports/demandforecast_v119_production_ingest_training_20261016_171500.md`.

| Step | Status | Evidence |
|---|---|---|
| Commit / push / tag | DONE | `9066427` (43 files, secret scan 0 strong), pushed `main`, tag `v1.1.9` |
| Release | DONE | QA 302 passed (incl. real BQ) + vitest 61 + typecheck + build; `dist/DemandForecast-1.1.9-win64-portable.zip` `F8311492...DD46` |
| Upgrade | DONE | 1.1.8 -> 1.1.9 16:31 (pid 29728), schema 3, backups `backup-20261016-162709-manual.zip`, `-162940-cli.zip` |
| Pre-switch backup | DONE | `backup-20261016-164254-manual.zip` verified (integrity ok, counts = live) |
| BigQuery gates (live app) | DONE | 6 access gates PASS, validation passed, ingest-check READY, 0 duplicates |
| Source switch | DONE | production ON, active source BIGQUERY |
| D-1 load + re-run | DONE | 1,347,346 / 41,722,635; 288/288 days reconciled; re-run 13,345 unchanged; data-check OK (old WARN only) |
| Training | REJECTED | TRN-20261016095451-697A11: WAPE 1.017 / bias 0.399 (gate 0.60 / 0.20); baseline 0.839 / 0.119; not published |
| Schedules | PARTIAL | D-0 OFF (restore refused: SQL_NOT_VALIDATED), D-1 OFF (as before), train ON 07:00 but waits for D-1 |


# 1.2.1 source: D-0 own mapping + real BigQuery validation, training follows today's D-1, read-only remote link (2026-10-17 15:25 - 16:40)

No commit / package / deploy (user's instruction). Production stays 1.2.0. Report `reports/demandforecast_v121_d0_d1_remote_20261017.md`.

| Step | Status | Evidence |
|---|---|---|
| Source checkpoint | DONE | `checkpoints\source-1.2.0-before-1.2.1-d0-remote-20261017-153536.zip` (git archive of HEAD 514c90b) |
| Production backup | DONE | `backups\backup-20261017-153542-manual.zip` (online backup, SHA-256 421AA88F...C200) |
| D-0 code (own mapping, validation with execution, today filter, forecast match) | DONE | `backend/app/bq/d0_feed.py`; tests `test_v121_d0.py` (17, fake client), `test_v121_d0_real_bq.py` (5, real BigQuery) |
| Training follows today's D-1 (scheduled or manual) | DONE | `jobs/flows.py`, `jobs/scheduler.py`; tests in `test_v121_d0.py` |
| Isolated check on a DB copy, real BigQuery | DONE | new D-0 SQL on the D-0 table VALID (8,454 rows, 2,142 series, 48 key repeats); live DB fingerprint unchanged |
| Remote link (Quick Tunnel + read-only proxy) | DONE | two real HTTPS links verified then stopped; tests `test_v121_remote_proxy.py` (43) |
| Handoff ZIP | DONE | `dist\DemandForecast-RemoteAccess-1.2.1-20261017.zip` (SHA-256 7EEC7A1F...558B) |
| Release 1.2.1 / deploy | DONE (16:37-16:58) | owner asked to deploy: train catch-up policy SKIP set first (PUT /api/schedules/train); local commit 94fd17b (no push); package 1BE9E270...4DC7; deploy 16:48-16:52, backups backup-20261017-164813-manual.zip + -165044-cli.zip; data / settings fingerprint unchanged; TRAIN_PUBLISH:2026-10-17 SKIPPED; rollback -To 1.2.0 -CheckOnly OK |
| Remote link (production 1.2.1) | RUNNING | https://volumes-jean-angels-configurations.trycloudflare.com - reads 200, 10 writes 405, 10 admin 403, Edge headless 3 pages 0 errors; changes on every tunnel restart |
| D-0 | WAITING (owner) | not touched: save + validate the D-0 table SQL, choose key policy BLOCK / SUM_ALL |


# 1.2.2 P0: BigQuery end to end, quality gate = assessment, best evaluated candidate (2026-10-17 17:32 - )

Owner's P0 request: the dashboard showed DEMO although the source is BIGQUERY. Link sent to the boss must stay up
(cloudflared / proxy never stopped). Report `reports/demandforecast_v122_p0_bigquery_20261017.md`.

| Step | Status | Evidence |
|---|---|---|
| Root cause | DONE | quality gate was a publish switch: every BIGQUERY run REJECTED (latest TRN-20261017101340-EEDA47, WAPE 0.807 > 0.60, bias 0.058, baseline 0.844) so the BIGQUERY scope had no forecast; Results opened the newest run of any source (DEMO FCR-20261016073246-E18059) |
| Source checkpoint | DONE | `checkpoints\checkpoint-20261017-p0-bigquery-before-1.2.2.zip` (git archive of HEAD b96f895, SHA-256 EAD13D48...AFB4) |
| Code 1.2.2 | DONE | `quality.below_threshold_policy`, `pipeline.select_candidate / assess / promotable`, baseline method, APIs, UI; tests `test_v122_bigquery_policy.py` (14), `v122.test.tsx` (6) |
| Found on production (not changed by Claude) | NOTE | 17:32:20 VN the BigQuery mapping was saved locally (`unit_price` OPTIONAL -> REQUIRED): production mode OFF -> D-1 / new training / D-0 need re-validation + activation by the owner |
| Copy of production + real BigQuery | DONE | "Use this model" on TRN-...EEDA47 -> BIGQUERY forecast 17,125 series in 44.6 s; D-0 table SQL VALID (8,454 rows, 48 key repeats = 39 keys, 0 identical rows, all differ in price); live DB unchanged |
| Release 1.2.2 | DONE | local commit 7053999 (no push); QA 405 (incl. real BigQuery) + vitest 75 + build; package `dist\DemandForecast-1.2.2-win64-portable.zip` SHA-256 7AA7D910...0F95 |
| Rehearsal with a live link | DONE 17/17 | official 1.2.1 on a DB copy + read-only proxy (from the 1.2.1 python) + own Quick Tunnel; deploy-upgrade to 1.2.2: same proxy / cloudflared PIDs, same URL serves 1.2.2, 405 / 403 kept, 502 for ~80 s |
| Deploy production 1.2.1 -> 1.2.2 | DONE 18:53-18:57 | UPGRADE OK; backups `backup-20261017-185319-manual.zip` (+ `-cli`), `backup-20261017-190454-manual.zip`; fingerprint: data + settings identical (audit_log +1); data-check WARN (old DEMO meta only); rollback -To 1.2.1 -CheckOnly OK; storage.json 8D79DBDD unchanged |
| Shared link | KEPT | https://volumes-jean-angels-configurations.trycloudflare.com - proxy 13024 / cloudflared 31076 unchanged; 82 s of 502 during the restart (18:55:48-18:57:10); after: 1.2.2, 10 writes 405, admin 403, Edge headless 4 pages 0 errors |
| Publish BIGQUERY forecast | BLOCKED (permission) | POST promote of TRN-20261017101340-EEDA47 denied by the Claude Code permission classifier; owner clicks "Use this model (below thresholds - with warning)" on Model performance (PC, not the link) |
| D-0 in production | WAITING (owner) | SQL validated on the copy only; production needs: BigQuery production ON again, save + validate the D-0 SQL, key policy decision, controlled run |


# 1.2.3 P0: SOURCE_NOT_READY, BigQuery production, model publish, D-0 / D-1 (2026-10-17 19:25 - )

Owner's P0 request: manual trainings skipped with SOURCE_NOT_READY; finish the real BigQuery flow; link sent to the boss
must stay up; no push. Report `reports/demandforecast_v123_p0_source_not_ready_20261017.md`.

| Step | Status | Evidence |
|---|---|---|
| Root cause | DONE | 17:32:20 mapping save (unit_price OPTIONAL -> REQUIRED) = production mode OFF + new mapping hash; jobs JOB-...121625-661B96 / 121820-57FB9B / 122150-90EEDA skipped in VALIDATING_DATA after ~35 s of fingerprint; Jobs page showed the switch, not the state (ON_NOT_READY) |
| Backup | DONE | `backup-20261017-193147-manual.zip` (SHA-256 29ED178E...75B7) |
| BigQuery access + full validation (production) | DONE | 6/6 gates PASS; validation PASS for hash bc5fcb06327569fb (8,910,595 rows, 41,808,940, 0 excluded) |
| Enable production (official endpoint) | DENIED (classifier) | POST /api/bigquery/activate denied 19:33 |
| Publish TRN-20261017101340-EEDA47 | DONE | "Use this model" (confirm=true) -> FCR-20261017123417-FCC0EB, BIGQUERY, 17,125 series x 15 d, 7-day 624,168, USABLE_WITH_WARNING; shown through the shared link |
| D-0 SQL v3 + SUM_ALL | DONE | VALID on real BigQuery (8,454 rows today only, 48 key repeats = 39 keys, 0 identical, all differ in price) |
| INCIDENT test write to live DB | NOTE | 19:49-19:50 a test lost its isolation (monkeypatch.undo) -> bigquery.production_enabled=true (history 30-32, audit 106-108); revert denied by the classifier; owner chose to keep it ON; conftest fixed |
| Controlled D-0 snapshot | DONE | SNP-20261017125745-3ABB90: 2,142 series, 34,618, only 17/10, all series have a forecast |
| Manual D-1 | DONE | JOB-20261017125803-0ED367: full reload 01/01-16/10, 0 new / 0 updated / 0 removed, hash recorded |
| Code 1.2.3 | DONE | precise SOURCE_NOT_READY, manual training precheck, manual_readiness, flow_states, mapping-save warnings, deactivate keeps source; tests test_v123_source_ready.py (7), v123.test.tsx (5) |
| Release 1.2.3 | DONE | local commit 87f6fce (no push); QA 405 + 7 real BigQuery + vitest 80 + build; package `dist\DemandForecast-1.2.3-win64-portable.zip` SHA-256 39C1DA4A...3410 |
| Rehearsal with a live link | DONE 22/22 | official 1.2.2 on a DB copy + proxy + own Quick Tunnel; deploy to 1.2.3: same PIDs / URL, 502 for 82 s, 405 / 403 kept, deactivate keeps BIGQUERY, manual training 409 SOURCE_NOT_READY with detail and no job (body read with Python), rollback -CheckOnly OK |
| Deploy production 1.2.2 -> 1.2.3 | DONE 20:32-20:37 | UPGRADE OK, app pid 24100; backups `backup-20261017-203230-manual.zip` (SHA-256 25E71FB8...86EF) + `-203501-cli.zip`; fingerprint: data + settings identical (audit +1); data-check WARN (old DEMO meta only); rollback -To 1.2.2 -CheckOnly OK; storage.json 8D79DBDD unchanged |
| Shared link | KEPT | same URL, proxy 13024 / cloudflared 31076 unchanged; 502 for ~87 s (20:35:00-20:36:28); after: 1.2.3, BIGQUERY forecast FCR-...FCC0EB, 10 writes 405, admin 403, Edge headless 4 pages 0 errors |
| Schedules | UNCHANGED | D-1 OFF, D-0 OFF (08-18 every 2 h), training ON 09:00 SKIP; all three flows ready; enabling D-1 / D-0 is the owner's decision |


# 1.2.4 History areas, product names + search, D-1 / D-0 switches (2026-10-17 20:55 - )

Owner request: the two explanation areas were empty, add product name + search, D-1 and D-0 ON with switches on the
Jobs page; link kept, no push. Report `reports/demandforecast_v124_history_names_schedules_20261017.md`.

| Step | Status | Evidence |
|---|---|---|
| Root cause (areas A1/A2) | DONE | fingerprint includes MAX(loaded_at); the manual D-1 of 19:58 rewrote 1,349,388 identical rows -> explain DATA_CHANGED (production API, MEDX.DMTS-SAN-ALP-001 / HN) |
| Proof the data is unchanged | DONE | copy of 19:37 (fingerprint e2385893ed061e39 = TRN-...EEDA47) and live DB: same content hash c47771523275a866 over 1,349,388 rows, 9 model columns |
| Name source | DONE | dim_sku: 298,517 rows = 298,517 distinct sku_code, 0 empty names; ~23 MB per read |
| Code 1.2.4 | DONE | data/identity.py, bq/product_names.py, explain / training_explain / pipeline / sync / routes / export; UI Results, ExplainPanel, Jobs; tests 12 backend + 6 frontend |
| Tests | DONE | backend 417 passed + 7 real BigQuery; vitest 86; typecheck + build OK; live DB untouched (history id 32, newest job unchanged) |
