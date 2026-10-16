# Shared helpers for the Demand Forecasting scripts (Windows PowerShell 5.1+). Keep this file ASCII-only.
# All storage locations come from the backend resolver (backend\app\paths.py) via "app.cli paths";
# no script computes a data/log/backup folder on its own.
$ErrorActionPreference = "Stop"
$Script:Root = Split-Path -Parent $PSScriptRoot
$Script:PathInfo = $null

function Get-AppPython {
    $cands = @((Join-Path $Script:Root "python\python.exe"), (Join-Path $Script:Root ".venv\Scripts\python.exe"))
    foreach ($c in $cands) { if (Test-Path $c) { return $c } }
    throw "Python runtime not found. Portable package: re-extract the zip. Source checkout: run scripts\setup-dev.ps1"
}

function Invoke-AppCliRaw([string[]]$CliArgs) {
    $ErrorActionPreference = "Continue"
    $py = Get-AppPython
    $env:PYTHONPATH = (Join-Path $Script:Root "backend")
    $env:PYTHONUTF8 = "1"
    $out = & $py -m app.cli @CliArgs 2>&1 | ForEach-Object { "$_" }
    return @{ code = $LASTEXITCODE; text = ($out -join "`n") }
}

function Get-PathInfo([switch]$Check) {
    # -Check validates the storage (and creates folders only where that is allowed).
    if ($Script:PathInfo -and -not $Check) { return $Script:PathInfo }
    $cliArgs = @("paths")
    if ($Check) { $cliArgs += "--check" }
    $r = Invoke-AppCliRaw $cliArgs
    try { $info = $r.text | ConvertFrom-Json } catch { throw "Cannot read storage paths: $($r.text)" }
    if ($r.code -ne 0 -or -not $info.ok) {
        Write-Host "LOI LUU TRU / STORAGE ERROR: $($info.code) - $($info.detail)" -ForegroundColor Red
        Write-Host "Ung dung KHONG tao database trong o noi khac. Xem docs\LUU-TRU.md (rollback: scripts\rollback-storage.ps1)." -ForegroundColor Yellow
        throw "storage error $($info.code)"
    }
    $Script:PathInfo = $info
    return $info
}

function Get-DataDir { return (Get-PathInfo).data_dir }

function Import-AppEnv {
    # Optional non-secret overrides (DF_PORT, DF_LOG_LEVEL, ...) in <data dir>\app.env
    $f = Join-Path (Get-DataDir) "app.env"
    if (Test-Path $f) {
        Get-Content $f | ForEach-Object {
            $line = $_.Trim()
            if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
                $k, $v = $line.Split("=", 2)
                if ($k.Trim() -notlike "DF_*_DIR" -and $k.Trim() -ne "DF_STORAGE_CONFIG") {
                    Set-Item -Path ("env:" + $k.Trim()) -Value $v.Trim()
                }
            }
        }
    }
}

function Get-Port {
    if ($env:DF_PORT) { return [int]$env:DF_PORT }
    return 8765
}

function Test-Health([int]$Port) {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 3
        return [bool]$r.ok
    } catch { return $false }
}

function Invoke-AppCli([string[]]$CliArgs) {
    $ErrorActionPreference = "Continue"
    $py = Get-AppPython
    $env:PYTHONPATH = (Join-Path $Script:Root "backend")
    $env:PYTHONUTF8 = "1"
    & $py -m app.cli @CliArgs | Out-Host
    return $LASTEXITCODE
}
