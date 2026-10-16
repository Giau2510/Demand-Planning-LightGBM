<# .SYNOPSIS  Stop the app safely (graceful shutdown endpoint, then process stop as a fallback). #>
. "$PSScriptRoot\_common.ps1"
$rtFile = (Get-PathInfo).runtime_file
if (-not (Test-Path $rtFile)) { Write-Host "Khong thay ung dung dang chay / app not running."; exit 0 }
$rt = Get-Content $rtFile -Raw | ConvertFrom-Json
$port = [int]$rt.port
if (Test-Health $port) {
    try {
        Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$port/api/system/shutdown" `
            -Headers @{ "X-DF-Client" = "web"; "X-DF-Shutdown-Token" = $rt.shutdown_token } -TimeoutSec 5 | Out-Null
    } catch { }
    for ($i = 0; $i -lt 20; $i++) { Start-Sleep -Milliseconds 500; if (-not (Test-Health $port)) { break } }
}
$proc = Get-Process -Id ([int]$rt.pid) -ErrorAction SilentlyContinue
# only stop it if it really is our Python server (a pid can be reused by another program)
if ($proc -and $proc.ProcessName -like "python*") { Stop-Process -Id $proc.Id -Force -Confirm:$false }
Remove-Item $rtFile -Force -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "Da dung / stopped."
