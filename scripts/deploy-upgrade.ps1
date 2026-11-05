<#
.SYNOPSIS  Controlled upgrade of Demand Forecasting from a portable ZIP. ASCII only.
           1. read-only prechecks (package SHA256 + VERSION, running app, storage, jobs, disk space)
           2. official online backup through the running app + verification of that backup
              (1.4.3: skipped, like the install.ps1 backup, with an accepted -VerifiedBackup / -RestoreReport)
           3. explicit confirmation BEFORE the app is stopped
           4. install.ps1 of the package (stops the app, verified backup, copy, migrations, start)
           5. post-checks (version, health, storage.json unchanged, business tables not reduced)
           Stops safely at the first failed condition. Never deletes data. Full log in <logs>\deploy-<time>.log
.PARAMETER Package         Path of DemandForecast-<version>-win64-portable.zip
.PARAMETER ExpectedSha256  SHA256 published with the package (from the report / .sha256 file)
.PARAMETER CheckOnly       Only run the read-only prechecks (nothing is written, nothing is stopped)
.PARAMETER ConfirmToken    Non-interactive confirmation: must equal UPGRADE-<version>
.PARAMETER VerifiedBackup  1.4.3: backup zip (with db/app.db) of the live database, restore-tested OK, directly in the
                           backups folder of the installation and named backup-YYYYMMDD-HHMMSS-<reason>.zip (Vietnam time,
                           at most 6 hours old). When it is accepted the two backups of the upgrade (2. online backup,
                           4. install.ps1 pre-upgrade backup) are skipped. Writes made after that backup (D0 snapshots,
                           publishes, imports, settings) are NOT in it.
.PARAMETER RestoreReport   1.4.3: JSON report of the restore test of -VerifiedBackup:
                           {"backup": "<full path of the zip>", "sha256": "<HEX>", "db_path": "<full path of the live DB>",
                            "schema_version": <MAX(version) of schema_migrations>, "integrity": "ok", "count_differences": {},
                            "models_equal_live_list": true, "model_sha_mismatch": [], "passed": true}  (extra keys allowed)
                           Any condition not met (file, path, folder, name, database, schema, SHA256, integrity, count
                           differences, passed, model checks, age, db/app.db, report older than the zip) only means: the
                           normal backups are taken.
