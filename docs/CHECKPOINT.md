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
| Release 1.2.4 | DONE | local commits addbfb9 + 1750f8d (no push); QA 418 + 7 real BigQuery + vitest 86 + build; package SHA-256 030418A5...1F2D (first build D2A13503... superseded, never deployed) |
| Rehearsal | DONE 34/34 | 1.2.3 on a DB copy + proxy + own tunnel -> 1.2.4: same PIDs / URL; attestation on the copy SAME_CONTENT; names from real BigQuery 9,657/9,657; search, Excel, switches; 405 through the URL; rollback OK |
| Deploy production 1.2.3 -> 1.2.4 | DONE 22:52-22:59 | UPGRADE OK, app pid 35168; backups backup-20261017-225247-manual.zip (SHA-256 7190A546...13E4) + -225648-cli.zip; data + settings identical (audit +1); rollback -To 1.2.3 -CheckOnly OK |
| Shared link | KEPT | same URL, proxy 13024 / cloudflared 31076; 502 for ~130 s (22:56:47-22:58:58); 23/23 link checks, Edge 5 pages 0 errors |
| Production actions | DONE | EEDA47 attested (sha cbd943c0..., SAME_CONTENT); names refreshed 9,657/9,657; explanation OK (33.8 s cold, ~8.5 s next; 7.7 s through the link); D-1 ON (next 18/10 03:00), D-0 ON (next 18/10 08:00); off/on tested; no job started |


# 1.2.5 UI redesign (scope D) + Forecast & actual history (2026-10-17 23:20 - )

Owner request "PHẠM VI D - redesign UI/UX", then (18/10 00:50) the master prompt "v1.2.5: Lịch sử Forecast D+1 + hoàn tất
UI redesign + deploy chung một lần". ONE release / deployment for both scopes. Local commit allowed by that prompt
(release.ps1 needs a clean tree); no push.

| Step | Status | Evidence |
|---|---|---|
| Checkpoint | DONE | `checkpoints/checkpoint-20261017-v125-ui-before.zip` (frontend src + package files, SHA-256 ECEDB45C...D3BB) at commit 3f35975 |
| Inventory | DONE | 16 routes + explanation / TreeSHAP dialogs; no icon or chart library (hand-made SVG chart); emoji calendar / close buttons; `.alert.error` unstyled |
| Design system | DONE | tokens + CSS status icons (`styles.css`), `components/icons.tsx` (lucide-react 1.48.0, ISC), shared components in `components/ui.tsx`; docs/UI-DESIGN-SYSTEM.md |
| Pages | DONE | all 16 pages + GoogleAuth / explanation / trace dialogs: PageHeader, icons, filters, tables, empty states, production markers |
| Tests | DONE | vitest 97/97 (11 new in v125.test.tsx, existing unchanged), typecheck OK, build OK; lint not configured |
| Visual check | DONE | repo source backend on a read-only copy of the live DB (scratch, port 8891, scheduler off): Edge screenshots of the 16 routes before / after (1440 px), phone width 390 px via iframe, tablet 1024 px; Edge render 16/16 with header + icons, 0 console errors (2 pre-existing React Router INFO notices) |
| History: checkpoint | DONE | `checkpoints/checkpoint-20261018-v125-history-before.zip` (backend app + tests, frontend src, scripts/remote, docs; SHA-256 03D2C59B...D11A) |
| History: survey | DONE | forecast runs only exist when published (initial model / promotion / exception / extension); the daily training makes candidates only -> history days only on publish days; no completion signal configured on production (D-1 = fallback 06:00 + row-count check) -> every actual PROVISIONAL; remote proxy allowlist needs the new GET paths |
| History: backend | DONE | migration 0004 (additive), `forecast_history.py`, `api/history_routes.py`, hooks after the 4 publish paths, reconcile at start + `app.cli history-reconcile`, 5 data-check checks, Excel H1, proxy 1.2.5 allowlist |
| History: frontend | DONE | `/forecast-history` (menu entry), `CompareChart`, filters / KPI / sessions / paged table / Excel link |
| Tests | DONE | backend 438 passed / 7 skipped (20 new); vitest 105/105 (8 new), typecheck, build |
| DB copy | DONE | migration on a fresh read-only copy (18/10 01:16): old row counts unchanged, data-check WARN (pre-existing forecast_series_meta) + 5 history checks OK; BIGQUERY 17/10 -> 18/10 FCC0EB 17,125 rows RECOVERED; summary 0.10 s, rows 0.06 s, Excel 3.8 s |
| Review | DONE | independent read-only review: 3 low defects fixed in c15f767 (session order tie-breaker, 400-day "all" range, active scope source); 1 kept by design (forecast total on all rows, actual / deviation / WAPE on rows with an actual, labelled) |
| Release | DONE | commits dadf77c + c15f767 (local, NOT pushed); release.ps1 -Force: QA backend 439 passed / 7 skipped, vitest 106, typecheck, build; package SHA-256 F502042C...C58E (the dadf77c build kept as -superseded-20261018-092944) |
| Rehearsal | DONE 28/28 | official 1.2.4 on a fresh read-only copy + proxy file of production + own Quick Tunnel: deploy-upgrade 1.2.5 (link 502 ~100 s), schema 4, old row counts unchanged, history via the URL after a proxy-only restart (0.6 s, 0 errors, same hostname), writes 405 / admin 403; rollback: -CheckOnly refuses (schema 4), restore pre-upgrade backup with 1.2.4 + rollback-version -To 1.2.4 OK |
| Deploy | DONE 18/10 10:00-10:09 | after D-0 10:00 (no active job): deploy-upgrade 1.2.4 -> 1.2.5 exit 0 (457 s; link 502 10:04:55-10:07:42); backups backup-20261018-100109-manual.zip (FCAEC813...CDD6), -100456-pre-migration-v3.zip, -100541-cli.zip; migration 0004 applied 10:05:41; history reconciled 5 runs, 0 errors; proxy only restarted (13024 -> 26416, 1.2.4 allowlist -> 1.2.5, 1.2 s, 0 errors), cloudflared 31076 and URL unchanged |
| Immutability evidence | DONE (levels 1-3) | 18/10 10:29: D+1 forecast of FCR-20261017123417-FCC0EB (17/10 -> 18/10, 17,125 rows) has the SAME sha256 b43dda4f...4754 in backup-20261017-225247 (before any actual of 18/10), backup-20261018-100109 (after the real D-0 08:00 = 0 and 10:00 = 3,764 updates), live published values and live history copy (GET); isolated fingerprint test through 4 actual updates PASS + test_v125_forecast_history 21/21; no job / training / forecast / publish created. Pending (3b): the history copy itself (10:07:44) has not met a production actual update yet (next: D-0 12:00). Report: reports/demandforecast_v125_history_ui_20261018.md section 13 (reports/ is not versioned) |
| Production check | DONE | 1.2.5 / current.txt 1.2.5, storage.json 8D79DBDD unchanged, BIGQUERY, forecast in use FCC0EB, 5 forecast runs, D-1 / D-0 / training ON with the same times, no job since the deploy, data-check WARN (pre-existing forecast_series_meta) + 5 history checks OK; through the link: history 17/10 -> 18/10 17,125 rows, actual 18/10 so far (D0 10:00) PROVISIONAL, Excel 1.46 MB, writes 405 |
| Immutability 3b | DONE 12:02 | after the scheduled D-0 12:00 (JOB-20261018050022-4B6AF2, actual source -> SNP-20261018050026-A83982) the stored D+1 of run date 17/10 read by GET is still 17,125 rows, sha256 b43dda4f...4754 (prod_fp_after_1200.py, GET only) |

# 1.2.6 End-of-day forecast backup + 23:59 actual close (2026-10-18 11:21 - ), NOT released

Owner master prompt "WAPE D-0 + EOD 7-Day Forecast Backup + Actual Finalization 23:59". No production write, no deploy,
no push; local commits allowed.

| Step | Status | Evidence |
|---|---|---|
| Checkpoint | DONE | `checkpoints/checkpoint-20261018-v126-eod-close-before.zip` (git archive of HEAD d60f81e: backend/app, backend/tests, frontend/src, package files, docs, CHANGELOG, AGENTS, scripts), SHA-256 BA60CE4E...ECE5 |
| Survey | DONE | forecast_origin = run date (horizon 1 = that day), D+1 = run date + 1, every series has every horizon date (backup copy); completion signal = audit D1_SYNC mode SIGNAL only (not configured on production); scheduler plans by idempotency key; D-1 post-commit hook `_after_d1` |
| Backend | DONE | migration 0005 (additive), `forecast_backup.py`, `actual_close.py`, fallback + CLOSED overlay in `forecast_history.py`, flows `eod` / `close` (default ON 23:55 / 23:59, 20:00-23:59 only), business date from the slot, `flows_first_seen`, reconcile after each D-1, 3 data-check checks, Excel H2, version 1.2.6 |
| Frontend | DONE | history: backup label / table / chart style, CLOSED status, forecast source filter; schedules: 2 flow cards; jobs: filter + flow list |
| Tests | DONE | backend 457 passed / 7 skipped (real-BigQuery only) incl. 18 new in test_v126_eod_backup_close.py (isolated DB); frontend vitest 110/110 (4 new), typecheck OK, build OK; lint not configured; 2 assertions updated for the new migration / flows (test_v125 migration target, test_v118 loaded flows) |
| DB copy | DONE | integ126.py copy2 (backup API, mode=ro, 12:00:32): schema 4 -> 5, 8 tables identical; snapshot 18/10 COMPLETE 119,889 rows = 7 x 17,127 (+11.76 MB, 1.04 s); close 17/10 D1 CLOSED_UNVERIFIED 68,598; close 18/10 D0 3,764; backup days 19-20/10 (simulated on the copy) 0 rows differing from source; WAPE 17/10 identical with / without the close; data-check 3 new OK |
| Review | DONE | data-reviewer: SAFE WITH CONDITIONS; fixed: day-end time validation, bounded data-check counts, duplicate index removed, reconcile scans the sources once outside the write lock; first-seen marker read without a write lock |
| Production | NOT TOUCHED | 12:08 read-only: 1.2.5, no job running, link 200 / POST 405, proxy 26416 + cloudflared 31076, storage.json 8D79DBDD; owner (UI) promoted TRN-20261018020140-642DB8 -> FCR-20261018043737-798B4D at 11:37 and saved the D-1 schedule (03:00 / 05:00) at 11:40 |
| Report | DONE | reports/demandforecast_v125_eod_backup_actual_finalization.md (not versioned) |
| Git | DONE (local) | 581fcdc code + tests, then this docs commit; not pushed; no package built, nothing deployed |


