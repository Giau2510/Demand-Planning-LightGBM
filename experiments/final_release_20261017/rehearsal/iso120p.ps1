# Isolated release rehearsal 1.1.9 -> 1.2.0, price group ON, on a COPY of the real DB that already holds the real
# BigQuery load WITH prices (price experiment copy, 01/01-15/10/2026): official 1.1.9 install, deploy-upgrade.ps1 of
# 1.2.0 (check-only, wrong SHA, wrong confirmation, real), settings / schedules unchanged, real metadata checks of the
# D-1 / D-0 tables, the production API sequence mapping -> validation -> activation (real BigQuery, read-only), D-1 dry
# run, D-0 manual run into the copy, DIRECT training with price -> rejected candidate with model file -> backup ->
# release with gate exception -> explanation -> restart -> rollback-version.ps1 -> 1.1.9 -> restore of the
# pre-release backup. ASCII only. Everything under the folder of this script (scratch); port 8877.
param([Parameter(Mandatory = $true)][string]$Sha)
$ErrorActionPreference = "Continue"
$sp = Split-Path -Parent $MyInvocation.MyCommand.Path
$proj = "D:\Buymed\Lightgbm AI"
$venvPy = Join-Path $proj ".venv\Scripts\python.exe"
$zip = Join-Path $proj "dist\DemandForecast-1.2.0-win64-portable.zip"
$realLocal = [Environment]::GetFolderPath("LocalApplicationData")
$env:PYTHONUTF8 = "1"
$env:DF_DISABLE_SCHEDULER = "1"
$env:DF_PORT = "8877"
$iso = Join-Path $sp "iso120p"
if ($sp -like "*Lightgbm AI*") { throw "run from a scratch copy, never from the repository" }
if (Test-Path $iso) { Remove-Item $iso -Recurse -Force -Confirm:$false }
New-Item -ItemType Directory -Force -Path (Join-Path $iso "LocalAppData") | Out-Null
$pkg119zip = Join-Path $proj "dist\DemandForecast-1.1.9-win64-portable.zip"
if ((Get-FileHash $pkg119zip).Hash -ne "F8311492670BE5293299E6980C74675B9011F3443138721ED4D5B12E0224DD46") { throw "1.1.9 package hash differs" }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::ExtractToDirectory($pkg119zip, (Join-Path $iso "pkg119"))
[IO.Compression.ZipFile]::ExtractToDirectory($zip, (Join-Path $iso "pkg120"))
$pkg119 = Join-Path $iso "pkg119\DemandForecast-1.1.9"
$pkg120 = Join-Path $iso "pkg120\DemandForecast-1.2.0"
$env:LOCALAPPDATA = Join-Path $iso "LocalAppData"
if ($env:LOCALAPPDATA -eq $realLocal) { throw "isolation failed" }
$data = Join-Path $iso "data"
New-Item -ItemType Directory -Force -Path (Join-Path $data "db"), (Join-Path $data "models") | Out-Null
$env:DF_DATA_DIR = $data; $env:DF_LOGS_DIR = Join-Path $iso "logs"; $env:DF_BACKUPS_DIR = Join-Path $iso "backups"; $env:DF_REPORTS_DIR = Join-Path $iso "reports"
New-Item -ItemType Directory -Force -Path $env:DF_LOGS_DIR, $env:DF_BACKUPS_DIR, $env:DF_REPORTS_DIR | Out-Null
& $venvPy (Join-Path $sp "copy_real_db.py") (Join-Path $sp "iso_price\data\db\app.db") (Join-Path $data "db\app.db") (Join-Path $iso "pre.json") | Out-Null
Copy-Item (Join-Path $proj "data\runtime\models\*") (Join-Path $data "models")
$base = "http://127.0.0.1:8877"
$hdr = @{ "X-DF-Client" = "web" }
$res = New-Object System.Collections.ArrayList
function Check([string]$name, [bool]$ok, [string]$info = "") { [void]$res.Add($ok); Write-Host (($(if ($ok) { "PASS " } else { "FAIL " })) + $name + $(if ($info) { "  [$info]" } else { "" })) }
function Facts { & $venvPy (Join-Path $sp "db_facts.py") (Join-Path $data "db\app.db") (Join-Path $iso "facts_tmp.json") | Out-Null; Get-Content (Join-Path $iso "facts_tmp.json") -Raw | ConvertFrom-Json }
function WaitJob([string]$id, [int]$max = 3000) { for ($i = 0; $i -lt $max; $i++) { $j = Invoke-RestMethod "$base/api/jobs/$id"; if ($j.status -notin @("PENDING", "RUNNING")) { return $j }; Start-Sleep -Seconds 2 }; return $j }
function J($o) { $o | ConvertTo-Json -Depth 8 -Compress }
function Post($path, $body) { Invoke-RestMethod -Method Post "$base$path" -Headers $hdr -ContentType "application/json" -Body (J $body) }
function Put($path, $body) { Invoke-RestMethod -Method Put "$base$path" -Headers $hdr -ContentType "application/json" -Body (J $body) }

