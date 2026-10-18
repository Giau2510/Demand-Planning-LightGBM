<#
.SYNOPSIS  Build the portable Windows package: dist\DemandForecast-<version>-win64-portable.zip (+ .sha256 + manifest)
           Contains an embedded CPython (python.org embeddable zip, PSF licence), all pinned wheels,
           the backend, the built UI, scripts, docs and Excel templates. Target machines need no Python/Node.
           Normally called by scripts\release.ps1 (QA first). See docs\PHAT-TRIEN-QA-PHAT-HANH.md.
.PARAMETER SkipFrontend  Reuse the existing frontend\dist build.
.PARAMETER NoZip         Only build the folder dist\DemandForecast-<version>\ (kept), no zip.
.PARAMETER KeepFolder    Keep the staging folder dist\DemandForecast-<version>\ after zipping (default: removed,
                         the zip is the artifact).
.PARAMETER AllowDirty    Build from a working tree with uncommitted changes (test build; marked "dirty": true).
.PARAMETER Force         Replace an existing package of the same version built from OTHER sources. The old
                         package is renamed ...-superseded-<time>-win64-portable.zip, never deleted.
Identity: BUILD-INFO.json in the package and the manifest record version, git commit, dirty flag and a source
fingerprint (SHA-256 of every packaged input + build settings). Same fingerprint + verified SHA256 = nothing rebuilt.
#>
param([switch]$SkipFrontend, [switch]$NoZip, [switch]$KeepFolder, [switch]$AllowDirty, [switch]$Force)
. "$PSScriptRoot\_common.ps1"
Set-Location $Root
$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Run scripts\setup-dev.ps1 first (.venv missing)" }
$version = (& $py -c "import sys; sys.path.insert(0, 'backend'); import app; print(app.__version__)").Trim()
$pyver = (& $py -c "import platform; print(platform.python_version())").Trim()
$tag = (& $py -c "import sys; print(f'{sys.version_info[0]}{sys.version_info[1]}')").Trim()
$name = "DemandForecast-$version"
$dist = Join-Path $Root "dist"
$out = Join-Path $dist $name
$zip = Join-Path $dist "$name-win64-portable.zip"
$manifestPath = Join-Path $dist "$name-win64-portable.manifest.json"
$packagedScripts = @("_common.ps1", "start.ps1", "stop.ps1", "check-env.ps1", "backup.ps1", "restore.ps1", "install.ps1",
                     "register-autostart.ps1", "unregister-autostart.ps1", "smoke_test.py",
                     "migrate-storage.ps1", "rollback-storage.ps1", "diagnose.ps1", "repair-storage.ps1",
                     "deploy-upgrade.ps1", "rollback-version.ps1", "eod-retention.ps1")

function Get-GitState {
    $ErrorActionPreference = "Continue"
    $c = & git -C $Root rev-parse HEAD 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $c) { return @{ commit = "unknown"; dirty = $true } }
    $s = & git -C $Root status --porcelain 2>$null
    return @{ commit = "$c".Trim(); dirty = [bool]$s }
}