# 1.2.6 blocker resolution: 90-day retention, flows OFF by default, F1 docs, release + rehearsal (2026-10-18 13:00 - )

Owner master prompt "1.2.6 BLOCKER RESOLUTION" (decisions B1 retention 90 days, B2 new flows OFF by default, F1 docs
match runner.py). No production write, no deploy, no push; local commits allowed.

| Step | Status | Evidence |
|---|---|---|
| Checkpoint | DONE | `checkpoints/checkpoint-20261018-v126-blockers-before.zip` (git archive of HEAD ba74335: backend/app, backend/tests, frontend/src, package files, docs, CHANGELOG, AGENTS, scripts), SHA-256 DC5F177F...EA33 |
| B1 retention | DONE (source) | migration 0006 (retention table, delete triggers replaced, REPLACE guards), `eod_retention.py`, CLI `eod-retention` (dry run default, `--apply --plan`), `scripts/eod-retention.ps1` (packaged), 3 data-check checks |
| B2 defaults | DONE (source) | `eod_enabled` / `close_enabled` default false; stored 1.2.5 schedule without the keys reads OFF; tests updated where they exercise the flows ON |
| F1 | DONE | messages.py, LICH-SU-FORECAST.md, SCHEDULER.md, VAN-HANH.md, CHANGELOG: EOD_SNAPSHOT_VERIFY_FAILED = FAILED + ERROR alert, no automatic retry, nothing stored |
| Review | DONE | data-reviewer: SAFE WITH CONDITIONS, no blocker; fixed: INSERT OR REPLACE guard, random permit seq, trigger-presence check, held snapshots not reported as due, start audit, plan_id includes status / rows |
| DB copy | DONE | p4/integ126b.py copyB: schema 4 -> 6, all 23 existing tables identical, schedule JSON unchanged (eod/close OFF), synthetic expired snapshot 119,889 rows deleted in ~2 s (+ ~60 s verified backup), other tables identical |
| Commit | DONE (local) | 6a65fa2 code + tests, d05ff97 docs; not pushed |
| Release | DONE | `scripts\release.ps1` on d05ff97: backend 472 passed / 7 skipped (real BigQuery only), vitest 111/111, typecheck + build OK; `dist\DemandForecast-1.2.6-win64-portable.zip` 92,241,672 bytes, SHA-256 BBD73386...09C3; prune plan dry run only |
| Rehearsal | DONE | isolated copy (port 8879, local proxy 8878, no tunnel): run 2 43/43 PASS (run 1 38/40: status timeout in the measurement, fixed); upgrade downtime 116 s, schema 6, flows OFF, plans = 1.2.5; retention applied on a synthetic expired snapshot; rollback with 1.2.5 restore.ps1 -> every table = pre-deploy, pre-restore zip = schema 6 DB |
| Production | NOT TOUCHED | 15:05 read-only: 1.2.5, db 4, FCR-...798B4D, flows unchanged, pids 22024 / 26416 / 31076, storage.json 8D79DBDD |
| Report | DONE | reports/demandforecast_v126_blocker_resolution_release_rehearsal.md (not versioned): READY FOR OWNER APPROVAL |

# 1.2.6 schedule configuration UI + automatic deploy in the approved window (2026-10-18 15:45 - )

Owner prompt "HOAN THIEN UI CAU HINH HAI LICH MOI, SAU DO CHO DEPLOY MOT LAN": complete the two day-end schedule
cards (switch, time, timezone, runtime state, dry run), QA, new package, rehearsal, then ONE production upgrade by a
Windows scheduled task in the 19:00-22:00 window after D-0 18:00; both flows switched ON only after the post-checks.
The earlier package BBD73386...09C3 (d05ff97) is superseded by the new build (never deployed).

| Step | Status | Evidence |
|---|---|---|
| Survey | DONE | cards, API, settings, scheduler reload, validation read; gaps: timezone not persistent, same-minute allowed, ON not confirmed by the scheduler, no runtime state / last change, no dry run, close_day default "23:59" |
| Source | DONE | settings_service (timezones, conflict), jobs/flows (defaults, config_updated, runtime, confirmed ON, preview), forecast_backup.preview, actual_close.preview + changed_days, schedule_routes, messages, export_i18n; Schedules.tsx, i18n.tsx |
| Tests | DONE | backend tests/test_v126_schedule_config.py (new) + 2 tests adapted to the confirmed-ON rule; frontend v126.test.tsx +5 |
| Commit | DONE (local) | 89d2f6a code + tests + docs; not pushed |
| Release | DONE | scripts/release.ps1 -Force on 89d2f6a: backend 493 passed / 7 skipped (real BigQuery only), vitest 116/116, typecheck + build OK; dist/DemandForecast-1.2.6-win64-portable.zip 92,248,384 bytes, SHA-256 0464EEDA8B767909000974A30718663F6558872F8372604235F72E2BB36C6171 (118/118 source files = Git blobs); old BBD73386 kept as -superseded-20261018-160552; prune plan dry run only |
| Rehearsal | DONE | isolated scratchpad/s (DB copy, 1.2.5 package, port 8879, proxy 8878) driven by a real Windows scheduled task running the deploy script -Target iso: run 1 and 2 BLOCKED by script defects (missing poller; $r clobbering $R) - fixed; run 3 DEPLOYED_AND_VERIFIED (exit 0); post-task checks 20/21 (1 measurement defect, replaced by a DB-copy check: dry runs change 0/28 tables); 3 rollbacks with 1.2.5 restore.ps1: tables identical to the pre-upgrade baseline |
| Deploy task | REGISTERED | Windows task DemandForecast-Deploy-1.2.6, once 2026-10-18 19:05 (VN), user LOG-PC/Giau Vo interactive, 4 h limit, IgnoreNew, no wake; script scratchpad/p6/deploytask126.ps1 SHA 350F754B...B70E (= rehearsal run 3): waits for D-0 18:00 SUCCEEDED, gates, backup, deploy-upgrade -ConfirmToken, post-checks, then eod + close ON only if all pass; result appended to the report (section K) |
| Production | NOT TOUCHED (17:47) | 1.2.5, db 4, FCR-...798B4D, flows unchanged, pids 22024 / 26416 / 31076, storage.json 8D79DBDD; deploy runs from 19:05 by the task |
| Report | READY_TO_WAIT | reports/demandforecast_v126_final_release_and_deploy.md (not versioned) |

# 1.2.9 source: weekday 1-7, SKU open hours mandatory, roles of every D-1 column, weekday names (2026-10-19 21:13 - )

Owner prompt "Fix Weekday Feature, Mandatory total_open_hours, and Vietnamese Weekday Display". No deploy, no push, no
production training, no D-1 reload, no schedule change. Production stays 1.2.8 (deployed 20:08 the same day).

| Step | Status | Evidence |
|---|---|---|
| Checkpoint | DONE | `checkpoints/checkpoint-20261019-v129-before.zip` (git archive of HEAD 0da73b6: backend/app, frontend/src, docs/MO-HINH-VA-CHI-SO.md, docs/data, CHANGELOG), SHA-256 0809B18F...8ACA |
| Survey | DONE | weekday never saved on production (1.2.6 until 20:08; settings history 1 save of 17/10); open_hours a reference-only field; the "Ngay thu" column was horizon_day; read-only BigQuery profile: total_open_hours NULL before 2026-03-19, 0..24, 2 conflicting keys in August |
| Source | DONE (uncommitted) | app/weekday.py, app/data/open_hours.py, migration 0007 (additive), features / connector / sync / identity / pipeline / registry / catalog / explain / routes; Mapping, Results, Config pages |
| Review | DONE | data-reviewer: SAFE WITH CONDITIONS; fixed: re-check after load_demand, no all-NaN panel, backfill route in the message, dry-run status counts, 4 data-check checks, DATA-MODEL / DATA-DICTIONARY, reverse-statement warning; open: owner decision on missing period / 2 conflicting keys |
| DB copy | DONE | migration 0007 on a copy of the production DB: only schema_migrations +1, demand_daily values / keys identical, new columns NULL, reverse statements restore schema 6 with identical values; 1,355,000 window rows NOT_LOADED |
| Tests | DONE | backend 574 passed / 8 skipped (real BigQuery only), 0 failed; real BigQuery opt-in 3 + 22 passed (inline rows, 0 bytes for the open-hours SQL); vitest 142/142 (21 files), typecheck + build OK; lint not configured |
| Production | NOT TOUCHED (22:16) | 1.2.8, pids 10884 / 16144 / 35236, storage.json 8D79DBDD, FCR-...9DE420, newest job D-0 18:00 |
| Report | DONE | reports/weekday_total_open_hours_mapping_fix.md (not versioned): A PASS, B PARTIAL, C PASS |

# 1.2.9 source, second batch: backfill preview + backup, whole-number history, backtest groups, data review (2026-10-19 22:35 - )

Owner prompt "Comprehensive Data, Model Intelligence, Backtesting & Safety Upgrade". No commit, no push, no package, no
deploy, no production training / D-0 / D-1 / EOD / backfill, no schedule or configuration change. Production stays 1.2.8.

