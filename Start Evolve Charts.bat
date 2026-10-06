@echo off
rem Double-click this file to start Evolve Charts. A page opens in your browser.
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"

if not exist "evolve-charts.py" (
    echo Evolve Charts can't start from inside the zip file.
    echo Right-click the zip, choose "Extract All...", then open the extracted folder
    echo and double-click "Start Evolve Charts" there.
    echo.
    pause
    exit /b 1
)

where uv >nul 2>nul
if errorlevel 1 (
    echo Evolve Charts needs "uv" to download Python and the libraries it uses.
    echo It will now be installed for your user account from https://astral.sh/uv
    echo.
    powershell -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    if errorlevel 1 goto failed
)

echo Starting Evolve Charts. The first start downloads Python and the libraries it uses
echo (about 150 MB) and can take a few minutes; later starts are quick.
echo Keep this window open while you use the tool; close it to stop.
echo.
uv run evolve-charts.py
if errorlevel 1 goto failed
exit /b 0

:failed
echo.
echo Something went wrong. Please send a screenshot of this window to Traverse Research.
pause
exit /b 1
