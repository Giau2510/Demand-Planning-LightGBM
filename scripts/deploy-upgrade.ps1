<#
.SYNOPSIS  Controlled upgrade of Demand Forecasting from a portable ZIP. ASCII only.
           1. read-only prechecks (package SHA256 + VERSION, running app, storage, jobs, disk space)
           2. official online backup through the running app + verification of that backup
           3. explicit confirmation BEFORE the app is stopped
           4. install.ps1 of the package (stops the app, verified backup, copy, migrations, start)
           5. post-checks (version, health, storage.json unchanged, business tables not reduced)
           Stops safely at the first failed condition. Never deletes data. Full log in <logs>\deploy-<time>.log
.PARAMETER Package         Path of DemandForecast-<version>-win64-portable.zip
.PARAMETER ExpectedSha256  SHA256 published with the package (from the report / .sha256 file)
.PARAMETER CheckOnly       Only run the read-only prechecks (nothing is written, nothing is stopped)
.PARAMETER ConfirmToken    Non-interactive confirmation: must equal UPGRADE-<version>
#>
param([Parameter(Mandatory = $true)][string]$Package, [Parameter(Mandatory = $true)][string]$ExpectedSha256,
      [switch]$CheckOnly, [string]$ConfirmToken, [switch]$NoShortcuts)
$ErrorActionPreference = "Continue"   # native tools log to stderr; exit codes are checked explicitly
$base = Join-Path $env:LOCALAPPDATA "Programs\DemandForecast"
$fails = New-Object System.Collections.ArrayList
function Ok([string]$m) { Write-Host "  [OK]   $m" -ForegroundColor Green }
function Bad([string]$m) { Write-Host "  [FAIL] $m" -ForegroundColor Red; [void]$fails.Add($m) }
function Info([string]$m) { Write-Host "  [..]   $m" }
# 1.2.14: the package is unpacked into one managed staging folder, removed at the end only when the upgrade passed
. "$PSScriptRoot\_deploy_staging.ps1"

