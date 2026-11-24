@echo off
setlocal
cd /d "%~dp0"
if exist ".venv-qt\Scripts\python.exe" goto install
if "%~1"=="" (
  echo Supply the path to an existing Python 3.12 installation.
  echo Example: setup_qt.bat "C:\Path\To\Python312\python.exe"
  pause
  exit /b 1
)
"%~1" -m venv .venv-qt
if errorlevel 1 goto failed
:install
".venv-qt\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Ready. Double-click launch_qt.vbs to open Chromatogram Viewer.
pause
exit /b 0
:failed
echo Setup failed. Read the error above and docs\QT_PROTOTYPE.md.
pause
exit /b 1
