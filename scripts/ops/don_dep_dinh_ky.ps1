<#
.SYNOPSIS  Periodic cleanup (owner rules 03/11/2026, extended 08/11/2026). DRY RUN unless -Apply. Keep this file ASCII-only.
           Owner rule 08/11: when in doubt KEEP (listed as kept_uncertain in the report).
           current / previous version: current = %LOCALAPPDATA%\Programs\DemandForecast\current.txt (read only);
           previous = the newest EXISTING version folder older than it (a version only in install-history.json is ignored).
           Groups and rules (everything not listed as a candidate stays):
             backups  <project>\backups: keep the newest backup overall, every backup of the last 7 days (name time),
                      for the current and the previous version the newest *-pre-<version without dots>.zip (pre-1.4.6 ->
                      backup-...-pre-146.zip), the newest backup taken before each install of that version and every
                      backup taken within 20 min before it (install time = version folder creation time, remembered in
                      <project>\logs\don_dep\install-history.json once seen); a kept zip keeps its .sha256 / config-*
                      companions. The other backup zips (+ their companions) are candidates. current.txt unreadable ->
                      group skipped.
             exports  <data>\exports\du_bao\YYYYMMDD\ folders that are not among the 30 newest day folders and older
                      than 30 days (folder date); in the kept folders, *_bo files (earlier versions of the day,
                      du_bao_YYYYMMDD_vK_bo.xlsx) older than 3 days (folder date and last write) while a newer
                      du_bao_YYYYMMDD_vM.xlsx (M > K) exists; otherwise kept (kept_uncertain). <data> = data_dir of
                      %LOCALAPPDATA%\DemandForecast\storage.json (read only); unreadable -> group skipped.
             logs     <data> log folder and <project>\logs\** files older than 30 days: added to
                      logs-archive-YYYYMM.zip next to them (verified) BEFORE deletion; a file in use is never touched.
             tmp      -TmpRoot (default D:\Buymed\tmp) entries older than -TmpMinAgeHours (default 24; newest creation /
                      last write time of the entry and, for a folder, of everything in it) that no running process names on
                      its command line and that hold no database file in use; names in -TmpKeep are never candidates.
             deploy_temp  %TEMP%\DemandForecast-deploy-* folders older than 1 day (same age rule as tmp) that no
                      running process names on its command line (the managed %TEMP%\DemandForecast-deploy\ is not touched).
             reports  <project>\reports\<folder> with a package* subfolder: data files (.parquet, .csv, .zip,
                      order_lines*) outside the package folder(s). Folders listed in scripts\ops\don_dep_ket_luan.txt
                      (concluded experiments) also: intermediate data files (.parquet .pkl .npz .npy .log .tmp .feather)
                      anywhere below and superseded versions (stem ending _v<N> while the same stem with a higher plain
                      _v<M> and the same extension exists in the same folder); code / text (.py .ps1 .sql .ipynb .sh .R
                      .bat .md .json .txt .yaml .yml) is always kept; lettered variants (_v3b) and matches inside a
                      package* folder are kept (kept_uncertain). Folders in scripts\ops\don_dep_giu.txt are excluded
                      entirely (the keep list wins). -KeepListFile / -ConcludedListFile replace the two lists.
             installs %LOCALAPPDATA%\Programs\DemandForecast\<x.y.z> folders other than the current and the previous
                      version; a folder newer than the current version, not named x.y.z or named in a scheduled task
                      action is kept (kept_uncertain); a
                      folder named on a running process command line / executable path is kept; current.txt is never
                      touched; current.txt unreadable -> group skipped.
             dist_versions  <project>\dist and <project>\worktrees\*\dist: DemandForecast-<x.y.z>* entries (packages,
                      .sha256, manifests, staging folders) of versions older than the current one other than the
                      previous and -DistKeep (newer -> kept_uncertain); deleted with -Apply alone (no -IncludeDist
                      needed: behaviour change 08/11). current.txt unreadable -> group skipped.
             dist     plan of scripts\prune-artifacts.ps1 (dry run); deleted only with -Apply -IncludeDist -DistKeep
                      <rollback version(s)> (-IncludeDist without -DistKeep is refused: no -Keep = rollback package gone);
                      the current and the previous version are added to its -Keep. Not in the totals (dist_versions
                      covers dist\; its deletions are). prune-artifacts.ps1 is not run at all (plan or apply) while
                      anything under dist\ / release\ is a junction / symlink or unreadable (it recurses through junctions).
             claude_temp  (owner 08/11; ONLY when named in -Groups, never in the default run / weekly task)
                      -ClaudeTempRoot (default %TEMP%\claude, long path; leaf name must be "claude"): session folders
                      <root>\<project>\<GUID> taken as finished when ALL hold: not in -ClaudeKeep (session ids, a prefix
                      of >= 8 characters allowed); newest creation / last write time of everything inside older than
                      -ClaudeMinAgeHours (default 24); the session transcript(s) -ClaudeProjectsRoot (default
                      %USERPROFILE%\.claude\projects)\<any project>\<id>.jsonl and \<id>\** (when they exist) also older
                      than that (a running session started with --resume names no id / path on its command line); no
                      running process naming the folder (long, 8.3 or Git Bash form) or the session id; no database
                      file in use (all checked again right before the deletion). Nothing else under the root (project
                      folders themselves, bash-edit-diff, files) is ever selected. Root missing -> skipped.
           -TmpKeep / -ClaudeKeep entries that match no entry / no session folder -> exit 2, nothing done (typo guard).
           -Groups <names> (comma list allowed) runs only these groups: backups, exports, logs, tmp, deploy_temp,
           reports, installs, dist_versions, dist, claude_temp; default = every group except claude_temp; an unknown
           name -> exit 2, nothing done.
           Info only: <project>\worktrees\<name> git worktrees whose version is installed, whose HEAD is on a
           remote-tracking branch, whose tag v<version> exists and whose status is clean -> "worktree_can_remove"
           (never removed here: scripts\ops\archive_worktree.py).
           Never: follows or deletes through a junction / symlink: a group root or a candidate that is, or lies under,
           a reparse point (any parent up to the drive root) is reported and skipped; touches the live DB, models,
           %LOCALAPPDATA%\DemandForecast, %LOCALAPPDATA%\Programs\DemandForecast (except a version folder of the
           installs group), checkpoints\, dist\ (except the dist_versions group and prune-artifacts.ps1 with
           -IncludeDist). Refuses a ProjectRoot inside %LOCALAPPDATA%\Programs\DemandForecast
           or %LOCALAPPDATA%\DemandForecast (a packaged copy: pass -ProjectRoot <source folder>; 8.3 short names are
           expanded first) or holding VERSION with current.txt next to it; a -TmpRoot that is a drive root or the
           project / data / %LOCALAPPDATA% folder or one of their parents.
           Report: <project>\logs\don_dep\don_dep-YYYYMMDD-HHMMSS.json (+ .txt): per group candidates (count, bytes),
           kept_uncertain, before / after; totals. With -Apply the .txt lists every candidate: "deleted <group> <GB>
           <path>" or "NOT deleted <group> <path> - <reason>". Exit 0 ok, 1 error, 2 refused.
           The weekly task should run scripts\ops\don_dep_current.ps1 (runs the script of the INSTALLED version).
.EXAMPLE   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ops\don_dep_dinh_ky.ps1            (plan only)
           powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ops\don_dep_dinh_ky.ps1 -Apply     (delete)
           ... -Apply -IncludeDist -DistKeep 1.3.1      (also dist\ retention, keeping the 1.3.1 rollback package)
           ... -Groups tmp,claude_temp -TmpKeep src148 -ClaudeKeep 145cefda,85d15b29          (plan of these 2 groups)
           ... -Groups tmp,claude_temp -TmpKeep src148 -ClaudeKeep 145cefda,85d15b29 -Apply   (delete in these 2 only)