Write-Host "== Demand Forecasting - kiem tra truoc nang cap / upgrade prechecks =="
# the installation is per Windows account (%LOCALAPPDATA%): every check below reads THIS account's installation
Info "Windows account: $env:USERNAME, installation folder: $base"
# --- package
if (-not (Test-Path -LiteralPath $Package)) { Bad "package not found: $Package"; exit 2 }
$pkgFull = (Resolve-Path -LiteralPath $Package).Path
$sha = (Get-FileHash -LiteralPath $pkgFull -Algorithm SHA256).Hash
if ($sha -ne $ExpectedSha256.Trim().ToUpper()) { Bad "SHA256 mismatch: $sha (expected $ExpectedSha256)" } else { Ok "package SHA256 $sha" }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($pkgFull)
try {
    # Compress-Archive (Windows PowerShell 5.1) writes entry names with backslashes: normalise before matching
    $ver = $zip.Entries | Where-Object { $_.FullName.Replace('\', '/') -match '^DemandForecast-[^/]+/VERSION$' } | Select-Object -First 1
    if (-not $ver) { Bad "VERSION file missing in the package" ; $newVersion = "?" }
    else { $r = New-Object System.IO.StreamReader($ver.Open()); $newVersion = $r.ReadToEnd().Trim(); $r.Close(); Ok "package version $newVersion" }
    $bad = $zip.Entries | Where-Object { $_.Name -match '(?i)(application_default_credentials|client_secret.*\.json|service.?account.*\.json|\.env$)' }
    if ($bad) { Bad "package contains credential-like files: $($bad.FullName -join ', ')" } else { Ok "no credential files in the package" }
} finally { $zip.Dispose() }
# --- currently installed / running version
$prev = $null
$cur = Join-Path $base "current.txt"
if (Test-Path $cur) { $prev = (Get-Content $cur -Raw).Trim() }
if (-not $prev) { Bad "no installed version found ($cur)"; exit 2 }
$prevPy = Join-Path $base "$prev\python\python.exe"
if (-not (Test-Path $prevPy)) { Bad "installed version $prev has no python runtime"; exit 2 }
Info "installed version: $prev"
$prevBackend = Join-Path $base "$prev\backend"
if (-not (Test-Path $prevBackend)) { Bad "installed version $prev has no backend folder"; exit 2 }
$env:PYTHONPATH = $prevBackend
# 22/10/2026 (repo script, after the 1.2.13 package): the CLI of THIS installation, run from its own backend folder - `python -m` puts the current folder first on
# sys.path, so an `app` package in the caller's folder (e.g. the backend of a source checkout) would shadow it
Push-Location $prevBackend
try {
    $pathsJson = & $prevPy -m app.cli paths 2>$null
    try { $paths = ($pathsJson -join "`n") | ConvertFrom-Json -ErrorAction Stop } catch { $paths = $null }
    if ($paths -and $paths.db_path) {
        Info "database: $($paths.db_path)"
        if (-not $paths.db_exists) { Bad "configured database not found: $($paths.db_path)" } else { Ok "database present (drive reachable)" }
        $verify = & $prevPy -m app.cli storage-verify 2>&1 | ForEach-Object { "$_" }
        if ($LASTEXITCODE -ne 0) {
            # an installation older than the storage checks has no such command: still a failure, with the likely cause
            $hint = if (($verify -join ' ') -match 'invalid choice') { " (the CLI of installed version $prev of Windows account $env:USERNAME has no storage-verify: an older, separate installation of this account?)" } else { "" }
            Bad "storage-verify failed: $($verify -join ' ')$hint"
        } else { Ok "storage-verify ok" }
    }
} finally { Pop-Location }
# without the storage paths nothing below can be checked (not even which port the app uses): stop here
if (-not ($paths -and $paths.db_path)) { Bad "the CLI of installed version $prev returned no storage paths: $((($pathsJson -join ' ') -replace '\s+', ' ').Trim())"; exit 2 }
$sj = Join-Path $env:LOCALAPPDATA "DemandForecast\storage.json"
$sjHash = if (Test-Path $sj) { (Get-FileHash $sj).Hash } else { $null }
Info "storage.json: $sj sha256 $sjHash"
$port = 8765
if (Test-Path $paths.runtime_file) { try { $port = [int]((Get-Content $paths.runtime_file -Raw | ConvertFrom-Json).port) } catch { } }
$baseUrl = "http://127.0.0.1:$port"
$running = $false
try { $h = Invoke-RestMethod "$baseUrl/api/health" -TimeoutSec 5 -ErrorAction Stop; $running = $true; Ok "running app $($h.version) on port $port" } catch { Info "app not running on port $port" }
if ($running -and $h.version -ne $prev) { Bad "running version $($h.version) differs from current.txt $prev (installation of Windows account $env:USERNAME)" }
if ($running) {
    # 22/10/2026 (repo script): the app answering on the port must be THIS account's installation (same database, same storage.json). Run
    # from another Windows account, the prechecks read that account's current.txt / CLI / storage, and an upgrade would
    # install into that account's profile while the running app stays untouched
    try {
        $rp = Invoke-RestMethod "$baseUrl/api/system/paths" -TimeoutSec 15 -ErrorAction Stop
        $norm = { param($x) if ($x) { [IO.Path]::GetFullPath([string]$x).TrimEnd('\') } else { "" } }
        $sameDb = (& $norm $rp.db_path) -ieq (& $norm $paths.db_path)
        $sameCfg = (& $norm $rp.storage_config) -ieq (& $norm $sj)
        if ($sameDb -and $sameCfg) { Ok "running app = this account's installation (same database and storage.json)" }
        else { Bad "the app on port $port is not the installation of Windows account $env:USERNAME (app: database $($rp.db_path), storage.json $($rp.storage_config); this account: database $($paths.db_path), storage.json $sj) - run the upgrade as the Windows user that runs the app" }
    } catch { Info "storage of the running app not readable ($($_.Exception.Message)): not compared" }
}
if ($running) {
    $jobs = Invoke-RestMethod "$baseUrl/api/jobs?limit=50" -TimeoutSec 10 -ErrorAction Stop
    $active = @($jobs | Where-Object { $_.status -in @("PENDING", "RUNNING") })
    if ($active.Count) { Bad "active jobs: $(($active | ForEach-Object { $_.id + ' ' + $_.job_type }) -join ', ')" } else { Ok "no active job" }
}
$dbSize = (Get-Item $paths.db_path).Length
$drive = (Get-Item $paths.db_path).PSDrive
$need = [int64](3 * $dbSize + 2 * (Get-Item $pkgFull).Length)
if ($drive.Free -lt $need) { Bad "not enough free space on $($drive.Name): ($($drive.Free) < $need bytes)" } else { Ok "free space on $($drive.Name): ok" }
if ($newVersion -eq $prev) { Info "package version equals the installed version (re-install)" }

if ($fails.Count) { Write-Host "PRECHECK FAILED - nothing was changed." -ForegroundColor Red; exit 3 }
if ($CheckOnly) { Write-Host "PRECHECK OK (check-only: nothing was changed)." -ForegroundColor Green; exit 0 }

# --- from here on things are written; everything is logged
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$log = Join-Path $paths.logs_dir "deploy-$stamp.log"
Start-Transcript -Path $log | Out-Null
$stage = $null
$stagingRoot = Get-DeployStagingRoot
$code = 1
try {
    Write-Host "== backup (official, online) =="
    if (-not $running) { throw "the app must be running for the online backup (start it, then run again)" }
    $b = Invoke-RestMethod -Method Post "$baseUrl/api/system/backups" -Headers @{ "X-DF-Client" = "web" } -TimeoutSec 600 -ErrorAction Stop
    $bz = Join-Path $b.dir $b.file
    $z2 = [System.IO.Compression.ZipFile]::OpenRead($bz)
    try { if (-not ($z2.Entries | Where-Object { $_.FullName -eq "db/app.db" })) { throw "backup has no db/app.db" } } finally { $z2.Dispose() }
    Write-Host "backup: $bz sha256 $((Get-FileHash $bz).Hash)"
    $before = Invoke-RestMethod "$baseUrl/api/system/status" -ErrorAction Stop
    Write-Host "== confirmation =="
    $want = "UPGRADE-$newVersion"
    if (-not $ConfirmToken) {
        # 22/10/2026 (repo script): keys typed while the backup ran (an Enter, a word typed too early) answer this question
        # unseen - discard them. The question goes through Write-Host: a transcript records no Read-Host prompt or answer
        try { $Host.UI.RawUI.FlushInputBuffer() } catch { }
        Write-Host "The app $prev will be STOPPED and upgraded to $newVersion. Type $want to continue:"
        $ConfirmToken = Read-Host "answer"
    }
    $ConfirmToken = $ConfirmToken.Trim()
    if ($ConfirmToken -ne $want) { throw "not confirmed (answer '$ConfirmToken', $($ConfirmToken.Length) characters, expected $want) - nothing was stopped or installed" }
    Write-Host "confirmed: $want"
    Write-Host "== install $newVersion =="
    $stage = New-DeployStaging $stagingRoot $stamp $newVersion $sha
    Expand-Archive -LiteralPath $pkgFull -DestinationPath $stage -ErrorAction Stop
    $inst = Get-ChildItem $stage -Directory | Select-Object -First 1
    if ($NoShortcuts) { & (Join-Path $inst.FullName "scripts\install.ps1") -NoShortcuts } else { & (Join-Path $inst.FullName "scripts\install.ps1") }
    if ($LASTEXITCODE -ne 0) { throw "install.ps1 failed with code $LASTEXITCODE (the previous version was restarted if it had been stopped)" }
    Write-Host "== post-checks =="
    $h2 = Invoke-RestMethod "$baseUrl/api/health" -TimeoutSec 30 -ErrorAction Stop
    if ($h2.version -ne $newVersion) { throw "running version $($h2.version), expected $newVersion" }
    $after = Invoke-RestMethod "$baseUrl/api/system/status" -ErrorAction Stop
    if ($after.data_dir -ne $before.data_dir) { throw "data folder changed: $($before.data_dir) -> $($after.data_dir)" }
    if ($after.active_source -ne $before.active_source) { throw "active source changed: $($before.active_source) -> $($after.active_source)" }
    if ($sjHash -and ((Get-FileHash $sj).Hash -ne $sjHash)) { throw "storage.json changed" }
    Write-Host "UPGRADE OK: $prev -> $newVersion. Rollback if needed: scripts\rollback-version.ps1 -To $prev" -ForegroundColor Green
    $code = 0
} catch {
    Write-Host "UPGRADE STOPPED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Rollback (if a new version is running): scripts\rollback-version.ps1 -To $prev" -ForegroundColor Yellow
    $code = 1
} finally {
    # the staging cleanup never changes the result of the upgrade: a staging folder that could not be removed is only
    # reported (the upgrade's own post-checks decide whether it is safe)
    try {
        $st = Complete-DeployStaging -Path $stage -Root $stagingRoot -Stamp $stamp -PackageSha256 $sha -Succeeded ($code -eq 0) `
                                     -NewVersion $newVersion -PrevVersion $prev -ProgramsBase $base
        if ($code -eq 0 -and $st.action -notin @('REMOVED', 'NOT_FOUND')) {
            Write-Host "WARNING: the upgrade passed its post-checks, but its staging folder was not removed ($($st.action): $($st.reason)). It can be removed by hand later: $($st.path)" -ForegroundColor Yellow
        }
    } catch { Write-Host "WARNING: staging cleanup error: $($_.Exception.Message) (staging folder: $stage)" -ForegroundColor Yellow }
    Stop-Transcript | Out-Null
    Write-Host "log: $log"
}
exit $code
