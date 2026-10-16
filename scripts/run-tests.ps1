<# .SYNOPSIS  Run backend (pytest), frontend (typecheck, vitest, build) suites; full output -> logs\development\ #>
. "$PSScriptRoot\_common.ps1"
$ErrorActionPreference = "Continue"
Set-Location $Root
$env:PYTHONUTF8 = "1"
$logDir = Join-Path $Root "logs\development"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$log = Join-Path $logDir "tests_$stamp.log"
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider backend\tests 2>&1 | Tee-Object -FilePath $log -Append
$be = $LASTEXITCODE
Push-Location frontend
npx tsc -b 2>&1 | Tee-Object -FilePath $log -Append; $tc = $LASTEXITCODE
npx vitest run 2>&1 | Tee-Object -FilePath $log -Append; $fe = $LASTEXITCODE
npx vite build 2>&1 | Tee-Object -FilePath $log -Append; $bd = $LASTEXITCODE
Pop-Location
$summary = "backend=$be typecheck=$tc frontend=$fe build=$bd (0 = pass)"
Add-Content -Path $log -Value $summary
Write-Host $summary
Write-Host "Log: $log"
if ($be -or $tc -or $fe -or $bd) { exit 1 }
