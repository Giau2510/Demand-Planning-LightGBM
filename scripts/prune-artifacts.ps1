<#
.SYNOPSIS  Retention of BUILD ARTIFACTS in dist\ and release\ of the source folder. Dry run unless -Apply.
           Never touches: the installed versions (%LOCALAPPDATA%\Programs\DemandForecast), data, models, backups,
           checkpoints, logs, reports, dist\.cache (build cache) or anything outside dist\ and release\.
           Kept:    the package of the RUNNING version (current.txt), of the chosen stable ROLLBACK version (-Keep)
                    and of the newest -KeepLatest version(s); a folder without package or whose content differs.
           Removed: packages of other versions, superseded packages, staging folders dist\DemandForecast-<v>\ and
                    extracted copies release\DemandForecast-*\ whose every file is identical in their package.
.EXAMPLE   scripts\prune-artifacts.ps1 -Keep 1.1.6            (plan only)
           scripts\prune-artifacts.ps1 -Keep 1.1.6 -Apply     (delete what the plan lists)
#>
param([string[]]$Keep = @(), [int]$KeepLatest = 1, [switch]$Apply)
. "$PSScriptRoot\_common.ps1"
$dist = Join-Path $Root "dist"
$rel = Join-Path $Root "release"
$re = '^DemandForecast-(\d+\.\d+\.\d+)(.*?)(-win64-portable\.(zip|zip\.sha256|manifest\.json)|-linux-src\.tar\.gz(\.sha256)?)$'

function Get-Bytes($item) {
    if ($item.PSIsContainer) { return [long](Get-ChildItem $item.FullName -Recurse -File -Force | Measure-Object Length -Sum).Sum }
    return [long]$item.Length
}

$current = $null
$cur = Join-Path $env:LOCALAPPDATA "Programs\DemandForecast\current.txt"
if (Test-Path $cur) { $current = (Get-Content $cur -Raw).Trim() }
$installed = @()
$progDir = Join-Path $env:LOCALAPPDATA "Programs\DemandForecast"
if (Test-Path $progDir) { $installed = @(Get-ChildItem $progDir -Directory | ForEach-Object { $_.Name }) }

$packages = @()
if (Test-Path $dist) {
    foreach ($f in Get-ChildItem $dist -File) {
        if ($f.Name -match $re) {
            $packages += [pscustomobject]@{ item = $f; version = $Matches[1]; superseded = ($Matches[2] -match 'superseded');
                                            main = ($f.Name -match '(\.zip|\.tar\.gz)$') }
        }
    }
}
$versions = @($packages | Where-Object { $_.main -and -not $_.superseded } | ForEach-Object { $_.version } | Sort-Object -Unique |
              Sort-Object { [version]$_ } -Descending)
$protect = @{}
foreach ($v in @($versions | Select-Object -First $KeepLatest)) { $protect[$v] = "newest $KeepLatest" }
foreach ($v in $Keep) { $protect[$v] = "kept (-Keep, rollback)" }
if ($current) { $protect[$current] = "installed current version" }
$hasPackage = @{}
foreach ($p in $packages | Where-Object { $_.main }) {
    $hasPackage[$p.item.Name -replace $re, 'DemandForecast-$1$2'] = $true          # e.g. release\DemandForecast-1.1.6-build1-superseded
    if (-not $p.superseded) { $hasPackage["DemandForecast-$($p.version)"] = $true }
}

