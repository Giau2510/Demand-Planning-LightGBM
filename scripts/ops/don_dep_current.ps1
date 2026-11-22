<#
.SYNOPSIS  Stable entry point of the weekly cleanup (owner 08/11/2026): runs scripts\ops\don_dep_dinh_ky.ps1 of the
           INSTALLED version (%LOCALAPPDATA%\Programs\DemandForecast\<current.txt>\scripts\ops\) with the arguments given
           here, so the task never runs an old copy of the rules. Keep this file ASCII-only.
           Refused (exit 2, nothing run): current.txt missing / unreadable / not a version x.y.z, or that version has no
           scripts\ops\don_dep_dinh_ky.ps1. Otherwise the exit code is the cleanup's (0 ok, 1 error, 2 refused).
           -ProjectRoot default: the folder holding this scripts\ folder (the cleanup refuses an installed version folder).
           <ProjectRoot>\scripts\ops\don_dep_giu.txt / don_dep_ket_luan.txt, when present, are passed as -KeepListFile /
           -ConcludedListFile (only to an installed script that has these parameters); else the installed copies are used.
           Plan lock (1.4.15, owner 19/11/2026): -PlanHash / -KeepListHash (PLAN_HASH / KEEP_LIST_SHA256 of the approved
           dry run) are passed on to an installed script that has these parameters. -Apply is refused (exit 2, nothing
           run) when the installed script does not declare -KeepListMaster, -PlanHash and -KeepListHash in its param
           block (read with the PowerShell parser) or cannot be parsed: 1.4.0 - 1.4.14 delete without these checks. A
           dry run (no -Apply) still runs an older script.
           -Groups a,b (1.4.15; "a,b" one string through -File, or an array, like -DistKeep) is passed on as one comma
           list. Refused (exit 2, nothing run, never the default groups instead) when -Groups is given but empty or the
           installed script has no -Groups parameter (or cannot be parsed). An unknown group name: the cleanup refuses it
           (exit 2). The plan (PLAN_HASH) depends on the groups: -Apply needs the same -Groups as the dry run.
.EXAMPLE   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ops\don_dep_current.ps1 -ProjectRoot "D:\Buymed\Lightgbm AI"
           ... the same + -Apply -PlanHash <PLAN_HASH> -KeepListHash <KEEP_LIST_SHA256>    (delete the approved plan)
.EXAMPLE   ... don_dep_current.ps1 -ProjectRoot "D:\Buymed\Lightgbm AI" -Groups backups                  (dry run, backups only)
           ... the same -Groups backups + -Apply -PlanHash <PLAN_HASH> -KeepListHash <KEEP_LIST_SHA256>
#>
param([string]$ProjectRoot = "", [switch]$Apply, [switch]$IncludeDist, [string[]]$DistKeep = @(), [string]$TmpRoot = "",
      [string]$PlanHash = "", [string]$KeepListHash = "", [string[]]$Groups = @())
function Get-ArgPath([string]$Path) {
    # a trailing \ before the closing quote would escape it on the child command line; a drive root keeps its \
    if ($Path.Length -le 3) { return $Path }
    return $Path.TrimEnd('\')
}
$ErrorActionPreference = "Stop"

$progDir = Join-Path $env:LOCALAPPDATA "Programs\DemandForecast"
$cur = Join-Path $progDir "current.txt"
if (-not (Test-Path -LiteralPath $cur -PathType Leaf)) { Write-Host "current.txt not found: $cur. Nothing run." -ForegroundColor Red; exit 2 }
try { $ver = "$(Get-Content -LiteralPath $cur -Raw -ErrorAction Stop)".Trim() }
catch { Write-Host "current.txt unreadable: $cur. Nothing run." -ForegroundColor Red; exit 2 }
if ($ver -notmatch '^\d+\.\d+\.\d+$') { Write-Host "current.txt holds no version x.y.z: $cur. Nothing run." -ForegroundColor Red; exit 2 }
$script = Join-Path $progDir "$ver\scripts\ops\don_dep_dinh_ky.ps1"
if (-not (Test-Path -LiteralPath $script -PathType Leaf)) {
    Write-Host "Installed version $ver has no scripts\ops\don_dep_dinh_ky.ps1 ($script). Nothing run." -ForegroundColor Red
    exit 2
}
# parameters declared by the installed script (syntax tree, not a text search); $null = it cannot be parsed
$params = $null
try {
    $perr = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($script, [ref]$null, [ref]$perr)
    if (-not @($perr).Count) {
        $params = @()
        if ($ast.ParamBlock) { $params = @($ast.ParamBlock.Parameters | ForEach-Object { $_.Name.VariablePath.UserPath }) }
    }
} catch { $params = $null }
$hasLock = ($null -ne $params) -and (@("KeepListMaster", "PlanHash", "KeepListHash" | Where-Object { $params -notcontains $_ }).Count -eq 0)
if ($Apply -and -not $hasLock) {
    $why = if ($null -eq $params) { "cannot be parsed" } else { "has no -KeepListMaster / -PlanHash / -KeepListHash (keep list and plan lock missing)" }
    Write-Host "-Apply refused: the installed cleanup of version $ver $why ($script). Nothing run." -ForegroundColor Red
    exit 2
}
# -Groups: passed on only to an installed script that declares it (else the default groups would run instead)
$grp = @($Groups | ForEach-Object { "$_".Split(',') } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if ($PSBoundParameters.ContainsKey("Groups") -and -not $grp.Count) {
    Write-Host "-Groups refused: no group name given. Nothing run." -ForegroundColor Red
    exit 2
}
if ($grp.Count -and -not (($null -ne $params) -and ($params -contains "Groups"))) {
    $why = if ($null -eq $params) { "cannot be parsed" } else { "has no -Groups parameter" }
    Write-Host "-Groups refused: the installed cleanup of version $ver $why ($script). Nothing run." -ForegroundColor Red
    exit 2
}
if (-not $ProjectRoot) { $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }
$argList = @("-ProjectRoot", (Get-ArgPath $ProjectRoot))
if ($TmpRoot) { $argList += @("-TmpRoot", (Get-ArgPath $TmpRoot)) }
# the reports lists of the source folder win over the installed copy (owner 08/11), when the installed script reads them
$takesLists = [bool](Select-String -LiteralPath $script -SimpleMatch -Pattern '$ConcludedListFile' -Quiet)
foreach ($x in @(@("-KeepListFile", "don_dep_giu.txt"), @("-ConcludedListFile", "don_dep_ket_luan.txt"))) {
    $f = Join-Path $ProjectRoot "scripts\ops\$($x[1])"
    if ($takesLists -and (Test-Path -LiteralPath $f -PathType Leaf)) { $argList += @($x[0], (Get-ArgPath $f)) }
}
if ($Apply) { $argList += "-Apply" }
if ($IncludeDist) { $argList += "-IncludeDist" }
$keep = @($DistKeep | ForEach-Object { "$_".Split(',') } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if ($keep.Count) { $argList += @("-DistKeep", ($keep -join ',')) }
if ($grp.Count) { $argList += @("-Groups", ($grp -join ',')) }
if ($hasLock -and $PlanHash) { $argList += @("-PlanHash", $PlanHash.Trim()) }
if ($hasLock -and $KeepListHash) { $argList += @("-KeepListHash", $KeepListHash.Trim()) }
Write-Host "Installed version $ver`: $script"
$ps = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
& $ps -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $script @argList
exit $LASTEXITCODE
