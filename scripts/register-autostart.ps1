<# .SYNOPSIS  Start the app automatically when the current user logs on (Windows Task Scheduler). #>
. "$PSScriptRoot\_common.ps1"
$ps = "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
$arg = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$PSScriptRoot\start.ps1`" -NoBrowser"
$action = New-ScheduledTaskAction -Execute $ps -Argument $arg
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0)
Register-ScheduledTask -TaskName "DemandForecast" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Demand Forecasting app (local scheduler)" -Force | Out-Null
Write-Host "Da dang ky tu khoi dong khi dang nhap / autostart registered (task 'DemandForecast')."
