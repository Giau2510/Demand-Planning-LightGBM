<#
.SYNOPSIS
  Read-only HTTPS link to the Demand Forecasting dashboard through a Cloudflare Quick Tunnel: no VPS, no domain, no
  router/firewall change, nothing to install for the viewer (Chrome only). Keep this file ASCII-only (PowerShell 5.1).
.DESCRIPTION
  start   app running? (else start it with the installed scripts\start.ps1) -> read-only proxy 127.0.0.1:<ProxyPort>
          (scripts\remote\readonly_proxy.py) -> cloudflared (downloaded once from the official GitHub release,
          SHA-256 and Authenticode signature checked) -> https://<random>.trycloudflare.com, verified from this PC
          (health, UI, a write refused). The tunnel NEVER points at the app port, only at the read-only proxy.
  stop    stops ONLY the tunnel and the proxy started by this script; the app keeps running.
  status  link, processes and health.
  -LocalOnly  start the app (if needed) and the proxy only, no tunnel (local check / diagnosis).
  Runtime files (cloudflared.exe, pid/link files, logs): %LOCALAPPDATA%\DemandForecastRemote (not the app data).
#>
param(
    [ValidateSet("start", "stop", "status")][string]$Action = "start",
    [int]$ProxyPort = 8766,
    [int]$MetricsPort = 8767,
    [string]$AppDir = "",
    [string]$PythonExe = "",
    [int]$AppPort = 0,
    [int]$AppStartTimeout = 150,
    [int]$TunnelTimeout = 90,
    [int]$VerifyTimeout = 120,
    [string]$ReleaseApi = "https://api.github.com/repos/cloudflare/cloudflared/releases/latest",
    [string]$QuickService = "",
    [string]$StateDir = "",
    [switch]$LocalOnly
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
if (-not $StateDir) { $StateDir = Join-Path $env:LOCALAPPDATA "DemandForecastRemote" }
$BinDir = Join-Path $StateDir "bin"
$RunDir = Join-Path $StateDir "run"
$LogDir = Join-Path $StateDir "logs"
foreach ($d in @($BinDir, $RunDir, $LogDir)) { if (-not (Test-Path $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null } }
$Cloudflared = Join-Path $BinDir "cloudflared.exe"
$CfMeta = Join-Path $BinDir "cloudflared.json"
$ProxyState = Join-Path $RunDir "proxy.json"
$TunnelState = Join-Path $RunDir "tunnel.json"
$ProxyScript = Join-Path $PSScriptRoot "readonly_proxy.py"

function Say([string]$m, [string]$c = "Gray") { Write-Host $m -ForegroundColor $c }
function Fail([string]$m, [string]$hint = "") {
    Write-Host ""
    Write-Host "LOI: $m" -ForegroundColor Red
    if ($hint) { Write-Host "Cach xu ly: $hint" -ForegroundColor Yellow }
    exit 1
}
function Read-State([string]$f) {
    if (-not (Test-Path $f)) { return $null }
    try { return (Get-Content $f -Raw | ConvertFrom-Json) } catch { return $null }
}
function Save-State([string]$f, $obj) { ($obj | ConvertTo-Json -Depth 4) | Set-Content -Path $f -Encoding ASCII }
function Get-Code([string]$method, [string]$url, [int]$timeout = 15) {
    # HTTP status of one request (0 = no answer); never throws
    try {
        $r = Invoke-WebRequest -Method $method -Uri $url -UseBasicParsing -TimeoutSec $timeout -MaximumRedirection 0 `
            -Headers @{ "Cache-Control" = "no-cache" }
        return [int]$r.StatusCode
    } catch {
        if ($_.Exception.Response) { return [int]$_.Exception.Response.StatusCode }
        return 0
    }
}
function Test-PortFree([int]$port) {
    $l = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $port)
    try { $l.Start(); $l.Stop(); return $true } catch { return $false }
}
function Get-ProxyProcesses([int]$port = 0) {
    # python processes running OUR proxy script (matched on the full script path in the command line, never by name)
    @(Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine.Contains($ProxyScript) -and
                       ($port -eq 0 -or $_.CommandLine.Contains("--listen-port $port ")) })
}
function Get-TunnelProcesses {
    # cloudflared processes started from OUR copy (matched on the executable path)
    @(Get-Process -Name "cloudflared" -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $Cloudflared })
}
function Show-Tail([string]$f, [int]$n = 15) {
    if (Test-Path $f) { Say "--- $f (cuoi) ---" "DarkGray"; Get-Content $f -Tail $n | ForEach-Object { Say $_ "DarkGray" } }
}

# ------------------------------------------------------------------ app (installed package, its own start script)
function Resolve-App {
    if ($AppDir) {
        if (-not (Test-Path (Join-Path $AppDir "scripts\start.ps1"))) { Fail "Khong thay scripts\start.ps1 trong $AppDir" }
        return (Resolve-Path $AppDir).Path
    }
    $base = Join-Path $env:LOCALAPPDATA "Programs\DemandForecast"
    $cur = Join-Path $base "current.txt"
    if (-not (Test-Path $cur)) {
        Fail "Khong tim thay ung dung Demand Forecasting da cai ($cur)." "Cai ung dung bang Install.bat cua goi phat hanh truoc."
    }
    $ver = (Get-Content $cur -Raw).Trim()
    $dir = Join-Path $base $ver
    if (-not (Test-Path (Join-Path $dir "scripts\start.ps1"))) { Fail "Ban cai $ver khong day du ($dir)." }
    return $dir
}

function Get-AppPortAndLogs([string]$app) {
    if ($AppPort -gt 0) { return @{ port = $AppPort; logs = "" } }
    # the app's own helpers: storage paths (backend resolver) + DF_PORT from <data>\app.env
    . (Join-Path $app "scripts\_common.ps1")
    try {
        $info = Get-PathInfo
        Import-AppEnv
        return @{ port = (Get-Port); logs = $info.logs_dir }
    } catch {
        Fail "Khong doc duoc cau hinh luu tru cua ung dung: $($_.Exception.Message)" "Chay Check-Environment.bat trong thu muc ung dung."
    }
}

function Test-App([int]$port) { return (Get-Code "GET" "http://127.0.0.1:$port/api/health" 4) -eq 200 }

function Start-AppIfNeeded([string]$app, [int]$port, [string]$logs) {
    if (Test-App $port) { Say "Ung dung dang chay: http://127.0.0.1:$port (giu nguyen, khong khoi dong lai)." "Green"; return }
    Say "Ung dung chua chay - dang khoi dong bang $app\scripts\start.ps1 (cho toi da $AppStartTimeout giay)..." "Yellow"
    $sp = Start-Process -FilePath "powershell.exe" -WindowStyle Hidden -PassThru -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$(Join-Path $app 'scripts\start.ps1')`"", "-NoBrowser")
    $t0 = Get-Date
    while (-not (Test-App $port)) {
        if (((Get-Date) - $t0).TotalSeconds -gt $AppStartTimeout) {
            if ($logs) { Show-Tail (Join-Path $logs "server.err.log") }
            Fail "Ung dung khong san sang sau $AppStartTimeout giay." "Mo Start.bat cua ung dung de xem loi, hoac xem log server.err.log o tren."
        }
        Start-Sleep -Seconds 3
    }
    Say "Ung dung da san sang sau $([int]((Get-Date) - $t0).TotalSeconds) giay." "Green"
}

# ------------------------------------------------------------------ read-only proxy
function Start-ProxyIfNeeded([string]$py, [int]$port) {
    $st = Read-State $ProxyState
    $alive = Get-ProxyProcesses $ProxyPort | Where-Object { $st -and $_.ProcessId -eq $st.pid }
    if ($alive -and $st.port -eq $ProxyPort -and $st.app_port -eq $port -and
            (Get-Code "GET" "http://127.0.0.1:$ProxyPort/__remote/health" 5) -eq 200) {
        Say "Proxy chi-doc dang chay: http://127.0.0.1:$ProxyPort (pid $($st.pid))." "Green"
        return
    }
    foreach ($p in Get-ProxyProcesses $ProxyPort) { Stop-Process -Id $p.ProcessId -Force -Confirm:$false -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 500
    if (-not (Test-PortFree $ProxyPort)) {
        Fail "Cong $ProxyPort dang bi chuong trinh khac dung." "Dong chuong trinh do, hoac chay: remote-access.ps1 start -ProxyPort <cong khac>"
    }
    if (-not (Test-Path $ProxyScript)) { Fail "Thieu $ProxyScript" }
    $pp = Start-Process -FilePath $py -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $LogDir "proxy.out.log") -RedirectStandardError (Join-Path $LogDir "proxy.err.log") `
        -ArgumentList @("-I", "-X", "utf8", "`"$ProxyScript`"", "--upstream-port", "$port", "--listen-port", "$ProxyPort",
                        "--log", "`"$(Join-Path $LogDir 'proxy-access.log')`"")
    $t0 = Get-Date
    while ((Get-Code "GET" "http://127.0.0.1:$ProxyPort/__remote/health" 3) -ne 200) {
        if ($pp.HasExited -or ((Get-Date) - $t0).TotalSeconds -gt 20) {
            Show-Tail (Join-Path $LogDir "proxy.err.log")
            Fail "Proxy chi-doc khong khoi dong duoc." "Xem log o tren."
        }
        Start-Sleep -Milliseconds 500
    }
    Save-State $ProxyState @{ pid = $pp.Id; port = $ProxyPort; app_port = $port; started_at = (Get-Date).ToString("s") }
    Say "Proxy chi-doc da chay: http://127.0.0.1:$ProxyPort -> ung dung 127.0.0.1:$port (pid $($pp.Id))." "Green"
}

# ------------------------------------------------------------------ cloudflared (official release, verified)
function Test-CloudflaredFile([string]$f) {
    $sig = Get-AuthenticodeSignature -FilePath $f
    $signed = ($sig.Status -eq "Valid") -and ($sig.SignerCertificate.Subject -match "Cloudflare")
    return @{ signed = $signed; signer = "$($sig.SignerCertificate.Subject)"; status = "$($sig.Status)";
              sha256 = (Get-FileHash -Path $f -Algorithm SHA256).Hash.ToLower() }
}

function Get-Cloudflared {
    if (Test-Path $Cloudflared) {
        $chk = Test-CloudflaredFile $Cloudflared
        $meta = Read-State $CfMeta
        if (-not $chk.signed -and -not ($meta -and $meta.sha256 -eq $chk.sha256)) {
            Fail "cloudflared.exe khong con dung ban da xac minh (chu ky/SHA-256 khong khop)." "Xoa $Cloudflared roi chay lai de tai ban chinh thuc."
        }
        Say "cloudflared: $($meta.version) (da xac minh: chu ky $($chk.status), SHA-256 $($chk.sha256.Substring(0,12))...)." "Green"
        return
    }
    Say "Chua co cloudflared - dang tai ban Windows tu trang phat hanh chinh thuc github.com/cloudflare/cloudflared ..." "Yellow"
    try {
        $rel = Invoke-RestMethod -Uri $ReleaseApi -Headers @{ "User-Agent" = "DemandForecast-remote-launcher" } -TimeoutSec 30
    } catch {
        Fail "Khong ket noi duoc GitHub de tai cloudflared ($($_.Exception.Message))." `
            "Kiem tra Internet/proxy. Hoac tai tay cloudflared-windows-amd64.exe tu https://github.com/cloudflare/cloudflared/releases , doi ten thanh cloudflared.exe va dat vao $BinDir"
    }
    $asset = $rel.assets | Where-Object { $_.name -eq "cloudflared-windows-amd64.exe" } | Select-Object -First 1
    if (-not $asset -or $asset.browser_download_url -notmatch '^https://github\.com/cloudflare/cloudflared/releases/download/') {
        Fail "Trang phat hanh khong co file cloudflared-windows-amd64.exe hop le."
    }
    $tmp = "$Cloudflared.download"
    try {
        Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $tmp -UseBasicParsing -TimeoutSec 600
    } catch { Fail "Tai cloudflared that bai ($($_.Exception.Message))." "Kiem tra Internet roi chay lai." }
    $chk = Test-CloudflaredFile $tmp
    $expected = $null
    if ("$($asset.digest)" -match '^sha256:([0-9a-fA-F]{64})$') { $expected = $Matches[1].ToLower() }
    elseif ("$($rel.body)" -match 'cloudflared-windows-amd64\.exe:\s*([0-9a-fA-F]{64})') { $expected = $Matches[1].ToLower() }
    if ($expected -and $chk.sha256 -ne $expected) {
        Remove-Item $tmp -Force -Confirm:$false
        Fail "SHA-256 cua cloudflared tai ve KHONG khop voi trang phat hanh - da huy file."
    }
    if (-not $chk.signed -and -not $expected) {
        Remove-Item $tmp -Force -Confirm:$false
        Fail "Khong xac minh duoc cloudflared (khong co chu ky Cloudflare hop le va khong co SHA-256 de doi chieu) - da huy file."
    }
    Move-Item -Path $tmp -Destination $Cloudflared -Force
    Save-State $CfMeta @{ version = $rel.tag_name; sha256 = $chk.sha256; sha256_expected = $expected; signed = $chk.signed;
                          signer = $chk.signer; source = $asset.browser_download_url; downloaded_at = (Get-Date).ToString("s") }
    Say "Da tai cloudflared $($rel.tag_name): SHA-256 khop=$([bool]$expected), chu ky Cloudflare hop le=$($chk.signed)." "Green"
}

# ------------------------------------------------------------------ tunnel
function Get-Hostname([string]$log) {
    try {
        $q = Invoke-RestMethod -Uri "http://127.0.0.1:$MetricsPort/quicktunnel" -TimeoutSec 3
        if ($q.hostname) { return "$($q.hostname)" }
    } catch { }
    if (Test-Path $log) {
        $m = Select-String -Path $log -Pattern 'https://([a-z0-9-]+\.trycloudflare\.com)' | Select-Object -Last 1
        if ($m) { return $m.Matches[0].Groups[1].Value }
    }
    return $null
}

function Test-Link([string]$url) {
    # the dashboard really answers through HTTPS, shows the read-only banner and refuses a write
    $h = Get-Code "GET" "$url/api/health" 20
    if ($h -ne 200) { return @{ ok = $false; health = $h } }
    $ui = $null
    try { $ui = (Invoke-WebRequest -Uri "$url/" -UseBasicParsing -TimeoutSec 20).Content } catch { }
    $w = Get-Code "POST" "$url/api/training/run" 20
    return @{ ok = ($ui -and $ui.Contains("df-remote-banner") -and $w -eq 405); health = $h; ui = [bool]$ui; write = $w }
}

function Show-Link([string]$url, [bool]$verified) {
    try { Set-Clipboard -Value $url } catch { }
    Write-Host ""
    Write-Host "==================================================================" -ForegroundColor Cyan
    Write-Host " LINK GUI SEP (chi xem):  $url" -ForegroundColor Cyan
    Write-Host "==================================================================" -ForegroundColor Cyan
    if ($verified) { Say " Da kiem tra tu may nay qua HTTPS: dashboard mo duoc, thao tac ghi bi chan." "Green" }
    else { Say " CHUA xac minh duoc link (Internet cham?). Thu mo link sau 1-2 phut." "Yellow" }
    Say " - Link da duoc chep vao clipboard (Ctrl+V de dan)."
    Say " - Link CHI DOC: khong chay huan luyen / luu / nhap du lieu qua link nay."
    Say " - May nay phai bat, co Internet; ung dung va tunnel phai dang chay (dung ngu may)."
    Say " - Link DOI moi khi khoi dong lai tunnel. Ai co link deu xem duoc: chi gui cho nguoi can xem."
    Say " - Dung chia se: Stop-DemandForecast-Remote.bat (ung dung chinh van chay)."
}

function Start-Tunnel {
    $st = Read-State $TunnelState
    $mine = Get-TunnelProcesses
    if ($st -and $st.url -and ($mine | Where-Object { $_.Id -eq $st.pid })) {
        Say "Tunnel dang chay (pid $($st.pid)) - kiem tra link cu..." "Gray"
        $v = Test-Link $st.url
        if ($v.ok) { Show-Link $st.url $true; return 0 }
        Say "Link cu khong con phan hoi - tao link moi." "Yellow"
    }
    foreach ($p in $mine) { Stop-Process -Id $p.Id -Force -Confirm:$false -ErrorAction SilentlyContinue }
    if (Test-Path $TunnelState) { Remove-Item $TunnelState -Force -Confirm:$false }
    if (-not (Test-PortFree $MetricsPort)) { Fail "Cong $MetricsPort (metrics cua cloudflared) dang bi dung." "Chay voi -MetricsPort <cong khac>." }
    $prof = Join-Path $env:USERPROFILE ".cloudflared"
    if ((Test-Path (Join-Path $prof "config.yml")) -or (Test-Path (Join-Path $prof "config.yaml"))) {
        Say "Canh bao: co $prof\config.yml - Quick Tunnel co the bi tu choi khi co file cau hinh nay." "Yellow"
    }
    $log = Join-Path $LogDir ("cloudflared-" + (Get-Date).ToString("yyyyMMdd-HHmmss") + ".log")
    $cfArgs = @("tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:$ProxyPort", "--metrics", "127.0.0.1:$MetricsPort",
                "--logfile", "`"$log`"", "--loglevel", "info")
    if ($QuickService) { $cfArgs += @("--quick-service", $QuickService) }
    Say "Dang tao tunnel HTTPS (Cloudflare Quick Tunnel), cho toi da $TunnelTimeout giay..." "Gray"
    $cp = Start-Process -FilePath $Cloudflared -ArgumentList $cfArgs -WindowStyle Hidden -PassThru
    $t0 = Get-Date
    $hostName = $null
    while (-not $hostName) {
        Start-Sleep -Seconds 2
        $hostName = Get-Hostname $log
        if ($hostName) { break }
        if ($cp.HasExited) { Show-Tail $log; Fail "cloudflared da dung (ma $($cp.ExitCode)) truoc khi co link." "Kiem tra Internet / tuong lua (cloudflared can ra Internet qua cong 443 va 7844)." }
        if (((Get-Date) - $t0).TotalSeconds -gt $TunnelTimeout) {
            Stop-Process -Id $cp.Id -Force -Confirm:$false -ErrorAction SilentlyContinue
            Show-Tail $log
            Fail "Khong nhan duoc link sau $TunnelTimeout giay (khong co Internet hoac dich vu Quick Tunnel khong tra loi)." `
                "Kiem tra Internet roi chay lai Start-DemandForecast-Remote.bat."
        }
    }
    $url = "https://$hostName"
    Save-State $TunnelState @{ pid = $cp.Id; url = $url; started_at = (Get-Date).ToString("s"); proxy_port = $ProxyPort;
                               metrics_port = $MetricsPort; log = $log; verified = $false }
    Say "Da nhan link $url - dang kiem tra qua HTTPS (toi da $VerifyTimeout giay)..." "Gray"
    $t1 = Get-Date
    $v = Test-Link $url
    while (-not $v.ok -and ((Get-Date) - $t1).TotalSeconds -lt $VerifyTimeout) { Start-Sleep -Seconds 5; $v = Test-Link $url }
    Save-State $TunnelState @{ pid = $cp.Id; url = $url; started_at = (Get-Date).ToString("s"); proxy_port = $ProxyPort;
                               metrics_port = $MetricsPort; log = $log; verified = [bool]$v.ok; health = $v.health; write = $v.write }
    Show-Link $url ([bool]$v.ok)
    if (-not $v.ok) { return 2 }
    return 0
}

