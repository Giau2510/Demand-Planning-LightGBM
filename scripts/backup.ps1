<# .SYNOPSIS  Create a backup zip (database + model files) in <data dir>\backups. Safe while the app runs. #>
. "$PSScriptRoot\_common.ps1"
Import-AppEnv
exit (Invoke-AppCli @("backup"))
