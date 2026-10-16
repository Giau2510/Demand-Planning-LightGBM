<#
.SYNOPSIS  Switch back to an installed older version (program folder kept side by side). ASCII only.
           No database restore: refused if the database schema is newer than the target version supports
           (then restore the pre-upgrade backup instead, see docs\VAN-HANH.md).
.PARAMETER To            Version to go back to, e.g. 1.1.5
.PARAMETER CheckOnly     Only check (nothing is stopped or changed)
.PARAMETER ConfirmToken  Non-interactive confirmation: must equal ROLLBACK-<To>
#>
param([Parameter(Mandatory = $true)][string]$To, [switch]$CheckOnly, [string]$ConfirmToken, [switch]$NoShortcuts)
$ErrorActionPreference = "Continue"   # native tools log to stderr; exit codes are checked explicitly
$base = Join-Path $env:LOCALAPPDATA "Programs\DemandForecast"
$target = Join-Path $base $To
$tpy = Join-Path $target "python\python.exe"
if (-not (Test-Path $tpy)) { Write-Host "[FAIL] version $To is not installed in $target" -ForegroundColor Red; exit 2 }
$cur = Join-Path $base "current.txt"
$now = if (Test-Path $cur) { (Get-Content $cur -Raw).Trim() } else { $null }
Write-Host "current: $now -> target: $To"
$env:PYTHONPATH = Join-Path $target "backend"
$paths = ((& $tpy -m app.cli paths 2>$null) -join "`n") | ConvertFrom-Json
if (-not $paths.db_exists) { Write-Host "[FAIL] database not found: $($paths.db_path)" -ForegroundColor Red; exit 2 }
# schema of the database vs the newest migration the target version knows (read-only)
$code = "import sqlite3,sys,pathlib; c=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True); v=c.execute('select max(version) from schema_migrations').fetchone()[0]; m=max(int(p.name.split('_')[0]) for p in pathlib.Path(sys.argv[2]).glob('*.sql')); print(v, m)"
$vm = (& $tpy -c $code $paths.db_path (Join-Path $target "backend\app\migrations")) -split ' '
Write-Host "database schema $($vm[0]); $To supports up to $($vm[1])"
if ([int]$vm[0] -gt [int]$vm[1]) { Write-Host "[FAIL] the database is newer than $To supports: restore the pre-upgrade backup instead (docs\VAN-HANH.md)." -ForegroundColor Red; exit 3 }
Write-Host "[OK] rollback possible without restoring the database" -ForegroundColor Green
if ($CheckOnly) { exit 0 }
$want = "ROLLBACK-$To"
if (-not $ConfirmToken) { $ConfirmToken = Read-Host "The running app will be STOPPED and $To started. Type $want to continue" }
if ($ConfirmToken -ne $want) { Write-Host "not confirmed - nothing changed"; exit 1 }
if ($now -and (Test-Path (Join-Path $base "$now\scripts\stop.ps1"))) { & (Join-Path $base "$now\scripts\stop.ps1") }
& (Join-Path $target "scripts\start.ps1") -NoBrowser
Set-Content -Path $cur -Value $To -Encoding ASCII
$shell = New-Object -ComObject WScript.Shell
if (-not $NoShortcuts) { foreach ($loc in @([Environment]::GetFolderPath("Desktop"), (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"))) {
    $lnkPath = Join-Path $loc "Demand Forecasting.lnk"
    if (Test-Path $lnkPath) { $lnk = $shell.CreateShortcut($lnkPath); $lnk.TargetPath = Join-Path $target "Start.bat"; $lnk.WorkingDirectory = $target; $lnk.Save() }
} }
$port = 8765
if (Test-Path $paths.runtime_file) { try { $port = [int]((Get-Content $paths.runtime_file -Raw | ConvertFrom-Json).port) } catch { } }
$h = Invoke-RestMethod "http://127.0.0.1:$port/api/health" -TimeoutSec 30 -ErrorAction Stop
if ($h.version -ne $To) { Write-Host "[FAIL] running version $($h.version), expected $To" -ForegroundColor Red; exit 4 }
Write-Host "ROLLBACK OK: now running $To (database unchanged)" -ForegroundColor Green
exit 0