# ------------------------------------------------------------------ actions
function Stop-Remote {
    $n = 0
    foreach ($p in Get-TunnelProcesses) { Stop-Process -Id $p.Id -Force -Confirm:$false -ErrorAction SilentlyContinue; $n++ }
    foreach ($p in Get-ProxyProcesses) { Stop-Process -Id $p.ProcessId -Force -Confirm:$false -ErrorAction SilentlyContinue; $n++ }
    foreach ($f in @($TunnelState, $ProxyState)) { if (Test-Path $f) { Remove-Item $f -Force -Confirm:$false } }
    if ($n) { Say "Da dung tunnel va proxy chi-doc ($n tien trinh). Link cu khong con dung duoc." "Green" }
    else { Say "Khong co tunnel/proxy nao dang chay." "Gray" }
    Say "Ung dung chinh KHONG bi dung (van mo duoc tren may nay)." "Gray"
}

function Show-Status {
    $t = Read-State $TunnelState
    $p = Read-State $ProxyState
    $tp = Get-TunnelProcesses
    $pp = Get-ProxyProcesses
    Say "Tunnel: $(if ($tp) { 'dang chay pid ' + (($tp | ForEach-Object { $_.Id }) -join ',') } else { 'khong chay' })"
    Say "Proxy chi-doc: $(if ($pp) { 'dang chay pid ' + (($pp | ForEach-Object { $_.ProcessId }) -join ',') + ' cong ' + $p.port } else { 'khong chay' })"
    if ($t -and $t.url -and $tp) {
        $v = Test-Link $t.url
        Say "Link: $($t.url)  (health=$($v.health), chan ghi=$($v.write), ok=$($v.ok))" $(if ($v.ok) { "Green" } else { "Yellow" })
    }
}

$mutex = New-Object System.Threading.Mutex($false, "Local\DemandForecastRemoteLauncher")
if (-not $mutex.WaitOne(0)) { Fail "Mot cua so launcher khac dang chay." "Doi cua so do xong, hoac dong no roi chay lai." }
try {
    switch ($Action) {
        "stop" { Stop-Remote; exit 0 }
        "status" { Show-Status; exit 0 }
        "start" {
            Say "Demand Forecasting - link xem tu xa (chi doc)" "Cyan"
            $app = Resolve-App
            $py = if ($PythonExe) { $PythonExe } else { Join-Path $app "python\python.exe" }
            if (-not (Test-Path $py)) { Fail "Khong thay Python cua ung dung ($py)." }
            $cfg = Get-AppPortAndLogs $app
            Start-AppIfNeeded $app $cfg.port $cfg.logs
            Start-ProxyIfNeeded $py $cfg.port
            if ($LocalOnly) { Say "LocalOnly: kiem tra cuc bo xong (khong tao tunnel): http://127.0.0.1:$ProxyPort" "Green"; exit 0 }
            Get-Cloudflared
            $rc = Start-Tunnel
            exit $rc
        }
    }
} finally {
    $mutex.ReleaseMutex()
}
