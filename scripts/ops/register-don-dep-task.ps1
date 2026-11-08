<#
.SYNOPSIS  Register the weekly cleanup task "DemandForecastCleanup" (Sundays 22:00, current Windows user, only when
           logged on). Since 08/11/2026 it runs scripts\ops\don_dep_current.ps1, which runs don_dep_dinh_ky.ps1 of the
           INSTALLED version (current.txt); -Direct keeps the old action (this folder's don_dep_dinh_ky.ps1). The report goes
           to <project>\logs\don_dep\. Default: the task runs the cleanup in DRY RUN (report only). Keep this file ASCII-only.
.PARAMETER Apply        The task runs the cleanup with -Apply (deletes the candidates).
.PARAMETER IncludeDist  The task passes -IncludeDist (dist\ retention by scripts\prune-artifacts.ps1; only with -Apply).
                        Needs -DistKeep (refused without it: prune-artifacts.ps1 without -Keep deletes the rollback package).
.PARAMETER DistKeep     Rollback version(s) x.y.z whose package dist\ keeps; passed to the task as -DistKeep "a,b".
.PARAMETER Direct       The task runs this folder's don_dep_dinh_ky.ps1 instead of the wrapper don_dep_current.ps1.
.PARAMETER Plan         Print the task definition, register / remove nothing.
.PARAMETER Unregister   Remove the task.
.PARAMETER ProjectRoot  Project (source) folder the cleanup works on (default: parent of scripts\). Refused inside
                        %LOCALAPPDATA%\Programs\DemandForecast or %LOCALAPPDATA%\DemandForecast (packaged copy: pass
                        -ProjectRoot <source folder>). Exit 2 = refused.
.EXAMPLE   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ops\register-don-dep-task.ps1 -Plan
#>
param([switch]$Apply, [switch]$IncludeDist, [switch]$Plan, [switch]$Unregister, [string]$ProjectRoot = "",
      [string[]]$DistKeep = @(), [switch]$Direct)
$ErrorActionPreference = "Stop"
$TaskName = "DemandForecastCleanup"

if ($Unregister) {
    if ($Plan) { Write-Host "Plan: remove scheduled task '$TaskName' (nothing changed)."; exit 0 }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Da go tac vu don dep / cleanup task removed ('$TaskName')."
    exit 0
}

$cleanup = Join-Path $PSScriptRoot $(if ($Direct) { "don_dep_dinh_ky.ps1" } else { "don_dep_current.ps1" })
if (-not (Test-Path -LiteralPath $cleanup -PathType Leaf)) { Write-Host "Not found: $cleanup" -ForegroundColor Red; exit 1 }
if (-not $ProjectRoot) { $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot "scripts") -PathType Container)) {
    Write-Host "ProjectRoot is not a Demand Forecasting folder (no scripts\): $ProjectRoot" -ForegroundColor Red
    exit 1
}
Add-Type -Namespace DfCleanupTask -Name Native -MemberDefinition @'
[DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
public static extern uint GetLongPathName(string shortPath, System.Text.StringBuilder longPath, uint bufferLength);
'@

function Get-LongPath([string]$Path) {
    # full path with 8.3 short names expanded (same helper as don_dep_dinh_ky.ps1); a missing part is kept as given
    $p = [IO.Path]::GetFullPath($Path)
    if ($p.Length -gt 3) { $p = $p.TrimEnd('\') }
    $rest = ""
    while ($p) {
        $sb = New-Object System.Text.StringBuilder 32768
        $n = [DfCleanupTask.Native]::GetLongPathName($p, $sb, [uint32]$sb.Capacity)
        if ($n -gt 0 -and $n -lt $sb.Capacity) {
            $l = $sb.ToString()
            if ($l.Length -gt 3) { $l = $l.TrimEnd('\') }
            if ($rest) { return [IO.Path]::Combine($l, $rest) }
            return $l
        }
        $leaf = [IO.Path]::GetFileName($p)
        $rest = if ($rest) { [IO.Path]::Combine($leaf, $rest) } else { $leaf }
        $p = [IO.Path]::GetDirectoryName($p)
    }
    return [IO.Path]::GetFullPath($Path).TrimEnd('\')
}

$ProjectRoot = Get-LongPath (Resolve-Path -LiteralPath $ProjectRoot).Path
if ($ProjectRoot.Length -le 3) {
    # a drive root is never the project folder (and "D:\" would escape the closing quote of the task argument)
    Write-Host "ProjectRoot is a drive root ($ProjectRoot): pass the project (source) folder. Nothing registered." -ForegroundColor Red
    exit 2
}
foreach ($base in @((Join-Path $env:LOCALAPPDATA "Programs\DemandForecast"), (Join-Path $env:LOCALAPPDATA "DemandForecast"))) {
    if (($ProjectRoot + '\').StartsWith((Get-LongPath $base) + '\', [StringComparison]::OrdinalIgnoreCase)) {
        Write-Host "ProjectRoot is inside $base ($ProjectRoot): pass -ProjectRoot <source folder>. Nothing registered." -ForegroundColor Red
        exit 2
    }
}
if ((Test-Path -LiteralPath (Join-Path $ProjectRoot "VERSION") -PathType Leaf) -and
    (Test-Path -LiteralPath (Join-Path (Split-Path -Parent $ProjectRoot) "current.txt") -PathType Leaf)) {
    Write-Host "ProjectRoot is an installed version folder ($ProjectRoot): pass -ProjectRoot <source folder>. Nothing registered." -ForegroundColor Red
    exit 2
}
$DistKeep = @($DistKeep | ForEach-Object { "$_".Split(',') } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
foreach ($v in $DistKeep) {
    if ($v -notmatch '^\d+\.\d+\.\d+$') { Write-Host "-DistKeep: not a version x.y.z: $v. Nothing registered." -ForegroundColor Red; exit 2 }
}
if ($IncludeDist -and $DistKeep.Count -eq 0) {
    Write-Host "-IncludeDist needs -DistKeep <rollback version> (without it prune-artifacts.ps1 deletes the rollback package). Nothing registered." -ForegroundColor Red
    exit 2
}
if ($IncludeDist -and -not $Apply) { Write-Host "-IncludeDist has no effect without -Apply (dist\ is only listed in a dry run)." -ForegroundColor Yellow }

$ps = "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
$arg = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$cleanup`" -ProjectRoot `"$($ProjectRoot.TrimEnd('\'))`""
if ($Apply) { $arg += " -Apply" }
if ($IncludeDist) { $arg += " -IncludeDist" }
if ($DistKeep.Count) { $arg += " -DistKeep `"$($DistKeep -join ',')`"" }
$user = "$env:USERDOMAIN\$env:USERNAME"
$mode = if ($Apply) { "APPLY (deletes candidates)" } else { "DRY RUN (report only)" }
$desc = "Demand Forecasting periodic cleanup, $mode; report in $ProjectRoot\logs\don_dep"

if ($Plan) {
    Write-Host "Plan (nothing registered):"
    Write-Host "  Task name : $TaskName"
    Write-Host "  User      : $user (interactive, only when logged on)"
    Write-Host "  Trigger   : weekly, Sunday 22:00 (missed run starts when available)"
    Write-Host "  Action    : $ps $arg"
    Write-Host "  Script    : $(if ($Direct) { 'this folder (-Direct)' } else { 'installed version through don_dep_current.ps1' })"
    Write-Host "  Mode      : $mode"
    Write-Host "  Settings  : time limit 2 h, battery allowed, no parallel instance"
    Write-Host "  Exists now: $([bool](Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue))"
    exit 0
}

$action = New-ScheduledTaskAction -Execute $ps -Argument $arg -WorkingDirectory $ProjectRoot
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "22:00"
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
    -Description $desc -Force | Out-Null
Write-Host "Da dang ky tac vu don dep / cleanup task registered ('$TaskName', Sunday 22:00, $mode)."
exit 0
