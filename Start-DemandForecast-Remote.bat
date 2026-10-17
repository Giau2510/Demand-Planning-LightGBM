@echo off
setlocal
title Demand Forecasting - link xem tu xa (chi doc)
rem Bam dup: mo ung dung neu chua chay, tao link HTTPS chi-doc (Cloudflare Quick Tunnel) va kiem tra link.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\remote\remote-access.ps1" start %*
set RC=%ERRORLEVEL%
echo.
if "%RC%"=="0" (
  echo Co the dong cua so nay: link van chay cho toi khi bam Stop-DemandForecast-Remote.bat
) else if "%RC%"=="2" (
  echo Link da tao nhung chua xac minh duoc tu may nay - thu mo link sau 1-2 phut.
) else (
  echo Co loi - doc thong bao o tren. Huong dan: REMOTE_ACCESS_GUIDE.md
)
pause
