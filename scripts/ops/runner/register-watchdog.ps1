<#
.SYNOPSIS  Registers the runner watchdog (watchdog.py) as the Scheduled Task "DemandForecastRunnerWatchdog" for the
           current Windows user: at logon + every 5 minutes, only when the user is logged on, pythonw (no window).
           Each start does one read-only check of the run dir (and production GET /api/jobs), then exits.
           ASCII only (Windows PowerShell 5.1).
.EXAMPLE   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ops\runner\register-watchdog.ps1 -RunDir D:\x\run
.EXAMPLE   ... register-watchdog.ps1 -RunDir D:\x\run -StaleMinutes 15 -DebounceMinutes 30 -PlanOnly
.EXAMPLE   ... register-watchdog.ps1 -Unregister
#>
param([string]$RunDir, [string]$TaskName = "DemandForecastRunnerWatchdog", [double]$StaleMinutes = 15,
      [double]$DebounceMinutes = 30, [string]$Python, [string]$RunnerTask = "DemandForecastRunner", [switch]$NoProd,
      [string[]]$IgnorePath = @("D:\Buymed\tmp\runner_test"),
      [switch]$Unregister, [switch]$PlanOnly, [switch]$WhatIf, [switch]$Disabled)
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
if ($Unregister) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        if ($PlanOnly -or $WhatIf) { Write-Host "would unregister $TaskName"; exit 0 }
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "$TaskName unregistered"
    } else { Write-Host "$TaskName not registered" }
    exit 0
}
if (-not $RunDir) { Write-Host "-RunDir is required" -ForegroundColor Red; exit 2 }
if (-not $Python) { $Python = Join-Path (Split-Path (Split-Path (Split-Path $here))) ".venv\Scripts\pythonw.exe" }
if (-not (Test-Path $Python)) { Write-Host "python not found: $Python" -ForegroundColor Red; exit 2 }
$inv = [Globalization.CultureInfo]::InvariantCulture
$arg = "`"$(Join-Path $here 'watchdog.py')`" --run-dir `"$RunDir`" --stale-minutes $($StaleMinutes.ToString($inv)) " +
       "--debounce-minutes $($DebounceMinutes.ToString($inv))"
if ($NoProd) { $arg += " --no-prod" }
$arg += " --runner-task `"$RunnerTask`""
foreach ($p in $IgnorePath) { $arg += " --ignore-path `"$p`"" }   # known heavy processes outside the runner (e.g. E2)
$user = "$env:USERDOMAIN\$env:USERNAME"
Write-Host "Task     : $TaskName (user $user, at logon + every 5 minutes, only when logged on)"
Write-Host "Execute  : $Python"
Write-Host "Arguments: $arg"
Write-Host "WorkDir  : $here"
if ($PlanOnly -or $WhatIf) { Write-Host "(plan only, nothing registered)"; exit 0 }
$action = New-ScheduledTaskAction -Execute $Python -Argument $arg -WorkingDirectory $here
$t1 = New-ScheduledTaskTrigger -AtLogOn -User $user
$t2 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 4) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($t1, $t2) -Settings $settings -Principal $principal `
    -Description "Demand Forecasting: watchdog of the multi-step runner (scripts\ops\runner\watchdog.py)" -Force | Out-Null
if ($Disabled) { Disable-ScheduledTask -TaskName $TaskName | Out-Null }
$t = Get-ScheduledTask -TaskName $TaskName
Write-Host "$TaskName registered, state $($t.State); repetition $($t.Triggers[1].Repetition.Interval) duration '$($t.Triggers[1].Repetition.Duration)'"