| Step | Status | Evidence |
|---|---|---|
| Checkpoint | DONE (late) | `checkpoints/checkpoint-20261019-v129b-worktree.zip` (63 working-tree files at 23:22, after the first edits of this batch), SHA-256 8207F8D6...8DFC; the state between batch 1 and batch 2 has no separate copy |
| Deploy report | DONE | `reports/demandforecast_fix_and_deploy_20261019.md`: header with the four states + section F (DEPLOYED_AND_VERIFIED 20:08; log FAIL = 6 ERROR lines older than the deploy) |
| Real data (read-only BigQuery, ~6.7 GB) | DONE | 2 CONFLICT keys = two item_code of one SKU at FC BD on 26/08 (open hours per item); sku_system_status = current state (35 / 17,128 SKU x FC vary); no customer column; no cancelled status |
| DB copy | DONE | `scratchpad/p17/e`: migration 6 -> 7 (pre-migration backup, idempotent, values / settings identical), backfill rehearsal 01/01-18/10 with real BigQuery (735 s, 100 updated / 27 removed rows, OK 954,889 / MISSING 400,082 / CONFLICT 2, other tables unchanged); rollback rehearsal with the 1.2.8 code (schema 7 refused, pre-migration backup restored = same values, app starts) |
| Source | DONE (uncommitted) | sync.py backfill preview / preview id / re-check under the write lock / pre-backfill backup; backup.py atomic zip; forecast_history.py whole numbers (H3); ml/demand_patterns.py + backtest segments; SqlSources / ForecastHistory pages |
| Review | DONE | data-reviewer: SAFE WITH CONDITIONS; fixed findings 1-8 (re-check under the write lock, data changed since the preview, empty read BLOCKED, future preview time, yesterday warning, atomic backup zip, int group codes, segments never fatal) |
| Experiments | DONE (copy only) | `scratchpad/p17/exp`: 66/70 fold trainings, 23:03-01:12, peak ~1.9 GB; screening folds 22/05-20/08, holdout 19/09-18/10. E00 (production config) 0.7972 / holdout 0.7983; best = E14 spike-capped training + 63 leaves 0.7650 / 0.7603 but 30-day bias -16.4% vs -9.6% (owner decision, not adopted); poisson failed; RECURSIVE 0.9701; weekday off worse; open hours inconclusive. Quiet-window bug (midnight) let experiments run during EOD / close: both SUCCEEDED (7 s / 1 s); fixed |
| Tests | DONE | backend 588 passed / 8 skipped (real BigQuery only) / 0 failed (01:02); real BigQuery opt-in 8 passed; vitest 145/145 (22 files); typecheck + build OK; lint not configured; EOL 0 problems on 65 files; secret scan 0 |
| Production | NOT TOUCHED (01:16) | 1.2.8, FCR-...9DE420, storage.json 8D79DBDD; only scheduled EOD 23:55 / close 23:59 ran (SUCCEEDED) |
| Report | DONE | reports/demandforecast_comprehensive_upgrade_review.md (not versioned) |

# 1.2.9 source, third batch: open hours by item, training start rule, spike weights (experiment), customer_id OFF (2026-10-20 09:40 - )

Owner prompt "DATA QUALITY, SPIKE EXPERIMENTS & CUSTOMER_ID", then the owner decision after S0-S5: skip S6, no more
training, rerun the backend tests, report, checkpoint. No commit, no push, no package, no deploy, no production training /
D-0 / D-1 / EOD / backfill, no schedule, Price or configuration change, customer_id not enabled. Production stays 1.2.8.

| Step | Status | Evidence |
|---|---|---|
| Checkpoint | DONE (late) | `checkpoints/checkpoint-20261020-v129c-worktree.zip` (75 working-tree files vs HEAD 0da73b6 + patch, the report, experiment plan / scripts / results / logs, 30 fold npz; taken after the edits and tests of this batch, no earlier copy of batch 3), SHA-256 in the `.sha256` file next to it: EB7800C2...3416, 106,047,154 bytes, 142 entries, 12:30 (verified: CRC, listing = manifest, per-file hashes) |
| Open hours grain | DONE | read-only BigQuery (~3.4 GB): hours are per item_code x day (batch 5 correction: the suffix is the opening order across regions, not a region); the 2 keys of 26/08 = 2 items with different hours -> new status MULTI_ITEM (training gate still blocks them until a rule is approved); 0 within-item conflicts, no JOIN error; source keeps open hours ~7 months (rolling) and rewrites history at each refresh |
| Training start rule | DONE (default unchanged) | data_policy.training_start_rule WINDOW_START (default) / OPEN_HOURS_COVERAGE (first stored day with hours, computed at use); excluded_summary per run; on the copy: 19/03-18/10, 77 days / 32.2 % of demand excluded incl. Tet; accuracy not lower (O1 vs E00) |
| Zero-hours Excel | DONE | reports/zero_open_hours_orders_20261020.xlsx (not versioned), 2,592 rows re-read and verified, 718 keys match, no export error |
| Spike experiments | DONE (copy only) | `scratchpad/p18/exp`: 30/30 fold trainings 10:17-11:27 on copy e8; S0 = O1 bit-for-bit; S1-S5 all TRADE_OFF under the pre-registered rule (lower WAPE, more 30-day underforecast, worse spike days); S6 NOT RUN (owner decision); nothing adopted or promoted; app training never passes weights |
| customer_id | DONE (OFF by default) / BLOCKED real data | bigquery.customer_id_column empty, model.feature_customer false, migration 0008 (3 nullable columns; rehearsal on copy 12/12 PASS, mapping hash unchanged); source has no customer column |
| Tests | DONE | backend 618 passed / 9 skipped (real BigQuery opt-in only) / 0 failed, exit 0 (12:15-12:28, after a 10:25 run with 12 expectation failures caused by this batch, fixed); real BigQuery opt-in test of this batch 1 passed (inline rows, 0 bytes); vitest 149/149 (23 files); typecheck + build OK; lint not configured; EOL 0 problems on 75 files; secret scan 0 |
| Production | NOT TOUCHED (12:16) | 1.2.8, pid 10884, storage.json 8D79DBDD...E047; only scheduled jobs ran (D-0 08/10/12 SUCCEEDED, D-1 03:00 FAILED SOURCE_INCOMPLETE - source had no 19/10) |
| Report | DONE | reports/demandforecast_dq_spike_customer_20261020.md (not versioned): BLOCKED_DATA_SAFETY |

# 1.2.9 source, fourth batch: MULTI_ITEM review workbook, normal-day overforecast (2026-10-20 12:44 - )

Owner prompt "MULTI_ITEM DATA REVIEW & NORMAL-DAY OVERFORECAST OPTIMIZATION" (P0 workbook, P1 normal-day overforecast
1-5 %, P2 spikes later). No commit, push, package, deploy, production training / backfill / job, schedule or
configuration change, promotion, Price off or customer_id on; no S0-S6 rerun.

| Step | Status | Evidence |
|---|---|---|
| Checkpoint | DONE (before edits) | `checkpoints/checkpoint-20261020-v129d-before.zip` (75 working-tree files + patch), SHA-256 F9B72DDD...DA5E, 12:45 |
| P0 MULTI_ITEM workbook | DONE | reports/demandforecast_multi_item_review_20261020.xlsx (not versioned), SHA-256 0C4C7ADA...DEADA, 7 sheets, re-read and verified; read-only BigQuery 2.32 GB (source refreshed 12:29); both keys = FC BD, item codes .1 / .2 (batch 5: no region inferred from the suffix), different orders; both .2 lines = order SOBD38271068; rule = owner decision |
| P1 metrics / cause | DONE | S0 reproduced (+19.4 % = signed bias; over-only formula 48.6 % / holdout 41.7 %); bias = forecast on actual-0 days (71.6 % of normal points); demand fall 161k -> 86k / day (66 % of the excess); no grain / rounding error; production config E00 the same |
| P1 experiments | DONE (copy only) | plan scratchpad/p19/plan_od.json (before results); K1-K3, K6 post-processing, K4 recency weights / K5 L1 trained 13:19-13:36 (10 folds, 0.33 h; first start stopped by STOP file while a production training of the user ran and free RAM was < 0.6 GB); all 6 FAIL the 1-5 % target; nothing adopted or promoted |
| Code | DONE (uncommitted) | ml/overforecast.py (evaluation / experiment only, not used by the app); sync.py fix: unique `load_id` of a D-1 load for the backfill preview re-check (same-second loads, found by a failing full-suite run) |
| Tests | DONE | backend 629 passed / 9 skipped (real BigQuery opt-in only) / 0 failed, exit 0 (13:47-13:53; the 13:37 run had 1 failure = the same-second defect, fixed + deterministic test); frontend unchanged (149/149 at 10:52); lint not configured; EOL 0 problems on 77 files; secret scan 0 |
| Production | NOT TOUCHED (13:54) | 1.2.8, storage.json 8D79DBDD...; jobs after 12:16 started by the user from the app (manual D-1 12:29 SUCCEEDED, manual training 12:43 -> candidate TRN-20261020054540-D7EEF6 PROMOTION_REVIEW_REQUIRED) or the scheduler |
| Report | DONE | reports/demandforecast_multi_item_overforecast_20261020.md (not versioned): BLOCKED_DATA_SAFETY |
| Checkpoint (final) | DONE | `checkpoints/checkpoint-20261020-v129d-worktree.zip` (77 files + patch, report, scratchpad p19 incl. 10 fold npz), SHA-256 3E2DFAB7...BFAF7, 31,797,325 bytes, 122 entries, 13:55 (verified: CRC, listing = manifest, per-file hashes); this table row is not in the copy inside the ZIP |

# 1.2.9 source, fifth batch: data recovery, open-hours re-audit, MULTI_ITEM correction, offline learning (2026-10-20 15:15 - )

Owner prompt "FULL DATA RECOVERY, OPEN-HOURS VALIDATION & MODEL LEARNING BATCH". Owner rule: the item_code suffix is the
opening order across regions, not a region. No commit, push, package, deploy, production training / backfill / job,
schedule or configuration change, promotion, Price off or customer_id on.

| Step | Status | Evidence |
|---|---|---|
| Checkpoint | DONE (before edits) | `checkpoints/checkpoint-20261020-v129e-before.zip` (77 files + patch), SHA-256 A488F502...E781, 15:17 |
| Suffix correction | DONE | open_hours.py docstring, feature_registry.py text, DATA-MODEL, BIGQUERY (§6, §11c), CHANGELOG; old reports / workbook kept; v2 workbook reports/demandforecast_multi_item_review_20261020_v2.xlsx (5B8AB036...65C4, re-read, keys reconciled) |
| Source audit | DONE | read-only BigQuery ~12 GB: refresh 15:05:19 (table recreated 08:05 UTC), 8,961,566 lines 01/01-19/10, hours on every line, 1,357,883 OK / 6 MULTI_ITEM keys, 0 exact duplicates, no cancelled status |
| Verified dataset | DONE (copy only) | scratchpad p20/e9: live DB copy 15:25 + migrate 6->8 + 1.2.9 backfill 01/01-19/10 (preview BFP-20261020082746-E6B4D7); = source 292/292 days; identity 2e11fa4d...0e80 (with hours f86669c2...f4b1) |
| Old results | DONE | e8 vs e9: hours identical where both OK, demand -0.03 %; S0-S5 / K1-K6 still valid for window 19/03 (S0 reproduced by C2) |
| Offline experiments | DONE (copy only) | plan scratchpad/p20/plan_lh.json (before results); B0 + C1-C6, 25 trainings 16:13-16:57; none IMPROVES (C2 / C4 not confirmed on holdout, C1 / C6 trade-off, C3 / C5 no improvement); nothing promoted |
| Code / tests | DONE (uncommitted) | text only + tests test_v129e_item_suffix.py, test_v129e_real_bq_item_suffix.py; backend 632 passed / 10 skipped / 0 failed (15:49-16:02); real BigQuery opt-in 2 passed |
| Production | NOT TOUCHED by Claude | 1.2.8, storage.json 8D79DBDD...; the USER promoted TRN-20261020054540-D7EEF6 at 15:24 (FCR-20261020082402-A42C91); D-0 16:00 by the scheduler |
| Report | DONE | reports/demandforecast_data_recovery_learning_readiness_20261020.md (not versioned): BLOCKED_BUSINESS_RULE (6 MULTI_ITEM keys) |
| Checkpoint (final) | DONE | `checkpoints/checkpoint-20261020-v129e-worktree.zip` (79 files + patch, report, scratchpad p20 incl. 25 fold npz; DB copy e9 excluded), SHA-256 FBD72FFD...5C05, 122,118,060 bytes, 159 entries, 17:15 (verified: CRC, listing = manifest, per-file hashes); this table row and the report's SHA line are not in the copies inside the ZIP |

