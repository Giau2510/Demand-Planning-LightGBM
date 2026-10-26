<#
.SYNOPSIS  Staging folders of deploy-upgrade.ps1 (dot-sourced). ASCII only.
           1.2.14: a deploy unpacks its package into ONE managed folder, <TEMP>\DemandForecast-deploy\<yyyyMMdd-HHmmss>,
           marked with .df-deploy-staging.json (kind, stamp, version, package SHA256). Only that folder of the current run is
           ever removed, and only after the upgrade passed its post-checks and nothing depends on it any more; a failed
           deploy keeps it for the investigation. Folders of earlier runs (also the old %TEMP%\DemandForecast-deploy-<stamp>
           ones) and folders without this run's marker are never touched.
#>
$script:DfStagingMarker = '.df-deploy-staging.json'
$script:DfStagingKind = 'DemandForecast-deploy-staging'

function Get-DeployStagingRoot([string]$TempDir = $env:TEMP) {
    Join-Path ([IO.Path]::GetFullPath($TempDir)) 'DemandForecast-deploy'
}

function New-DeployStaging([string]$Root, [string]$Stamp, [string]$Version, [string]$PackageSha256) {
    if ($Stamp -notmatch '^\d{8}-\d{6}$') { throw "invalid staging stamp '$Stamp'" }
    $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    New-Item -ItemType Directory -Force -Path $rootFull | Out-Null
    $path = Join-Path $rootFull $Stamp
    if (Test-Path -LiteralPath $path) { throw "staging folder already exists: $path" }
    New-Item -ItemType Directory -Path $path | Out-Null
    $marker = [ordered]@{ kind = $script:DfStagingKind; stamp = $Stamp; version = $Version; package_sha256 = $PackageSha256.ToUpper()
                          created_at = (Get-Date).ToString('o'); pid = $PID; user = $env:USERNAME }
    ($marker | ConvertTo-Json) | Set-Content -LiteralPath (Join-Path $path $script:DfStagingMarker) -Encoding ASCII
    Write-Host "staging: created $path (version $Version)"
    return $path
}

