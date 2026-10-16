<#
.SYNOPSIS  Restore a backup zip. Stop the app first (stop.ps1); the restore refuses to run while it is up.
.PARAMETER File  Backup zip (full path, or a file name inside <data dir>\backups).
#>
param([Parameter(Mandatory = $true)][string]$File)
. "$PSScriptRoot\_common.ps1"
Import-AppEnv
if (-not (Test-Path $File)) { $File = Join-Path (Join-Path (Get-DataDir) "backups") $File }
if (-not (Test-Path $File)) { Write-Host "Khong tim thay / not found: $File" -ForegroundColor Red; exit 1 }
exit (Invoke-AppCli @("restore", $File))