Write-Host "== install official 1.1.9 (isolated) on the DB copy =="
& (Join-Path $pkg119 "scripts\install.ps1") -NoShortcuts *>&1 | Select-Object -Last 2 | ForEach-Object { "  $_" }
$h = Invoke-RestMethod "$base/api/health"; Check "1.1.9 running isolated" ($h.version -eq "1.1.9") $h.version
$paths = Invoke-RestMethod "$base/api/system/paths"
if (-not $paths.data_dir.StartsWith($iso, [StringComparison]::OrdinalIgnoreCase)) { Write-Host "NOT ISOLATED" -ForegroundColor Red; exit 9 }
$f0 = Facts
$s0 = Invoke-RestMethod "$base/api/settings"
$sc0 = Invoke-RestMethod "$base/api/schedules"
$deploy = Join-Path $pkg120 "scripts\deploy-upgrade.ps1"
& $deploy -Package $zip -ExpectedSha256 $Sha -CheckOnly *>&1 | Out-Null
Check "deploy -CheckOnly passes, nothing changed" ($LASTEXITCODE -eq 0 -and (Invoke-RestMethod "$base/api/health").version -eq "1.1.9") "$LASTEXITCODE"
& $deploy -Package $zip -ExpectedSha256 ("0" * 64) -CheckOnly *>&1 | Out-Null
Check "deploy refuses a wrong SHA256 (exit 3)" ($LASTEXITCODE -eq 3) "$LASTEXITCODE"
& $deploy -Package $zip -ExpectedSha256 $Sha -ConfirmToken "NO" -NoShortcuts *>&1 | Out-Null
Check "deploy without the right confirmation keeps 1.1.9 running" ($LASTEXITCODE -eq 1 -and (Invoke-RestMethod "$base/api/health").version -eq "1.1.9") "$LASTEXITCODE"
& $deploy -Package $zip -ExpectedSha256 $Sha -ConfirmToken "UPGRADE-1.2.0" -NoShortcuts *>&1 | Select-Object -Last 2 | ForEach-Object { "  $_" }
$h = Invoke-RestMethod "$base/api/health"
Check "deploy upgrades to 1.2.0 (exit 0)" ($LASTEXITCODE -eq 0 -and $h.version -eq "1.2.0") "$LASTEXITCODE $($h.version)"
$f1 = Facts
Check "after upgrade: schema 3, integrity ok, demand and forecast runs identical" ($f1.schema -eq 3 -and $f1.integrity -eq "ok" -and $f1.demand_daily_sum -eq $f0.demand_daily_sum -and (J $f1.forecast_runs) -eq (J $f0.forecast_runs)) "$($f1.schema) $($f1.demand_daily_sum)"
$s1 = Invoke-RestMethod "$base/api/settings"
$same = $true
foreach ($k in "general", "schedule", "horizons", "quality", "sql_sources", "data_policy") { if ((J $s1.$k) -ne (J $s0.$k)) { $same = $false; Write-Host "  settings differ: $k" } }
$bq0 = $s0.bigquery | Select-Object * -ExcludeProperty d0_table_id; $bq1 = $s1.bigquery | Select-Object * -ExcludeProperty d0_table_id
Check "settings unchanged by the upgrade (only the new key bigquery.d0_table_id appears)" ($same -and (J $bq0) -eq (J $bq1) -and $s1.bigquery.d0_table_id -like "*demand_planing_lightgbm_D0") $s1.bigquery.d0_table_id
$sc1 = Invoke-RestMethod "$base/api/schedules"
Check "schedules unchanged: D-1 off (poll 03:00), D-0 off, training on 09:00" (-not $sc1.flows.d1.enabled -and -not $sc1.flows.d0.enabled -and $sc1.flows.train.enabled -and $sc1.flows.d1.config.time -eq $sc0.flows.d1.config.time -and $sc1.flows.train.config.time -eq $sc0.flows.train.config.time -and (J $sc1.flows.d0.config) -eq (J $sc0.flows.d0.config)) "d1=$($sc1.flows.d1.config.time) train=$($sc1.flows.train.config.time)"
$py = Join-Path $env:LOCALAPPDATA "Programs\DemandForecast\1.2.0\python\python.exe"
$env:PYTHONPATH = Join-Path $env:LOCALAPPDATA "Programs\DemandForecast\1.2.0\backend"
$dcj = ((& $py -m app.cli data-check 2>$null) -join "`n") | ConvertFrom-Json
Check "data-check (1.2.0 CLI) on the upgraded copy: no FAIL" ($dcj.status -ne "FAIL") "$($dcj.status)"
Remove-Item Env:PYTHONPATH