# 1.2.9 source, sixth batch: 931 zero-open-hours keys export + independent audit items (2026-10-20 17:38 - )

Owner prompt "EXPORT 931 ZERO-OPEN-HOURS KEYS + CONTINUE OTHER AUDIT WORK". No commit, push, package, deploy, production
training / backfill / job, schedule or configuration change, promotion, Price off or customer_id on; the 931 keys and the 6
MULTI_ITEM keys are NOT decided or changed.

| Step | Status | Evidence |
|---|---|---|
| Checkpoint | DONE (before edits) | `checkpoints/checkpoint-20261020-v129f-before.zip` (79 files + patch), SHA-256 C9329CCB...AD9D, 17:42 |
| A. 931 keys workbook | DONE | reports/demandforecast_zero_open_hours_with_orders_20261020.xlsx (not versioned), SHA-256 A9640616...1025: 931 keys / 3,017 lines / 25,542 units = batch-5 audit; e9 931 MATCH; live copy 930 + 1 lag; verified (openpyxl + pandas, all_pass) |
| B1-B3 / B4 / B5 / B6 | DONE (read only) | 71,834 line has 19.25 h (premise corrected); 6 MULTI_ITEM rule values + impact; demand decline evidence + candidate availability tables (meaning not confirmed); production GET verified; release plan + blockers; next experiments PREPARED_NOT_RUN (scratchpad p21/plan_next.json) |
| Code / tests | DONE (uncommitted) | no code change; new backend/tests/test_v129f_zero_open_hours.py; backend 634 passed / 10 skipped / 0 failed (19:26-19:31) |
| Production | NOT TOUCHED by Claude | 1.2.8, storage.json 8D79DBDD..., active TRN-20261020054540-D7EEF6 (GET only) |
| Report | DONE | reports/demandforecast_zero_hours_followup_audit_20261020.md (not versioned): BLOCKED_BUSINESS_RULE + BLOCKED_USER_REVIEW |
| Checkpoint (final) | DONE | `checkpoints/checkpoint-20261020-v129f-worktree.zip` (80 files + patch, report, workbook, scratchpad p21; live DB copy excluded), SHA-256 8CD38C10...FDF02, 1,577,137 bytes, 116 entries, 19:33 (verified: CRC, listing = manifest, per-file hashes, PowerShell hash); changed since v129f-before: CHANGELOG, BIGQUERY, CHECKPOINT, test_v129f |

# 1.2.9 source, seventh batch: finalized (frozen) actual on the forecast history page (2026-10-20 19:51 - )

Owner prompt "FIX IMMUTABLE ACTUAL SNAPSHOTS IN FORECAST HISTORY DASHBOARD + CONTINUE INDEPENDENT ...". Owner rule: the
actual of a completed day is finalized from the successful D-1 load and never changes. No commit, push, package, deploy,
production training / backfill / job, schedule or configuration change; MULTI_ITEM and the 931 keys untouched.

| Step | Status | Evidence |
|---|---|---|
| Checkpoint | DONE (before edits) | `checkpoints/checkpoint-20261020-v129g-before.zip` (80 files + patch), SHA-256 02BC4A77...46BC, 19:51 |
| Root cause | FOUND | forecast_history: COMPLETE only with a SIGNAL-mode D-1 (production runs FALLBACK_TIME_VERIFIED) + figure always re-read from mutable demand_daily + KPI mixing statuses |
| Code | DONE (uncommitted) | migration 0009 (additive, schema 9), app/actual_final.py, sync hook after D-1, forecast_history (FINAL source, KPI finalized only, provisional / closed apart, Excel H4), history overview, data-check x2, CLI actual-finalize, UI + i18n |
| DB copy | DONE (copy only) | live DB copy 20:19 (scratchpad p22/f2): migrate 6 -> 9 28.6 s; dry run 292/292 days traceable; finalize 292 days 1,358,317 rows ~38 s, +81 MB; rerun writes nothing (0.3 s); data-check new checks OK; 18/10, 19/10 CLOSED -> COMPLETE |
| Secondary | DONE (read only) | fact_product_sku_status grain verified (1 row / item x FC x day, 202/202 days); decline classes vs OUT_OF_STOCK share (descriptive); next source refresh NOT_VERIFIED (not refreshed yet) |
| Production | NOT TOUCHED | GET only 19:32 / 20:30: 1.2.8, schema 6, storage.json 8D79DBDD..., no job, no new audit |
| Report | DONE | reports/demandforecast_actual_finalization_20261020.md (not versioned): release BLOCKED_BUSINESS_RULE |
| Tests | DONE | backend 647 passed / 10 skipped / 0 failed (20:31-20:36); vitest 152 passed; typecheck / build exit 0 |
| Checkpoint (final) | DONE | `checkpoints/checkpoint-20261020-v129g-worktree.zip` (86 files + patch, report, scratchpad p22; DB copies f1 / f2 excluded), SHA-256 753FC2C2...D48D, 1,301,625 bytes, 107 entries, 20:36 (verified: CRC, listing = manifest, per-file hashes, PowerShell hash); changed since v129g-before: exactly the 24 source files of the report |

# 1.2.9 source, eighth batch: isolated upgrade 6 -> 9 + controlled backfill + first finalization rehearsal (2026-10-20 21:11 - )

Owner prompt "DEMAND FORECASTING 1.2.9 - ISOLATED UPGRADE & BACKFILL REHEARSAL". Owner decisions: backfill first, then the
first finalization; check data impact and provenance before finalizing; rehearse 6 -> 9 in isolation; report, commit is a
separate step. No commit, push, release.ps1, package, deploy, production write / job / schedule / configuration change.

| Step | Status | Evidence |
|---|---|---|
| Checkpoint | DONE (before any write) | `checkpoints/checkpoint-20261020-v129h-before.zip` (86 files + patch + batch-7 report), SHA-256 2FCDB393...301B, 804,134 bytes, 89 entries, 21:16; extracted into a new folder and compared byte for byte with the working tree (0 differences) |
| Live DB copy | DONE (read only) | 21:22 SQLite backup API, source mode=ro -> scratchpad p23/a (726,626,304 bytes, integrity ok, 12 model files); all app paths asserted inside p23, scheduler disabled |
| Migration 6 -> 9 | PASS (copy) | 89.8 s (pre-migration-v6 backup 05FBF72C...5AC2; 0007-0009 < 0.1 s); +2 tables, +10 triggers; every old table identical on its old columns; rerun applies nothing; integrity / FK ok; data-check no FAIL |
| Backfill 01/01-19/10 | PASS (copy, BigQuery read only) | preview BFP-20261020143352-B2F6F7 READY 483 s; backfill D1L-20261020145411-F00BD1 804 s = preview (new 344 / updated 213 / removed 772, -12,109 = -0.029%); pre-backfill backup 72762EC3...8107; finalize hook recorded, not run (harness) |
| Dry run before first finalization | PASS | CLI default dry run wrote nothing (file hashes equal): 292/292 days FINALIZE from the backfill load, 0 blocked, 0 keys without / ambiguous provenance; per-day CSV in reports/ |
| First finalization | PASS (copy) | `actual-finalize --apply`: 292 days sealed, 1,357,889 rows, 42,011,108 units, +80,982,016 bytes; second apply writes nothing; production hook path (copy b) identical per day; 14/14 forbidden changes blocked; simulated later D-1 / failed D-1 / mixed loads / crash + retry all as designed; forecast, history, model tables unchanged |
| Dashboard / KPI | PASS (copy) | finalized KPI 148,240, WAPE 73.0 %, bias +14.82 % on 34,252 rows / 2 days = independent recomputation (also FC BD / HN); provisional 20/10 apart; API, Excel H4 vi / en; screenshots in reports/ |
| Restore | PASS (copy r, 1.2.8 code from HEAD) | 1.2.8 migrate refuses schema 9; 1.2.8 restore of pre-migration-v6 (67 s) -> schema 6, every table identical to before; data-check WARN (old forecast_series_meta only); backup file unchanged |
| Tests | DONE | backend 647 passed / 10 skipped / 0 failed (22:28-22:33); focused 165 passed; vitest 152 passed; typecheck / build exit 0 |
| Production | NOT TOUCHED | GET only: 1.2.8, storage.json 8D79DBDD..., no running job, newest job D-0 19:14 |
| Report | DONE | reports/demandforecast_upgrade_backfill_rehearsal_20261020.md (not versioned): rehearsal PASS; release not ready (commit authorization, MULTI_ITEM, how to keep the backfill-first order in production) |
| Checkpoint (final) | DONE | `checkpoints/checkpoint-20261020-v129h-worktree.zip` (86 files + patch, 2 reports, 37 scratchpad p23 scripts / results / screenshots; DB copies and backups excluded), SHA-256 99445579...3210, 2,197,530 bytes, 127 entries, 22:35 (verified: CRC, listing = manifest, per-file hashes, extraction compared byte for byte, PowerShell hash); changed since v129h-before: docs/CHECKPOINT.md, docs/LICH-SU-FORECAST.md |

# 1.2.9 release night (2026-10-20 22:55 - 2026-10-21): commit + package + package rehearsal; production NOT upgraded (source blocked)

Owner prompt "RELEASE TOI NAY, BACKFILL CO KIEM SOAT" (plan A: upgrade -> preview -> backfill -> finalize the same
evening). Commit authorized for the release scope only; no push. Price ON, customer_id OFF, D-0 schedule unchanged.

