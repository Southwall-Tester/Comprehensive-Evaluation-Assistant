@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\launch.py %*
) else (
  python scripts\launch.py %*
)
set "CEA_EXIT_CODE=%ERRORLEVEL%"
if not "%CEA_EXIT_CODE%"=="0" pause
exit /b %CEA_EXIT_CODE%