Write-Host "== D-1 / D-0 source tables (real BigQuery metadata, read-only) =="
$t = Invoke-RestMethod "$base/api/bigquery/source-tables"
$c0 = Post "/api/bigquery/source-tables/d0/check" @{ table_id = $t.d0.table_id }
Check "D-0 table check on the real table" ($c0.status -eq "PASSED") "$($c0.status) rows=$($c0.num_rows) cols=$($c0.n_columns) $((J $c0.errors))"
$c1 = Post "/api/bigquery/source-tables/d1/check" @{ table_id = $t.d1.table_id }
Check "D-1 table check on the real table" ($c1.status -eq "PASSED") "$($c1.status) rows=$($c1.num_rows) cols=$($c1.n_columns)"
try { Put "/api/bigquery/source-tables/d1" @{ table_id = "lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm_D0" } | Out-Null; $lock = $false } catch { $lock = ($_.ErrorDetails.Message -match "BQ_TABLE_CHANGE_NEEDS_PRODUCTION_OFF") }
Check "the D-1 table cannot change while production is on" $lock ""

Write-Host "== price ON (owner decision 17/10): the production API sequence on the copy (real BigQuery, read-only) =="
$bqs = (Invoke-RestMethod "$base/api/settings").bigquery
Check "the copy already holds the price load of 17/10 00:3x (mapping unit_price <- sales_price)" ($bqs.field_mapping.unit_price.column -eq "sales_price") ""
$fm = $bqs.field_mapping; $fm.unit_price.column = "sales_price"; $fm.unit_price.usage = "OPTIONAL"
$mp = Post "/api/bigquery/mapping" @{ field_mapping = $fm; reference_mapping = $bqs.reference_mapping }
Check "POST /api/bigquery/mapping saves unit_price <- sales_price and switches production mode off" ($mp.settings.field_mapping.unit_price.column -eq "sales_price" -and -not $mp.settings.production_enabled) "warnings=$((J $mp.check.warnings))"
$t1 = Get-Date
$v = Post "/api/bigquery/validate" @{}
Check "full-period validation with the price mapping (real BigQuery)" ($v.passed) "bytes=$($v.estimated_bytes) $([math]::Round(((Get-Date) - $t1).TotalSeconds))s blocking=$((J $v.blocking_issues)) warnings=$((J @($v.warnings | ForEach-Object { $_.code })))"
$act = Post "/api/bigquery/activate" @{}
Check "production mode on again (activation requirements met)" ($act.ok -and (Invoke-RestMethod "$base/api/settings").bigquery.production_enabled) "$((J $act.requirements))"
$dr = Post "/api/bigquery/ingest-check" @{}
$stp = @{}; foreach ($x in $dr.steps) { $stp[$x.step] = $x.status }
Check "D-1 dry run (READ_ONLY_TEST): mapping, duplicates, aggregation, reconciliation pass; nothing written" (-not $dr.written -and $stp["mapping"] -eq "PASSED" -and $stp["aggregate"] -eq "PASSED" -and $stp["reconciliation"] -eq "PASSED") "$((J $stp))"
$reg = Invoke-RestMethod "$base/api/features/registry"
Check "registry: price coverage >= 0.99, used (DATA_OK), price features in the next training" ($reg.decisions.price.used -and $reg.decisions.price.coverage -ge 0.99 -and $reg.next_training.features -contains "price_last" -and $reg.next_training.features -contains "price_rel_28") "coverage=$($reg.decisions.price.coverage)"
$c0b = Post "/api/bigquery/source-tables/d0/check" @{ table_id = $t.d0.table_id }
Check "D-0 table check again with the price mapping (sales_price exists in the D-0 table)" ($c0b.status -eq "PASSED") "$($c0b.status) $((J $c0b.errors))"
Write-Host "== D-0 manual run on the COPY only (COPY_PIPELINE_TEST; production D-0 settings and schedule untouched) =="
Put "/api/sql-sources/d0/options" @{ mode = "TABLE" } | Out-Null
$j0 = Post "/api/schedules/d0/run" @{}
$j0 = WaitJob $j0.id 300
Check "D-0 snapshot from the real D-0 table into the copy" ($j0.status -eq "SUCCEEDED") "$($j0.status) $($j0.reason_code) series=$($j0.result.result.series) $((J $j0.error))"
$sc2 = Invoke-RestMethod "$base/api/schedules"
Check "manual runs changed no schedule (D-0 off, D-1 off 03:00, training on 09:00)" (-not $sc2.flows.d0.enabled -and -not $sc2.flows.d1.enabled -and $sc2.flows.train.enabled -and $sc2.flows.train.config.time -eq $sc0.flows.train.config.time -and $sc2.flows.d1.config.time -eq $sc0.flows.d1.config.time) ""