function Test-DeployStaging([string]$Path, [string]$Root, [string]$Stamp, [string]$PackageSha256) {
    # $null = $Path is the managed staging folder of THIS run; 'NOT_FOUND'; otherwise why it must not be removed
    if (-not $Path) { return 'NOT_FOUND' }
    if ($Stamp -notmatch '^\d{8}-\d{6}$') { return "invalid stamp '$Stamp'" }
    try { $full = [IO.Path]::GetFullPath($Path).TrimEnd('\'); $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\') }
    catch { return "invalid path ($($_.Exception.Message))" }
    $expected = Join-Path $rootFull $Stamp
    # canonical comparison: '..', '.', a trailing '\' or another folder never match the one managed path of this run
    if ($full -ine $expected) { return "not the managed staging folder of this run (expected $expected)" }
    if (-not (Test-Path -LiteralPath $full -PathType Container)) { return 'NOT_FOUND' }
    foreach ($p in @($rootFull, $full)) {
        if ((Get-Item -LiteralPath $p -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { return "$p is a link / junction" }
    }
    $mf = Join-Path $full $script:DfStagingMarker
    if (-not (Test-Path -LiteralPath $mf -PathType Leaf)) { return 'no staging marker: not created by deploy-upgrade' }
    try { $m = Get-Content -LiteralPath $mf -Raw | ConvertFrom-Json } catch { return 'unreadable staging marker' }
    if ($m.kind -ne $script:DfStagingKind -or $m.stamp -ne $Stamp) { return 'staging marker of another run' }
    if (-not $PackageSha256 -or $m.package_sha256 -ne $PackageSha256.ToUpper()) { return 'staging marker of another package' }
    $links = @(Get-ChildItem -LiteralPath $full -Recurse -Force -Attributes ReparsePoint -ErrorAction SilentlyContinue)
    if ($links.Count) { return "contains $($links.Count) link(s) / junction(s)" }
    return $null
}

function Remove-DeployStaging([string]$Path, [string]$Root, [string]$Stamp, [string]$PackageSha256) {
    # result.action: REMOVED | NOT_FOUND | REFUSED | KEPT_IN_USE | FAILED
    # local to this function: an "Access is denied" line of rd on stderr must give FAILED, never end the caller's script
    # (Windows PowerShell 5.1 turns native stderr into a terminating error under the caller's 'Stop')
    $ErrorActionPreference = 'Continue'
    $why = Test-DeployStaging $Path $Root $Stamp $PackageSha256
    if ($why -eq 'NOT_FOUND') {
        Write-Host "staging: nothing to remove ($Path not found)"
        return [pscustomobject]@{ action = 'NOT_FOUND'; path = $Path; reason = 'not found (already removed or never created)' }
    }
    if ($why) {
        Write-Host "staging: KEPT $Path - $why" -ForegroundColor Yellow
        return [pscustomobject]@{ action = 'REFUSED'; path = $Path; reason = $why }
    }
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $leaf = Split-Path $full -Leaf
    $busy = "$full.removing"
    if (Test-Path -LiteralPath $busy) {
        Write-Host "staging: KEPT $full - an earlier removal left $busy" -ForegroundColor Yellow
        return [pscustomobject]@{ action = 'FAILED'; path = $full; reason = "an earlier removal left $busy" }
    }
    # in-use test: renaming fails while a process has a file of the folder open (no lock is ever forced)
    try { Rename-Item -LiteralPath $full -NewName "$leaf.removing" -ErrorAction Stop }
    catch {
        Write-Host "staging: KEPT $full - in use ($($_.Exception.Message))" -ForegroundColor Yellow
        return [pscustomobject]@{ action = 'KEPT_IN_USE'; path = $full; reason = "in use: $($_.Exception.Message)" }
    }
    # the content first, the marker last: after a partial failure the folder can still be identified by a later run.
    # rd with the \\?\ prefix also removes files whose path is longer than 260 characters
    foreach ($c in @(Get-ChildItem -LiteralPath $busy -Force | Where-Object { $_.Name -ne $script:DfStagingMarker })) {
        if ($c.PSIsContainer) { & cmd.exe /d /c "rd /s /q `"\\?\$($c.FullName)`"" 2>&1 | Out-Null }
        else { Remove-Item -LiteralPath $c.FullName -Force -ErrorAction SilentlyContinue }
    }
    if (-not @(Get-ChildItem -LiteralPath $busy -Force | Where-Object { $_.Name -ne $script:DfStagingMarker }).Count) {
        Remove-Item -LiteralPath (Join-Path $busy $script:DfStagingMarker) -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $busy -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $busy) {
        $left = $busy
        try { Rename-Item -LiteralPath $busy -NewName $leaf -ErrorAction Stop; $left = $full } catch { }
        Write-Host "staging: WARNING could not remove the staging folder; what is left stays at $left" -ForegroundColor Yellow
        return [pscustomobject]@{ action = 'FAILED'; path = $left; reason = 'delete failed (access denied or a file locked during the removal)' }
    }
    Write-Host "staging: removed $full"
    return [pscustomobject]@{ action = 'REMOVED'; path = $full; reason = '' }
}

function Get-StagingProcesses([string]$Path) {
    # processes whose executable lies inside the staging folder (e.g. an app started from the unpacked package)
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\') + '\'
    @(Get-CimInstance Win32_Process -Property ProcessId, Name, ExecutablePath -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($full, [StringComparison]::OrdinalIgnoreCase) } |
        ForEach-Object { "$($_.Name) (pid $($_.ProcessId))" })
}

function Complete-DeployStaging([string]$Path, [string]$Root, [string]$Stamp, [string]$PackageSha256, [bool]$Succeeded,
                                [string]$NewVersion, [string]$PrevVersion, [string]$ProgramsBase) {
    # Called once at the end of deploy-upgrade: removes this run's staging only when the upgrade passed its post-checks,
    # the installed copy is complete, nothing runs from the staging folder and the rollback version does not need it.
    if (-not $Path) {
        Write-Host "staging: none for this run (the deploy stopped before unpacking)"
        return [pscustomobject]@{ action = 'NOT_FOUND'; path = $null; reason = 'no staging for this run' }
    }
    $keep = @()
    if (-not $Succeeded) { $keep += 'the upgrade did not complete its post-checks: kept for the investigation' }
    else {
        $cur = Join-Path $ProgramsBase 'current.txt'
        $now = if (Test-Path -LiteralPath $cur) { (Get-Content -LiteralPath $cur -Raw).Trim() } else { $null }
        if ($now -ne $NewVersion) { $keep += "current.txt is '$now', not $NewVersion" }
        $inst = Join-Path $ProgramsBase $NewVersion
        if (-not (Test-Path -LiteralPath (Join-Path $inst 'python\python.exe'))) { $keep += "installed copy $inst has no python\python.exe" }
        elseif ((Get-Item -LiteralPath $inst -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { $keep += "installed copy $inst is a link" }
        if ($PrevVersion -and $PrevVersion -ne $NewVersion -and -not (Test-Path -LiteralPath (Join-Path $ProgramsBase "$PrevVersion\python\python.exe"))) {
            $keep += "rollback version $PrevVersion is not installed in $ProgramsBase"
        }
        if (Test-Path -LiteralPath $Path) {
            $procs = Get-StagingProcesses $Path
            if ($procs.Count) { $keep += "running from the staging folder: $($procs -join ', ')" }
        }
    }
    if ($keep.Count) {
        $reason = $keep -join '; '
        $label = if ($Succeeded) { 'WARNING staging kept' } else { 'staging kept' }
        Write-Host "staging: $label at $Path - $reason" -ForegroundColor Yellow
        return [pscustomobject]@{ action = 'KEPT'; path = $Path; reason = $reason }
    }
    return Remove-DeployStaging $Path $Root $Stamp $PackageSha256
}