$plan = @()
foreach ($p in $packages) {
    if ($p.superseded) { $plan += [pscustomobject]@{ action = "DELETE"; path = $p.item.FullName; reason = "superseded package (never the release of its version)" } }
    elseif ($protect.ContainsKey($p.version)) { $plan += [pscustomobject]@{ action = "KEEP"; path = $p.item.FullName; reason = $protect[$p.version] } }
    else { $plan += [pscustomobject]@{ action = "DELETE"; path = $p.item.FullName; reason = "old package (not current, not -Keep, not newest $KeepLatest)" } }
}
$folders = @()
if (Test-Path $dist) { $folders += @(Get-ChildItem $dist -Directory | Where-Object { $_.Name -like "DemandForecast-*" }) }
if (Test-Path $rel) { $folders += @(Get-ChildItem $rel -Directory | Where-Object { $_.Name -like "DemandForecast-*" }) }
function Test-FolderInZip([string]$Folder, [string]$Zip) {
    # never decided on the name: every file must be in the zip with the same size and SHA-256 (bytecode caches excepted)
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $z = [IO.Compression.ZipFile]::OpenRead($Zip)
    try {
        $entries = @{}
        foreach ($e in $z.Entries) { $entries[$e.FullName.Replace('\', '/')] = $e }
        $base = (Resolve-Path -LiteralPath $Folder).Path.TrimEnd('\')
        $prefix = (Split-Path $base -Leaf) + "/"
        $h = [Security.Cryptography.SHA256]::Create()
        foreach ($f in Get-ChildItem -LiteralPath $base -Recurse -File) {
            $rp = $f.FullName.Substring($base.Length + 1).Replace('\', '/')
            if ($rp -match '(^|/)__pycache__/' -or $rp.EndsWith(".pyc")) { continue }
            $e = $entries[$prefix + $rp]
            if (-not $e -or $e.Length -ne $f.Length) { return $false }
            $s = $e.Open()
            try { $hz = [BitConverter]::ToString($h.ComputeHash($s)).Replace("-", "") } finally { $s.Close() }
            if ($hz -ne (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash) { return $false }
        }
        return $true
    } finally { $z.Dispose() }
}

foreach ($d in $folders) {
    $kind = if ($d.Parent.FullName -eq $rel) { "extracted copy" } else { "staging folder" }
    $zipFile = Join-Path $dist "$($d.Name)-win64-portable.zip"
    $inner = $d.FullName
    $sub = @(Get-ChildItem -LiteralPath $d.FullName -Directory)
    if ($kind -eq "extracted copy" -and $sub.Count -eq 1 -and -not (Test-Path (Join-Path $d.FullName "VERSION"))) { $inner = $sub[0].FullName }
    if (-not $hasPackage.ContainsKey($d.Name) -or -not (Test-Path $zipFile)) {
        $plan += [pscustomobject]@{ action = "KEEP"; path = $d.FullName; reason = "$kind WITHOUT package: keep (only copy)" }
    } elseif (Test-FolderInZip $inner $zipFile) {
        $plan += [pscustomobject]@{ action = "DELETE"; path = $d.FullName; reason = "$kind, every file identical in its package (SHA-256)" }
    } else {
        $plan += [pscustomobject]@{ action = "KEEP"; path = $d.FullName; reason = "$kind DIFFERS from its package (another build): decide manually" }
    }
}

$total = 0L
foreach ($row in $plan) {
    $b = Get-Bytes (Get-Item -LiteralPath $row.path)
    if ($row.action -eq "DELETE") { $total += $b }
    Write-Host ("{0,-6} {1,10:N1} MB  {2}  - {3}" -f $row.action, ($b / 1MB), $row.path.Substring($Root.Length + 1), $row.reason)
}
Write-Host ("Installed versions (not touched by this script): {0}; current: {1}" -f ($installed -join ", "), $current)
Write-Host ("To free: {0:N1} MB" -f ($total / 1MB))
if (-not $Keep) { Write-Host "WARNING: no rollback version given (-Keep <version>): only the running / newest packages are kept." -ForegroundColor Yellow }
if (-not $Apply) { Write-Host "Dry run: nothing deleted. Re-run with -Apply to delete the DELETE rows."; return }
foreach ($row in $plan | Where-Object { $_.action -eq "DELETE" }) {
    Remove-Item -LiteralPath $row.path -Recurse -Force -Confirm:$false
    Write-Host "deleted $($row.path)"
}
