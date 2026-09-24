@echo off
setlocal
title Sensorius
set "HERE=%~dp0"
set "VENVPY=%HERE%venv\Scripts\python.exe"
set "VENVPYW=%HERE%venv\Scripts\pythonw.exe"

if exist "%VENVPY%" goto :checkvenv
goto :createvenv

:checkvenv
rem A venv folder copied from another PC still contains python.exe, but it
rem points at that machine's Python install (e.g. ...\Python313\python.exe).
"%VENVPY%" -c "import sys" >nul 2>nul
if not errorlevel 1 goto :havevenv
echo.
echo The existing "venv" folder cannot run on this computer.
echo It was probably copied from another PC or Python was moved/uninstalled.
echo Recreating a fresh virtual environment here...
rd /s /q "%HERE%venv" 2>nul

:createvenv
echo ========================================
echo  Setting up Python environment
echo ========================================
where python >nul 2>nul
if errorlevel 1 goto :trypy
python -m venv "%HERE%venv"
if errorlevel 1 goto :setupfail
goto :havevenv

:trypy
where py >nul 2>nul
if errorlevel 1 goto :nopython
py -3 -m venv "%HERE%venv"
if errorlevel 1 goto :setupfail

:havevenv
"%VENVPY%" -c "import PySide6, pyqtgraph, pandas, numpy, scipy" >nul 2>nul
if not errorlevel 1 goto :launch
echo Installing requirements (one-time, may take a few minutes)...
"%VENVPY%" -m pip install --upgrade pip
"%VENVPY%" -m pip install -r "%HERE%requirements.txt"
if errorlevel 1 goto :setupfail

:launch
cd /d "%HERE%.."
"%VENVPY%" -c "import sensor_standalone.gui.main_window"
if errorlevel 1 goto :appfail

start "" "%VENVPYW%" -m sensor_standalone
exit /b 0

:nopython
echo.
echo Python was not found. Install Python 3.10+ from https://www.python.org/downloads/
echo Tick "Add python.exe to PATH" during setup, then run this launcher again.
pause
exit /b 1

:setupfail
echo.
echo Environment setup failed - see the messages above.
echo If problems persist, delete the "venv" folder inside sensor_standalone
echo and double-click this launcher again.
pause
exit /b 1

:appfail
echo.
echo The app failed to start - see the error above.
echo If it mentions a missing module, delete the "venv" folder inside
echo sensor_standalone and run this launcher again to reinstall.
pause
exit /b 1