function Get-SourceFingerprint([string[]]$Inputs, [string]$Settings) {
    # SHA-256 over "relative/path sha256" of every input file (ordinal order) + the build settings
    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($i in $Inputs) {
        $p = Join-Path $Root $i
        if (-not (Test-Path $p)) { continue }
        $files = if (Test-Path $p -PathType Leaf) { @(Get-Item $p) } else {
            Get-ChildItem $p -Recurse -File | Where-Object { $_.FullName -notmatch '\\(__pycache__|node_modules)\\' } }
        foreach ($f in $files) {
            $rel = $f.FullName.Substring($Root.Length).TrimStart('\').Replace('\', '/')
            $lines.Add("$rel $((Get-FileHash $f.FullName -Algorithm SHA256).Hash)")
        }
    }
    $arr = $lines.ToArray()
    [Array]::Sort($arr, [StringComparer]::Ordinal)
    $bytes = [Text.Encoding]::UTF8.GetBytes((($arr -join "`n") + "`n" + $Settings))
    $h = [Security.Cryptography.SHA256]::Create()
    return ([BitConverter]::ToString($h.ComputeHash($bytes))).Replace("-", "")
}

# 0. identity of this build: commit, dirty flag, source fingerprint
$git = Get-GitState
if ($git.dirty -and -not $AllowDirty) {
    throw "Uncommitted changes in the working tree (git status). A release is built from a commit: commit first, or pass -AllowDirty for a test build."
}
$inputs = @("backend\app", "backend\requirements.txt", "backend\requirements.lock.txt", "backend\requirements-dev.txt",
            "frontend\src", "frontend\index.html", "frontend\package.json", "frontend\package-lock.json",
            "frontend\vite.config.ts", "frontend\tsconfig.json", "docs", "config", "README.md", "CHANGELOG.md",
            "scripts\build-package.ps1") + ($packagedScripts | ForEach-Object { "scripts\$_" })
if ($SkipFrontend) { $inputs += "frontend\dist" }
$fingerprint = Get-SourceFingerprint $inputs "python=$pyver;embed=python-$pyver-embed-amd64.zip;tag=$tag"
Write-Host "Building $name (embedded Python $pyver), commit $($git.commit), dirty=$($git.dirty), source $($fingerprint.Substring(0, 16))"

# an existing package of this version: same sources + valid SHA256 -> done; otherwise never silently replaced
if (-not $NoZip -and (Test-Path $zip)) {
    $same = $false
    if ((Test-Path "$zip.sha256") -and (Test-Path $manifestPath)) {
        $recorded = ((Get-Content "$zip.sha256" -Raw).Trim() -split '\s+')[0].ToUpper()
        $old = Get-Content $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $same = ($old.source_fingerprint -eq $fingerprint) -and ($recorded -eq (Get-FileHash $zip -Algorithm SHA256).Hash)
    }
    if ($same) {
        Write-Host "Up to date: $zip (same sources and build settings, SHA256 verified). Nothing rebuilt." -ForegroundColor Green
        return
    }
    if (-not $Force) {
        throw "$zip already exists and was built from other sources (or cannot be verified). Raise the version in backend\app\__init__.py, or pass -Force (the old package is renamed ...-superseded-<time>, not deleted)."
    }
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    foreach ($f in @($zip, "$zip.sha256", $manifestPath)) {
        if (Test-Path $f) {
            $new = (Split-Path $f -Leaf) -replace "-win64-portable", "-superseded-$stamp-win64-portable"
            Rename-Item -LiteralPath $f -NewName $new
            Write-Host "Kept the old package as $new" -ForegroundColor Yellow
        }
    }
}

if (-not $SkipFrontend) {
    Push-Location frontend
    if (-not (Test-Path node_modules)) { npm ci }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "frontend build failed" }
    Pop-Location
}
if (-not (Test-Path "frontend\dist\index.html")) { throw "frontend\dist missing" }

if (Test-Path $out) { Remove-Item $out -Recurse -Force -Confirm:$false }
New-Item -ItemType Directory -Force -Path $out | Out-Null

# 1. embedded Python (cached between builds)
$cache = Join-Path $dist ".cache"
New-Item -ItemType Directory -Force -Path $cache | Out-Null
$embedZip = Join-Path $cache "python-$pyver-embed-amd64.zip"
if (-not (Test-Path $embedZip)) {
    $url = "https://www.python.org/ftp/python/$pyver/python-$pyver-embed-amd64.zip"
    Write-Host "Downloading $url"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $url -OutFile $embedZip -UseBasicParsing
}
$pyDir = Join-Path $out "python"
Expand-Archive -Path $embedZip -DestinationPath $pyDir -Force
$pth = Get-ChildItem $pyDir -Filter "python$tag._pth" | Select-Object -First 1
Set-Content -Path $pth.FullName -Encoding ASCII -Value @("python$tag.zip", ".", "Lib\site-packages", "..\backend", "import site")

# 2. pinned dependencies as binary wheels into the embedded runtime
$site = Join-Path $pyDir "Lib\site-packages"
New-Item -ItemType Directory -Force -Path $site | Out-Null
& $py -m pip install --disable-pip-version-check --no-compile --only-binary=:all: --target $site -r backend\requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw "pip install into the embedded runtime failed" }

# 3. application files
Copy-Item -Recurse backend\app (Join-Path $out "backend\app")
Get-ChildItem (Join-Path $out "backend") -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -Confirm:$false
Copy-Item backend\requirements*.txt (Join-Path $out "backend")
Copy-Item -Recurse frontend\dist (Join-Path $out "web")
New-Item -ItemType Directory -Force -Path (Join-Path $out "scripts") | Out-Null
foreach ($s in $packagedScripts) {
    Copy-Item (Join-Path "scripts" $s) (Join-Path $out "scripts")
}
Copy-Item -Recurse docs (Join-Path $out "docs")
Copy-Item README.md $out
Copy-Item CHANGELOG.md $out
Copy-Item -Recurse config (Join-Path $out "config")
Set-Content -Path (Join-Path $out "VERSION") -Value $version -Encoding ASCII
$buildInfo = [ordered]@{ version = $version; commit = $git.commit; dirty = $git.dirty; source_fingerprint = $fingerprint;
                         python = $pyver; built_at = (Get-Date).ToString("s") }
