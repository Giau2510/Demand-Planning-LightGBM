<#
.SYNOPSIS  1.4.13: pause ONLY the D-0 slots for maintenance (1..6 hours, default 6; resumes by itself on expiry).
           Writes one schedule setting through the app CLI (history kept); the running app reads it on its next tick.
           Prints the pause end time (Vietnam time). D-1, training, day-end jobs and the forecast refresh are untouched.
#>
param([int]$Hours = 6, [string]$By = "owner")
. "$PSScriptRoot\_common.ps1"
exit (Invoke-AppCli @("d0-pause", "--hours", "$Hours", "--by", $By))
