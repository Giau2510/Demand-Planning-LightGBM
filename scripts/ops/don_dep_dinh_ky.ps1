<#
.SYNOPSIS  Periodic cleanup (owner rules 03/11/2026). DRY RUN unless -Apply. Keep this file ASCII-only.
           Groups and rules (everything not listed as a candidate stays):
             backups  <project>\backups: keep the 7 newest *-manual.zip, the 7 newest *-cli.zip, every other backup
                      (*-pre-*.zip) younger than 30 days, the newest backup taken before each install (version folder
                      creation time under %LOCALAPPDATA%\Programs\DemandForecast, remembered in
                      <project>\logs\don_dep\install-history.json once seen), every backup taken within 20 min
                      before an install and a cli backup taken right after a manual one (deploy pair); a kept zip keeps
                      its .sha256 / config-* companions. The other backup zips (+ their companions) are candidates.
             exports  <data>\exports\du_bao\YYYYMMDD\ folders older than 90 days (folder date). <data> = data_dir of
                      %LOCALAPPDATA%\DemandForecast\storage.json (read only); unreadable -> group skipped.
             logs     <data> log folder and <project>\logs\** files older than 30 days: added to
                      logs-archive-YYYYMM.zip next to them (verified) BEFORE deletion; a file in use is never touched.
             tmp      -TmpRoot (default D:\Buymed\tmp) entries older than 1 day (newest creation / last write time of the
                      entry and, for a folder, of everything in it) that no running process names on its command line.
             reports  <project>\reports\<folder> with a package* subfolder: data files (.parquet, .csv, .zip,
                      order_lines*) outside the package folder(s); folders in scripts\ops\don_dep_giu.txt are excluded.
             dist     plan of scripts\prune-artifacts.ps1 (dry run); deleted only with -Apply -IncludeDist -DistKeep
                      <rollback version(s)> (-IncludeDist without -DistKeep is refused: no -Keep = rollback package gone).
                      prune-artifacts.ps1 is not run at all (plan or apply) while anything under dist\ / release\ is a
                      junction / symlink or unreadable (it recurses through junctions).
           Never: follows or deletes through a junction / symlink: a group root or a candidate that is, or lies under,
           a reparse point (any parent up to the drive root) is reported and skipped; touches the live DB, models,
           %LOCALAPPDATA%\DemandForecast, %LOCALAPPDATA%\Programs\DemandForecast, checkpoints\, dist\ (except through
           prune-artifacts.ps1 with -IncludeDist). Refuses a ProjectRoot inside %LOCALAPPDATA%\Programs\DemandForecast
           or %LOCALAPPDATA%\DemandForecast (a packaged copy: pass -ProjectRoot <source folder>; 8.3 short names are
           expanded first) or holding VERSION with current.txt next to it; a -TmpRoot that is a drive root or the
           project / data / %LOCALAPPDATA% folder or one of their parents.
           Report: <project>\logs\don_dep\don_dep-YYYYMMDD-HHMMSS.json (+ .txt). Exit 0 ok, 1 error, 2 refused.
.EXAMPLE   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ops\don_dep_dinh_ky.ps1            (plan only)
           powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ops\don_dep_dinh_ky.ps1 -Apply     (delete)
           ... -Apply -IncludeDist -DistKeep 1.3.1      (also dist\ retention, keeping the 1.3.1 rollback package)
#>
param([string]$ProjectRoot = "", [switch]$Apply, [switch]$IncludeDist, [string[]]$DistKeep = @(),
      [string]$TmpRoot = "D:\Buymed\tmp")       # owner rule: the only folder on D: this script cleans (tests pass their own)
$ErrorActionPreference = "Stop"
$Now = Get-Date
$Today = $Now.Date
$Inv = [Globalization.CultureInfo]::InvariantCulture

