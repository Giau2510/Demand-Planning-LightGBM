# Final engineering batch 1.2.0 - checkpoint log (resume from the last DONE line)

| Checkpoint | Status | Evidence |
|---|---|---|
| A. Audit + snapshot | DONE 2026-10-17 00:10 | HEAD 72d7671 clean (+ untracked experiments/); app 1.1.9 pid 29728 healthy; backup `backups/backup-20261016-235420-manual.zip` (FCBF37D5...) verified; source checkpoint `checkpoints/source-1.1.9-before-1.2.0-20261016-235440.zip`; fingerprints scratchpad `protected_120_before.json`, `prod_fp_120_before.json` |
| A findings | - | scheduler 'database is locked' tick errors (bug, fix); D-1 03:00 vs source refresh ~12-14h D+1 (ops risk, owner decision); D-0 TABLE mode reads the D-1 table (bug, fix with D-0 table); sales_price = unit price per line (evidence bq_audit_120.txt); D-0 table exists (12 cols, today only) |
| B. L7_direct production + gate exception | CODE+TESTS DONE 00:40 | parity production vs harness = 0.0 diff (pooled + 7 folds), backtest 660 s, final train 86-88 s 5.2M rows, peak WS 1.69 GB / private 2.05 GB, reload identical, h31 refused; tests test_v120_direct.py |
| C. BigQuery D-1/D-0 tables + scheduler fix | CODE+TESTS DONE 00:45 | bq/source_tables.py, fetch_d0 TABLE reads d0_table_id, readiness D0_TABLE_NOT_CHECKED, Scheduler.safe_tick; tests test_v120_sources.py |
| D. Price features + feature group toggles | DONE 2026-10-17 00:59 | Config FeatureGroups, training run feature_groups/config_fingerprint; tests test_v120_features.py, v120.test.tsx; price backtest (isolated copy, 7 folds): demand only WAPE 0.805953 bias +0.068976, demand+price WAPE 0.808117 bias +0.071829 (no gain) |
| D2. Owner decision: price group ON for the release | CODE+TESTS+DOCS DONE 2026-10-17 01:50; production NOT done | price_decision.md; tests test_v120_price.py (mapping -> demand_daily -> registry -> DIRECT training -> inference/explain, control with price off, switch persistence); real-data check price_verify.py (coverage 99.98%, 239 NULL, 83 zero, origin price_last 100%); production 1.1.9: switch on by code default only, unit_price unmapped, coverage 0 -> NO_DATA; iso120.ps1 now rehearses mapping + validation + D-1 full reload + price training |
| E. Packaging / upgrade safety | TODO | |
| F. Tests, release, deploy, report | TODO | |
