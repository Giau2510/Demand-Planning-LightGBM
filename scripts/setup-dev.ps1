<# .SYNOPSIS  Source checkout setup: .venv with pinned packages + frontend build. Needs Python 3.14 (py launcher) and Node 18+. #>
. "$PSScriptRoot\_common.ps1"
Set-Location $Root
if (-not (Test-Path ".venv\Scripts\python.exe")) { py -3.14 -m venv .venv }
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
Push-Location frontend
npm ci
npm run build
Pop-Location
Write-Host "OK. Chay / run: scripts\start.ps1"
