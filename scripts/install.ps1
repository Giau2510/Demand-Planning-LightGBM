<#
.SYNOPSIS  Install / upgrade the portable package for the current Windows user (no admin rights needed).
           Program: %LOCALAPPDATA%\Programs\DemandForecast\<version>   (old versions are kept side by side)
           Data:    wherever the storage configuration points (default %LOCALAPPDATA%\DemandForecast;
                    see docs\LUU-TRU.md). Install NEVER deletes or resets the database or the user's configuration.
.PARAMETER DataDir   Fresh installs only: keep the database/models in this folder (e.g. D:\DemandForecast\runtime).
                     If data already exists elsewhere it is NOT moved here - use scripts\migrate-storage.ps1.
.PARAMETER LogsDir / BackupsDir / ReportsDir  Optional, with -DataDir.
.PARAMETER Autostart  Also start the app automatically at logon.
#>
param([string]$DataDir, [string]$LogsDir, [string]$BackupsDir, [string]$ReportsDir,
      [switch]$Autostart, [switch]$NoShortcuts, [switch]$NoStart)
$ErrorActionPreference = "Continue"  # native tools (python, winget) write to stderr; exit codes are checked explicitly
$src = Split-Path -Parent $PSScriptRoot
$version = (Get-Content (Join-Path $src "VERSION") -Raw).Trim()
$base = Join-Path $env:LOCALAPPDATA "Programs\DemandForecast"
$dest = Join-Path $base $version
$srcPy = Join-Path $src "python\python.exe"
$env:PYTHONPATH = ""

function Get-Paths([string]$Py) {
    $out = & $Py -m app.cli paths 2>&1 | ForEach-Object { "$_" }
    return (($out -join "`n") | ConvertFrom-Json)
}

