<#
.SYNOPSIS  Release = QA on this PC, then ONE package of a committed source, then verification of that package.
           1. the working tree must be clean (a release is a commit; -AllowDirty only for a test build)
           2. QA: scripts\run-tests.ps1 (backend pytest, frontend typecheck + vitest + build); any failure = no package
           3. scripts\build-package.ps1 (skips the build when the same sources were already packaged and verified)
           4. verification: .sha256 matches the zip, VERSION and BUILD-INFO.json inside match version / commit
           5. retention plan (dry run) of scripts\prune-artifacts.ps1 - nothing is deleted here
           Deployment is a separate, explicit step (docs\PHAT-TRIEN-QA-PHAT-HANH.md, docs\TRIEN-KHAI-VPS.md).
#>
param([switch]$AllowDirty, [switch]$Force)
. "$PSScriptRoot\_common.ps1"
Set-Location $Root
$py = Join-Path $Root ".venv\Scripts\python.exe"
$version = (& $py -c "import sys; sys.path.insert(0, 'backend'); import app; print(app.__version__)").Trim()
$ErrorActionPreference = "Continue"
$commit = "$(& git rev-parse HEAD 2>$null)".Trim()
$dirty = [bool](& git status --porcelain 2>$null)
$ErrorActionPreference = "Stop"
Write-Host "Release $version from commit $commit (dirty=$dirty)"
if ($dirty -and -not $AllowDirty) { throw "Uncommitted changes: commit (and review) first. -AllowDirty only for a test build." }

Write-Host "== QA (scripts\run-tests.ps1)" -ForegroundColor Cyan
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "run-tests.ps1")
if ($LASTEXITCODE -ne 0) { throw "QA FAILED: no package is built (see logs\development\)" }

Write-Host "== Package (scripts\build-package.ps1)" -ForegroundColor Cyan
& (Join-Path $PSScriptRoot "build-package.ps1") -SkipFrontend -AllowDirty:$AllowDirty -Force:$Force

Write-Host "== Verify" -ForegroundColor Cyan
$zip = Join-Path $Root "dist\DemandForecast-$version-win64-portable.zip"
$sha = (Get-FileHash $zip -Algorithm SHA256).Hash
$recorded = ((Get-Content "$zip.sha256" -Raw).Trim() -split '\s+')[0].ToUpper()
if ($sha -ne $recorded) { throw "SHA256 of $zip does not match its .sha256 file" }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$z = [IO.Compression.ZipFile]::OpenRead($zip)
try {
    function Read-Entry([string]$leaf) {
        $e = $z.Entries | Where-Object { $_.FullName.Replace('\', '/') -match "^DemandForecast-[^/]+/$leaf$" } | Select-Object -First 1
        if (-not $e) { throw "$leaf missing in the package" }
        $r = New-Object IO.StreamReader($e.Open())
        try { return $r.ReadToEnd() } finally { $r.Close() }
    }
    $v = (Read-Entry "VERSION").Trim()
    $bi = (Read-Entry "BUILD-INFO.json") | ConvertFrom-Json
} finally { $z.Dispose() }
if ($v -ne $version -or $bi.version -ne $version) { throw "VERSION in the package ($v / $($bi.version)) is not $version" }
if ($bi.commit -ne $commit -or [bool]$bi.dirty -ne $dirty) { throw "package was built from $($bi.commit) dirty=$($bi.dirty), not $commit dirty=$dirty" }
Write-Host "OK  $zip"
Write-Host "    SHA256 $sha"
Write-Host "    commit $($bi.commit) dirty=$($bi.dirty) source $($bi.source_fingerprint.Substring(0, 16))"

Write-Host "== Retention plan (nothing deleted)" -ForegroundColor Cyan
& (Join-Path $PSScriptRoot "prune-artifacts.ps1")
Write-Host ""
Write-Host "Next (explicit, separate): this PC  -> scripts\deploy-upgrade.ps1 -Package `"$zip`" -ExpectedSha256 $sha -CheckOnly"
Write-Host "                           VPS      -> docs\TRIEN-KHAI-VPS.md"
