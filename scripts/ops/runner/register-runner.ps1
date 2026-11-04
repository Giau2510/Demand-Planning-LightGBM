<#
.SYNOPSIS  Registers the step runner (runner.py) as the Scheduled Task "DemandForecastRunner" for the current Windows
           user: at logon + every 5 minutes, only when the user is logged on (toasts, Credential Manager). The task
           starts pythonw (no window); a start while a runner is alive ends at once (named mutex per plan name), a
           finished or stopped run does nothing. ASCII only (Windows PowerShell 5.1).
.EXAMPLE   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ops\runner\register-runner.ps1 -Plan D:\x\plan.json -RunDir D:\x\run -StatusCopy "D:\Buymed\Lightgbm AI\STATUS.md"
.EXAMPLE   ... register-runner.ps1 -Plan D:\x\plan.json -RunDir D:\x\run -PlanOnly     (prints the definition only)
.EXAMPLE   ... register-runner.ps1 -Unregister
#>
param([string]$Plan, [string]$RunDir, [string]$StatusCopy, [string]$TaskName = "DemandForecastRunner",
      [string]$Python, [switch]$Unregister, [switch]$PlanOnly, [switch]$WhatIf, [switch]$Disabled)
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
if (-not $Plan -or -not $RunDir) { Write-Host "-Plan and -RunDir are required" -ForegroundColor Red; exit 2 }
$Plan = (Resolve-Path $Plan).Path
if (-not $Python) { $Python = Join-Path (Split-Path (Split-Path (Split-Path $here))) ".venv\Scripts\pythonw.exe" }
if (-not (Test-Path $Python)) { Write-Host "python not found: $Python" -ForegroundColor Red; exit 2 }
$arg = "`"$(Join-Path $here 'runner.py')`" --plan `"$Plan`" --run-dir `"$RunDir`""
if ($StatusCopy) { $arg += " --status-copy `"$StatusCopy`"" }
$user = "$env:USERDOMAIN\$env:USERNAME"
Write-Host "Task     : $TaskName (user $user, at logon + every 5 minutes, only when logged on)"
Write-Host "Execute  : $Python"
Write-Host "Arguments: $arg"
Write-Host "WorkDir  : $here"
Write-Host "Settings : no time limit, ignore new instance while running, runs on battery, start when available"
if ($PlanOnly -or $WhatIf) { Write-Host "(plan only, nothing registered)"; exit 0 }
$action = New-ScheduledTaskAction -Execute $Python -Argument $arg -WorkingDirectory $here
$t1 = New-ScheduledTaskTrigger -AtLogOn -User $user
$t2 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($t1, $t2) -Settings $settings -Principal $principal `
    -Description "Demand Forecasting: multi-step runner (scripts\ops\runner\runner.py)" -Force | Out-Null
if ($Disabled) { Disable-ScheduledTask -TaskName $TaskName | Out-Null }
$t = Get-ScheduledTask -TaskName $TaskName
Write-Host "$TaskName registered, state $($t.State); repetition $($t.Triggers[1].Repetition.Interval) duration '$($t.Triggers[1].Repetition.Duration)'"
