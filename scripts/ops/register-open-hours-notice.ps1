<#
.SYNOPSIS  Registers open_hours_notice.py (release 1.4.5 item C5: morning phone notice when today's daily Excel has the
           flag OPEN_HOURS_LAG) as the Scheduled Task "DemandForecastOpenHoursNotice" for the current Windows user:
           daily from 07:30, repeated every 30 minutes until 11:00 (an Excel written late is still noticed), only
           when the user is logged on (toasts, phone push), start when available (a pass missed during sleep runs at
           wake). The per-day state of the script prevents a second notice the same day. The task starts pythonw (no window); the script is read-only on the DB and
           sends at most one notice per day. ASCII only (Windows PowerShell 5.1).
.EXAMPLE   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ops\register-open-hours-notice.ps1
.EXAMPLE   ... register-open-hours-notice.ps1 -PlanOnly        (prints the definition only)
.EXAMPLE   ... register-open-hours-notice.ps1 -DryRun          (task passes only log what they would send)
.EXAMPLE   ... register-open-hours-notice.ps1 -Unregister
#>
param([string]$TaskName = "DemandForecastOpenHoursNotice", [string]$At = "07:30", [int]$EveryMinutes = 30,
      [int]$ForMinutes = 210, [string]$Python,
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
$arg = "`"$(Join-Path $here 'open_hours_notice.py')`""
if ($DryRun) { $arg += " --dry-run" }
$user = "$env:USERDOMAIN\$env:USERNAME"
Write-Host "Task     : $TaskName (user $user, daily at $At, every $EveryMinutes min for $ForMinutes min, only when logged on)"
Write-Host "Execute  : $Python"
Write-Host "Arguments: $arg"
Write-Host "WorkDir  : $here"
Write-Host "Settings : 10 min time limit, ignore new instance while running, runs on battery, start when available"
if ($PlanOnly) { Write-Host "(plan only, nothing registered)"; exit 0 }
$action = New-ScheduledTaskAction -Execute $Python -Argument $arg -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$rep = New-ScheduledTaskTrigger -Once -At $At -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes) `
    -RepetitionDuration (New-TimeSpan -Minutes $ForMinutes)
$trigger.Repetition = $rep.Repetition
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "Demand Forecasting: morning notice of the open-hours lag (scripts\ops\open_hours_notice.py)" -Force | Out-Null
if ($Disabled) { Disable-ScheduledTask -TaskName $TaskName | Out-Null }
$t = Get-ScheduledTask -TaskName $TaskName
Write-Host "$TaskName registered, state $($t.State)"