| Step | Status | Evidence |
|---|---|---|
| Schedules (GET) | VERIFIED | D-1 06:00 / fallback 06:30 / poll 30 min (owner change ~23:05, was 03:00 / 05:00); D-0 08-18 unchanged; train 09:00 SKIP; eod 23:55 / close 23:59 |
| Source check | BLOCKER | D-1 table rebuilt 20/10 22:18:39 VN (+customer_id, 8,961,545 rows): read-only preview 01/01-19/10 BLOCKED BQ_DATA_DUPLICATES (18 groups / 67 rows / 49 extra, 16/10 + 19/10): 307 WAIT_TO_CONFIRM lines without so_code, each group = different customer_id; also blocks D-1 21/10 06:00 (window 16-20/10) on any version |
| Checkpoint | DONE | `checkpoints/checkpoint-20261020-v129i-prerelease.zip` SHA-256 0A37954C...6C97 (90 entries, extraction compared byte for byte) |
| Commit | DONE (local) | 15d4f4b "Release 1.2.9 ..." = 86 source files of batches 1-8 + version 1.2.9 (3 files); secret / EOL / PS1 scan clean; not pushed |
| Package | DONE | release.ps1: QA backend 647 passed / 10 skipped, vitest 152; dist\DemandForecast-1.2.9-win64-portable.zip SHA-256 B705F3DF...62BB (92,343,940 bytes); prune dry run only |
| Package rehearsal | PASS 33/34 (+1 explained) | scratchpad r9: official 1.2.8 isolated on a live DB copy -> deploy-upgrade 1.2.9 (601 s, 284 s unavailable) schema 9, tables identical on schema-6 columns, flows unchanged, 0 finalized; rollback-version refuses schema 9 (exit 3); 1.2.8 restore.ps1 140 s -> identical tables; the 1 FAIL = new status field data_window.start_rule (WINDOW_START), all values equal |
| Production precheck | OK | deploy-upgrade -CheckOnly exit 0 (nothing changed); newest backup backup-20261019-200655-cli.zip readable, schema 6 |
| Deploy / backfill / finalize | NOT DONE (held at Gate 3) | without a backfill plan A cannot hold (first successful D-1 would freeze old loads; KPI empty; training blocked) -> production stays 1.2.8 |
| Secondary (read only) | DONE | 6 MULTI_ITEM keys re-verified (156 units, values per item); 931 combo keys: 98% of units via combo (combo table to 09/07 + calibrated signal after), CSV in reports/; customer_id profile (0 NULL, 35,055 customers, 1 customer per order) - offline experiments NOT RUN (reload blocked by the same duplicates) |
| Report | DONE | reports/demandforecast_release_20261020_final_report.md (not versioned): PARTIAL / BLOCKED_DATA_SAFETY |

# Master audit (2026-10-21 00:54 - 02:00): grain, duplicates, MULTI_ITEM, combo, customer_id, performance - NOT committed

Owner prompt "MASTER BATCH: RA SOAT, SUA LOI, KIEM THU HOI QUY VA TOI UU HIEU NANG". No push, no deploy, no backfill, no
finalization, no training, no schedule / mapping / config change. Production 1.2.8 (schema 6) unchanged. Commit not
authorized: the changes below are uncommitted on top of a9486bb. Reports: `reports/master-audit-20261021/` (FINAL_REPORT,
FINDINGS_REGISTER, TEST_RESULTS, PERFORMANCE_REPORT, DATA_RECONCILIATION, RESUME_CHECKPOINT + 4 anomaly workbooks).

| Step | Status | Evidence |
|---|---|---|
| Checkpoint before | DONE | `checkpoints/source-1.2.9-before-master-audit-20261021-010045.zip` SHA-256 86BBDF6C...C429 (git archive a9486bb, 358 files) |
| SKU suffix -> FC | VERIFIED, no violation | code sweep + BigQuery audit: suffixes .1-.4 present in both BD and HN; FC only from fc_code |
| Duplicates | FIXED_LOCAL | 18 groups / 67 rows = WAIT_TO_CONFIRM without so_code, each row a different customer (snapshot 20/10 22:18); `connector.PENDING_STATUSES`: never exact duplicates, counted apart; isolated full-range preview with the fix READY (BFP-20261020181139-18A4F4) |
| MULTI_ITEM 6 keys | BLOCKED (business rule) | unchanged before/after (39 lines, 156 units); hours are per item x day |
| Combo 931 | VERIFIED (part INFERRED) | 3,017 lines / 931 keys / 25,542 units match the CSV line by line; 98.25 % via combo |
| Source vs app | UNRESOLVED (source team) | 344 new / 308 changed / 785 removed keys, -13,255 units |
| Performance | FIXED_LOCAL | NOT INDEXED: registry coverage 8.3 s -> 0.47 s (endpoint 9.0 s -> 1.5 s, identical body), lineage 8.6 s -> 1.0 s, load_demand 15.3 s -> 6.2 s (identical frame) |
| Tests | PASS | backend 661 passed / 13 skipped / 0 failed (342 s); vitest 154; typecheck + build OK; inline real BigQuery 8 passed |
| Checkpoint after | DONE | `checkpoints/checkpoint-20261021-master-audit.zip` SHA-256 C3D5D5B2CBB86FC52B8B75E25891576C0F6DB9A6E418A25DD321D5FCBAEDEAAC (108 entries: diff + 16 files + reports + scratchpad p25; verified) |

# Fix 7.1 - restore D-1: release 1.2.10 DEPLOYED (2026-10-21 07:57 - 13:00)

Owner prompt "EXECUTE: FIX 7.1 - RESTORE D-1 SAFELY" (deploy, preview, backfill, reconciliation, finalization authorized if
every gate passes; no push, no training, no promotion, no schedule change). Reports: `reports/fix71-restore-d1-20261021/`
(FINAL_REPORT, TEST_RESULTS, DATA_RECONCILIATION, RESUME_CHECKPOINT + 7-sheet workbook). Status READY_FOR_PRODUCTION
(DEPLOYED_AND_VERIFIED).

| Step | Status | Evidence |
|---|---|---|
| Checkpoint before | DONE | `checkpoints/checkpoint-20261021-fix71-before.zip` SHA-256 C0BBE916...4713 (uncommitted master-audit tree) |
| Source | VERIFIED | D-1 table rebuilt 21/10 07:10:38 (8,979,752 rows, has 20/10); 46 groups / 136 rows identical in the 15 mapped columns = WAIT_TO_CONFIRM without so_code, every row another customer and another full source row; 0 true duplicates, 0 rows identical in every source column. Production 1.2.8 manual D-1 09:36 FAILED BQ_DATA_DUPLICATES (46 / 136 / 90) |
| Fix 7.1 | DONE | pending rows without order code compared on the WHOLE source row (`_praw`): separate orders kept, rows identical in every source column still blocked; tests +4 offline / +2 real-BQ inline, 4 test files updated for the new SQL |
| Release | DONE | commit dd0dfa1 "Release 1.2.10" (20 files, not pushed); release.ps1 QA 663 passed / 15 skipped, vitest 155; package SHA-256 326E3587...4E62 |
| Rehearsal | PASS | r10 28/31 (3 script FAILs explained), r11 40/40: upgrade, preview READY = independent recon, backfill, app = source, 292 finalized, D-1 dry run + real D-1, rollback by restore -> identical |
| Production | DEPLOYED | verified backup backup-20261021-120556-manual.zip (6DE2BA71...BC46); deploy-upgrade 12:09-12:18 exit 0 (backup 121031 AEFEA751...601F); preview BFP-20261021051921-51731D READY; backfill JOB-20261021052939-2D9CCE (pre-backfill backup 123506 978F86D2...C14E); app = source 1,357,876 keys / 42,009,957 qty; 292 days finalized; close revisions 18/10 r4, 19/10 r3; D-1 dry run READY |
| Open | OWNER | 6 MULTI_ITEM keys block BIGQUERY training (OPEN_HOURS_INVALID) from 22/10 07:00; 20/10 not loaded until the next D-1 (06:00 may hit SOURCE_INCOMPLETE if the source rebuilds after 06:38) |
| Checkpoint after | DONE | `checkpoints/checkpoint-20261021-fix71-after.zip` SHA-256 190F1A205D8E8B364884016E7A99CC3312EF22D501286A4F2215D5BDE6CC9F1D (115 entries, verified) |

# MULTI_ITEM open hours -> D-1 -> training (2026-10-21 14:10 - 15:40) - training BLOCKED by owner decision

Owner prompt "EXECUTE NOW - FIX MULTI_ITEM OPEN HOURS -> RUN D-1 -> TRAIN TODAY" (no push, no schedule / target / grain /
customer_id change, training candidate allowed only when every gate passes, no promotion). Reports:
`reports/multi-item-d1-20261021/` (FINAL_REPORT, TEST_RESULTS, DATA_RECONCILIATION, RESUME_CHECKPOINT + 10-sheet workbook).
Status BLOCKED_DATA_SAFETY at Gate D (training); Gates A-C passed. Uncommitted: 2 new test files, `open_hours.py` note,
docs (BIGQUERY.md 11f, DATA-MODEL, CHANGELOG Unreleased, this section).

| Step | Status | Evidence |
|---|---|---|
| Gate A | DONE | production 1.2.10 PID 30096, 0 active jobs, storage.json unchanged; source rebuilt 21/10 07:10:38 (table description: PIC giau.vo, refresh 07h00); backup `backup-20261021-145525-cli.zip` 8DB29115...D0F2 verified (integrity ok, schema 9); checkpoint `checkpoints/checkpoint-20261021-multiitem-d1-before.zip` 94FBBB73...288F |
| Gate B | DONE (classification) | the 6 keys = two items = the SKU's listings in two sales regions (`sales_region_code`, not the suffix), same FC; item hours = time in NORMAL / LIMIT (rebuilt 2,190 / 2,191 item-days); no join fan-out, no inconsistency, no mapping error; no aggregation rule in source / repo -> owner decided: keep blocked. Tests +20 offline / +2 real-BQ inline; backend 683 passed / 17 skipped; vitest 155; typecheck + build OK |
| Gate C | DONE | dry run READY = independent recon (3,037 new, 0 changed, 0 removed); D-1 `JOB-20261021081102-643FC7` 15:11:02-15:11:58 SUCCEEDED; app = source 16/10-20/10 (15,115 keys / 385,502) and 01/01-20/10 (1,360,913 / 42,088,223); 293 days finalized; close 20/10 r2 |
| Gate D | BLOCKED | `OPEN_HOURS_INVALID` (6 MULTI_ITEM rows 09/02-26/08), shown on an isolated copy (409, nothing written); no training, model `TRN-20261020054540-D7EEF6` / forecast `FCR-20261020082402-A42C91` unchanged; 07:00 slot SKIPPED |
| Open | OWNER | open-hours rule for multi-listing keys (or source value at SKU x FC); training 22/10 07:00 will fail OPEN_HOURS_INVALID; D-1 06:00 vs source refresh ~07:10; commit approval |
| Checkpoint after | DONE | `checkpoints/checkpoint-20261021-multiitem-d1-after.zip` SHA-256 F0B2B69B240E653B596B5284A8BB870BE56287972B8A9FA75AD55162C548A80B (58 entries: diff, 2 new tests, 8 sources, reports + workbook, scratchpad p27; verified) |

