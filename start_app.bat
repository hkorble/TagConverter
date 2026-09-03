@echo off
setlocal
cd /d "%~dp0"
set "TAGOPS_PYTHON=%~dp0.runtime\python\python.exe"
if not exist "%TAGOPS_PYTHON%" (
  echo Tag Operations portable Python runtime is missing.
  echo Expected: %TAGOPS_PYTHON%
  pause
  exit /b 1
)
start "Tag Operations" http://127.0.0.1:8765
"%TAGOPS_PYTHON%" server.py --port 8765
endlocal
