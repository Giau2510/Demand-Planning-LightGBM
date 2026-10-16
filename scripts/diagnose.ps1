<#
.SYNOPSIS  Write a diagnostic report (.md, no secrets) to the configured reports folder, or to -OutDir.
#>
param([string]$OutDir)
. "$PSScriptRoot\_common.ps1"
$cli = @("diagnose")
if ($OutDir) { $cli += @("--out", $OutDir) }
exit (Invoke-AppCli $cli)
