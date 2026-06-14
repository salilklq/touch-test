@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fix_serial_env.ps1" %*
set "EXITCODE=%ERRORLEVEL%"

echo.
if not "%EXITCODE%"=="0" (
    echo Fix failed with exit code %EXITCODE%.
    echo You can re-run this file after installing Python from python.org.
    pause
    exit /b %EXITCODE%
)

echo Fix completed successfully.
pause
