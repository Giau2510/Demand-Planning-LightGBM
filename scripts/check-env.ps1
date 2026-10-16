<# .SYNOPSIS  Check the Windows environment: Python runtime, packages, LightGBM, VC++ runtime, data dir, DB, port. #>
. "$PSScriptRoot\_common.ps1"
Import-AppEnv
$ok = $true
Write-Host "== Demand Forecasting - kiem tra moi truong / environment check =="
Write-Host ("Windows: " + [Environment]::OSVersion.VersionString + "  64-bit: " + [Environment]::Is64BitOperatingSystem)
if (-not (Test-Path "$env:WINDIR\System32\vcomp140.dll")) {
    Write-Host "THIEU / MISSING: Microsoft Visual C++ Redistributable (vcomp140.dll) - LightGBM can thu vien nay." -ForegroundColor Red
    Write-Host "  Cai dat / install:  winget install Microsoft.VCRedist.2015+.x64" -ForegroundColor Yellow
    $ok = $false
} else { Write-Host "VC++ runtime (vcomp140.dll): OK" }
try { $py = Get-AppPython; Write-Host "Python: $py" } catch { Write-Host $_ -ForegroundColor Red; exit 1 }
$code = Invoke-AppCli @("check-env")
if ($code -ne 0) { $ok = $false }
$port = Get-Port
if (Test-Health $port) { Write-Host "Ung dung dang chay tren cong $port / app running on port $port" }
else {
    $busy = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($busy) {
        Write-Host "Cong $port dang bi chiem boi pid $($busy.OwningProcess) / port in use. Dat DF_PORT=<cong khac> trong app.env." -ForegroundColor Yellow
        $ok = $false
    } else { Write-Host "Cong $port trong / port free: OK" }
}
if ($ok) { Write-Host "KET QUA / RESULT: OK" -ForegroundColor Green; exit 0 }
Write-Host "KET QUA / RESULT: CO VAN DE / PROBLEMS" -ForegroundColor Red
exit 1
