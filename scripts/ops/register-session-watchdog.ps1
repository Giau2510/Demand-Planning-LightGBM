<#
.SYNOPSIS  Registers session_watchdog.py (Claude Code orchestrator session idle / waiting for Allow, owner 07/11) as the Scheduled Task
           "DemandForecastSessionWatchdog" for the current Windows user: at logon + every 5 minutes, only when the user is
           logged on (toasts, phone push), start when available (a pass missed during sleep runs at wake). The task
           starts pythonw (no window); a pass still running makes the next start a no-op (IgnoreNew).
           ASCII only (Windows PowerShell 5.1).
.EXAMPLE   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ops\register-night-catchup.ps1
.EXAMPLE   ... register-night-catchup.ps1 -PlanOnly        (prints the definition only)
.EXAMPLE   ... register-night-catchup.ps1 -DryRun          (task passes only log what they would do)
.EXAMPLE   ... register-night-catchup.ps1 -Unregister
#>
param([string]$TaskName = "DemandForecastSessionWatchdog", [string]$StateDir, [string]$Python,
      [switch]$DryRun, [switch]$Unregister, [switch]$PlanOnly, [switch]$Disabled)
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
if ($Unregister) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        if ($PlanOnly) { Write-Host "would unregister $TaskName"; exit 0 }
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "$TaskName unregistered"
    } else { Write-Host "$TaskName not registered" }
    exit 0
}
if (-not $Python) { $Python = Join-Path (Split-Path (Split-Path $here)) ".venv\Scripts\pythonw.exe" }
if (-not (Test-Path $Python)) { Write-Host "python not found: $Python" -ForegroundColor Red; exit 2 }
$arg = "`"$(Join-Path $here 'session_watchdog.py')`""
if ($StateDir) { $arg += " --state `"$StateDir`"" }
if ($DryRun) { $arg += " --dry-run" }
$user = "$env:USERDOMAIN\$env:USERNAME"
Write-Host "Task     : $TaskName (user $user, at logon + every 5 minutes, only when logged on)"
Write-Host "Execute  : $Python"
Write-Host "Arguments: $arg"
Write-Host "WorkDir  : $here"
Write-Host "Settings : 4 min time limit, ignore new instance while running, runs on battery, start when available"
if ($PlanOnly) { Write-Host "(plan only, nothing registered)"; exit 0 }
$action = New-ScheduledTaskAction -Execute $Python -Argument $arg -WorkingDirectory $here
$t1 = New-ScheduledTaskTrigger -AtLogOn -User $user
$t2 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 4) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($t1, $t2) -Settings $settings -Principal $principal `
    -Description "Demand Forecasting: app watch + night D-1 catch-up (scripts\ops\night_catchup.py)" -Force | Out-Null
if ($Disabled) { Disable-ScheduledTask -TaskName $TaskName | Out-Null }
$t = Get-ScheduledTask -TaskName $TaskName
Write-Host "$TaskName registered, state $($t.State); repetition $($t.Triggers[1].Repetition.Interval) duration '$($t.Triggers[1].Repetition.Duration)'"
