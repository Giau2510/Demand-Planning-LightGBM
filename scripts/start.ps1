<#
.SYNOPSIS  Start the Demand Forecasting app (backend + UI + scheduler) on http://127.0.0.1:<port>.
.PARAMETER NoBrowser  Do not open the browser (used by the autostart task).
#>
param([switch]$NoBrowser)
. "$PSScriptRoot\_common.ps1"
$info = Get-PathInfo -Check      # stops here with a clear message if the configured storage is unavailable
Import-AppEnv
$port = Get-Port
$url = "http://127.0.0.1:$port/"
if (Test-Health $port) {
    Write-Host "Ung dung da chay / already running: $url"
    if (-not $NoBrowser) { Start-Process $url }
    exit 0
}
$py = Get-AppPython
$logDir = $info.logs_dir
Write-Host "Database: $($info.db_path)"
Write-Host "Logs:     $logDir"
$env:PYTHONPATH = (Join-Path $Root "backend")
$env:PYTHONUTF8 = "1"
$env:DF_PORT = "$port"
$p = Start-Process -FilePath $py -ArgumentList @("-m", "app.cli", "serve", "--port", "$port") -WorkingDirectory $Root `
    -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir "server.out.log") `
    -RedirectStandardError (Join-Path $logDir "server.err.log")
Write-Host "Dang khoi dong / starting (pid $($p.Id))..."
for ($i = 0; $i -lt 90; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Health $port) {
        Write-Host "San sang / ready: $url"
        if (-not $NoBrowser) { Start-Process $url }
        exit 0
    }
    if ($p.HasExited) { break }
}
Write-Host "Khong khoi dong duoc / failed to start. Xem log / see: $logDir\server.err.log" -ForegroundColor Red
foreach ($f in @("server.out.log", "server.err.log")) {
    $lf = Join-Path $logDir $f
    if (Test-Path $lf) { Get-Content $lf -Tail 15 }
}
exit 1