#>
param([Parameter(Mandatory = $true)][string]$Package, [Parameter(Mandatory = $true)][string]$ExpectedSha256,
      [switch]$CheckOnly, [string]$ConfirmToken, [switch]$NoShortcuts, [string]$VerifiedBackup, [string]$RestoreReport)
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
    # 1.4.3: does the install.ps1 of the package know -SkipBackup (an older one takes its own pre-upgrade backup)
    $pkgSkip = $false
    $ie = $zip.Entries | Where-Object { $_.FullName.Replace('\', '/') -match '^DemandForecast-[^/]+/scripts/install\.ps1$' } | Select-Object -First 1
    if ($ie) {
        $r = New-Object System.IO.StreamReader($ie.Open()); $it = $r.ReadToEnd(); $r.Close()
        $ia = [System.Management.Automation.Language.Parser]::ParseInput($it, [ref]$null, [ref]$null)
        $pkgSkip = [bool]($ia.ParamBlock -and ($ia.ParamBlock.Parameters | Where-Object { $_.Name.VariablePath.UserPath -eq "SkipBackup" }))
    }
} finally { $zip.Dispose() }
# --- 1.4.3 (05/11/2026, owner): a backup restore-tested OK within the last 6 hours replaces the two backups of the
# upgrade (the online backup and the pre-upgrade backup of install.ps1): with a 10 GB database they take hours.
# Every condition must hold; otherwise the normal backups are taken (never a precheck failure). Decided once the
# installation's storage paths are known (the backup must be of THIS database and schema, in its backups folder);
# checked again right before the backup stage and right before the install
$verifiedMaxHours = 6
$restoreNote = "writes after it (D0 snapshots, publishes, imports, settings) are NOT in it - D0 values cannot be fetched again; " +
               "a restore first takes a 'pre-restore' safety backup: keep it; if this upgrade changes the schema, the newer " +
               "'pre-migration' backup (db.migrate) is the first restore point"
function Get-EntryCount($x) {
    # entries of a JSON value: absent/null/empty = 0; any other scalar counts as one entry
    if ($null -eq $x) { return 0 }
    if ($x -is [System.Management.Automation.PSCustomObject]) { return @($x.PSObject.Properties).Count }
    if ($x -is [array]) { return $x.Count }
    if ($x -is [string] -and $x -eq "") { return 0 }
    return 1
}
function Get-StampAgeHours([datetime]$Stamp) {
    # backup names carry Vietnam time (backup.py: now_vn; UTC+7, no daylight saving time)
    return ([DateTime]::UtcNow - $Stamp.AddHours(-7)).TotalHours
}
function Test-VerifiedStill($V) {
    # the accepted backup is unchanged (size, write time) and still at most 6 hours old: $null, otherwise the reason
    $f = Get-Item -LiteralPath $V.Path -ErrorAction SilentlyContinue
    if (-not $f -or $f.Length -ne $V.Length -or $f.LastWriteTime -ne $V.Written) { return "verified backup changed or removed since the prechecks" }
    $a = Get-StampAgeHours $V.Stamp
    if ($a -gt $verifiedMaxHours) { return "verified backup is now $([math]::Round($a, 2)) h old (more than $verifiedMaxHours h)" }
    return $null
}
function Test-VerifiedBackup([string]$Zip, [string]$Report, $Paths, $LiveSchema) {
    # returns the accepted backup (Path, Sha, AgeHours, Stamp, StampText, Length, Written) or the reason (a string) why
    # it is not accepted
    if (-not $Zip) { return "no -VerifiedBackup given" }
    if (-not $Report) { return "no -RestoreReport given" }
    if (-not (Test-Path -LiteralPath $Zip -PathType Leaf)) { return "backup not found: $Zip" }
    if (-not (Test-Path -LiteralPath $Report -PathType Leaf)) { return "restore report not found: $Report" }
    $zf = Get-Item -LiteralPath $Zip
    $rf = Get-Item -LiteralPath $Report
    try { $rep = Get-Content -LiteralPath $rf.FullName -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop } catch { return "restore report is not valid JSON ($($_.Exception.Message))" }
    if (-not $rep.backup) { return "restore report names no backup" }
    try { $same = [IO.Path]::GetFullPath([string]$rep.backup).TrimEnd('\') -ieq [IO.Path]::GetFullPath($zf.FullName).TrimEnd('\') } catch { $same = $false }
    if (-not $same) { return "restore report is for another file ($($rep.backup))" }
    # a restore point the backup retention keeps: directly in the backups folder, named like the app's backups
    $bdir = if ($Paths.backups_dir) { [IO.Path]::GetFullPath([string]$Paths.backups_dir).TrimEnd('\') } else { "" }
    if (-not $bdir) { return "the installation reports no backups folder" }
    if ([IO.Path]::GetDirectoryName($zf.FullName).TrimEnd('\') -ine $bdir) { return "backup is not directly in the backups folder $bdir" }
    $m = [regex]::Match($zf.Name, '^backup-(\d{8}-\d{6})-.+\.zip$', 'IgnoreCase')
    if (-not $m.Success) { return "backup name $($zf.Name) is not backup-YYYYMMDD-HHMMSS-<reason>.zip" }
    try { $stamp = [DateTime]::ParseExact($m.Groups[1].Value, 'yyyyMMdd-HHmmss', [Globalization.CultureInfo]::InvariantCulture) } catch { return "backup name $($zf.Name) has no valid time stamp" }
    $stampText = $stamp.ToString('yyyy-MM-dd HH:mm:ss')
    # the backup is of THIS database, at its current schema
    if (-not $rep.db_path) { return "restore report names no database (db_path)" }
    try { $sameDb = [IO.Path]::GetFullPath([string]$rep.db_path).TrimEnd('\') -ieq [IO.Path]::GetFullPath([string]$Paths.db_path).TrimEnd('\') } catch { $sameDb = $false }
    if (-not $sameDb) { return "backup is of another database ($($rep.db_path); live $($Paths.db_path))" }
    if ($null -eq $LiveSchema) { return "schema version of the live database not readable" }
    $rs = $rep.schema_version
    if ($null -eq $rs -or "$rs" -notmatch '^\d+$' -or [int]"$rs" -ne $LiveSchema) {
        return "backup schema version $(if ($null -eq $rs) { 'missing' } else { $rs }) differs from the live database ($LiveSchema)"
    }
    if ([string]$rep.integrity -ne "ok") { return "restore test integrity '$($rep.integrity)' (expected ok)" }
    $nDiff = Get-EntryCount $rep.count_differences
    if ($nDiff) { return "restore test reported $nDiff count difference(s)" }
    # the model results of the restore test: "passed" is required; the two model keys only when present
    if (-not ($rep.passed -is [bool] -and $rep.passed)) { return "restore test passed is not true ($(if ($null -eq $rep.passed) { 'missing' } else { $rep.passed }))" }
    $nMis = Get-EntryCount $rep.model_sha_mismatch
    if ($nMis) { return "restore test reported $nMis model SHA256 mismatch(es)" }
    if ($rep.PSObject.Properties["models_equal_live_list"] -and -not ($rep.models_equal_live_list -is [bool] -and $rep.models_equal_live_list)) {
        return "restored models differ from the live model list (models_equal_live_list $($rep.models_equal_live_list))"
    }
    # the age comes from the time stamp in the name (a copy or a touch changes the write time, not the content)
    $age = Get-StampAgeHours $stamp
    if ($age -lt 0) { return "backup time stamp $stampText is in the future" }
    if ($age -gt $verifiedMaxHours) { return "backup age $([math]::Round($age, 2)) h (allowed 0-$verifiedMaxHours h)" }
    if ($rf.LastWriteTime -lt $zf.LastWriteTime) { return "restore report is older than the backup" }
    try {
        $vz = [System.IO.Compression.ZipFile]::OpenRead($zf.FullName)
        try { $hasDb = [bool]($vz.Entries | Where-Object { $_.FullName.Replace('\', '/') -eq 'db/app.db' }) } finally { $vz.Dispose() }
    } catch { return "backup is not a readable zip ($($_.Exception.Message))" }
    if (-not $hasDb) { return "backup has no db/app.db" }
    Info "computing SHA-256 of the backup (can take minutes)..."
    $h = (Get-FileHash -LiteralPath $zf.FullName -Algorithm SHA256).Hash
    if ($h -ine ([string]$rep.sha256).Trim()) { return "backup SHA256 $h differs from the restore report ($($rep.sha256))" }
    return [pscustomobject]@{ Path = $zf.FullName; Sha = $h; AgeHours = $age; Stamp = $stamp; StampText = $stampText
                              Length = $zf.Length; Written = $zf.LastWriteTime }
}
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
$verified = $null
if ($VerifiedBackup -or $RestoreReport) {
    # schema version of the live database: read-only (mode=ro) with the stdlib sqlite3 of the installed runtime, run from
    # its own backend folder (no double quotes in the code: Windows PowerShell 5.1 native arguments)
    $liveSchema = $null
    Push-Location $prevBackend
    try {
        $sv = & $prevPy -c "import sqlite3,sys,pathlib; c=sqlite3.connect(pathlib.Path(sys.argv[1]).as_uri()+'?mode=ro',uri=True); print(c.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]); c.close()" $paths.db_path 2>$null
        $svLast = "$(@($sv)[-1])".Trim()
        if ($LASTEXITCODE -eq 0 -and $svLast -match '^\d+$') { $liveSchema = [int]$svLast }
    } finally { Pop-Location }
    $vb = Test-VerifiedBackup $VerifiedBackup $RestoreReport $paths $liveSchema
    if ($vb -is [string]) { Info "verified backup not accepted: $vb - normal backups" }
    else {
        $verified = $vb
        $skipped = if ($pkgSkip) { "the two backups are skipped" } else { "only the online backup is skipped (install.ps1 of the package has no -SkipBackup: it takes its own pre-upgrade backup)" }
        Ok "verified backup $(Split-Path -Leaf $vb.Path) (taken $($vb.StampText) Vietnam time, age $([math]::Round($vb.AgeHours, 2)) h, schema $liveSchema, restore test ok): $skipped"
        Info "restore point: verified backup $($vb.Path) taken $($vb.StampText); $restoreNote"
    }
}
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
$restorePoint = ""
try {
    Write-Host "== backup (official, online) =="
    if (-not $running) { throw "the app must be running for the online backup (start it, then run again)" }
    if ($verified) {
        # 1.4.3: checked again - the prechecks (storage-verify of a 10 GB database) can take long
        $why = Test-VerifiedStill $verified
        if ($why) { Write-Host "${why}: normal backups"; $verified = $null }
        else {
            Write-Host "backup: skipped, verified backup $($verified.Path) sha256 $($verified.Sha)"
            $restorePoint = " (restore point: verified backup $($verified.Path) taken $($verified.StampText); $restoreNote)"
        }
    }
    if (-not $verified) {
        # 1.4.2: 3600 s (was 600): the online backup of a 9.4 GB database takes about 20 min, longer under memory pressure
        # (04/11/2026: the 1.4.1 deploy stopped here with "The operation has timed out")
        $b = Invoke-RestMethod -Method Post "$baseUrl/api/system/backups" -Headers @{ "X-DF-Client" = "web" } -TimeoutSec 3600 -ErrorAction Stop
        $bz = Join-Path $b.dir $b.file
        $z2 = [System.IO.Compression.ZipFile]::OpenRead($bz)
        try { if (-not ($z2.Entries | Where-Object { $_.FullName -eq "db/app.db" })) { throw "backup has no db/app.db" } } finally { $z2.Dispose() }
        Write-Host "backup: $bz sha256 $((Get-FileHash $bz).Hash)"
    }
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
    $instPs1 = Join-Path $inst.FullName "scripts\install.ps1"
    $instArgs = @{}
    if ($NoShortcuts) { $instArgs.NoShortcuts = $true }
    if ($verified) {
        # 1.4.3: an install.ps1 without -SkipBackup (older package) would refuse the parameter: it then takes its own backup
        $instParams = try { (Get-Command -Name $instPs1 -ErrorAction Stop).Parameters } catch { $null }
        # checked once more right before the install: the confirmation and the staging can take long
        $why = Test-VerifiedStill $verified
        if (-not ($instParams -and $instParams.ContainsKey("SkipBackup"))) { Write-Host "install.ps1 of the package has no -SkipBackup: it takes its own pre-upgrade backup" }
        elseif ($why) { Write-Host "${why}: install.ps1 takes its own pre-upgrade backup" }
        else {
            $instArgs.SkipBackup = $true
            # install.ps1 honours -SkipBackup only with this variable naming an existing file (never on a manual call)
            $env:DF_DEPLOY_VERIFIED_BACKUP = $verified.Path
        }
    }
    try { & $instPs1 @instArgs } finally { $env:DF_DEPLOY_VERIFIED_BACKUP = $null }   # removed, also on error
    if ($LASTEXITCODE -ne 0) { throw "install.ps1 failed with code $LASTEXITCODE (the previous version was restarted if it had been stopped)" }
    Write-Host "== post-checks =="
    $h2 = Invoke-RestMethod "$baseUrl/api/health" -TimeoutSec 30 -ErrorAction Stop
    if ($h2.version -ne $newVersion) { throw "running version $($h2.version), expected $newVersion" }
    $after = Invoke-RestMethod "$baseUrl/api/system/status" -ErrorAction Stop
    if ($after.data_dir -ne $before.data_dir) { throw "data folder changed: $($before.data_dir) -> $($after.data_dir)" }
    if ($after.active_source -ne $before.active_source) { throw "active source changed: $($before.active_source) -> $($after.active_source)" }
    if ($sjHash -and ((Get-FileHash $sj).Hash -ne $sjHash)) { throw "storage.json changed" }
    Write-Host "UPGRADE OK: $prev -> $newVersion. Rollback if needed: scripts\rollback-version.ps1 -To $prev$restorePoint" -ForegroundColor Green
    $code = 0
} catch {
    Write-Host "UPGRADE STOPPED: $($_.Exception.Message)$restorePoint" -ForegroundColor Red
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
