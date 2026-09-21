@echo off
setlocal
cd /d "%~dp0"

echo ===================================================
echo   Starting Sorti - MoodleDoc Sorter & Explorer
echo ===================================================

:: Check if standalone Sorti.exe exists
if exist "Sorti.exe" (
    start "" "Sorti.exe"
    exit /b 0
)

:: Otherwise run via Python
if exist "..\..\.venv\Scripts\python.exe" (
    start "" "..\..\.venv\Scripts\python.exe" "app.py"
    exit /b 0
)

:: Fallback to system python
start "" python "app.py"
exit /b 0
