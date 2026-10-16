<#
.SYNOPSIS  Undo the last storage migration: the previous database folder and storage configuration become primary
           again; the migrated copy is kept untouched and marked NOT-PRIMARY. Nothing is deleted.
#>
. "$PSScriptRoot\_common.ps1"
$ErrorActionPreference = "Continue"
& "$PSScriptRoot\stop.ps1"
$code = Invoke-AppCli @("storage-rollback")
if ($code -ne 0) { Write-Host "Rollback khong thuc hien / not done (exit $code)." -ForegroundColor Red; exit $code }
$Script:PathInfo = $null
$info = Get-PathInfo -Check
Write-Host "Database chinh / primary database: $($info.db_path)" -ForegroundColor Green
Invoke-AppCli @("storage-inventory") | Out-Null