Write-Host "== DIRECT training on the copy (real data, price ON), gate exception, explanation =="
$m = (Invoke-RestMethod "$base/api/settings").model
$m.forecast_strategy = "DIRECT"; $m.feature_price = $true
$saved = Put "/api/settings/model" $m
Check "model settings saved explicitly: DIRECT, price group ON" ($saved.forecast_strategy -eq "DIRECT" -and $saved.feature_price) ""
$t0 = Get-Date
$j = Post "/api/training/run" @{ force = $true }
$j = WaitJob $j.id
$secs = [math]::Round(((Get-Date) - $t0).TotalSeconds)
$trid = $j.result.result.training_run_id
Check "training job finishes: REJECTED by the standard gate (not published)" ($j.status -eq "SUCCEEDED" -and $j.reason_code -eq "QUALITY_GATE_FAILED") "$($j.status) $($j.reason_code) ${secs}s"
$d = Invoke-RestMethod "$base/api/training-runs/$trid"
Check "rejected run keeps its model file and is eligible for an exception" ($d.model_path -and $d.gate_exception.eligible) "$($d.model_version) wape=$([math]::Round([double]$d.metrics.wape,6)) bias=$([math]::Round([double]$d.metrics.bias,6)) folds=$($d.backtest.config.folds_evaluated)"
$fg = $d.feature_config.feature_groups.price
Check "the run really trained with the price: switch on, used, price_last + price_rel_28 in the model" ($fg.switch_on -and $fg.used -and $d.feature_config.config.feature_price -and $d.feature_config.features -contains "price_last" -and $d.feature_config.features -contains "price_rel_28") "reason=$($d.feature_config.feature_decisions.price.reason) n_features=$(@($d.feature_config.features).Count)"
$bk = Post "/api/system/backups" @{}
Write-Host "  pre-release backup $($bk.file)"
$fpre = Facts
$body = @{ confirm_text = "EXCEPTION-$trid"; approved_by = "Chu du an (rehearsal)"; reason = "Rehearsal on an isolated DB copy of the approved L7_direct exception"; review_by = (Get-Date).AddDays(30).ToString("yyyy-MM-dd"); acknowledged_wape = [math]::Round([double]$d.metrics.wape, 3); acknowledged_bias = [math]::Round([double]$d.metrics.bias, 3) }
$r = Post "/api/training-runs/$trid/release-with-exception" $body
$st = Invoke-RestMethod "$base/api/system/status"
Check "release with exception publishes this run" ($r.status -eq "PUBLISHED" -and $st.latest_forecast_run.id -eq $r.forecast_run_id) "$($r.forecast_run_id)"
$q = (Invoke-RestMethod "$base/api/settings").quality
Check "standard quality gate unchanged" ($q.wape_max -eq $s1.quality.wape_max -and $q.abs_bias_max -eq $s1.quality.abs_bias_max) "$($q.wape_max) / $($q.abs_bias_max)"
$fr = Invoke-RestMethod "$base/api/forecast-runs/$($r.forecast_run_id)"
Check "forecast run: n_series x 15 values, horizons 7/15" ($fr.max_horizon -eq 15 -and $fr.n_series -gt 0) "series=$($fr.n_series) methods=$((J $fr.method_counts))"
$vals = Invoke-RestMethod "$base/api/forecast-runs/$($r.forecast_run_id)/values?limit=5000"
$one = @($vals.rows | Where-Object { $_.method -eq "LIGHTGBM" })[0]
$ex = Invoke-RestMethod "$base/api/forecast-runs/$($r.forecast_run_id)/explain?sku_id=$([uri]::EscapeDataString($one.sku_id))&fc_id=$($one.fc_id)&target_date=$($one.target_date)"
Check "explanation of a DIRECT value reproduces the published number, no recursion" ($ex.lightgbm.status -eq "OK" -and $ex.lightgbm.matches_published -and $ex.lightgbm.forecast_strategy -eq "DIRECT" -and -not $ex.lightgbm.uses_forecast_inputs) "$($one.sku_id) $($one.fc_id) $($one.target_date)"
$pf = @($ex.lightgbm.features | Where-Object { $_.name -eq "price_last" })[0]
Check "explanation: price_last is an ACTUAL input of the published value" ($pf -and $pf.source -eq "ACTUAL") "value=$($pf.value) missing=$($pf.missing) used_in_trees=$($pf.used_in_trees)"

