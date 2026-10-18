<#
.SYNOPSIS  90-day retention of the end-of-day forecast backup (1.2.6). ASCII only. See docs\LICH-SU-FORECAST.md section 14.
           Without -Apply: DRY RUN (read-only). Prints the plan: the snapshots, rows and business dates that would be
           deleted, the ones held back and why, and the plan_id. Nothing is written.
           With -Apply -Plan <plan_id>: deletes exactly that reviewed plan (refused when the plan changed), after a
           verified backup. A snapshot younger than 90 days (Vietnam business date) is never deleted: the database
           itself refuses it. Forecasts, the D+1 history and actual closes are never touched.
.PARAMETER Apply  Delete the snapshots of the reviewed plan.
.PARAMETER Plan   plan_id printed by the dry run that was reviewed (required with -Apply).
#>
param([switch]$Apply, [string]$Plan)
. "$PSScriptRoot\_common.ps1"
Import-AppEnv
$cli = @("eod-retention")
if ($Apply) {
    if (-not $Plan) { Write-Host "-Apply needs -Plan <plan_id> from a reviewed dry run (run without -Apply first). Nothing was changed." -ForegroundColor Red; exit 2 }
    $cli += @("--apply", "--plan", $Plan)
}
$code = Invoke-AppCli $cli
if ($Apply) { exit $code }
if ($code -eq 0) { Write-Host "Dry run: nothing was deleted. After review: scripts\eod-retention.ps1 -Apply -Plan <plan_id>" -ForegroundColor Yellow }
exit $code
