<#
.SYNOPSIS  1.4.13: end the D-0 maintenance pause now (the D-0 slots run again from the next slot).
#>
param([string]$By = "owner")
. "$PSScriptRoot\_common.ps1"
exit (Invoke-AppCli @("d0-resume", "--by", $By))
