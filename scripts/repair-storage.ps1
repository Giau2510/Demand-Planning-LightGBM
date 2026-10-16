<#
.SYNOPSIS  Restore a LOST storage.json from the last successful storage migration - only when the target folder's
           storage-id.json, its migration record, the history and the database all agree. Never guesses, never
           creates or moves a database. Run without -Apply first: it only shows what would be written.
.PARAMETER Apply  Actually write storage.json (after the same verification).
#>
param([switch]$Apply)
. "$PSScriptRoot\_common.ps1"
$ErrorActionPreference = "Continue"
Write-Host "== Kiem tra / verify (chi doc / read-only) =="
Invoke-AppCli @("storage-verify") | Out-Null
$cli = @("storage-repair")
if ($Apply) { $cli += "--apply" }
$code = Invoke-AppCli $cli
if ($code -ne 0) { Write-Host "Khong khoi phuc / not repaired (exit $code). Khong co gi bi thay doi." -ForegroundColor Red; exit $code }
if (-not $Apply) { Write-Host "Dry run OK. Chay lai voi -Apply de ghi storage.json." -ForegroundColor Yellow; exit 0 }
$Script:PathInfo = $null
$info = Get-PathInfo -Check
Write-Host "Database: $($info.db_path)" -ForegroundColor Green
