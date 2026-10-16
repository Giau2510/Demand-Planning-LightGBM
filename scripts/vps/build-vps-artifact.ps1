<#
.SYNOPSIS  Build the Linux VPS release artifact on this PC: DemandForecast-<version>-<commit7>-linux-src.tar.gz (+ .sha256)
           Contents: backend\app (no caches), backend\requirements.lock.txt, the built UI (web\), scripts\vps\,
           docs\TRIEN-KHAI-VPS.md, README.md, CHANGELOG.md, VERSION, BUILD-INFO.json. No Python runtime, no data, no
           credentials: the VPS creates a venv from the pinned lock (scripts/vps/deploy.sh). See docs\TRIEN-KHAI-VPS.md.
.PARAMETER OutDir        Where the artifact goes (default dist\).
.PARAMETER SkipFrontend  Reuse the existing frontend\dist build.
.PARAMETER AllowDirty    Test build from uncommitted changes (name ends with -dirty, replaced on every run).
#>
param([string]$OutDir = "", [switch]$SkipFrontend, [switch]$AllowDirty)
. "$PSScriptRoot\..\_common.ps1"
Set-Location $Root
$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Run scripts\setup-dev.ps1 first (.venv missing)" }
if (-not $OutDir) { $OutDir = Join-Path $Root "dist" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$version = (& $py -c "import sys; sys.path.insert(0, 'backend'); import app; print(app.__version__)").Trim()
$ErrorActionPreference = "Continue"
$commit = "$(& git rev-parse HEAD 2>$null)".Trim()
$dirty = [bool](& git status --porcelain 2>$null)
$ErrorActionPreference = "Stop"
if (-not $commit) { throw "not a git checkout: the artifact must be identified by a commit" }
if ($dirty -and -not $AllowDirty) { throw "Uncommitted changes: commit first (a release is a commit), or -AllowDirty for a test build." }
$name = "DemandForecast-$version-$($commit.Substring(0, 7))" + $(if ($dirty) { "-dirty" } else { "" }) + "-linux-src"
$tgz = Join-Path $OutDir "$name.tar.gz"
if ((Test-Path $tgz) -and (Test-Path "$tgz.sha256") -and -not $dirty) {
    $recorded = ((Get-Content "$tgz.sha256" -Raw).Trim() -split '\s+')[0].ToUpper()
    if ($recorded -eq (Get-FileHash $tgz -Algorithm SHA256).Hash) {
        Write-Host "Up to date: $tgz (same commit, SHA256 verified). Nothing rebuilt." -ForegroundColor Green
        return
    }
    throw "$tgz exists but does not match its .sha256: inspect it, nothing was replaced"
}

if (-not $SkipFrontend) {
    Push-Location frontend
    if (-not (Test-Path node_modules)) { npm ci }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "frontend build failed" }
    Pop-Location
}
if (-not (Test-Path "frontend\dist\index.html")) { throw "frontend\dist missing" }

$stage = Join-Path ([IO.Path]::GetTempPath()) "df-vps-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
$out = Join-Path $stage $name
try {
    New-Item -ItemType Directory -Force -Path (Join-Path $out "backend") | Out-Null
    Copy-Item -Recurse backend\app (Join-Path $out "backend\app")
    Get-ChildItem (Join-Path $out "backend") -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -Confirm:$false
    Copy-Item backend\requirements.lock.txt (Join-Path $out "backend")
    Copy-Item -Recurse frontend\dist (Join-Path $out "web")
    New-Item -ItemType Directory -Force -Path (Join-Path $out "scripts\vps"), (Join-Path $out "docs") | Out-Null
    Get-ChildItem scripts\vps -File | Where-Object { $_.Extension -ne ".ps1" } | Copy-Item -Destination (Join-Path $out "scripts\vps")
    Copy-Item docs\TRIEN-KHAI-VPS.md (Join-Path $out "docs")
    Copy-Item README.md, CHANGELOG.md $out
    Set-Content -Path (Join-Path $out "VERSION") -Value $version -Encoding ASCII -NoNewline
    $info = [ordered]@{ version = $version; commit = $commit; dirty = $dirty; target = "linux x86_64, CPython 3.14, venv from backend/requirements.lock.txt";
                        built_at = (Get-Date).ToString("s") }
    $info | ConvertTo-Json | Set-Content -Path (Join-Path $out "BUILD-INFO.json") -Encoding ASCII
    $bad = Get-ChildItem $out -Recurse -File | Where-Object { $_.Name -match '\.(db|db-wal|db-shm|sqlite3?|env|key|pem|p12|pfx|xlsx|csv)$' -or $_.Name -match '^(client_secret|service-account|application_default_credentials)' }
    if ($bad) { throw "forbidden file in the artifact: $($bad[0].FullName)" }
    if (Test-Path $tgz) { Remove-Item $tgz -Force -Confirm:$false }          # only a -dirty test build reaches here
    & (Join-Path $env:SystemRoot "System32\tar.exe") -czf $tgz -C $stage $name
    if ($LASTEXITCODE -ne 0) { throw "tar failed" }
} finally {
    if (Test-Path $stage) { Remove-Item $stage -Recurse -Force -Confirm:$false }
}
$sha = (Get-FileHash $tgz -Algorithm SHA256).Hash
# LF line ending: the file is checked on Linux with `sha256sum -c`
[IO.File]::WriteAllText("$tgz.sha256", "$($sha.ToLower())  $(Split-Path $tgz -Leaf)`n", (New-Object Text.ASCIIEncoding))
Write-Host "Artifact: $tgz ($([math]::Round((Get-Item $tgz).Length / 1MB, 1)) MB)"
Write-Host "SHA256:   $sha"
Write-Host "On the VPS: sudo bash scripts/vps/deploy.sh $(Split-Path $tgz -Leaf) $($sha.ToLower())"