# Release 1.2.11 DEPLOYED (2026-10-21 16:02 - 18:30): duplicate rule by order status, item_code, proxy hardening

Owner prompt "EXECUTE NOW - CONSOLIDATED PENDING FIXES + RELEASE" (deploy authorized when every gate passes; no push, no
schedule / target / Price / customer_id / promotion change; training only with verified open-hours semantics). Reports:
`reports/release-1.2.11-20261021/` (FINAL_REPORT, TEST_RESULTS, DATA_RECONCILIATION, RESUME_CHECKPOINT + 13-sheet
workbook). Release READY_FOR_PRODUCTION (deployed, verified); training BLOCKED_DATA_SAFETY; public link
BLOCKED_EXTERNAL_SETUP.

| Step | Status | Evidence |
|---|---|---|
| item_code / MULTI_ITEM | VERIFIED + TESTS | item_code never a key; 101 multi-item keys, 95 OK (same hours), 6 MULTI_ITEM (hours differ between two regional listings); blocking never depends on item counts (test); fact_classification_sku_history is not a usable rule (1-43 % keys without association, 184 cross-region, would change 19 keys) |
| Duplicate rule | DONE | WAIT_TO_CONFIRM exempt (with or without so_code); other statuses compared on the mapped columns except item_code; real table: 0 groups, 904 pending rows exempt |
| Proxy | HARDENED | GET /api/data-quality (writes on a cache miss) and HEAD /api refused; local check 28/29 (1 client-side artefact explained) |
| Release | DONE | commit 9ee5a4a (22 files, not pushed); release.ps1 QA 686 passed / 19 skipped, vitest 155; package SHA-256 5A7A73AA...0886 |
| Rehearsal | PASS | r12 36/36: upgrade (no migration), full-range preview = source, D-1, training gate OPEN_HOURS_INVALID, rollback-version 14 s |
| Production | DEPLOYED | gates 18:00; verified backup backup-20261021-180216-manual.zip (EEEC86E6...5CEB); deploy-upgrade 18:03-18:08 exit 0 (backup 180400 29DC5902...43D3); preview BFP-20261021110908-3FC80A 0 changes = independent recon; D-1 JOB-20261021111824-17023B SUCCEEDED 0 changes; app = source 1,360,913 / 42,088,223; 293 finalized; post-checks 7/7 |
| Training | BLOCKED | OPEN_HOURS_INVALID (6 MULTI_ITEM rows); an operator click at 16:35 (train Run now) failed at the gate, nothing written |
| Open | OWNER | open-hours rule (or source SKU x FC hours); D-1 / training schedule (4/4 scheduled D-1 failed, source ~07:10); public link provider + access + autostart; push |
| Checkpoint after | DONE | `checkpoints/checkpoint-20261021-release1211-after.zip` SHA-256 96084B02FD550A3FD37931DF8BE612B66F438B13F3A72C7107B8DB33AF51B5F1 (76 entries: reports + workbook, scratchpad p28 scripts / results / state; verified) |

# Release 1.2.12 READY, NOT DEPLOYED (2026-10-21 21:13 - 22/10 00:45): six-key open-hours MAX rule, weekday, customer_id experiment

Owner prompts "URGENT - RELEASE 1.2.12 ..." and "CRITICAL COMPLETION GATE - WEEKDAY FEATURE AND CUSTOMER_ID" (owner approved
the MAX rule for the six blocked keys; deploy when every gate passes; no push, no schedule / target / Price / customer_id /
promotion change). Reports: `reports/release-1.2.12-20261021/` (FINAL_REPORT, TEST_RESULTS, DATA_RECONCILIATION,
RESUME_CHECKPOINT, OPEN_HOURS_OVERRIDE_EVIDENCE.xlsx, TRAINING_FORECAST_REPORT.xlsx, candidate/). Release
READY_FOR_PRODUCTION; production deploy BLOCKED (permission classifier); training done on an isolated production copy.

| Step | Status | Evidence |
|---|---|---|
| Six-key rule | DONE + TESTS | `app/data/open_hours_override.py`: MAX of valid listing values (24, 24, 24, 24, 24, 22.85), key scope x date x SKU x FC, stored row must still be MULTI_ITEM with approved qty / orders / load (`loaded_at` 2026-10-21T05:36:47Z), otherwise it keeps blocking with a reason; demand_daily and D-1 classification unchanged; recorded with the run + audit; 22 tests; independent review SAFE WITH CONDITIONS (S1-S4 handled) |
| Weekday | VERIFIED + UI | dow / is_weekend of the target date (ISO 1..7) in every training row, fold and predict() row (8 parity tests; real model: 5,206,698 rows, 0 mismatch); UI one form "Thu 2 ... Chu nhat" incl. history page, chart tooltip, SHAP subtitle |
| customer_id | OFFLINE ONLY | INTEGER, 0 NULL, 35,075 customers, 1 per order (not an order key); app SQL aggregates cover 100 % keys; A 0.8053 vs B 0.8019 pooled WAPE (5 / 7 folds better, latest fold worse, bias +0.0019); production OFF |
| Release | DONE | commits fe4ca9b + a601f4c (local); first QA failed on fe4ca9b (ROW_NOT_FOUND blocked every test scope with the production table name) -> fixed, no package from fe4ca9b; QA a601f4c 716 passed / 19 skipped, vitest 159, real BQ 14; package SHA-256 10BF50BF...4C05 |
| Rehearsal | PASS | r13 36/36: upgrade 1.2.11 -> 1.2.12 (no migration), gate open (6 covered, nothing else not OK), stored rows unchanged, D-1 dry run READY, rollback 14.8 s, 1.2.11 blocks the six keys again |
| Production | NOT DEPLOYED | gates PASS 22/10 00:03:44; verified backup `backup-20261022-000431-manual.zip` (ED0F8EC6...E7A7); the deploy command was refused by the Claude Code permission classifier 00:06 -> production still 1.2.11 (PID 7316), still OPEN_HOURS_INVALID; EOD / close of 21/10 SUCCEEDED |
| Candidate (copy) | DONE | copy of production 00:06 + models; TRN-20261021170704-F58EB8 / MV-20261022-003132-8EB8 (33 features), CANDIDATE, WAPE 0.80535 vs model in use 0.80555 on the same 7 folds (BETTER by 0.0002), WAPE_MAX FAIL -> not promoted; forecast FCR-20261021173318-869CF1 on the copy only (15 days, 256,935 values); artifacts in the report folder |
| Open | OWNER | run / allow deploy-upgrade 1.2.12 then "Chay ngay" training; promotion decision; public link provider + access + autostart; D-1 schedule vs source ~07:10; push |

# Release 1.2.12 deploy, second attempt (2026-10-22 10:45 - 11:40): refused again, production 1.2.11

Owner prompt "CONTINUE DEMAND FORECASTING - RELEASE 1.2.12 DEPLOY, PRODUCTION TRAINING AND NEW FORECAST" (no push, no
schedule change, no promotion; no workaround if the permission classifier refuses). Reports: `reports/release-1.2.12-20261021/`
(updated 11:40).

| Step | Status | Evidence |
|---|---|---|
| D-1 | VERIFIED | scheduled 06:00 `JOB-20261021235733-F4FE52` SOURCE_INCOMPLETE 4/4; manual `JOB-20261022001433-6BAF6C` 07:14 SUCCEEDED, window 17-21/10 = source |
| Package / gates | PASS | 10BF50BF...4C05 = commit a601f4c, manifest 7,148 / 7,148; verified backup `backup-20261022-111140-manual.zip` (A3564E18...AFD6); deploy-upgrade -CheckOnly PASS 11:18:33 |
| Deploy | REFUSED | the official deploy command was refused by the Claude Code permission classifier a second time (11:20:37); nothing installed, no workaround |
| Training / forecast | NOT RUN | needs 1.2.12 in production (07:00 slot stopped OPEN_HOURS_INVALID on 1.2.11) |
| Checkpoint | DONE | `checkpoints/checkpoint-20261022-release1212-deploy-denied2-r2.zip` (CDC1D0AD...5292) |

# 1.2.13 history sync: cancelled orders and history changes after D-1 (2026-10-22 11:45 - 15:20) - NOT committed, NOT deployed

Owner prompt "FIX DONG BO LICH SU DU LIEU D-1, DON HUY VA HUAN LUYEN" (target = gross demand at order creation; never reduce
history only because an order disappears; no deploy, production backfill, schedule change, training / promotion, push).
Reports: `reports/history-sync-20261022/` (FINAL_REPORT, TEST_RESULTS, evidence/, workbook
`HISTORY_RECONCILIATION_BIGQUERY_20260101-20261021_20261022-1504.xlsx` 773A265C...A5EE). Status READY_FOR_EXTERNAL_SETUP,
conclusion PARTIAL.