Write-Host "== Cai dat Demand Forecasting $version / installing =="
Write-Host "Chuong trinh / program: $dest"
# Storage must be consistent BEFORE anything is changed (e.g. storage.json lost after a migration to another
# drive would otherwise make the new version start on an empty database in the default folder).
$verify = & $srcPy -m app.cli storage-verify 2>&1 | ForEach-Object { "$_" }
if ($LASTEXITCODE -ne 0) {
    Write-Host ($verify -join "`n")
    Write-Host "CAU HINH LUU TRU KHONG NHAT QUAN / storage configuration problem - cai dat dung lai, khong thay doi gi." -ForegroundColor Red
    Write-Host "Neu storage.json bi mat: scripts\repair-storage.ps1 (khoi phuc tu lich su di chuyen da xac minh)." -ForegroundColor Yellow
    exit 3
}
$p = Get-Paths $srcPy
Write-Host "Database hien tai / current database: $($p.db_path) (ton tai / exists: $($p.db_exists))"
# the program folder of this version is replaced below: user data must never live inside it
$destFull = [System.IO.Path]::GetFullPath($dest).TrimEnd('\') + '\'
foreach ($d in @($p.data_dir, $p.backups_dir, $p.logs_dir, $p.reports_dir)) {
    if ($d -and ([System.IO.Path]::GetFullPath($d).TrimEnd('\') + '\').StartsWith($destFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        Write-Host "Thu muc du lieu nam trong thu muc chuong trinh ($d) - cai dat dung lai, khong thay doi gi." -ForegroundColor Red
        Write-Host "Data folder is inside the program folder - installation stopped, nothing changed." -ForegroundColor Red
        exit 5
    }
}
# the version that runs now: restarted automatically if the installation stops after it was stopped
$prevVersion = $null
$cur = Join-Path $base "current.txt"
if (Test-Path $cur) { $prevVersion = (Get-Content $cur -Raw).Trim() }
$wasRunning = Test-Path $p.runtime_file
function Stop-Install([int]$Code, [string]$Message) {
    Write-Host $Message -ForegroundColor Red
    if ($script:stopped -and $prevVersion -and ($prevVersion -ne $version)) {
        $prevStart = Join-Path $base "$prevVersion\scripts\start.ps1"
        if (Test-Path $prevStart) {
            Write-Host "Khoi dong lai phien ban truoc / restarting previous version $prevVersion" -ForegroundColor Yellow
            & $prevStart -NoBrowser
        }
    }
    exit $Code
}
$script:stopped = $false

if (-not (Test-Path "$env:WINDIR\System32\vcomp140.dll")) {
    Write-Host "Can Microsoft Visual C++ Redistributable cho LightGBM / VC++ runtime required." -ForegroundColor Yellow
    $w = Get-Command winget -ErrorAction SilentlyContinue
    if ($w) {
        winget install --id Microsoft.VCRedist.2015+.x64 --silent --accept-package-agreements --accept-source-agreements
    } else {
        Write-Host "Tai / download: https://aka.ms/vs/17/release/vc_redist.x64.exe roi chay lai / then re-run." -ForegroundColor Red
        exit 1
    }
}

# stop a running instance (any version) before switching
& (Join-Path $src "scripts\stop.ps1") | Out-Null
$script:stopped = $wasRunning
# never replace program files that are still in use (a half-deleted install could not start any more)
# both sides normalised the same way (GetFullPath expands 8.3 short names like GIAUVO~1)
$busy = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -and [System.IO.Path]::GetFullPath($_.ExecutablePath).StartsWith($destFull, [System.StringComparison]::OrdinalIgnoreCase) }
if ($busy) {
    Write-Host "Ung dung van dang chay tu $dest (pid $($busy.ProcessId -join ', ')). Dung ung dung roi chay lai; chua thay doi gi." -ForegroundColor Red
    exit 4
}
# independent of how the path is spelled: a running python.exe cannot be opened for exclusive write
$destExe = Join-Path $dest "python\python.exe"
if (($src.TrimEnd('\') -ne $dest.TrimEnd('\')) -and (Test-Path $destExe)) {
    try { $fs = [System.IO.File]::Open($destExe, 'Open', 'ReadWrite', 'None'); $fs.Close() }
    catch {
        Write-Host "$destExe dang duoc su dung (file bi khoa). Dung ung dung roi chay lai; chua thay doi gi." -ForegroundColor Red
        exit 4
    }
}

if ($p.db_exists) {
    if ($DataDir -and ((Resolve-Path -LiteralPath $p.data_dir).Path.TrimEnd('\') -ne $DataDir.TrimEnd('\'))) {
        Write-Host "Da co du lieu tai $($p.data_dir). -DataDir KHONG tu di chuyen du lieu." -ForegroundColor Yellow
        Write-Host "Dung / use: scripts\migrate-storage.ps1 -DataDir `"$DataDir`"" -ForegroundColor Yellow
    }
    # back up existing data before an upgrade (verified backup)
    & $srcPy -m app.cli backup | Out-Host
    if ($LASTEXITCODE -ne 0) { Stop-Install 1 "Pre-upgrade backup failed - installation aborted, nothing changed." }
} elseif ($DataDir) {
    $initArgs = @("-m", "app.cli", "storage-init", "--data-dir", $DataDir)
    if ($LogsDir) { $initArgs += @("--logs-dir", $LogsDir) }
    if ($BackupsDir) { $initArgs += @("--backups-dir", $BackupsDir) }
    if ($ReportsDir) { $initArgs += @("--reports-dir", $ReportsDir) }
    & $srcPy @initArgs | Out-Host
    if ($LASTEXITCODE -ne 0) { Write-Host "Khong cau hinh duoc thu muc du lieu / storage-init failed." -ForegroundColor Red; exit 1 }
}

if ($src.TrimEnd('\') -ne $dest.TrimEnd('\')) {
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force -Confirm:$false }
    New-Item -ItemType Directory -Force -Path $base | Out-Null
    Copy-Item -Recurse $src $dest
}
# schema migrations (a verified backup is taken automatically before any schema change)
& (Join-Path $dest "python\python.exe") -m app.cli migrate | Out-Host
if ($LASTEXITCODE -ne 0) {
    Stop-Install 1 "Migration that bai / failed. Du lieu chua bi xoa; phien ban truoc van la phien ban hien hanh. Xem docs\VAN-HANH.md muc Rollback."
}
# only now does the new version become the current one
Set-Content -Path (Join-Path $base "current.txt") -Value $version -Encoding ASCII

if (-not $NoShortcuts) {
    $shell = New-Object -ComObject WScript.Shell
    foreach ($loc in @([Environment]::GetFolderPath("Desktop"), (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"))) {
        $lnk = $shell.CreateShortcut((Join-Path $loc "Demand Forecasting.lnk"))
        $lnk.TargetPath = Join-Path $dest "Start.bat"
        $lnk.WorkingDirectory = $dest
        $lnk.WindowStyle = 7
        $lnk.Save()
    }
}
if ($Autostart) { & (Join-Path $dest "scripts\register-autostart.ps1") }
else {
    $task = Get-ScheduledTask -TaskName "DemandForecast" -ErrorAction SilentlyContinue
    if ($task) { & (Join-Path $dest "scripts\register-autostart.ps1") }   # keep autostart, now pointing at this version
}
& (Join-Path $dest "scripts\check-env.ps1")
if (-not $NoStart) { & (Join-Path $dest "scripts\start.ps1") }
Write-Host "Hoan tat / done. Phien ban cu (neu co) van nam trong $base de rollback." -ForegroundColor Green