# -DistKeep "1.3.1,1.2.14" (one string through -File / the scheduled task) or an array
$DistKeep = @($DistKeep | ForEach-Object { "$_".Split(',') } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
foreach ($v in $DistKeep) {
    if ($v -notmatch '^\d+\.\d+\.\d+$') { Write-Host "-DistKeep: not a version x.y.z: $v. Nothing done." -ForegroundColor Red; exit 2 }
}
if ($IncludeDist -and $DistKeep.Count -eq 0) {
    Write-Host "-IncludeDist needs -DistKeep <rollback version> (without it prune-artifacts.ps1 deletes the rollback package). Nothing done." -ForegroundColor Red
    exit 2
}
Add-Type -Namespace DfCleanup -Name Native -MemberDefinition @'
[DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
public static extern uint GetLongPathName(string shortPath, System.Text.StringBuilder longPath, uint bufferLength);
'@

function Get-LongPath([string]$Path) {
    # full path with 8.3 short names (C:\Users\GIAUVO~1\...) expanded, so that every prefix check compares one form;
    # a part that does not exist (yet) is kept as given
    $p = [IO.Path]::GetFullPath($Path)
    if ($p.Length -gt 3) { $p = $p.TrimEnd('\') }
    $rest = ""
    while ($p) {
        $sb = New-Object System.Text.StringBuilder 32768
        $n = [DfCleanup.Native]::GetLongPathName($p, $sb, [uint32]$sb.Capacity)
        if ($n -gt 0 -and $n -lt $sb.Capacity) {
            $l = $sb.ToString()
            if ($l.Length -gt 3) { $l = $l.TrimEnd('\') }
            if ($rest) { return [IO.Path]::Combine($l, $rest) }
            return $l
        }
        $leaf = [IO.Path]::GetFileName($p)
        $rest = if ($rest) { [IO.Path]::Combine($leaf, $rest) } else { $leaf }
        $p = [IO.Path]::GetDirectoryName($p)
    }
    return [IO.Path]::GetFullPath($Path).TrimEnd('\')
}

function Test-Under([string]$Path, [string]$Base) {
    # $Path equals $Base or lies under it (both long full paths, case-insensitive)
    return ($Path.TrimEnd('\') + '\').StartsWith($Base.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)
}

$TmpRoot = Get-LongPath $TmpRoot
$LocalApp = Get-LongPath (Join-Path $env:LOCALAPPDATA "DemandForecast")
$ProgDir = Get-LongPath (Join-Path $env:LOCALAPPDATA "Programs\DemandForecast")

if (-not $ProjectRoot) { $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot "scripts") -PathType Container)) {
    Write-Host "ProjectRoot is not a Demand Forecasting folder (no scripts\): $ProjectRoot" -ForegroundColor Red
    exit 1
}
$ProjectRoot = Get-LongPath (Resolve-Path -LiteralPath $ProjectRoot).Path
foreach ($base in @($ProgDir, $LocalApp)) {
    # a packaged copy (<installed version>\scripts\ops) would otherwise clean the installation folder
    if (Test-Under $ProjectRoot $base) {
        Write-Host "ProjectRoot is inside $base ($ProjectRoot): pass -ProjectRoot <source folder>. Nothing done." -ForegroundColor Red
        exit 2
    }
}
if ((Test-Path -LiteralPath (Join-Path $ProjectRoot "VERSION") -PathType Leaf) -and
    (Test-Path -LiteralPath (Join-Path (Split-Path -Parent $ProjectRoot) "current.txt") -PathType Leaf)) {
    # an installed version folder elsewhere (VERSION + current.txt next to it), e.g. another %LOCALAPPDATA%
    Write-Host "ProjectRoot is an installed version folder ($ProjectRoot): pass -ProjectRoot <source folder>. Nothing done." -ForegroundColor Red
    exit 2
}
$HistFile = Join-Path $ProjectRoot "logs\don_dep\install-history.json"
$Script:InstallHistory = $null

function Test-Reparse($Item) { return [bool]($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) }

function Get-ReparseInChain([string]$Path) {
    # the path itself or the first parent (up to the drive root) that is a junction / symlink, else $null;
    # GetAttributes reads the link itself (never its target); a part that cannot be read counts as one
    $p = [IO.Path]::GetFullPath($Path)
    if ($p.Length -gt 3) { $p = $p.TrimEnd('\') }
    while ($p) {
        try {
            if ([IO.File]::GetAttributes($p) -band [IO.FileAttributes]::ReparsePoint) { return $p }
        } catch [IO.FileNotFoundException], [IO.DirectoryNotFoundException] {
        } catch { return "$p (attributes unreadable)" }
        $p = [IO.Path]::GetDirectoryName($p)
    }
    return $null
}

function Get-Tree([string]$Dir) {
    # files and folders under $Dir; a reparse point (junction / symlink) is reported, never entered
    $res = [pscustomobject]@{ files = New-Object System.Collections.Generic.List[object]
                              dirs = New-Object System.Collections.Generic.List[object]
                              reparse = New-Object System.Collections.Generic.List[string]
                              errors = New-Object System.Collections.Generic.List[string] }
    $stack = New-Object System.Collections.Generic.Stack[string]
    $stack.Push($Dir)
    while ($stack.Count -gt 0) {
        $d = $stack.Pop()
        try { $items = @(Get-ChildItem -LiteralPath $d -Force -ErrorAction Stop) }
        catch { $res.errors.Add("${d}: $($_.Exception.Message)"); continue }
        foreach ($i in $items) {
            if (Test-Reparse $i) { $res.reparse.Add($i.FullName); continue }
            if ($i.PSIsContainer) { $res.dirs.Add($i); $stack.Push($i.FullName) } else { $res.files.Add($i) }
        }
    }
    return $res
}

function Get-Sum($Files) { $t = 0L; foreach ($f in $Files) { $t += $f.Length }; return $t }

function Test-InUse([string]$Path) {
    # an exclusive read open fails while another process (e.g. the app logger) has the file open
    try { $s = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None); $s.Close(); return $false }
    catch { return $true }
}

function Read-StorageConfig {
    # data_dir / logs_dir of storage.json, READ ONLY (never written by this script)
    $f = Join-Path $LocalApp "storage.json"
    if (-not (Test-Path -LiteralPath $f -PathType Leaf)) { return @{ ok = $false; note = "storage.json not found: data folder unknown" } }
    try { $cfg = Get-Content -LiteralPath $f -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { return @{ ok = $false; note = "storage.json unreadable: $($_.Exception.GetType().Name)" } }
    $d = "$($cfg.data_dir)"
    if (-not $d -or -not [IO.Path]::IsPathRooted($d) -or -not (Test-Path -LiteralPath $d -PathType Container)) {
        return @{ ok = $false; note = "storage.json has no usable data_dir" }
    }
    $l = "$($cfg.logs_dir)"
    if (-not $l -or -not [IO.Path]::IsPathRooted($l)) { $l = Join-Path $d "logs" }
    return @{ ok = $true; data = (Get-LongPath $d); logs = (Get-LongPath $l); note = "" }
}

$Storage = Read-StorageConfig
$DataDir = if ($Storage.ok) { $Storage.data } else { $null }

# -TmpRoot: never a drive root, never the project / data / %LOCALAPPDATA% folders or one of their parents
$tmpBad = $null
if ($TmpRoot.Length -le 3) { $tmpBad = "a drive root" }
foreach ($x in @($ProjectRoot, $DataDir, $LocalApp, $ProgDir)) {
    if (-not $tmpBad -and $x -and (Test-Under $x $TmpRoot)) { $tmpBad = "$x or one of its parents" }
}
if ($tmpBad) {
    Write-Host "-TmpRoot $TmpRoot is ${tmpBad}: refused. Nothing done." -ForegroundColor Red
    exit 2
}

# never deleted, whatever a group finds (prefix match, case-insensitive, long paths: no 8.3 short names)
$Protected = [ordered]@{}
$Protected[$LocalApp.TrimEnd('\') + '\'] = "%LOCALAPPDATA%\DemandForecast"
$Protected[$ProgDir.TrimEnd('\') + '\'] = "installed versions"
$Protected[(Join-Path $ProjectRoot "dist") + '\'] = "dist\ (scripts\prune-artifacts.ps1 only)"
$Protected[(Join-Path $ProjectRoot "checkpoints") + '\'] = "checkpoints\"
if ($DataDir) {
    $Protected[(Join-Path $DataDir "db") + '\'] = "live database"
    $Protected[(Join-Path $DataDir "models") + '\'] = "models"
}

function Get-ProtectReason([string]$Path) {
    # path strings only say nothing about where a junction leads: any reparse point in the chain refuses the path
    $rp = Get-ReparseInChain $Path
    if ($rp) { return "reparse point in path: $rp" }
    $p = (Get-LongPath $Path) + '\'
    foreach ($k in $Protected.Keys) {
        if ($p.StartsWith($k, [StringComparison]::OrdinalIgnoreCase)) { return $Protected[$k] }
        if ($k.StartsWith($p, [StringComparison]::OrdinalIgnoreCase)) { return "contains $($Protected[$k])" }
    }
    if ((Split-Path $Path -Leaf) -like "app.db*") { return "database file" }
    return $null
}

function New-Group([string]$Name, [string[]]$Roots) {
    return [ordered]@{ group = $Name; roots = @($Roots); status = "ok"; note = ""; before_bytes = 0L; candidate_count = 0
                       candidate_bytes = 0L; after_bytes = 0L; after_is_projection = (-not $Apply); deleted_count = 0
                       deleted_bytes = 0L; candidates = (New-Object System.Collections.ArrayList)
                       skipped = (New-Object System.Collections.ArrayList); errors = (New-Object System.Collections.ArrayList) }
}

function Add-Candidate($G, [string]$Path, [string]$Kind, [long]$Bytes, [datetime]$Time, [string]$Reason) {
    $why = Get-ProtectReason $Path
    if ($why) { [void]$G.skipped.Add([ordered]@{ path = $Path; reason = "protected ($why)" }); return $null }
    $c = [ordered]@{ path = $Path; kind = $Kind; bytes = $Bytes; age_days = [math]::Round(($Now - $Time).TotalDays, 1)
                     last_write = $Time.ToString("s"); reason = $Reason }
    [void]$G.candidates.Add($c)
    $G.candidate_count += 1
    $G.candidate_bytes += $Bytes
    return $c
}

function Add-Skip($G, [string]$Path, [string]$Reason) { [void]$G.skipped.Add([ordered]@{ path = $Path; reason = $Reason }) }

function Test-GroupRoot($G, [string]$Root) {
    # a group root that is, or lies under, a junction / symlink is never entered: reported, nothing selected in it
    $rp = Get-ReparseInChain $Root
    if (-not $rp) { return $true }
    Add-Skip $G $Root "reparse point in path ($rp): folder not entered, nothing deleted"
    return $false
}

function Add-TreeIssues($G, $Tree) {
    foreach ($r in $Tree.reparse) { Add-Skip $G $r "reparse point (junction / symlink): not followed, not deleted" }
    foreach ($e in $Tree.errors) { [void]$G.errors.Add($e) }
}

# ------------------------------------------------------------------ backups
function Get-BackupGroup {
    $root = Join-Path $ProjectRoot "backups"
    $g = New-Group "backups" @($root)
    if (-not (Test-GroupRoot $g $root)) { $g.status = "skipped"; $g.note = "reparse point in path: nothing selected"; return $g }
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { $g.status = "skipped"; $g.note = "folder not found"; return $g }
    if (-not (Test-Path -LiteralPath $ProgDir -PathType Container)) {
        $g.status = "skipped"; $g.note = "install folder not found: install times unknown, nothing selected"; return $g
    }
    # install times = version folders now + every install seen before (install-history.json keeps them after an old
    # version folder is removed; entries can also be added by hand: {"version": "...", "created": "yyyy-MM-ddTHH:mm:ss"})
    $hist = [ordered]@{}
    if (Test-Path -LiteralPath $HistFile -PathType Leaf) {
        try {
            foreach ($e in @((Get-Content -LiteralPath $HistFile -Raw -Encoding UTF8 | ConvertFrom-Json).installs)) {
                $t = [datetime]::ParseExact("$($e.created)", "s", $Inv)
                $hist["$($e.version)|$($t.ToString('s'))"] = [ordered]@{ version = "$($e.version)"; created = $t.ToString("s"); source = "$($e.source)" }
            }
        } catch { $g.status = "skipped"; $g.note = "install-history.json unreadable: nothing selected ($($_.Exception.Message))"; return $g }
    }
    foreach ($d in @(Get-ChildItem -LiteralPath $ProgDir -Directory -Force | Where-Object { -not (Test-Reparse $_) })) {
        $k = "$($d.Name)|$($d.CreationTime.ToString('s'))"
        if (-not $hist.Contains($k)) { $hist[$k] = [ordered]@{ version = $d.Name; created = $d.CreationTime.ToString("s"); source = "version folder" } }
    }
    $zips = @(); $configs = @(); $shas = @{}
    foreach ($i in @(Get-ChildItem -LiteralPath $root -Force)) {
        if (Test-Reparse $i) { Add-Skip $g $i.FullName "reparse point (junction / symlink): not followed, not deleted"; continue }
        $tree = $null
        if ($i.PSIsContainer) { $tree = Get-Tree $i.FullName; Add-TreeIssues $g $tree; $bytes = Get-Sum $tree.files } else { $bytes = $i.Length }
        $g.before_bytes += $bytes
        $t = $null
        if ($i.Name -match '^(?:backup|config)-(\d{8}-\d{6})-') {
            try { $t = [datetime]::ParseExact($Matches[1], "yyyyMMdd-HHmmss", $Inv) } catch { $t = $null }
        }
        if ($t -and -not $i.PSIsContainer -and $i.Name -match '^backup-\d{8}-\d{6}-(.+)\.zip$') {
            $kind = $Matches[1]
            $type = if ($kind -eq "manual" -or $kind -eq "cli") { $kind } elseif ($kind -like "pre*") { "pre" } else { "other" }
            $zips += [pscustomobject]@{ item = $i; name = $i.Name; t = $t; kind = $kind; type = $type; bytes = $bytes }
        } elseif ($t -and $i.Name -match '^config-\d{8}-\d{6}-(.+?)(\.json)?$') {
            $configs += [pscustomobject]@{ item = $i; t = $t; kind = $Matches[1]; bytes = $bytes; clean = ($null -eq $tree -or ($tree.reparse.Count -eq 0 -and $tree.errors.Count -eq 0)) }
        } elseif (-not $i.PSIsContainer -and $i.Name -like "*.zip.sha256") {
            $shas[$i.Name] = $i
        } else {
            Add-Skip $g $i.FullName "not a recognised backup file: kept"
        }
    }
    $keep = @{}
    foreach ($typ in @("manual", "cli")) {
        foreach ($z in @($zips | Where-Object { $_.type -eq $typ } | Sort-Object t, name | Select-Object -Last 7)) {
            if (-not $keep.ContainsKey($z.name)) { $keep[$z.name] = "7 newest $typ" }
        }
    }
    foreach ($z in $zips) {
        if (($z.type -eq "pre" -or $z.type -eq "other") -and ($Now - $z.t).TotalDays -le 30 -and -not $keep.ContainsKey($z.name)) {
            $keep[$z.name] = "$($z.type) backup younger than 30 days"
        }
    }
    $srt = @($zips | Sort-Object t, name)
    for ($k = 1; $k -lt $srt.Count; $k++) {
        # deploy-upgrade.ps1 takes a manual backup, then install.ps1 a cli one: that cli = the backup before an install.
        # Remembered in install-history.json, so it stays kept after the manual partner is removed.
        $a = $srt[$k - 1]; $b = $srt[$k]
        if ($b.type -eq "cli" -and $a.type -eq "manual" -and ($b.t - $a.t).TotalMinutes -le 6) {
            $key = "deploy-pair|$($b.t.ToString('s'))"
            if (-not $hist.Contains($key)) { $hist[$key] = [ordered]@{ version = "deploy-pair"; created = $b.t.ToString("s"); source = "manual + cli backup pair ($($b.name))" } }
        }
    }
    $Script:InstallHistory = @($hist.Values | Sort-Object { $_.created })
    $installs = @($Script:InstallHistory | ForEach-Object { [pscustomobject]@{ t = [datetime]::ParseExact($_.created, "s", $Inv); pair = ($_.version -eq "deploy-pair") } } |
                  Sort-Object t)
    foreach ($ins in $installs) {
        $it = $ins.t
        $before = @($zips | Where-Object { $_.t -le $it } | Sort-Object t, name)
        if ($before.Count -eq 0) { continue }
        $nb = $before[$before.Count - 1]
        if ($ins.pair) {
            if (-not $keep.ContainsKey($nb.name)) { $keep[$nb.name] = "cli right after a manual backup (deploy pair = before an install)" }
            continue
        }
        if (-not $keep.ContainsKey($nb.name)) { $keep[$nb.name] = "newest backup before install $($it.ToString('s'))" }
        foreach ($z in @($before | Where-Object { ($it - $_.t).TotalMinutes -le 20 })) {
            if (-not $keep.ContainsKey($z.name)) { $keep[$z.name] = "taken within 20 min before install $($it.ToString('s'))" }
        }
    }
    $g["kept"] = New-Object System.Collections.ArrayList
    foreach ($z in $srt) {
        $sha = $shas[$z.name + ".sha256"]
        if ($keep.ContainsKey($z.name)) {
            [void]$g.kept.Add([ordered]@{ name = $z.name; bytes = $z.bytes; reason = $keep[$z.name] })
            continue
        }
        [void](Add-Candidate $g $z.item.FullName "file" $z.bytes $z.t "backup outside the retention rule (type $($z.type))")
        if ($sha) { [void](Add-Candidate $g $sha.FullName "file" $sha.Length $z.t "companion of deleted $($z.name)") }
    }
    foreach ($c in $configs) {
        # companion = the backup of the same kind taken at most 30 min before the config copy
        $m = @($zips | Where-Object { $_.kind -eq $c.kind -and $_.t -le $c.t -and ($c.t - $_.t).TotalMinutes -le 30 } | Sort-Object t)
        if ($m.Count -eq 0) { Add-Skip $g $c.item.FullName "config copy without a matching backup: kept"; continue }
        $z = $m[$m.Count - 1]
        if ($keep.ContainsKey($z.name)) { continue }
        if (-not $c.clean) { Add-Skip $g $c.item.FullName "companion folder contains a reparse point / unreadable entry: kept"; continue }
        $kind = if ($c.item.PSIsContainer) { "dir" } else { "file" }
        [void](Add-Candidate $g $c.item.FullName $kind $c.bytes $z.t "companion of deleted $($z.name)")
    }
    $g.note = "installs known: $($installs.Count); backup zips: $($zips.Count), kept: $($keep.Count)"
    return $g
}

# ------------------------------------------------------------------ exports
function Get-ExportGroup {
    if (-not $DataDir) { $g = New-Group "exports" @(); $g.status = "skipped"; $g.note = $Storage.note; return $g }
    $root = Join-Path $DataDir "exports\du_bao"
    $g = New-Group "exports" @($root)
    if (-not (Test-GroupRoot $g $root)) { $g.status = "skipped"; $g.note = "reparse point in path: nothing selected"; return $g }
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { $g.status = "skipped"; $g.note = "folder not found"; return $g }
    foreach ($i in @(Get-ChildItem -LiteralPath $root -Force)) {
        if (Test-Reparse $i) { Add-Skip $g $i.FullName "reparse point (junction / symlink): not followed, not deleted"; continue }
        if (-not $i.PSIsContainer) { $g.before_bytes += $i.Length; continue }
        $tree = Get-Tree $i.FullName
        $bytes = Get-Sum $tree.files
        $g.before_bytes += $bytes
        if ($i.Name -notmatch '^\d{8}$') { continue }
        try { $d = [datetime]::ParseExact($i.Name, "yyyyMMdd", $Inv) } catch { continue }
        if (($Today - $d).TotalDays -le 90) { continue }
        if ($tree.reparse.Count -or $tree.errors.Count) { Add-TreeIssues $g $tree; Add-Skip $g $i.FullName "contains a reparse point / unreadable entry: kept"; continue }
        [void](Add-Candidate $g $i.FullName "dir" $bytes $d "daily export folder older than 90 days ($($i.Name))")
    }
    return $g
}

# ------------------------------------------------------------------ logs
function Get-LogGroup {
    $roots = @()
    if ($DataDir) { $roots += $Storage.logs }
    $roots += (Join-Path $ProjectRoot "logs")
    $uniq = @()
    foreach ($r in $roots) {
        $rp = [IO.Path]::GetFullPath($r).TrimEnd('\')
        $dup = $false
        foreach ($u in $uniq) { if (($rp + '\').StartsWith($u + '\', [StringComparison]::OrdinalIgnoreCase)) { $dup = $true } }
        if (-not $dup) { $uniq += $rp }
    }
    $g = New-Group "logs" $uniq
    if (-not $DataDir) { $g.note = "data log folder skipped: $($Storage.note)" }
    $limit = $Now.AddDays(-30)
    foreach ($root in $uniq) {
        if (-not (Test-GroupRoot $g $root)) { continue }
        if (-not (Test-Path -LiteralPath $root -PathType Container)) { continue }
        $tree = Get-Tree $root
        Add-TreeIssues $g $tree
        $g.before_bytes += Get-Sum $tree.files
        foreach ($f in $tree.files) {
            if ($f.Name -like "logs-archive-*.zip" -or $f.FullName -eq $HistFile -or $f.LastWriteTime -ge $limit) { continue }
            if (Test-InUse $f.FullName) { Add-Skip $g $f.FullName "file in use: not touched"; continue }
            $zip = Join-Path $f.DirectoryName ("logs-archive-{0}.zip" -f $f.LastWriteTime.ToString("yyyyMM"))
            $c = Add-Candidate $g $f.FullName "file" $f.Length $f.LastWriteTime "log older than 30 days (archived before deletion)"
            if ($c) { $c["archive"] = $zip }
        }
    }
    return $g
}

# ------------------------------------------------------------------ temporary DB copies
function Get-TmpGroup {
    $g = New-Group "tmp" @($TmpRoot)
    if (-not (Test-GroupRoot $g $TmpRoot)) { $g.status = "skipped"; $g.note = "reparse point in path: nothing selected"; return $g }
    if (-not (Test-Path -LiteralPath $TmpRoot -PathType Container)) { $g.status = "skipped"; $g.note = "folder not found"; return $g }
    # Git Bash form of the folder on a command line: D:\Buymed\tmp -> /d/Buymed/tmp (-> \d\buymed\tmp after Replace)
    $bash = if ($TmpRoot -match '^([A-Za-z]):\\(.*)$') { ("\" + $Matches[1] + "\" + $Matches[2]).ToLowerInvariant() } else { $null }
    try {
        $procs = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object { $_.CommandLine } |
                   ForEach-Object { [pscustomobject]@{ pid = $_.ProcessId; cmd = $_.CommandLine.ToLowerInvariant().Replace('/', '\') } })
    } catch { $g.status = "skipped"; $g.note = "process command lines unreadable: nothing selected"; return $g }
    $limit = $Now.AddDays(-1)
    foreach ($i in @(Get-ChildItem -LiteralPath $TmpRoot -Force)) {
        if (Test-Reparse $i) { Add-Skip $g $i.FullName "reparse point (junction / symlink): not followed, not deleted"; continue }
        # age = newest creation / last write time (a copied file keeps an old last write time); Get-Tree never
        # enters a reparse point
        $newest = $i.LastWriteTime
        if ($i.CreationTime -gt $newest) { $newest = $i.CreationTime }
        $tree = $null
        if ($i.PSIsContainer) {
            $tree = Get-Tree $i.FullName
            $bytes = Get-Sum $tree.files
            foreach ($lst in @($tree.files, $tree.dirs)) {
                foreach ($x in $lst) {
                    if ($x.LastWriteTime -gt $newest) { $newest = $x.LastWriteTime }
                    if ($x.CreationTime -gt $newest) { $newest = $x.CreationTime }
                }
            }
        } else { $bytes = $i.Length }
        $g.before_bytes += $bytes
        if ($newest -ge $limit) { continue }
        $needles = @($i.FullName.ToLowerInvariant())
        if ($bash) { $needles += ($bash + "\" + $i.Name.ToLowerInvariant()) }
        $users = @($procs | Where-Object { $p = $_; @($needles | Where-Object { $p.cmd.Contains($_) }).Count -gt 0 } | ForEach-Object { $_.pid })
        if ($users.Count) { Add-Skip $g $i.FullName "used by running process(es) $($users -join ', '): kept"; continue }
        if ($null -ne $tree -and ($tree.reparse.Count -or $tree.errors.Count)) { Add-TreeIssues $g $tree; Add-Skip $g $i.FullName "contains a reparse point / unreadable entry: kept"; continue }
        $files = if ($null -ne $tree) { $tree.files.ToArray() } else { @($i) }
        $open = @($files | Where-Object { $_.Name -match '\.(db|sqlite|sqlite3)(-wal|-shm|-journal)?$' -and (Test-InUse $_.FullName) })
        if ($open.Count) { Add-Skip $g $i.FullName "database file in use ($($open[0].Name)): kept"; continue }
        $kind = if ($i.PSIsContainer) { "dir" } else { "file" }
        [void](Add-Candidate $g $i.FullName $kind $bytes $newest "temporary entry older than 1 day, no running process uses it")
    }
    return $g
}

# ------------------------------------------------------------------ packaged experiments
function Get-ReportGroup {
    $root = Join-Path $ProjectRoot "reports"
    $g = New-Group "reports" @($root)
    if (-not (Test-GroupRoot $g $root)) { $g.status = "skipped"; $g.note = "reparse point in path: nothing selected"; return $g }
    $keepFile = Join-Path $PSScriptRoot "don_dep_giu.txt"
    if (-not (Test-Path -LiteralPath $keepFile -PathType Leaf)) { $g.status = "skipped"; $g.note = "keep list not found: $keepFile"; return $g }
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { $g.status = "skipped"; $g.note = "folder not found"; return $g }
    $keepList = @{}
    foreach ($line in Get-Content -LiteralPath $keepFile) {
        $s = $line.Trim()
        if ($s -and -not $s.StartsWith("#")) { $keepList[$s] = $true }
    }
    $g.note = "keep list: $($keepList.Count) folder(s)"
    $dataExt = @(".parquet", ".csv", ".zip")
    foreach ($d in @(Get-ChildItem -LiteralPath $root -Directory -Force)) {
        if (Test-Reparse $d) { Add-Skip $g $d.FullName "reparse point (junction / symlink): not followed, not deleted"; continue }
        $pk = @(Get-ChildItem -LiteralPath $d.FullName -Directory -Force | Where-Object { $_.Name -like "package*" -and -not (Test-Reparse $_) } |
                ForEach-Object { $_.Name })
        if ($pk.Count -eq 0) { continue }
        if ($keepList.ContainsKey($d.Name)) { Add-Skip $g $d.FullName "in keep list (don_dep_giu.txt)"; continue }
        $tree = Get-Tree $d.FullName
        Add-TreeIssues $g $tree
        $g.before_bytes += Get-Sum $tree.files
        foreach ($f in $tree.files) {
            $rel = $f.FullName.Substring($d.FullName.Length + 1)
            $parts = $rel.Split('\')
            if ($parts.Count -gt 1 -and $pk -contains $parts[0]) { continue }       # inside a package folder
            if ($f.Extension -eq ".md" -or $f.Name -like "package*") { continue }
            if (($dataExt -contains $f.Extension.ToLowerInvariant()) -or $f.Name -like "order_lines*") {
                [void](Add-Candidate $g $f.FullName "file" $f.Length $f.LastWriteTime "data file of packaged experiment $($d.Name) outside its package folder")
            }
        }
    }
    return $g
}

# ------------------------------------------------------------------ dist (own retention script)
function Get-DistGroup {
    $prune = Join-Path $ProjectRoot "scripts\prune-artifacts.ps1"
    $roots = @((Join-Path $ProjectRoot "dist"), (Join-Path $ProjectRoot "release"))
    $g = New-Group "dist" $roots
    $bad = @($roots | Where-Object { -not (Test-GroupRoot $g $_) })
    if ($bad.Count) { $g.status = "skipped"; $g.note = "reparse point in dist\ / release\ path: prune-artifacts.ps1 not run"; return $g }
    if (-not (Test-Path -LiteralPath $prune -PathType Leaf)) { $g.status = "skipped"; $g.note = "scripts\prune-artifacts.ps1 not found"; return $g }
    $issues = 0
    foreach ($r in $roots) {
        if (Test-Path -LiteralPath $r -PathType Container) {
            $t = Get-Tree $r; Add-TreeIssues $g $t; $g.before_bytes += Get-Sum $t.files
            $issues += $t.reparse.Count + $t.errors.Count
        }
    }
    if ($issues) {
        # prune-artifacts.ps1 enumerates with -Recurse (follows junctions in PS 5.1) and deletes with Remove-Item -Recurse:
        # it never runs (plan or apply) while anything under dist\ / release\ is a reparse point or unreadable
        $g.status = "skipped"; $g.note = "reparse point / unreadable entry under dist\ / release\: prune-artifacts.ps1 not run"; return $g
    }
    $p = @{}
    if ($DistKeep.Count) { $p["Keep"] = $DistKeep }
    try { $out = @(& $prune @p *>&1 | ForEach-Object { "$_" }) }
    catch { [void]$g.errors.Add("prune-artifacts.ps1 (plan): $($_.Exception.Message)"); $g.status = "error"; return $g }
    $g["plan"] = $out
    foreach ($line in $out) {
        if ($line -notmatch '^DELETE\s+\S+ MB  (.+?)  - (.*)$') { continue }
        $path = Join-Path $ProjectRoot $Matches[1]
        $reason = $Matches[2]
        if (-not (Test-Path -LiteralPath $path)) { continue }
        $it = Get-Item -LiteralPath $path -Force
        if ($it.PSIsContainer) { $t = Get-Tree $path; $bytes = Get-Sum $t.files } else { $bytes = $it.Length }
        # listed only: dist\ is protected here, deletion is left to prune-artifacts.ps1 itself
        $c = [ordered]@{ path = $path; kind = $(if ($it.PSIsContainer) { "dir" } else { "file" }); bytes = $bytes
                         age_days = [math]::Round(($Now - $it.LastWriteTime).TotalDays, 1); last_write = $it.LastWriteTime.ToString("s")
                         reason = "prune-artifacts.ps1: $reason" }
        [void]$g.candidates.Add($c)
        $g.candidate_count += 1
        $g.candidate_bytes += $bytes
    }
    $g.note = if ($IncludeDist) { "plan of scripts\prune-artifacts.ps1; -IncludeDist: deleted by it with -Apply" } else { "plan of scripts\prune-artifacts.ps1 only (-IncludeDist not given: never deleted)" }
    return $g
}

# ------------------------------------------------------------------ apply
function Remove-Candidate($G, $C) {
    $p = $C.path
    $why = Get-ProtectReason $p
    if ($why) { [void]$G.errors.Add("${p}: refused, protected ($why)"); return }
    try {
        if (-not (Test-Path -LiteralPath $p)) { Add-Skip $G $p "gone before deletion"; return }
        $it = Get-Item -LiteralPath $p -Force
        if (Test-Reparse $it) { Add-Skip $G $p "reparse point at deletion time: not deleted"; return }
        if ($it.PSIsContainer) {
            $t = Get-Tree $p
            if ($t.reparse.Count -or $t.errors.Count) { Add-TreeIssues $G $t; Add-Skip $G $p "reparse point / unreadable entry at deletion time: not deleted"; return }
        }
        Remove-Item -LiteralPath $p -Recurse -Force -Confirm:$false
        $C["deleted"] = $true
        $G.deleted_count += 1
        $G.deleted_bytes += $C.bytes
    } catch { [void]$G.errors.Add("${p}: $($_.Exception.Message)") }
}

function Invoke-LogArchive($G) {
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    foreach ($grp in @($G.candidates | Group-Object { $_.archive })) {
        $zip = $grp.Name
        $rp = Get-ReparseInChain $zip
        if ($rp) { [void]$G.errors.Add("${zip}: refused, reparse point in path ($rp): nothing archived or deleted"); continue }
        try {
            $names = @{}
            if (Test-Path -LiteralPath $zip) {
                $r = [IO.Compression.ZipFile]::OpenRead($zip)
                try { foreach ($e in $r.Entries) { $names[$e.FullName] = $true } } finally { $r.Dispose() }
            }
            $todo = @()
            foreach ($c in $grp.Group) {
                if (Test-InUse $c.path) { Add-Skip $G $c.path "file in use at archive time: not touched"; continue }
                $leaf = Split-Path $c.path -Leaf
                $entry = $leaf; $n = 1
                while ($names.ContainsKey($entry)) { $entry = "$leaf.$n"; $n += 1 }
                $names[$entry] = $true
                $todo += [pscustomobject]@{ c = $c; entry = $entry }
            }
            if ($todo.Count -eq 0) { continue }
            $mode = if (Test-Path -LiteralPath $zip) { [IO.Compression.ZipArchiveMode]::Update } else { [IO.Compression.ZipArchiveMode]::Create }
            $w = [IO.Compression.ZipFile]::Open($zip, $mode)
            try {
                foreach ($x in $todo) {
                    [void][IO.Compression.ZipFileExtensions]::CreateEntryFromFile($w, $x.c.path, $x.entry, [IO.Compression.CompressionLevel]::Optimal)
                }
            } finally { $w.Dispose() }
            $r = [IO.Compression.ZipFile]::OpenRead($zip)
            $len = @{}
            try { foreach ($e in $r.Entries) { $len[$e.FullName] = $e.Length } } finally { $r.Dispose() }
            foreach ($x in $todo) {
                if ($len.ContainsKey($x.entry) -and $len[$x.entry] -eq $x.c.bytes) { $x.c["archived_as"] = $x.entry; Remove-Candidate $G $x.c }
                else { [void]$G.errors.Add("$($x.c.path): not verified in $zip, not deleted") }
            }
        } catch { [void]$G.errors.Add("${zip}: $($_.Exception.Message)") }
    }
}

function Invoke-DistApply($G) {
    if (-not $IncludeDist) { return }
    $prune = Join-Path $ProjectRoot "scripts\prune-artifacts.ps1"
    foreach ($r in @((Join-Path $ProjectRoot "dist"), (Join-Path $ProjectRoot "release"))) {
        # checked again right before the deletion (see Get-DistGroup)
        $rp = Get-ReparseInChain $r
        $t = if (-not $rp -and (Test-Path -LiteralPath $r -PathType Container)) { Get-Tree $r } else { $null }
        if ($rp -or ($null -ne $t -and ($t.reparse.Count -or $t.errors.Count))) {
            [void]$G.errors.Add("${r}: reparse point / unreadable entry at deletion time: prune-artifacts.ps1 -Apply not run"); return
        }
    }
    $p = @{ Apply = $true }
    if ($DistKeep.Count) { $p["Keep"] = $DistKeep }
    try {
        $out = @(& $prune @p *>&1 | ForEach-Object { "$_" })
        $G["apply_output"] = $out
        foreach ($c in $G.candidates) {
            if (-not (Test-Path -LiteralPath $c.path)) { $c["deleted"] = $true; $G.deleted_count += 1; $G.deleted_bytes += $c.bytes }
        }
    } catch { [void]$G.errors.Add("prune-artifacts.ps1 -Apply: $($_.Exception.Message)") }
}

# ------------------------------------------------------------------ main
$mode = if ($Apply) { "APPLY" } else { "DRY_RUN" }
$stamp = $Now.ToString("yyyyMMdd-HHmmss")
$outDir = Join-Path $ProjectRoot "logs\don_dep"
$report = [ordered]@{ tool = "scripts\ops\don_dep_dinh_ky.ps1"; mode = $mode; started_at = $Now.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
                      local_time = $Now.ToString("s"); project_root = $ProjectRoot; include_dist = [bool]$IncludeDist
                      dist_keep = @($DistKeep); tmp_root = $TmpRoot
                      data_dir = $DataDir; storage_note = $Storage.note; groups = @(); totals = $null; errors = @(); exit_code = 0 }
$groups = @()
foreach ($fn in @("Get-BackupGroup", "Get-ExportGroup", "Get-LogGroup", "Get-TmpGroup", "Get-ReportGroup", "Get-DistGroup")) {
    try { $groups += , (& $fn) }
    catch {
        $gname = ($fn -replace '^Get-|Group$', '').ToLowerInvariant()
        $g = New-Group $gname @()
        $g.status = "error"; [void]$g.errors.Add("line $($_.InvocationInfo.ScriptLineNumber): $($_.Exception.Message) $($_.ScriptStackTrace)")
        $groups += , $g
    }
}
if ($Apply) {
    foreach ($g in $groups) {
        if ($g.status -ne "ok") { continue }
        if ($g.group -eq "logs") { Invoke-LogArchive $g }
        elseif ($g.group -eq "dist") { Invoke-DistApply $g }
        else { foreach ($c in @($g.candidates)) { Remove-Candidate $g $c } }
    }
}
$tot = [ordered]@{ before_bytes = 0L; candidate_count = 0; candidate_bytes = 0L; after_bytes = 0L; deleted_count = 0; deleted_bytes = 0L }
foreach ($g in $groups) {
    if ($Apply) { $g.after_bytes = $g.before_bytes - $g.deleted_bytes }
    elseif ($g.group -eq "dist" -and -not $IncludeDist) { $g.after_bytes = $g.before_bytes }
    else { $g.after_bytes = $g.before_bytes - $g.candidate_bytes }
    if ($g.errors.Count -and $g.status -eq "ok") { $g.status = "error" }
    foreach ($k in @($tot.Keys)) { $tot[$k] += $g[$k] }
}
$report.groups = $groups
$report.totals = $tot
$failed = @($groups | Where-Object { $_.status -eq "error" }).Count -gt 0
$report.exit_code = if ($failed) { 1 } else { 0 }

$gb = { param($b) "{0:N3} GB" -f ($b / 1GB) }
$lines = @("Don dep dinh ky / periodic cleanup  mode=$mode  $($Now.ToString('s'))  project=$ProjectRoot")
if (-not $Apply) { $lines += "DRY RUN: nothing deleted. Re-run with -Apply to delete the candidates (dist only with -IncludeDist)." }
foreach ($g in $groups) {
    $lines += ("{0,-8} {1,-8} candidates {2,5}  {3,12}  before {4,12}  after {5,12}{6}  skipped {7}  errors {8}  {9}" -f $g.group, $g.status,
               $g.candidate_count, (& $gb $g.candidate_bytes), (& $gb $g.before_bytes), (& $gb $g.after_bytes),
               $(if ($g.after_is_projection) { "*" } else { " " }), $g.skipped.Count, $g.errors.Count, $g.note)
}
$lines += ("TOTAL    candidates {0,5}  {1,12}  before {2,12}  after {3,12}  deleted {4} ({5})" -f $tot.candidate_count, (& $gb $tot.candidate_bytes),
           (& $gb $tot.before_bytes), (& $gb $tot.after_bytes), $tot.deleted_count, (& $gb $tot.deleted_bytes))
if (-not $Apply) { $lines += "* after = projection if applied (logs: archives add their compressed size)" }
try {
    New-Item -ItemType Directory -Force -Path $outDir | Out-Null
    if ($Script:InstallHistory) {
        $h = [ordered]@{ note = "install times seen by scripts\ops\don_dep_dinh_ky.ps1 (backup retention: newest backup before each install)"
                         updated_at = $Now.ToString("s"); installs = $Script:InstallHistory }
        $h | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $HistFile -Encoding UTF8
    }
    $json = Join-Path $outDir "don_dep-$stamp.json"
    $report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $json -Encoding UTF8
    $lines += "Report: $json"
    Set-Content -LiteralPath (Join-Path $outDir "don_dep-$stamp.txt") -Value $lines -Encoding UTF8
} catch {
    $lines += "Report NOT written: $($_.Exception.Message)"
    $failed = $true
}
foreach ($l in $lines) { Write-Host $l }
if ($failed) { exit 1 }
exit 0
