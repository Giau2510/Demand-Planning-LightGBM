<#
.SYNOPSIS  Move the runtime storage (database, models, app.env; copy of old logs) to a new folder, safely.
           Steps: stop app -> inventory -> verified backup -> SQLite online copy -> verify -> switch storage.json
           -> archive (rename, never delete) the old db folder -> start app -> health check.
           On any failure the previous configuration and database are restored.
.EXAMPLE   scripts\migrate-storage.ps1 -DataDir "D:\Buymed\Lightgbm AI\data\runtime" `
              -LogsDir "D:\Buymed\Lightgbm AI\logs\runtime" -BackupsDir "D:\Buymed\Lightgbm AI\backups" `
              -ReportsDir "D:\Buymed\Lightgbm AI\reports"
.PARAMETER DryRun  Only inventory + checks, change nothing.
#>
param([Parameter(Mandatory = $true)][string]$DataDir, [string]$LogsDir, [string]$BackupsDir, [string]$ReportsDir,
      [switch]$DryRun, [switch]$NoStart)
. "$PSScriptRoot\_common.ps1"
$ErrorActionPreference = "Continue"
$before = Get-PathInfo -Check
Write-Host "Nguon / source database: $($before.db_path)"
Write-Host "Dich / target folder:    $DataDir"
& "$PSScriptRoot\stop.ps1"
$cli = @("storage-migrate", "--to", $DataDir)
if ($LogsDir) { $cli += @("--logs-dir", $LogsDir) }
if ($BackupsDir) { $cli += @("--backups-dir", $BackupsDir) }
if ($ReportsDir) { $cli += @("--reports-dir", $ReportsDir) }
if ($DryRun) { $cli += "--dry-run" }
$code = Invoke-AppCli $cli
if ($code -ne 0) {
    Write-Host "DI CHUYEN KHONG THANH CONG / migration not done (exit $code). Du lieu cu van la du lieu chinh." -ForegroundColor Red
    exit $code
}
if ($DryRun) { Write-Host "Dry run: khong thay doi gi / nothing changed."; exit 0 }
$Script:PathInfo = $null
$after = Get-PathInfo -Check
Write-Host "Database chinh moi / new primary database: $($after.db_path)" -ForegroundColor Green
if (-not $NoStart) {
    & "$PSScriptRoot\start.ps1" -NoBrowser
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Ung dung khong khoi dong duoc tren database moi -> tu dong rollback." -ForegroundColor Red
        & "$PSScriptRoot\rollback-storage.ps1"
        exit 1
    }
}