| Step | Status | Evidence |
|---|---|---|
| Checkpoint before | DONE | `checkpoints/source-1.2.12-before-history-sync-20261022.zip` (B8B335BB...0137) |
| Root cause | FOUND | D-1 rewrote only its window as the source shows it; days before the window never re-read, no per-key log; the D-1 table is rebuilt daily ~07:10 without a cancel status: a cancelled order (fact_order CANCEL) leaves with all its lines, unconfirmed WAIT_TO_CONFIRM lines leave, the product scope adds / removes whole SKU histories |
| Code | DONE (uncommitted, 23 files on 24590d2) | migration 0010 (5 additive tables, append-only triggers); `app/data/history_sync.py`, `app/bq/source_lines.py`; policy KEEP_OBSERVED_LINES (default) / FOLLOW_SOURCE; held lines, change log, run records, day checks, rollback, owner release; CLI sync-runs / sync-rollback / held-lines / history-check; version 1.2.13; independent review SAFE WITH CONDITIONS, every item fixed with a test |
| Tests | PASS | backend 751 passed / 19 skipped / 0 failed; new test file 35 passed (20 mandatory cases); vitest 159 passed; typecheck + build OK; lint not configured |
| Rehearsal | PASS (DB copy + real BigQuery read only) | copy 13:35:54; 01/01-21/10 in 9 chunks of 35 days 13:50-14:58: day check 239 -> 0 differing days of 294; 1,364,054 -> 1,364,268 rows, +8,092 units (3 SKUs added by the source), 933 held lines / 6,789 units; rerun writes nothing; rollback RBK-20261022074834-EDB725 exact; re-apply identical; six keys 6/6; training gate OK; other scopes, runs, forecasts, finals unchanged; 122 queries / 122.26 GB estimated |
| Production | NOT TOUCHED | 1.2.11, schema 9, storage.json 8D79DBDD..., no job (GET only 15:09) |
| Open | OWNER | deploy 1.2.12; commit + package + deploy 1.2.13; first controlled production backfill; keep / release the 7 SKUs removed by the source (6,323 units); gross-demand source incl. orders cancelled before the first load; window cancellations already removed (126 + 313 units, time travel until ~28/10) |
| Checkpoint after | DONE | `checkpoints/source-1.2.13-history-sync-rehearsed-20261022.zip` SHA-256 64EB82052B636C5E655AC3FBA15EA8436617BAC0C53BC8EBB5B60969B69C2D0F (49 entries: 23 sources, git state, rehearsal log + JSON, scripts; verified) |

# Resource audit RAM / CPU / disk (2026-10-22 15:00 - 17:30) - NOT committed, NOT deployed

Owner prompt "AUDIT VA TOI UU TOAN DIEN RAM, CPU, O DIA VA DU LIEU" (watch the running rehearsal read-only first; no
deploy, push, schedule / storage / credential change, promotion; no bulk deletion; quality parameters unchanged unless
benchmarked). Report: `reports/resource-audit-20261022/` (FINAL_REPORT 12 points, evidence/, workbook). Status
READY_FOR_EXTERNAL_SETUP.

| Step | Status | Evidence |
|---|---|---|
| Rehearsal watch | DONE | read only until exit 0 (14:58); silent monitor = `cut` buffering in the Git Bash pipe; PowerShell watcher (FileShare.ReadWrite, per-line flush) tested PASS 5/5 on Windows after fixing its `0..-1` range bug |
| Baseline | DONE | machine 15:15: 1,095 MB available, commit 84 %, page file 6.65 GB; browsers ~13.6 GB, python of another account (PID 10412) 4.19 GB, app 7316 2.75 GB (29 MB resident); per-task benchmark on an isolated copy: training +2,403 MB peak / 1,672 s, quality report +1,008 MB, load +1,130 MB, export +1,169 MB (0.94 GB held until GC), D-1 +331 MB; no leak (3 rounds: 0.2 MB live objects) |
| Checkpoint before | DONE | `checkpoints/source-1.2.13-before-resource-audit-20261022.zip` (B66AFA98...D63D) |
| Changes | DONE (uncommitted) | `jobs/resources.py` (new), runner (resources per attempt, timed-out thread keeps its lock, one heavy job at a time, measured memory guard INSUFFICIENT_MEMORY / PAGING_EXPECTED), scheduler + explain + shap_audit (stale panels dropped, idle release 30 min), pipeline / model (frame and raw matrix released), features (preallocated training matrix), excel_io (export garbage collected); forced gc after every job measured useless (0-6 MB) and removed |
| After | DONE | same copy: training peak growth -733 MB (-31 %), mean -587 MB (-24 %); matrix build -680 MB (-47 %, exactly equal on production data); export held -676 MB; model file byte-identical (68b95f22...), WAPE / bias / points identical |
| Disk | PLAN (deletion refused) | C: 9.8 GB free; 15.4 GB of own scratch copies verified safe (7 steps) - the permission classifier refused the deletion, not worked around; 17 old installed versions ~5.0 GB (owner) |
| Tests | PASS | 17 new tests; full suite 768 passed / 19 skipped / 0 failed (17:02, final code); monitor test 5/5; matrix equality on production data |
| Production | NOT TOUCHED | 1.2.11, schema 9, storage.json 8D79DBDD..., D-0 16:00 SUCCEEDED during the benchmarks |
| Checkpoint after | DONE | `checkpoints/source-1.2.13-after-resource-audit-20261022.zip` (all 36 changed / new files of 1.2.13 + this audit, git state, p32 evidence and scripts; SHA-256 in the `.sha256` file next to it: this row is not in the copy inside the ZIP) |
| Next | OWNER | verified scratch cleanup 15.4 GB (command in the report, section 12); old installed versions; commit 1.2.13; deploy 1.2.12 then 1.2.13; partition of the D-1 source table; identify python PID 10412 |

# Master batch: release 1.2.13 + Customer ID + demand + forecast readiness (2026-10-22 17:30 - 21:00) - committed, NOT deployed

Owner prompt "MASTER BATCH - DEMAND FORECASTING RELEASE, CUSTOMER_ID, DEMAND & FORECAST READINESS" (bring Customer ID and
the agreed demand rules to production, then forecast for review; no push, no workaround of the permission classifier, no
production promotion / schedule change). Report: `reports/release-1.2.13-20261022/` (FINAL_REPORT sections A-F, owner
scripts, quality workbook, forecast Excel of the copy, evidence/ with MANIFEST.json, RESUME_CHECKPOINT). Status
READY_FOR_PRODUCTION; deploy BLOCKED by the permission classifier.