$buildInfo | ConvertTo-Json | Set-Content -Path (Join-Path $out "BUILD-INFO.json") -Encoding ASCII

# 4. Excel template + samples generated by the app itself
$tpl = Join-Path $out "templates"
New-Item -ItemType Directory -Force -Path $tpl | Out-Null
$env:PYTHONPATH = (Join-Path $Root "backend")
& $py -c "from app.data import excel_io, demo; import sys; d=sys.argv[1]; open(d+'/mau-nhap-du-lieu-lich-su.xlsx','wb').write(excel_io.build_template()); open(d+'/du-lieu-mau-hop-le.xlsx','wb').write(demo.sample_history_xlsx()); open(d+'/du-lieu-mau-co-loi.xlsx','wb').write(demo.sample_errors_xlsx())" $tpl

# 5. double-click launchers
$bat = '@echo off' + "`r`n" + 'powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\{0}" %*' + "`r`n"
Set-Content -Path (Join-Path $out "Start.bat") -Value ($bat -f "start.ps1") -Encoding ASCII
Set-Content -Path (Join-Path $out "Stop.bat") -Value ($bat -f "stop.ps1") -Encoding ASCII
Set-Content -Path (Join-Path $out "Check-Environment.bat") -Value (($bat -f "check-env.ps1") + "pause`r`n") -Encoding ASCII
Set-Content -Path (Join-Path $out "Install.bat") -Value (($bat -f "install.ps1") + "pause`r`n") -Encoding ASCII
Set-Content -Path (Join-Path $out "Backup.bat") -Value (($bat -f "backup.ps1") + "pause`r`n") -Encoding ASCII
Set-Content -Path (Join-Path $out "Diagnose.bat") -Value (($bat -f "diagnose.ps1") + "pause`r`n") -Encoding ASCII

# 6. verify the embedded runtime actually works (imports + LightGBM train/predict)
$env:PYTHONPATH = ""
& (Join-Path $pyDir "python.exe") -B -c "import lightgbm, numpy, pandas, fastapi, openpyxl, google.cloud.bigquery, app; import numpy as np; X=np.random.rand(200,3); b=lightgbm.train({'verbose':-1}, lightgbm.Dataset(X, X[:,0]), 5); print('embedded runtime OK, app', app.__version__, 'lightgbm', lightgbm.__version__, b.predict(X[:1]).shape)"
if ($LASTEXITCODE -ne 0) { throw "embedded runtime verification failed" }
# no development / verification bytecode caches of the app in the package
Get-ChildItem (Join-Path $out "backend") -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -Confirm:$false

if (-not $NoZip) {
    Compress-Archive -Path $out -DestinationPath $zip -CompressionLevel Optimal
    $mb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
    Write-Host "Package: $zip ($mb MB)"
    # manifest of every packaged file + SHA256 of the zip (published next to it)
    $outFull = (Resolve-Path $out).Path.TrimEnd('\') + '\'
    $files = Get-ChildItem $out -Recurse -File | ForEach-Object {
        [ordered]@{ path = $_.FullName.Substring($outFull.Length).Replace('\', '/'); bytes = $_.Length; sha256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash } }
    $zipSha = (Get-FileHash $zip -Algorithm SHA256).Hash
    $manifest = [ordered]@{ package = (Split-Path $zip -Leaf); version = $version; commit = $git.commit; dirty = $git.dirty;
                            source_fingerprint = $fingerprint; zip_sha256 = $zipSha; zip_bytes = (Get-Item $zip).Length;
                            files = @($files).Count; built_at = $buildInfo.built_at; entries = @($files) }
    $manifest | ConvertTo-Json -Depth 4 | Set-Content -Path $manifestPath -Encoding UTF8
    Set-Content -Path "$zip.sha256" -Value "$zipSha  $(Split-Path $zip -Leaf)" -Encoding ASCII
    Write-Host "SHA256:  $zipSha"
    if (-not $KeepFolder) {
        Remove-Item $out -Recurse -Force -Confirm:$false
        Write-Host "Staging folder removed (the zip is the artifact; -KeepFolder keeps it)."
    }
}
if (Test-Path $out) { Write-Host "Folder:  $out" }
