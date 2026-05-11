@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ====================================
echo Elpis Proxy Manager
echo ====================================
echo.

:: Check if python is installed
set "PY="
where py >nul 2>&1
if !errorlevel!==0 (
    set "PY=py -3"
) else (
    where python >nul 2>&1
    if !errorlevel!==0 (
        set "PY=python"
    )
)

if "%PY%"=="" (
    echo [ERROR] Python 3.10+ was not found on your system!
    echo Please install Python from https://www.python.org/downloads/
    echo VERY IMPORTANT: When installing, make sure to check the box that says
    echo "Add Python to PATH" or "Add python.exe to PATH" at the bottom of the installer.
    echo.
    pause
    exit /b 1
)

echo [*] Found Python. Starting Elpis...
%PY% gui.py

if !errorlevel! neq 0 (
    echo.
    echo [ERROR] The application crashed or failed to start.
    echo Check the error messages above.
    pause
)