| Step | Status | Evidence |
|---|---|---|
| Target version | 1.2.13 | contains 1.2.12; 1.2.12 alone re-blocks training after the Customer ID full reload (RELOADED_SINCE_APPROVAL); 1.2.12 has no migration, 1.2.11 -> 1.2.13 = migration 0010 only |
| Code | DONE | six-key re-verification per load: `open_hours_override.verify_load` / `verified_for`, result in `demand_sync_runs.summary_json.open_hours_override`; `test_v1213_six_key_reverify.py` (14) |
| Commit | DONE (local) | `1b00c42` "Release 1.2.13: history sync for gross demand, six-key rule across reloads, Customer ID ready, job resources"; ahead of origin 36, NOT pushed |
| QA + package | PASS | `release.ps1`: backend 782 passed / 19 skipped / 0 failed, vitest 159, typecheck + build OK, lint not configured; `dist\DemandForecast-1.2.13-win64-portable.zip` ABE0C9B1631095F86BFA5F8549F53DC9C25C308C433F8EAD53D5DB37E58B8469 |
| Production CheckOnly | PASS | 18:10:35, nothing changed |
| Production deploy | DENIED | classifier `[Production Deploy]` ~18:11 (3rd denial after 00:06 and 11:20); not worked around |
| Rehearsal r14 (production copy, real BigQuery read only) | A 20/21, B 10/11, C 8/8, D 4/5 | each FAIL explained (A: expected schema_migrations row; B: script parse, data verified; D: 2 candidate model files kept by restore, settings 6/6 and old models 12/12 identical). B full reload 831 s, coverage 0.9996, six keys 6/6, 933 held lines / 6,789 units. C candidate `TRN-20261022125113-487BFA` / `MV-20261022-202359-7BFA` (36 features, 34 min) WAPE 0.8058 vs model in use re-fitted 0.8074 vs baseline 0.8488; promoted on the copy only -> `FCR-20261022132426-A8126A` |
| Evaluation | DONE | re-run backtest = stored WAPE exactly (3,364,320 points); customer A/B same folds 0.8058 vs 0.8074 (4/7 folds better, worse in the 2 latest); BD 0.738 / HN 0.965; workbook `FORECAST_QUALITY_TRN-20261022125113-487BFA_20261022-2049.xlsx` 0B44820F...3856 |
| Production | NOT TOUCHED | 1.2.11, schema 9, storage.json 8D79DBDD..., read-only checks 17:59 and 20:53; training FAILED OPEN_HOURS_INVALID 21/10 x2 + 22/10 -> last production forecast `FCR-20261020082402-A42C91` |
| Checkpoint | DONE | `checkpoints/release-1.2.13-master-batch-20261022.zip` (report folder incl. the copy's forecast Excel + quality workbook - the copy itself was restored by phase D -, p33 scripts and state, git state, this file; SHA-256 in the `.sha256` file next to it) |
| Next | OWNER | `reports\release-1.2.13-20261022\OWNER_RELEASE_1.2.13.ps1` (UPGRADE-1.2.13, CUSTOMER-ON, optional TRAIN) in 18:30-21:45 or 00:05-05:00; promotion decision in the UI; gross-demand source incl. cancellations; D-1 time after the 07:10 source refresh (scheduled D-1 failed SOURCE_INCOMPLETE 4/4 every day 19-22/10) |

# Owner runs of 22/10 evening: deploy preflight and confirmation (2026-10-22 22:00 - 23/10 00:15) - NOT committed, NOT deployed

Two owner runs stopped safely, nothing installed. Report: first two sections of `reports/release-1.2.13-20261022/FINAL_REPORT.md`.

| Step | Status | Evidence |
|---|---|---|
| CheckOnly ~22:00 | FAIL (correct) | run from the Windows account `Administrator` (own old 1.1.0 install, own current.txt / storage.json) while 8765 is 1.2.11 of `Giau Vo`. Fix: `deploy-upgrade.ps1` checks that the app on the port is this account's installation, runs the CLI from its own backend folder, stops when the CLI returns no paths |
| Owner run 23:10 (`Giau Vo`) | STOPPED "not confirmed" | `logs\runtime\deploy-20261022-231056.log`: CheckOnly PASS, online backup `backup-20261022-231056-manual.zip` (105BEA65...E8E1), then the answer read by `Read-Host` (~3 s after the question, after the backup) was not `UPGRADE-1.2.13`; not recorded anywhere (a transcript keeps no Read-Host prompt / answer). First upgrade on this PC confirmed by typing (all earlier ones: `-ConfirmToken`). OWNER_DEPLOY then ignored the exit code and failed in `Push-Location ...\1.2.13\backend` |
| Fix | DONE (uncommitted) | `deploy-upgrade.ps1` confirmation branch: typeahead discarded, question printed, answer trimmed, refused answer reported, `confirmed:` logged (word, check and order unchanged). Owner scripts (reports, not versioned): word asked right after the CheckOnly and passed to `-ConfirmToken`; every non-zero exit code stops with that code; job check fixed (PS 5.1 passes a JSON list as one object); CANCELLED ends the D-1 wait; logs `owner-*-1.2.13-<time>.log` |
| Tests | PASS | `test_v1213_deploy_preflight.py` 15 passed (5 fail on the previous script) + `reports/.../tests/test_owner_scripts.py` 15 passed (15 fail on the original owner logic): real PowerShell scripts, fake install / package (9.8.7) / stub app, isolated; full `run-tests.ps1` 23:52: backend 797 passed / 19 skipped / 0 failed, vitest 159, typecheck + build OK, lint not configured |
| Production | NOT TOUCHED (except the 23:10 online backup made by deploy-upgrade) | 1.2.11, PID 7316, storage.json 8D79DBDD..., no 1.2.13 folder (read-only checks to 23:57) |
| Checkpoint | DONE | `checkpoints/release-1.2.13-owner-scripts-20261023.zip` (before/ and after/ of the 4 scripts and the tests, docs, evidence, git state; SHA-256 in the `.sha256` file next to it) |
| Next | OWNER | review; then `OWNER_RELEASE_1.2.13.ps1` as `Giau Vo` in 18:30-21:45 or 00:05-05:00, typing each word only when its question is shown (done 23/10 00:04, see below) |

# Owner release run 23/10 00:04: 1.2.13 deployed; Customer ID step stopped before any change (2026-10-23 00:04 - 01:00) - NOT committed

| Step | Status | Evidence |
|---|---|---|
| Deploy + verification | DONE (owner) | `deploy-20261023-000655.log` UPGRADE OK 1.2.11 -> 1.2.13; OWNER_DEPLOY "DEPLOYED AND VERIFIED" (data-check WARN forecast_series_meta + finalized_days_changed, gate open, six keys 6/6); production 1.2.13 PID 22004, schema 10, storage.json 8D79DBDD... unchanged |
| Customer ID (owner, CUSTOMER-ON typed) | STOPPED, nothing changed | step 3 "Cannot bind parameter 'Headers'": `$H` (header table) replaced by `$h = <health answer>` (PowerShell names ignore case; OWNER_CUSTOMER_ID 33/62/52, same pair in OWNER_RELEASE 32/75/93 for TRAIN); the binding failed before any request. Read-only 00:39: customer_id_column empty, feature_customer off, production mode on, no settings saved since 17/10, no job since 23:59 |
| Fix | DONE (reports, not versioned; test stub versioned, uncommitted) | `$WebHeaders`; OWNER_CUSTOMER_ID reads and prints the Customer ID state (missing field -> stop before the question), reads back every write, skips steps already done (mapping not re-sent: a save switches production off), re-checks jobs + state before the reload, stops on already_active, shows the app's HTTP answer |
| Tests | PASS (fakes) / 1 unrelated FAIL | owner 27 passed (before the fix: 12 of the 14 related fail, the Customer ID run with the exact production error); deploy-upgrade 15 passed; full run-tests 00:42: backend 796 passed / 19 skipped / 1 failed = test_v128_fixes weekday-off demo (date-dependent: fails only with today 23/10, passes 21/22/24/10), vitest 159, typecheck + build OK |
| Checkpoint | DONE | `checkpoints/release-1.2.13-customer-id-fix-20261023.zip` (SHA-256 in the `.sha256` file next to it) |
| Next | OWNER | review; then ONLY `OWNER_CUSTOMER_ID_1.2.13.ps1` as `Giau Vo` (not OWNER_RELEASE: it would re-install 1.2.13); then the 07:00 training (candidate, no promotion) and read-only post_verify A/B/C |

# Disk cleanup finalized, managed deploy staging, LightGBM forecast explainer (2026-10-26 11:30 - 13:45) - NOT committed, NOT deployed

Owner prompt "MASTER TASK - FINALIZE DISK CLEANUP SAFELY & BUILD LIGHTGBM FORECAST EXPLAINER" (no deploy, no commit / push,
no promotion, no change of features / schedule / source SQL / schema / public link). Report:
`reports/forecast-explainer-20261026/FINAL_REPORT.md` (evidence/). Status READY_FOR_PRODUCTION (commit + release 1.2.14 +
owner deploy still to approve).

| Step | Status | Evidence |
|---|---|---|
| Backup | DONE | `backups\backup-20261026-113756-manual.zip` 249,363,253 B, SHA-256 E6514810967DF01E54B652F30C28D4C09DE1BFF0CB73EFCCA6A2431B8602D1E6 (re-hashed 13:05); testzip OK, 21 entries, integrity ok, schema 10; restored on an isolated copy: data-check 34 OK / 3 WARN (forecast_series_meta, finalized_days_changed, history_source_drift) / 0 FAIL |
| Cleanup | DONE | 337 loose TEMP files deleted (58,526,739 B), each with evidence (`loose-temp-plan.csv` / `-results.csv`); kept: `bt` (the 22/10 backtest report is pinned to that copy, SHA 8ABD356D...), `Rar$EXa672.19942` (original archive not found), 5 deploy folders and installs 1.0.0-1.1.5 (no package to restore), loose files of unknown owner |
| Deploy staging | DONE (uncommitted) | `scripts/_deploy_staging.ps1` (new, packaged) + `deploy-upgrade.ps1`: one marked folder `%TEMP%\DemandForecast-deploy\<stamp>`, removed only after a verified upgrade, kept on failure, warning on a failed cleanup, exit codes unchanged; `test_v1214_deploy_staging.py` 24 passed |
| Explainer | DONE (uncommitted) | `app/ml/forecast_explainer.py`, `api/explainer_routes.py`, page `/forecast-explainer`; reads by primary key per day (first open 31.9 s -> 2.5 s); `test_v1214_forecast_explainer.py` 12 + `v1214.test.tsx` 6 |
| Real data (isolated copies) | MATCH | backup copy: run `FCR-20261024163842-4EEFD8`, MEDX.DMTS-DON-SIL-001 x BD 26/10 -> 2429 = stored; live copy 13:14 (after `MV-20261026-105345-C73F` was promoted through the app at 11:40, run `FCR-20261026044021-330262`): same series 26/10 -> 1859 = stored, random 12 series x h1/h7/h15 = 36/36 verified and equal |
| Tests | PASS | backend 879 passed / 19 skipped / 0 failed; vitest 165; typecheck + build OK; lint not configured |
| Production | NOT TOUCHED by this batch (except the requested backup) | 1.2.13 PID 11964, current.txt 1.2.13, storage.json 8D79DBDD...; one write = `POST /api/system/backups` 11:37:54 (Part A), all other calls GET; C73F was promoted through the app at 11:40 (audit `MODEL_PROMOTED`, not by this session); read-only data-check 13:25: 34 OK / 3 WARN / 0 FAIL, demand_daily 1,414,512 and change log 1,374,849 = backup, forecast_values +257,250 = the promoted run |
| Checkpoint | DONE | `checkpoints/source-1.2.13-before-explainer-staging-20261026.zip` D3614D628831861A072EB24C943D2D8ACD2D92E6BE78356E430AB56368089505 (+ `.sha256`) |
| Next | OWNER | review; approve the commit; release 1.2.14 (`release.ps1`) and deploy with `deploy-upgrade.ps1` outside scheduler slots; the read-only public link answers 403 for `/api/forecast-explainer` until the owner allows it |

# Release 1.2.14 preparation: MODEL_PROMOTED investigation, pre-commit review, local commit (2026-10-26 14:00 - 14:45) - committed locally, NOT pushed, NOT packaged, NOT deployed

Owner prompt "EXECUTION TASK - INVESTIGATE MODEL PROMOTION & PREPARE RELEASE 1.2.14" (no packaging, deploy, rollback,
push, promotion, schedule or public-link change). Report: `reports/release-1.2.14-prep-20261026/FINAL_REPORT.md`
(evidence/); the commit hash is recorded there.

| Step | Status | Evidence |
|---|---|---|
| MODEL_PROMOTED 26/10 11:40 | INVESTIGATED; actor NOT RECORDED | `TRN-20261026031942-53C73F` / `MV-20261026-105345-C73F` (training job `JOB-20261026031846-CE1653`, trigger MANUAL, 10:18-10:53, verdict EQUAL, kept for review) promoted at 04:40:21Z (`promotion.decision` PROMOTED_BY_USER), audit `MODEL_PROMOTED` 04:40:31Z; new run `FCR-20261026044021-330262` (257,250 rows) replaced `TRN-20261024090507-1EEA7D` / `FCR-20261024163842-4EEFD8`. Only path: `POST /api/training-runs/{id}/promote {confirm:true}` (Performance page button + `window.confirm`), synchronous, no job; Host 127.0.0.1/localhost and `X-DF-Client: web` required; no scheduler, worker, retry or rule calls `promote_candidate`; the remote proxy forwards GET/HEAD only (405) and was not listening; agent session logs hold no promote request (only write = the backup POST 11:37:54); the app records no client, user or request id for HTTP calls |
| C635 | NOT promoted, superseded | `TRN-20261025152426-A4C635` still REJECTED / PROMOTION_REVIEW_REQUIRED; the API shows `can_promote: true` (`promotable()` ignores newer runs) but `promote_candidate` refuses it: newer ACCEPTED run C73F, then the data fingerprint |
| Scope review | DONE | committed: explainer, staging cleanup, deploy preflight / confirmation of 22-23/10 (same script, harness of the staging tests), version 1.2.14, docs, CHANGELOG 1.2.14; left uncommitted, unchanged: remote link tooling (7 files) and its two CHANGELOG sections; checkpoint `checkpoints/worktree-before-commit-1.2.14-20261026.zip` 7F1EEA1E...8D5A |
| Tests (commit content in a separate worktree) | PASS | backend 833 passed / 19 skipped / 0 failed (incl. explainer 12, staging 24, preflight 15); vitest 165; typecheck + build OK; lint not configured; isolated instance of the commit code on a read-only copy of the live DB 14:37: run in use 1859 = stored, random 36/36 = stored, write methods 405, no internal strings, installed proxy 403 |
| Production | NOT TOUCHED | 1.2.13 PID 11964; GET only in this task |
| Next | OWNER | review; decide the remote link tooling (commit separately or keep: `release.ps1` needs a clean tree); then `release.ps1` 1.2.14 and an owner deploy; promotion audit (actor / typed confirmation) and hiding promote for superseded candidates are proposals only |