#>
param([string]$ProjectRoot = "", [switch]$Apply, [switch]$IncludeDist, [string[]]$DistKeep = @(),
      [string]$KeepListFile = "", [string]$ConcludedListFile = "",   # reports lists (default: next to this script)
      [string]$TmpRoot = "D:\Buymed\tmp",       # owner rule: the only folder on D: this script cleans (tests pass their own)
      [string[]]$Groups = @(),                  # default: every group except claude_temp
      [int]$TmpMinAgeHours = 24, [string[]]$TmpKeep = @(),
      [string]$ClaudeTempRoot = "",             # default %TEMP%\claude (tests pass their own)
      [string[]]$ClaudeKeep = @(), [int]$ClaudeMinAgeHours = 24,
      [string]$ClaudeProjectsRoot = "")         # session transcripts, default %USERPROFILE%\.claude\projects (read only)
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
# -Groups / -TmpKeep / -ClaudeKeep: "a,b" (one string through -File) or an array, like -DistKeep
$AllGroups = @("backups", "exports", "logs", "tmp", "deploy_temp", "reports", "installs", "dist_versions", "dist", "claude_temp")
$Groups = @($Groups | ForEach-Object { "$_".Split(',') } | ForEach-Object { $_.Trim().ToLowerInvariant() } | Where-Object { $_ } | Sort-Object -Unique)
foreach ($n in $Groups) {
    if ($AllGroups -notcontains $n) { Write-Host "-Groups: unknown group $n (valid: $($AllGroups -join ', ')). Nothing done." -ForegroundColor Red; exit 2 }
}
# default run (weekly task): every group except claude_temp, which runs only when named
$Selected = if ($Groups.Count) { @($AllGroups | Where-Object { $Groups -contains $_ }) } else { @($AllGroups | Where-Object { $_ -ne "claude_temp" }) }
$TmpKeep = @($TmpKeep | ForEach-Object { "$_".Split(',') } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
foreach ($n in $TmpKeep) {
    if ($n.IndexOfAny([char[]]@('\', '/', ':')) -ge 0 -or $n -eq "." -or $n -eq "..") {
        Write-Host "-TmpKeep: an entry name directly under -TmpRoot expected, not a path: $n. Nothing done." -ForegroundColor Red; exit 2
    }
}
$ClaudeKeep = @($ClaudeKeep | ForEach-Object { "$_".Split(',') } | ForEach-Object { $_.Trim().ToLowerInvariant() } | Where-Object { $_ })
foreach ($n in $ClaudeKeep) {
    if ($n -notmatch '^[0-9a-f][0-9a-f-]{7,35}$') { Write-Host "-ClaudeKeep: a session id (or a prefix of >= 8 characters) expected: $n. Nothing done." -ForegroundColor Red; exit 2 }
}
foreach ($h in @(@("-TmpMinAgeHours", $TmpMinAgeHours), @("-ClaudeMinAgeHours", $ClaudeMinAgeHours))) {
    if ($h[1] -lt 1) { Write-Host "$($h[0]) must be at least 1 (hours): $($h[1]). Nothing done." -ForegroundColor Red; exit 2 }
}
Add-Type -Namespace DfCleanup -Name Native -MemberDefinition @'
[DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
public static extern uint GetLongPathName(string shortPath, System.Text.StringBuilder longPath, uint bufferLength);
[DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
public static extern uint GetShortPathName(string longPath, System.Text.StringBuilder shortPath, uint bufferLength);
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

function Read-InstallState {
    # current version = current.txt (READ ONLY); previous = newest EXISTING version folder x.y.z older than it (a version
    # only remembered in install-history.json whose folder is gone is not a rollback target); versions = folders + history
    $st = @{ ok = $false; current = $null; previous = $null; keep = @(); versions = @(); note = "" }
    $f = Join-Path $ProgDir "current.txt"
    if (-not (Test-Path -LiteralPath $ProgDir -PathType Container)) { $st.note = "install folder not found"; return $st }
    if (-not (Test-Path -LiteralPath $f -PathType Leaf)) { $st.note = "current.txt not found"; return $st }
    try { $v = "$(Get-Content -LiteralPath $f -Raw -ErrorAction Stop)".Trim() } catch { $st.note = "current.txt unreadable"; return $st }
    if ($v -notmatch '^\d+\.\d+\.\d+$') { $st.note = "current.txt holds no version x.y.z"; return $st }
    $vs = @{}
    $dirs = @()
    foreach ($d in @(Get-ChildItem -LiteralPath $ProgDir -Directory -Force)) {
        if ($d.Name -match '^\d+\.\d+\.\d+$') { $vs[$d.Name] = $true; if (-not (Test-Reparse $d)) { $dirs += $d.Name } }
    }
    if (Test-Path -LiteralPath $HistFile -PathType Leaf) {
        try {
            foreach ($e in @((Get-Content -LiteralPath $HistFile -Raw -Encoding UTF8 | ConvertFrom-Json).installs)) {
                if ("$($e.version)" -match '^\d+\.\d+\.\d+$') { $vs["$($e.version)"] = $true }
            }
        } catch { $st.note = "install-history.json unreadable; " }
    }
    $older = @($dirs | Where-Object { [version]$_ -lt [version]$v } | Sort-Object { [version]$_ })
    $st.ok = $true
    $st.current = $v
    $st.versions = @($vs.Keys)
    if ($older.Count) { $st.previous = $older[$older.Count - 1] }
    $st.keep = @(@($v, $st.previous) | Where-Object { $_ })
    $st.note += "current $v, previous $(if ($st.previous) { $st.previous } else { 'none' })"
    return $st
}

$Inst = Read-InstallState
$Script:ProcLines = $null

function Get-ProcLines {
    # command line + executable path of every running process (lower case, / -> \), read once; $null = unreadable
    if ($null -ne $Script:ProcLines) { return , $Script:ProcLines }
    try {
        $Script:ProcLines = @(Get-CimInstance Win32_Process -ErrorAction Stop | ForEach-Object {
            [pscustomobject]@{ pid = $_.ProcessId; text = ("$($_.CommandLine) | $($_.ExecutablePath)").ToLowerInvariant().Replace('/', '\') } })
    } catch { return $null }
    return , $Script:ProcLines
}

function Get-PathUsers([string]$Path) {
    # pids whose command line / executable path names $Path (long or 8.3 short form, Git Bash form) or something below
    # it; nothing when the process list is unreadable (callers check Get-ProcLines first)
    $procs = Get-ProcLines
    if ($null -eq $procs) { return $null }
    $forms = @($Path.ToLowerInvariant())
    $sb = New-Object System.Text.StringBuilder 32768
    $n = [DfCleanup.Native]::GetShortPathName($Path, $sb, [uint32]$sb.Capacity)
    if ($n -gt 0 -and $n -lt $sb.Capacity) { $forms += $sb.ToString().ToLowerInvariant() }
    if ($Path -match '^([A-Za-z]):\\(.*)$') { $forms += ("\" + $Matches[1] + "\" + $Matches[2]).ToLowerInvariant() }
    $pats = @($forms | Sort-Object -Unique | ForEach-Object { [regex]::Escape($_.TrimEnd('\')) + '(\\|"|''|\s|\||$)' })
    return @($procs | Where-Object { $t = $_.text; @($pats | Where-Object { [regex]::IsMatch($t, $_) }).Count -gt 0 } | ForEach-Object { $_.pid })
}

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
# -ClaudeTempRoot (claude_temp group): same refusals as -TmpRoot; checked only when the group is selected
$ClaudeRoot = $null
if ($ClaudeTempRoot) { $ClaudeRoot = Get-LongPath $ClaudeTempRoot }
elseif ($env:TEMP -and [IO.Path]::IsPathRooted($env:TEMP)) { $ClaudeRoot = Get-LongPath (Join-Path $env:TEMP "claude") }
if ($ClaudeRoot -and $Selected -contains "claude_temp") {
    $cBad = $null
    if ($ClaudeRoot.Length -le 3) { $cBad = "a drive root" }
    foreach ($x in @($ProjectRoot, $DataDir, $LocalApp, $ProgDir)) {
        if (-not $cBad -and $x -and (Test-Under $x $ClaudeRoot)) { $cBad = "$x or one of its parents" }
    }
    if (-not $cBad -and (Split-Path $ClaudeRoot -Leaf) -ine "claude") { $cBad = "not a folder named claude" }
    if ($cBad) {
        Write-Host "-ClaudeTempRoot $ClaudeRoot is ${cBad}: refused. Nothing done." -ForegroundColor Red
        exit 2
    }
}
$ProjRootClaude = $null
if ($ClaudeProjectsRoot) { $ProjRootClaude = Get-LongPath $ClaudeProjectsRoot }
elseif ($env:USERPROFILE -and [IO.Path]::IsPathRooted($env:USERPROFILE)) { $ProjRootClaude = Get-LongPath (Join-Path $env:USERPROFILE ".claude\projects") }

# typo guard (owner 08/11, g1 copy): a -TmpKeep / -ClaudeKeep entry that matches nothing refuses the whole run
if ($Selected -contains "tmp") {
    foreach ($n in $TmpKeep) {
        if (-not (Test-Path -LiteralPath (Join-Path $TmpRoot $n))) {
            Write-Host "-TmpKeep: no entry $n under $TmpRoot (typo?). Nothing done." -ForegroundColor Red; exit 2
        }
    }
}
if ($Selected -contains "claude_temp" -and $ClaudeKeep.Count) {
    $sids = @()
    if ($ClaudeRoot -and (Test-Path -LiteralPath $ClaudeRoot -PathType Container)) {
        foreach ($p in @(Get-ChildItem -LiteralPath $ClaudeRoot -Directory -Force | Where-Object { -not (Test-Reparse $_) })) {
            $sids += @(Get-ChildItem -LiteralPath $p.FullName -Directory -Force | ForEach-Object { $_.Name.ToLowerInvariant() })
        }
    }
    foreach ($n in $ClaudeKeep) {
        if (@($sids | Where-Object { $_ -match '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' -and $_.StartsWith($n) }).Count -eq 0) {
            Write-Host "-ClaudeKeep: no session folder $n* under $ClaudeRoot\<project> (typo?). Nothing done." -ForegroundColor Red; exit 2
        }
    }
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

function Get-ProtectReason([string]$Path, [string]$Allow = "") {
    # path strings only say nothing about where a junction leads: any reparse point in the chain refuses the path.
    # $Allow = one protected key whose entries (strictly below it, never the key folder itself) a group may select:
    # installs (a version folder) and dist_versions (a package in dist\)
    $rp = Get-ReparseInChain $Path
    if ($rp) { return "reparse point in path: $rp" }
    $p = (Get-LongPath $Path) + '\'
    foreach ($k in $Protected.Keys) {
        if ($Allow -and $k -ieq $Allow -and $p.Length -gt $k.Length -and $p.StartsWith($k, [StringComparison]::OrdinalIgnoreCase)) { continue }
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
                       kept_uncertain = (New-Object System.Collections.ArrayList)
                       skipped = (New-Object System.Collections.ArrayList); errors = (New-Object System.Collections.ArrayList) }
}

function Add-Candidate($G, [string]$Path, [string]$Kind, [long]$Bytes, [datetime]$Time, [string]$Reason, [string]$Allow = "") {
    $why = Get-ProtectReason $Path $Allow
    if ($why) { [void]$G.skipped.Add([ordered]@{ path = $Path; reason = "protected ($why)" }); return $null }
    $c = [ordered]@{ path = $Path; kind = $Kind; bytes = $Bytes; age_days = [math]::Round(($Now - $Time).TotalDays, 1)
                     last_write = $Time.ToString("s"); reason = $Reason }
    if ($Allow) { $c["allow"] = $Allow }
    [void]$G.candidates.Add($c)
    $G.candidate_count += 1
    $G.candidate_bytes += $Bytes
    return $c
}

function Add-Skip($G, [string]$Path, [string]$Reason) { [void]$G.skipped.Add([ordered]@{ path = $Path; reason = $Reason }) }

function Add-Uncertain($G, [string]$Path, [long]$Bytes, [string]$Reason) {
    # owner rule 08/11: not sure -> kept and listed
    [void]$G.kept_uncertain.Add([ordered]@{ path = $Path; bytes = $Bytes; reason = $Reason })
}

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
    if (-not $Inst.ok) { $g.status = "skipped"; $g.note = "$($Inst.note): current version unknown, nothing selected"; return $g }
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
    $srt = @($zips | Sort-Object t, name)
    if ($srt.Count) { $keep[$srt[$srt.Count - 1].name] = "newest backup overall" }
    foreach ($z in $srt) {
        if (($Now - $z.t).TotalDays -le 7 -and -not $keep.ContainsKey($z.name)) { $keep[$z.name] = "backup of the last 7 days" }
    }
    foreach ($ver in $Inst.keep) {
        # cai_14x.py: backup reason "pre-1.4.6" -> backup-<stamp>-pre-146.zip (backup.py keeps letters, digits, - and _)
        $tag = "pre-" + $ver.Replace('.', '')
        $pre = @($srt | Where-Object { $_.kind -eq $tag -or $_.kind -like "$tag-*" -or $_.kind -like "${tag}_*" })
        if ($pre.Count -and -not $keep.ContainsKey($pre[$pre.Count - 1].name)) {
            $keep[$pre[$pre.Count - 1].name] = "newest $tag backup (before the install of $ver)"
        }
    }
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
    # 08/11: only the installs of the current and the previous version keep backups (deploy pairs stay recorded in
    # install-history.json but no longer keep a backup by themselves)
    $installs = @($Script:InstallHistory | Where-Object { $Inst.keep -contains $_.version } |
                  ForEach-Object { [pscustomobject]@{ t = [datetime]::ParseExact($_.created, "s", $Inv); version = $_.version } } |
                  Sort-Object t)
    foreach ($ins in $installs) {
        $it = $ins.t
        $before = @($zips | Where-Object { $_.t -le $it } | Sort-Object t, name)
        if ($before.Count -eq 0) { continue }
        $nb = $before[$before.Count - 1]
        if (-not $keep.ContainsKey($nb.name)) { $keep[$nb.name] = "newest backup before install of $($ins.version) $($it.ToString('s'))" }
        foreach ($z in @($before | Where-Object { ($it - $_.t).TotalMinutes -le 20 })) {
            if (-not $keep.ContainsKey($z.name)) { $keep[$z.name] = "taken within 20 min before install of $($ins.version) $($it.ToString('s'))" }
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
    $g.note = "kept versions: $($Inst.keep -join ', '), their installs known: $($installs.Count); backup zips: $($zips.Count), kept: $($keep.Count)"
    return $g
}

# ------------------------------------------------------------------ exports
function Get-ExportGroup {
    if (-not $DataDir) { $g = New-Group "exports" @(); $g.status = "skipped"; $g.note = $Storage.note; return $g }
    $root = Join-Path $DataDir "exports\du_bao"
    $g = New-Group "exports" @($root)
    if (-not (Test-GroupRoot $g $root)) { $g.status = "skipped"; $g.note = "reparse point in path: nothing selected"; return $g }
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { $g.status = "skipped"; $g.note = "folder not found"; return $g }
    $days = @()
    foreach ($i in @(Get-ChildItem -LiteralPath $root -Force)) {
        if (Test-Reparse $i) { Add-Skip $g $i.FullName "reparse point (junction / symlink): not followed, not deleted"; continue }
        if (-not $i.PSIsContainer) { $g.before_bytes += $i.Length; continue }
        $tree = Get-Tree $i.FullName
        $bytes = Get-Sum $tree.files
        $g.before_bytes += $bytes
        if ($i.Name -notmatch '^\d{8}$') { continue }
        try { $d = [datetime]::ParseExact($i.Name, "yyyyMMdd", $Inv) } catch { continue }
        $days += [pscustomobject]@{ item = $i; d = $d; tree = $tree; bytes = $bytes }
    }
    # owner 08/11: the 30 newest day folders stay; a folder goes only when it is ALSO older than 30 days
    $newest = @{}
    foreach ($x in @($days | Sort-Object d -Descending | Select-Object -First 30)) { $newest[$x.item.Name] = $true }
    $boLimit = $Now.AddDays(-3)
    foreach ($x in $days) {
        $i = $x.item; $tree = $x.tree
        if (-not $newest.ContainsKey($i.Name) -and ($Today - $x.d).TotalDays -gt 30) {
            if ($tree.reparse.Count -or $tree.errors.Count) { Add-TreeIssues $g $tree; Add-Skip $g $i.FullName "contains a reparse point / unreadable entry: kept"; continue }
            [void](Add-Candidate $g $i.FullName "dir" $x.bytes $x.d "daily export folder outside the 30 newest days and older than 30 days ($($i.Name))")
            continue
        }
        # kept day: its earlier versions du_bao_YYYYMMDD_vK_bo.xlsx older than 3 days, only while a NEWER version file
        # du_bao_YYYYMMDD_vM.xlsx (M > K, not _bo) exists in the folder (a _TAM or other file does not count)
        $top = @($tree.files | Where-Object { $_.DirectoryName -ieq $i.FullName })
        $bo = @($top | Where-Object { $_.BaseName -match '_bo$' })
        if ($bo.Count -eq 0) { continue }
        $verRe = '^du_bao_' + $i.Name + '_v(\d+)$'
        $maxV = -1L
        foreach ($f in $top) {
            if ($f.Extension -ieq ".xlsx" -and $f.BaseName -match $verRe) { if ([long]$Matches[1] -gt $maxV) { $maxV = [long]$Matches[1] } }
        }
        $young = (($Today - $x.d).TotalDays -le 3)
        foreach ($f in $bo) {
            if ($f.Extension -ine ".xlsx" -or $f.BaseName -notmatch ('^du_bao_' + $i.Name + '_v(\d+)_bo$')) {
                Add-Uncertain $g $f.FullName $f.Length "_bo file not named du_bao_$($i.Name)_v<K>_bo.xlsx: kept"; continue
            }
            $k = [long]$Matches[1]
            if ($maxV -le $k) {
                Add-Uncertain $g $f.FullName $f.Length "no newer version file du_bao_$($i.Name)_v<M>.xlsx (M > $k) in the folder: kept"; continue
            }
            if ($young -or $f.LastWriteTime -ge $boLimit) { continue }
            [void](Add-Candidate $g $f.FullName "file" $f.Length $f.LastWriteTime "earlier version v$k of day $($i.Name) (_bo, newer v$maxV exists) older than 3 days")
        }
    }
    $g.note = "day folders: $($days.Count)"
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
    $limit = $Now.AddHours(-$TmpMinAgeHours)
    $g.note = "older than $TmpMinAgeHours h; -TmpKeep: $(if ($TmpKeep.Count) { $TmpKeep -join ', ' } else { 'none' })"
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
        if (@($TmpKeep | Where-Object { $_ -ieq $i.Name }).Count) { Add-Skip $g $i.FullName "kept by -TmpKeep"; continue }
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
        $c = Add-Candidate $g $i.FullName $kind $bytes $newest "temporary entry older than $TmpMinAgeHours h, no running process uses it"
        if ($c) { $c["tmp_entry"] = $true }
    }
    return $g
}

# ------------------------------------------------------------------ old deploy staging folders in %TEMP%
function Get-DeployTempGroup {
    if (-not $env:TEMP -or -not [IO.Path]::IsPathRooted($env:TEMP)) { $g = New-Group "deploy_temp" @(); $g.status = "skipped"; $g.note = "TEMP not set"; return $g }
    $root = Get-LongPath $env:TEMP
    $g = New-Group "deploy_temp" @($root)
    if (-not (Test-GroupRoot $g $root)) { $g.status = "skipped"; $g.note = "reparse point in path: nothing selected"; return $g }
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { $g.status = "skipped"; $g.note = "folder not found"; return $g }
    if ($null -eq (Get-ProcLines)) { $g.status = "skipped"; $g.note = "process command lines unreadable: nothing selected"; return $g }
    $limit = $Now.AddDays(-1)
    # only DemandForecast-deploy-<stamp> (deploy-upgrade.ps1 before 1.2.14); the managed DemandForecast-deploy\ is not
    # matched (deploy-upgrade.ps1 removes its own run folder)
    foreach ($i in @(Get-ChildItem -LiteralPath $root -Directory -Force | Where-Object { $_.Name -like "DemandForecast-deploy-*" })) {
        if (Test-Reparse $i) { Add-Skip $g $i.FullName "reparse point (junction / symlink): not followed, not deleted"; continue }
        $tree = Get-Tree $i.FullName
        $bytes = Get-Sum $tree.files
        $g.before_bytes += $bytes
        $newest = $i.LastWriteTime
        if ($i.CreationTime -gt $newest) { $newest = $i.CreationTime }
        foreach ($lst in @($tree.files, $tree.dirs)) {
            foreach ($x in $lst) {
                if ($x.LastWriteTime -gt $newest) { $newest = $x.LastWriteTime }
                if ($x.CreationTime -gt $newest) { $newest = $x.CreationTime }
            }
        }
        if ($newest -ge $limit) { continue }
        $users = @(Get-PathUsers $i.FullName)
        if ($users.Count) { Add-Skip $g $i.FullName "used by running process(es) $($users -join ', '): kept"; continue }
        if ($tree.reparse.Count -or $tree.errors.Count) { Add-TreeIssues $g $tree; Add-Skip $g $i.FullName "contains a reparse point / unreadable entry: kept"; continue }
        [void](Add-Candidate $g $i.FullName "dir" $bytes $newest "deploy staging folder older than 1 day, no running process uses it")
    }
    return $g
}

# ------------------------------------------------------------------ finished Claude Code sessions in %TEMP%\claude
$SessionRe = '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'

function Get-SessionUsers([string]$Path, [string]$Session) {
    # pids naming the session folder (long / 8.3 / Git Bash form, Get-PathUsers) or the session id; $null = unreadable
    $procs = Get-ProcLines
    if ($null -eq $procs) { return $null }
    $sid = $Session.ToLowerInvariant()
    return @(@(Get-PathUsers $Path) + @($procs | Where-Object { $_.text.Contains($sid) } | ForEach-Object { $_.pid }) | Sort-Object -Unique)
}

function Get-TranscriptTime([string]$Session) {
    # newest last write time of the session transcript <projects>\<any project>\<id>.jsonl and of <projects>\<any
    # project>\<id>\** (subagent transcripts), READ ONLY; $null = none found. A session resumed with --resume names no
    # id / path on its command line: its transcript is what shows it is still running.
    if (-not $ProjRootClaude -or -not (Test-Path -LiteralPath $ProjRootClaude -PathType Container)) { return $null }
    $newest = $null
    foreach ($d in @(Get-ChildItem -LiteralPath $ProjRootClaude -Directory -Force | Where-Object { -not (Test-Reparse $_) })) {
        $f = Join-Path $d.FullName "$Session.jsonl"
        if (Test-Path -LiteralPath $f -PathType Leaf) {
            $t = (Get-Item -LiteralPath $f -Force).LastWriteTime
            if ($null -eq $newest -or $t -gt $newest) { $newest = $t }
        }
        $sd = Join-Path $d.FullName $Session
        if (Test-Path -LiteralPath $sd -PathType Container) {
            $tr = Get-Tree $sd
            foreach ($x in $tr.files) { if ($null -eq $newest -or $x.LastWriteTime -gt $newest) { $newest = $x.LastWriteTime } }
        }
    }
    return $newest
}

function Get-ClaudeTempGroup {
    if (-not $ClaudeRoot) { $g = New-Group "claude_temp" @(); $g.status = "skipped"; $g.note = "TEMP not set and no -ClaudeTempRoot"; return $g }
    $g = New-Group "claude_temp" @($ClaudeRoot)
    if (-not (Test-GroupRoot $g $ClaudeRoot)) { $g.status = "skipped"; $g.note = "reparse point in path: nothing selected"; return $g }
    if (-not (Test-Path -LiteralPath $ClaudeRoot -PathType Container)) { $g.status = "skipped"; $g.note = "folder not found"; return $g }
    if ($null -eq (Get-ProcLines)) { $g.status = "skipped"; $g.note = "process command lines unreadable: nothing selected"; return $g }
    $limit = $Now.AddHours(-$ClaudeMinAgeHours)
    $trn = if ($ProjRootClaude -and (Test-Path -LiteralPath $ProjRootClaude -PathType Container)) { $ProjRootClaude } else { "none found ($ProjRootClaude): folder age only" }
    $g.note = "session folders <project>\<GUID> older than $ClaudeMinAgeHours h (before = these folders only); transcripts: $trn; -ClaudeKeep: $(if ($ClaudeKeep.Count) { $ClaudeKeep -join ', ' } else { 'none' })"
    # only <root>\<project>\<GUID>: files under the root, project folders themselves and non-GUID folders are ignored
    foreach ($p in @(Get-ChildItem -LiteralPath $ClaudeRoot -Directory -Force)) {
        if (Test-Reparse $p) { Add-Skip $g $p.FullName "reparse point (junction / symlink): not followed, not deleted"; continue }
        foreach ($i in @(Get-ChildItem -LiteralPath $p.FullName -Directory -Force | Where-Object { $_.Name -match $SessionRe })) {
            if (Test-Reparse $i) { Add-Skip $g $i.FullName "reparse point (junction / symlink): not followed, not deleted"; continue }
            $tree = Get-Tree $i.FullName
            $bytes = Get-Sum $tree.files
            $g.before_bytes += $bytes
            $sid = $i.Name.ToLowerInvariant()
            $k = @($ClaudeKeep | Where-Object { $sid.StartsWith($_) })
            if ($k.Count) { Add-Skip $g $i.FullName "kept by -ClaudeKeep ($($k[0]))"; continue }
            $newest = $i.LastWriteTime
            if ($i.CreationTime -gt $newest) { $newest = $i.CreationTime }
            foreach ($lst in @($tree.files, $tree.dirs)) {
                foreach ($x in $lst) {
                    if ($x.LastWriteTime -gt $newest) { $newest = $x.LastWriteTime }
                    if ($x.CreationTime -gt $newest) { $newest = $x.CreationTime }
                }
            }
            if ($newest -ge $limit) { continue }
            $tt = Get-TranscriptTime $sid
            if ($null -ne $tt -and $tt -ge $limit) { Add-Skip $g $i.FullName "session transcript written $($tt.ToString('s')) (newer than $ClaudeMinAgeHours h): session may be running, kept"; continue }
            $users = @(Get-SessionUsers $i.FullName $sid)
            if ($users.Count) { Add-Skip $g $i.FullName "used by running process(es) $($users -join ', '): kept"; continue }
            if ($tree.reparse.Count -or $tree.errors.Count) { Add-TreeIssues $g $tree; Add-Skip $g $i.FullName "contains a reparse point / unreadable entry: kept"; continue }
            $open = @($tree.files | Where-Object { $_.Name -match '\.(db|sqlite|sqlite3)(-wal|-shm|-journal)?$' -and (Test-InUse $_.FullName) })
            if ($open.Count) { Add-Skip $g $i.FullName "database file in use ($($open[0].Name)): kept"; continue }
            $c = Add-Candidate $g $i.FullName "dir" $bytes $newest "finished Claude Code session: folder and transcript older than $ClaudeMinAgeHours h, no running process names it"
            if ($c) { $c["session_id"] = $sid }
        }
    }
    return $g
}

# ------------------------------------------------------------------ packaged experiments
function Get-ReportGroup {
    $root = Join-Path $ProjectRoot "reports"
    $g = New-Group "reports" @($root)
    if (-not (Test-GroupRoot $g $root)) { $g.status = "skipped"; $g.note = "reparse point in path: nothing selected"; return $g }
    $keepFile = if ($KeepListFile) { $KeepListFile } else { Join-Path $PSScriptRoot "don_dep_giu.txt" }
    if (-not (Test-Path -LiteralPath $keepFile -PathType Leaf)) { $g.status = "skipped"; $g.note = "keep list not found: $keepFile"; return $g }
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { $g.status = "skipped"; $g.note = "folder not found"; return $g }
    $keepList = @{}
    foreach ($line in Get-Content -LiteralPath $keepFile) {
        $s = $line.Trim()
        if ($s -and -not $s.StartsWith("#")) { $keepList[$s] = $true }
    }
    # concluded experiments (owner 08/11): optional list next to the keep list; missing = none
    $doneList = @{}
    $doneFile = if ($ConcludedListFile) { $ConcludedListFile } else { Join-Path $PSScriptRoot "don_dep_ket_luan.txt" }
    if (Test-Path -LiteralPath $doneFile -PathType Leaf) {
        foreach ($line in Get-Content -LiteralPath $doneFile) {
            $s = $line.Trim()
            if ($s -and -not $s.StartsWith("#")) { $doneList[$s] = $true }
        }
    }
    $g.note = "keep list: $($keepList.Count) folder(s) ($keepFile); concluded list: $($doneList.Count) folder(s) ($doneFile)"
    foreach ($n in @($doneList.Keys)) {
        if (-not (Test-Path -LiteralPath (Join-Path $root $n) -PathType Container)) { Add-Skip $g (Join-Path $root $n) "listed in don_dep_ket_luan.txt but not found" }
    }
    $dataExt = @(".parquet", ".csv", ".zip")
    $interExt = @(".parquet", ".pkl", ".npz", ".npy", ".log", ".tmp", ".feather")
    $alwaysKeep = @(".py", ".ps1", ".sql", ".ipynb", ".sh", ".r", ".bat", ".md", ".json", ".txt", ".yaml", ".yml")   # code / text
    foreach ($d in @(Get-ChildItem -LiteralPath $root -Directory -Force)) {
        if (Test-Reparse $d) { Add-Skip $g $d.FullName "reparse point (junction / symlink): not followed, not deleted"; continue }
        $pk = @(Get-ChildItem -LiteralPath $d.FullName -Directory -Force | Where-Object { $_.Name -like "package*" -and -not (Test-Reparse $_) } |
                ForEach-Object { $_.Name })
        $done = $doneList.ContainsKey($d.Name)
        if ($pk.Count -eq 0 -and -not $done) { continue }
        if ($keepList.ContainsKey($d.Name)) { Add-Skip $g $d.FullName "in keep list (don_dep_giu.txt)"; continue }
        $tree = Get-Tree $d.FullName
        Add-TreeIssues $g $tree
        $g.before_bytes += Get-Sum $tree.files
        $sup = if ($done) { Get-Superseded $tree.files } else { [pscustomobject]@{ sup = @{}; variant = @{} } }
        foreach ($f in $tree.files) {
            $rel = $f.FullName.Substring($d.FullName.Length + 1)
            $parts = $rel.Split('\')
            $inPk = ($parts.Count -gt 1 -and $pk -contains $parts[0])               # inside a package folder
            $ext = $f.Extension.ToLowerInvariant()
            if ($pk.Count -and -not $inPk -and $f.Extension -ne ".md" -and $f.Name -notlike "package*" -and
                (($dataExt -contains $ext) -or $f.Name -like "order_lines*")) {
                [void](Add-Candidate $g $f.FullName "file" $f.Length $f.LastWriteTime "data file of packaged experiment $($d.Name) outside its package folder")
                continue
            }
            if (-not $done -or $alwaysKeep -contains $ext) { continue }
            $why = $null
            if ($interExt -contains $ext) { $why = "intermediate data file ($ext)" }
            elseif ($sup.sup.ContainsKey($f.FullName)) { $why = "superseded by $($sup.sup[$f.FullName])" }
            elseif ($sup.variant.ContainsKey($f.FullName)) {
                Add-Uncertain $g $f.FullName $f.Length "variant $($sup.variant[$f.FullName]) of concluded experiment $($d.Name) (letter suffix): kept"; continue
            }
            if (-not $why) { continue }
            if ($inPk) { Add-Uncertain $g $f.FullName $f.Length "inside package folder $($parts[0]) of concluded experiment $($d.Name) ($why): kept"; continue }
            if (Test-InUse $f.FullName) { Add-Skip $g $f.FullName "file in use: not touched"; continue }
            [void](Add-Candidate $g $f.FullName "file" $f.Length $f.LastWriteTime "concluded experiment $($d.Name): $why")
        }
    }
    return $g
}

function Get-Superseded($Files) {
    # .sup: FullName -> name of the newer version: stem <base>_v<N>, same folder, same extension, a higher plain N exists.
    # .variant: FullName -> stem of a lettered version <base>_v<N><letters> (_v3b: a variant, not a newer version) of a
    # base that has other versions: kept (kept_uncertain), and never counted as superseding another file
    $groups = @{}
    foreach ($f in $Files) {
        if ($f.BaseName -notmatch '^(.+)_v(\d+)([A-Za-z]*)$') { continue }
        $key = "$($f.DirectoryName)|$($Matches[1])|$($f.Extension)".ToLowerInvariant()
        if (-not $groups.ContainsKey($key)) { $groups[$key] = New-Object System.Collections.ArrayList }
        [void]$groups[$key].Add([pscustomobject]@{ f = $f; n = [long]$Matches[2]; s = $Matches[3].ToLowerInvariant() })
    }
    $res = [pscustomobject]@{ sup = @{}; variant = @{} }
    foreach ($lst in $groups.Values) {
        if ($lst.Count -lt 2) { continue }
        foreach ($x in @($lst | Where-Object { $_.s })) { $res.variant[$x.f.FullName] = $x.f.BaseName }
        $plain = @($lst | Where-Object { -not $_.s } | Sort-Object n)
        if ($plain.Count -lt 2) { continue }
        $top = $plain[$plain.Count - 1]
        foreach ($x in $plain) {
            if ($x.n -lt $top.n) { $res.sup[$x.f.FullName] = $top.f.Name }
        }
    }
    return $res
}

# ------------------------------------------------------------------ installed version folders
function Get-TaskActionVersions([string]$Text, [string]$Base) {
    # versions x.y.z whose folder <Base>\<x.y.z> (or something inside it) a task action names; %VAR% expanded, / -> \;
    # the version must end at \ " ' a blank or the end (1.4.30 never counts as 1.4.3)
    $txt = [Environment]::ExpandEnvironmentVariables($Text).ToLowerInvariant().Replace('/', '\')
    $pre = [regex]::Escape($Base.ToLowerInvariant().TrimEnd('\') + '\')
    $bs = [string][char]92
    $re = $pre + '(\d+\.\d+\.\d+)(?=' + [regex]::Escape($bs) + '|"|''|\s|$)'
    return @([regex]::Matches($txt, $re) | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique)
}

function Get-InstallGroup {
    $g = New-Group "installs" @($ProgDir)
    if (-not (Test-GroupRoot $g $ProgDir)) { $g.status = "skipped"; $g.note = "reparse point in path: nothing selected"; return $g }
    if (-not $Inst.ok) { $g.status = "skipped"; $g.note = "$($Inst.note): nothing selected"; return $g }
    if ($null -eq (Get-ProcLines)) { $g.status = "skipped"; $g.note = "process command lines unreadable: nothing selected"; return $g }
    $g.note = $Inst.note
    $allow = $ProgDir.TrimEnd('\') + '\'
    # a version folder named in a scheduled task action (program, arguments, working folder) is kept
    $taskVers = @{}
    try {
        foreach ($t in @(Get-ScheduledTask -ErrorAction Stop)) {
            foreach ($a in @($t.Actions)) {
                foreach ($v in @(Get-TaskActionVersions "$($a.Execute) $($a.Arguments) $($a.WorkingDirectory)" $ProgDir)) {
                    $taskVers[$v] = (@($taskVers[$v], $t.TaskName) | Where-Object { $_ }) -join ', '
                }
            }
        }
    } catch { $g.status = "skipped"; $g.note = "scheduled tasks unreadable: nothing selected"; return $g }
    foreach ($i in @(Get-ChildItem -LiteralPath $ProgDir -Directory -Force)) {
        if (Test-Reparse $i) { Add-Skip $g $i.FullName "reparse point (junction / symlink): not followed, not deleted"; continue }
        $tree = Get-Tree $i.FullName
        $bytes = Get-Sum $tree.files
        $g.before_bytes += $bytes
        if ($i.Name -notmatch '^\d+\.\d+\.\d+$') { Add-Uncertain $g $i.FullName $bytes "not a version folder x.y.z: kept"; continue }
        if ($Inst.keep -contains $i.Name) { continue }
        if ([version]$i.Name -gt [version]$Inst.current) { Add-Uncertain $g $i.FullName $bytes "newer than the current version $($Inst.current): kept"; continue }
        if ($taskVers.ContainsKey($i.Name)) { Add-Uncertain $g $i.FullName $bytes "named in scheduled task(s) $($taskVers[$i.Name]): kept"; continue }
        $users = @(Get-PathUsers $i.FullName)
        if ($users.Count) { Add-Skip $g $i.FullName "used by running process(es) $($users -join ', '): kept"; continue }
        if ($tree.reparse.Count -or $tree.errors.Count) { Add-TreeIssues $g $tree; Add-Skip $g $i.FullName "contains a reparse point / unreadable entry: kept"; continue }
        $c = Add-Candidate $g $i.FullName "dir" $bytes $i.CreationTime "installed version $($i.Name) is neither the current ($($Inst.current)) nor the previous ($($Inst.previous))" $allow
        if ($c) { $c["install_version"] = $i.Name }
    }
    return $g
}

# ------------------------------------------------------------------ dist folders: packages of other versions
function Get-DistVersionGroup {
    $roots = @(Join-Path $ProjectRoot "dist")
    $wt = Join-Path $ProjectRoot "worktrees"
    if ((Test-Path -LiteralPath $wt -PathType Container) -and -not (Get-ReparseInChain $wt)) {
        foreach ($w in @(Get-ChildItem -LiteralPath $wt -Directory -Force | Where-Object { -not (Test-Reparse $_) })) { $roots += (Join-Path $w.FullName "dist") }
    }
    $g = New-Group "dist_versions" $roots
    if (-not $Inst.ok) { $g.status = "skipped"; $g.note = "$($Inst.note): nothing selected"; return $g }
    $keepV = @(@($Inst.keep) + @($DistKeep) | Sort-Object -Unique)
    $g.note = "kept versions: $($keepV -join ', ')"
    $allow = (Join-Path $ProjectRoot "dist") + '\'
    foreach ($r in $roots) {
        if (-not (Test-Path -LiteralPath $r)) { continue }
        if (-not (Test-GroupRoot $g $r)) { continue }
        if (-not (Test-Path -LiteralPath $r -PathType Container)) { continue }
        foreach ($i in @(Get-ChildItem -LiteralPath $r -Force | Where-Object { $_.Name -like "DemandForecast-*" })) {
            if (Test-Reparse $i) { Add-Skip $g $i.FullName "reparse point (junction / symlink): not followed, not deleted"; continue }
            $tree = $null
            if ($i.PSIsContainer) { $tree = Get-Tree $i.FullName; $bytes = Get-Sum $tree.files } else { $bytes = $i.Length }
            $g.before_bytes += $bytes
            if ($i.Name -notmatch '^DemandForecast-(\d+\.\d+\.\d+)(?=$|[-.])') { Add-Uncertain $g $i.FullName $bytes "no version x.y.z in the name: kept"; continue }
            $v = $Matches[1]
            if ($keepV -contains $v) { continue }
            if ([version]$v -gt [version]$Inst.current) { Add-Uncertain $g $i.FullName $bytes "version $v newer than the current version $($Inst.current): kept"; continue }
            if ($null -ne $tree -and ($tree.reparse.Count -or $tree.errors.Count)) { Add-TreeIssues $g $tree; Add-Skip $g $i.FullName "contains a reparse point / unreadable entry: kept"; continue }
            $kind = if ($i.PSIsContainer) { "dir" } else { "file" }
            [void](Add-Candidate $g $i.FullName $kind $bytes $i.LastWriteTime "package entry of version $v (kept: $($keepV -join ', '))" $allow)
        }
    }
    return $g
}

# ------------------------------------------------------------------ worktrees (information only)
function Get-WorktreeInfo {
    $res = New-Object System.Collections.ArrayList
    $wt = Join-Path $ProjectRoot "worktrees"
    if (-not (Test-Path -LiteralPath $wt -PathType Container) -or (Get-ReparseInChain $wt)) { return , $res }
    $git = Get-Command git.exe -ErrorAction SilentlyContinue
    $ErrorActionPreference = "Continue"           # git writes to stderr; only its exit code / output matter here
    foreach ($w in @(Get-ChildItem -LiteralPath $wt -Directory -Force | Where-Object { -not (Test-Reparse $_) })) {
        if (-not (Test-Path -LiteralPath (Join-Path $w.FullName ".git"))) { continue }
        $info = [ordered]@{ path = $w.FullName; branch = ""; version = ""; clean = $false; pushed = $false; tag = $false
                            installed = $false; can_remove = $false; reason = "" }
        $init = Join-Path $w.FullName "backend\app\__init__.py"
        if (Test-Path -LiteralPath $init -PathType Leaf) {
            $m = Select-String -LiteralPath $init -Pattern '^__version__\s*=\s*"(\d+\.\d+\.\d+)"' | Select-Object -First 1
            if ($m) { $info.version = $m.Matches[0].Groups[1].Value }
        }
        if (-not $git) { $info.reason = "git not found"; [void]$res.Add($info); continue }
        $info.branch = "$(& $git.Source -C $w.FullName branch --show-current 2>$null)".Trim()
        $st = @(& $git.Source -C $w.FullName --no-optional-locks status --porcelain 2>$null)
        $info.clean = ($LASTEXITCODE -eq 0 -and $st.Count -eq 0)
        $rb = @(& $git.Source -C $w.FullName branch -r --contains HEAD 2>$null)
        $info.pushed = ($LASTEXITCODE -eq 0 -and $rb.Count -gt 0)
        if ($info.version) {
            $tg = @(& $git.Source -C $w.FullName tag -l "v$($info.version)" 2>$null)
            $info.tag = ($tg.Count -gt 0)
            $info.installed = ($Inst.versions -contains $info.version)
        }
        $why = @()
        if (-not $info.version) { $why += "version unknown" }
        if (-not $info.clean) { $why += "uncommitted changes (or git status failed)" }
        if (-not $info.pushed) { $why += "HEAD not on a remote-tracking branch" }
        if ($info.version -and -not $info.tag) { $why += "tag v$($info.version) not found" }
        if ($info.version -and -not $info.installed) { $why += "version not installed" }
        $info.can_remove = ($why.Count -eq 0)
        $info.reason = if ($why.Count) { $why -join "; " } else { "clean, pushed, tagged, installed (remove with scripts\ops\archive_worktree.py)" }
        [void]$res.Add($info)
    }
    return , $res
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
    $pk = @(@($DistKeep) + @(if ($Inst.ok) { $Inst.keep }) | Sort-Object -Unique)    # + current / previous (08/11)
    if ($pk.Count) { $p["Keep"] = $pk }
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
    $allow = if ($C.Contains("allow")) { $C.allow } else { "" }
    $why = Get-ProtectReason $p $allow
    if ($why) { [void]$G.errors.Add("${p}: refused, protected ($why)"); return }
    try {
        if (-not (Test-Path -LiteralPath $p)) { Add-Skip $G $p "gone before deletion"; return }
        $it = Get-Item -LiteralPath $p -Force
        if (Test-Reparse $it) { Add-Skip $G $p "reparse point at deletion time: not deleted"; return }
        if ($C.Contains("install_version")) {
            # checked again right before the deletion: current.txt still readable and naming another version, the
            # folder still not used by a running process (process list read again)
            $inst2 = Read-InstallState
            if (-not $inst2.ok -or $inst2.keep -contains $C.install_version -or -not $it.PSIsContainer -or
                [version]$C.install_version -gt [version]$inst2.current) {
                Add-Skip $G $p "current / previous version changed or current.txt unreadable at deletion time: not deleted"; return
            }
            $Script:ProcLines = $null
            if ($null -eq (Get-ProcLines)) { Add-Skip $G $p "process list unreadable at deletion time: not deleted"; return }
            $users = @(Get-PathUsers $p)
            if ($users.Count) { Add-Skip $G $p "used by running process(es) $($users -join ', ') at deletion time: not deleted"; return }
        }
        if ($C.Contains("session_id")) {
            # claude_temp: process list read again, age and open database files checked again right before the deletion
            $Script:ProcLines = $null
            if ($null -eq (Get-ProcLines)) { Add-Skip $G $p "process list unreadable at deletion time: not deleted"; return }
            $users = @(Get-SessionUsers $p $C.session_id)
            if ($users.Count) { Add-Skip $G $p "used by running process(es) $($users -join ', ') at deletion time: not deleted"; return }
            $t = Get-Tree $p
            $limit = $Now.AddHours(-$ClaudeMinAgeHours)
            $young = @($t.files.ToArray() + $t.dirs.ToArray() | Where-Object { $_.LastWriteTime -ge $limit -or $_.CreationTime -ge $limit })
            if ($young.Count -or $it.LastWriteTime -ge $limit -or $it.CreationTime -ge $limit) { Add-Skip $G $p "changed after the plan (newer than $ClaudeMinAgeHours h) at deletion time: not deleted"; return }
            $open = @($t.files | Where-Object { $_.Name -match '\.(db|sqlite|sqlite3)(-wal|-shm|-journal)?$' -and (Test-InUse $_.FullName) })
            if ($open.Count) { Add-Skip $G $p "database file in use ($($open[0].Name)) at deletion time: not deleted"; return }
            $tt = Get-TranscriptTime $C.session_id
            if ($null -ne $tt -and $tt -ge $limit) { Add-Skip $G $p "session transcript written $($tt.ToString('s')) at deletion time: not deleted"; return }
        }
        if ($C.Contains("tmp_entry")) {
            # tmp: process command lines read again (same needles as Get-TmpGroup), age and open database files
            # checked again right before the deletion
            $Script:ProcLines = $null
            $procs = Get-ProcLines
            if ($null -eq $procs) { Add-Skip $G $p "process list unreadable at deletion time: not deleted"; return }
            $needles = @($p.ToLowerInvariant())
            if ($p -match '^([A-Za-z]):\\(.*)$') { $needles += ("\" + $Matches[1] + "\" + $Matches[2]).ToLowerInvariant() }
            $users = @($procs | Where-Object { $q = $_; @($needles | Where-Object { $q.text.Contains($_) }).Count -gt 0 } | ForEach-Object { $_.pid })
            if ($users.Count) { Add-Skip $G $p "used by running process(es) $($users -join ', ') at deletion time: not deleted"; return }
            $limit = $Now.AddHours(-$TmpMinAgeHours)
            $all = @($it)
            if ($it.PSIsContainer) { $t = Get-Tree $p; $all += $t.files.ToArray() + $t.dirs.ToArray() }
            $young = @($all | Where-Object { $_.LastWriteTime -ge $limit -or $_.CreationTime -ge $limit })
            if ($young.Count) { Add-Skip $G $p "changed after the plan (newer than $TmpMinAgeHours h) at deletion time: not deleted"; return }
            $open = @($all | Where-Object { -not $_.PSIsContainer -and $_.Name -match '\.(db|sqlite|sqlite3)(-wal|-shm|-journal)?$' -and (Test-InUse $_.FullName) })
            if ($open.Count) { Add-Skip $G $p "database file in use ($($open[0].Name)) at deletion time: not deleted"; return }
        }
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
    $pk = @(@($DistKeep) + @(if ($Inst.ok) { $Inst.keep }) | Sort-Object -Unique)    # + current / previous (08/11)
    if ($pk.Count) { $p["Keep"] = $pk }
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
                      dist_keep = @($DistKeep); tmp_root = $TmpRoot; groups_selected = @($Selected)
                      tmp_min_age_hours = $TmpMinAgeHours; tmp_keep = @($TmpKeep); claude_temp_root = $ClaudeRoot
                      claude_keep = @($ClaudeKeep); claude_min_age_hours = $ClaudeMinAgeHours
                      data_dir = $DataDir; storage_note = $Storage.note; current_version = $Inst.current
                      previous_version = $Inst.previous; install_note = $Inst.note; groups = @(); totals = $null
                      kept_uncertain = @(); worktrees = @(); errors = @(); exit_code = 0 }
$results = @()
# dist_versions before dist: its own deletions first, prune-artifacts.ps1 (-IncludeDist) afterwards
$fns = [ordered]@{ "Get-BackupGroup" = "backups"; "Get-ExportGroup" = "exports"; "Get-LogGroup" = "logs"; "Get-TmpGroup" = "tmp"
                   "Get-DeployTempGroup" = "deploy_temp"; "Get-ReportGroup" = "reports"; "Get-InstallGroup" = "installs"
                   "Get-DistVersionGroup" = "dist_versions"; "Get-DistGroup" = "dist"; "Get-ClaudeTempGroup" = "claude_temp" }
foreach ($fn in @($fns.Keys)) {
    if ($Selected -notcontains $fns[$fn]) { continue }       # -Groups: the other groups are not computed at all
    try { $results += , (& $fn) }
    catch {
        $gname = $fns[$fn]
        $g = New-Group $gname @()
        $g.status = "error"; [void]$g.errors.Add("line $($_.InvocationInfo.ScriptLineNumber): $($_.Exception.Message) $($_.ScriptStackTrace)")
        $results += , $g
    }
}
if ($Apply) {
    foreach ($g in $results) {
        if ($g.status -ne "ok") { continue }
        $g["applied"] = $true
        if ($g.group -eq "logs") { Invoke-LogArchive $g }
        elseif ($g.group -eq "dist") { Invoke-DistApply $g }
        else { foreach ($c in @($g.candidates)) { Remove-Candidate $g $c } }
    }
}
$tot = [ordered]@{ before_bytes = 0L; candidate_count = 0; candidate_bytes = 0L; after_bytes = 0L; deleted_count = 0; deleted_bytes = 0L
                   kept_uncertain_count = 0; kept_uncertain_bytes = 0L }
$uncertain = New-Object System.Collections.ArrayList
foreach ($g in $results) {
    if ($Apply) { $g.after_bytes = $g.before_bytes - $g.deleted_bytes }
    elseif ($g.group -eq "dist" -and -not $IncludeDist) { $g.after_bytes = $g.before_bytes }
    else { $g.after_bytes = $g.before_bytes - $g.candidate_bytes }
    if ($g.errors.Count -and $g.status -eq "ok") { $g.status = "error" }
    foreach ($u in $g.kept_uncertain) { [void]$uncertain.Add([ordered]@{ group = $g.group; path = $u.path; bytes = $u.bytes; reason = $u.reason }) }
    $tot.kept_uncertain_count += $g.kept_uncertain.Count
    foreach ($u in $g.kept_uncertain) { $tot.kept_uncertain_bytes += $u.bytes }
    # the prune-artifacts.ps1 plan overlaps dist_versions (same dist\ packages): only its deletions count in the totals
    $keys = if ($g.group -eq "dist") { @("deleted_count", "deleted_bytes") } else { @("before_bytes", "candidate_count", "candidate_bytes", "after_bytes", "deleted_count", "deleted_bytes") }
    foreach ($k in $keys) { $tot[$k] += $g[$k] }
}
$report.groups = $results
$report.totals = $tot
$report.kept_uncertain = $uncertain
try { $report.worktrees = Get-WorktreeInfo }
catch { $report.errors += "worktree info: $($_.Exception.Message)" }
$failed = @($results | Where-Object { $_.status -eq "error" }).Count -gt 0
$report.exit_code = if ($failed) { 1 } else { 0 }

$gb = { param($b) "{0:N3} GB" -f ($b / 1GB) }
$lines = @("Don dep dinh ky / periodic cleanup  mode=$mode  $($Now.ToString('s'))  project=$ProjectRoot  groups=$($Selected -join ',')")
if (-not $Apply) { $lines += "DRY RUN: nothing deleted. Re-run with -Apply to delete the candidates (dist only with -IncludeDist)." }
foreach ($g in $results) {
    $lines += ("{0,-13} {1,-8} candidates {2,5}  {3,12}  before {4,12}  after {5,12}{6}  uncertain {7}  skipped {8}  errors {9}  {10}" -f
               $g.group, $g.status, $g.candidate_count, (& $gb $g.candidate_bytes), (& $gb $g.before_bytes), (& $gb $g.after_bytes),
               $(if ($g.after_is_projection) { "*" } else { " " }), $g.kept_uncertain.Count, $g.skipped.Count, $g.errors.Count, $g.note)
}
$lines += ("TOTAL         candidates {0,5}  {1,12}  before {2,12}  after {3,12}  deleted {4} ({5})  kept_uncertain {6} ({7})" -f
           $tot.candidate_count, (& $gb $tot.candidate_bytes), (& $gb $tot.before_bytes), (& $gb $tot.after_bytes), $tot.deleted_count,
           (& $gb $tot.deleted_bytes), $tot.kept_uncertain_count, (& $gb $tot.kept_uncertain_bytes))
if (-not $Apply) { $lines += "* after = projection if applied (logs: archives add their compressed size; dist = prune-artifacts.ps1 plan, not in the totals)" }
foreach ($u in $uncertain) { $lines += ("kept_uncertain  {0,-13} {1,12}  {2}  - {3}" -f $u.group, (& $gb $u.bytes), $u.path, $u.reason) }
if ($Apply) {
    # owner 08/11: every candidate of an APPLY run in the .txt, deleted or not (with the reason)
    foreach ($g in $results) {
        foreach ($c in @($g.candidates)) {
            if ($c.Contains("deleted") -and $c.deleted) { $lines += ("deleted {0} {1} {2}" -f $g.group, (& $gb $c.bytes), $c.path); continue }
            $why = $null
            $sk = @($g.skipped | Where-Object { $_.path -eq $c.path })
            if ($sk.Count) { $why = $sk[$sk.Count - 1].reason }
            if (-not $why) {
                $pre = @("$($c.path):")
                if ($c.Contains("archive")) { $pre += "$($c.archive):" }
                $er = @($g.errors | Where-Object { $e = "$_"; @($pre | Where-Object { $e.StartsWith($_, [StringComparison]::OrdinalIgnoreCase) }).Count -gt 0 })
                if ($er.Count) { $why = "error: $($er[$er.Count - 1])" }
            }
            if (-not $why) {
                $why = if (-not $g.Contains("applied")) { "group not applied (status $($g.status))" }
                       elseif ($g.group -eq "dist" -and -not $IncludeDist) { "dist: deleted only with -IncludeDist" }
                       else { "no reason recorded" }
            }
            $lines += ("NOT deleted {0} {1} - {2}" -f $g.group, $c.path, $why)
        }
    }
}
foreach ($w in @($report.worktrees)) {
    if ($w.can_remove) { $lines += "worktree_can_remove  $($w.path)  (branch $($w.branch), version $($w.version))" }
    else { $lines += "worktree_kept  $($w.path)  ($($w.reason))" }
}
foreach ($e in @($report.errors)) { $lines += "error: $e" }
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
