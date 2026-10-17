@echo off
setlocal
title Demand Forecasting - dung link xem tu xa
rem Chi dung tunnel va proxy chi-doc; ung dung chinh van chay.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\remote\remote-access.ps1" stop
echo.
pause
