@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv-qt\Scripts\python.exe" (
    echo Qt environment not found. See README.md or run:
    echo install.bat "C:\Path\To\Python312\python.exe"
    pause
    exit /b 1
)
".venv-qt\Scripts\python.exe" -m gcviewer.desktop %*
exit /b %errorlevel%