Write-Host "== restart of 1.2.0: settings, forecast and explanation survive =="
& (Join-Path $env:LOCALAPPDATA "Programs\DemandForecast\1.2.0\scripts\stop.ps1") *>&1 | Out-Null
& (Join-Path $env:LOCALAPPDATA "Programs\DemandForecast\1.2.0\scripts\start.ps1") *>&1 | Out-Null
for ($i = 0; $i -lt 60; $i++) { try { $h = Invoke-RestMethod "$base/api/health" -TimeoutSec 3; break } catch { Start-Sleep -Seconds 2 } }
$m2 = (Invoke-RestMethod "$base/api/settings").model
$ex2 = Invoke-RestMethod "$base/api/forecast-runs/$($r.forecast_run_id)/explain?sku_id=$([uri]::EscapeDataString($one.sku_id))&fc_id=$($one.fc_id)&target_date=$($one.target_date)"
Check "after restart: price ON + DIRECT kept, same forecast run in use, explanation reproduces the published value" ($h.version -eq "1.2.0" -and $m2.feature_price -and $m2.forecast_strategy -eq "DIRECT" -and (Invoke-RestMethod "$base/api/system/status").latest_forecast_run.id -eq $r.forecast_run_id -and $ex2.lightgbm.matches_published) "$($h.version)"

Write-Host "== rollback to 1.1.9, then restore the pre-release backup =="
$rb = Join-Path $env:LOCALAPPDATA "Programs\DemandForecast\1.2.0\scripts\rollback-version.ps1"
& $rb -To 1.1.9 -CheckOnly *>&1 | Out-Null
Check "rollback -CheckOnly: schema compatible" ($LASTEXITCODE -eq 0) "$LASTEXITCODE"
& $rb -To 1.1.9 -ConfirmToken "ROLLBACK-1.1.9" -NoShortcuts *>&1 | Select-Object -Last 1 | ForEach-Object { "  $_" }
$h = Invoke-RestMethod "$base/api/health"
Check "rollback to 1.1.9 without DB restore (exit 0)" ($LASTEXITCODE -eq 0 -and $h.version -eq "1.1.9") "$LASTEXITCODE $($h.version)"
Check "1.1.9 still displays the DIRECT forecast run" ((Invoke-RestMethod "$base/api/system/status").latest_forecast_run.id -eq $r.forecast_run_id) ""
try { $ex9 = Invoke-RestMethod "$base/api/forecast-runs/$($r.forecast_run_id)/explain?sku_id=$([uri]::EscapeDataString($one.sku_id))&fc_id=$($one.fc_id)&target_date=$($one.target_date)"; $ex9s = "$($ex9.lightgbm.status)" } catch { $ex9s = "HTTP error" }
Check "1.1.9 does not give a wrong explanation of the DIRECT model (not OK)" ($ex9s -ne "OK") $ex9s
& (Join-Path $env:LOCALAPPDATA "Programs\DemandForecast\1.1.9\scripts\stop.ps1") | Out-Null
& (Join-Path $env:LOCALAPPDATA "Programs\DemandForecast\1.1.9\scripts\restore.ps1") -File (Join-Path $env:DF_BACKUPS_DIR $bk.file) *>&1 | Select-Object -Last 2 | ForEach-Object { "  $_" }
Check "restore of the pre-release backup (1.1.9 restore.ps1)" ($LASTEXITCODE -eq 0) "$LASTEXITCODE"
$f4 = Facts
Check "after restore: integrity ok, the exception release is gone, data equals the pre-release state" ($f4.integrity -eq "ok" -and (J $f4.forecast_runs) -eq (J $fpre.forecast_runs) -and $f4.demand_daily_sum -eq $fpre.demand_daily_sum -and $f4.accepted_trainings -eq $fpre.accepted_trainings) "runs=$(@($f4.forecast_runs).Count) accepted=$($f4.accepted_trainings)"
$failed = @($res | Where-Object { -not $_ }).Count
Write-Host "RESULT release-rehearsal-120p: $($res.Count - $failed) passed, $failed failed"
exit $failed
