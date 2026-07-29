@echo off
title NekoCode
setlocal enabledelayedexpansion
set "PYTHONPATH=%~dp0"
set "ROUTERAI_API_KEY=sk-qb7zV-PB6KnuIxy0IqlGm4SeuR2e2dUE"
cd /d "%~dp0"

:: Set UTF-8 and enable colors
reg add HKCU\Console /v VirtualTerminalLevel /t REG_DWORD /d 1 /f >nul 2>&1
chcp 65001 >nul

python -m nekocode --provider routerai --model "qwen/qwen3.7-flash"

if errorlevel 1 (
    echo.
    pause
)
endlocal
