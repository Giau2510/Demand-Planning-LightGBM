<# .SYNOPSIS  Remove the logon autostart task. #>
Unregister-ScheduledTask -TaskName "DemandForecast" -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "Da go tu khoi dong / autostart removed."
