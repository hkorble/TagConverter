@echo off
setlocal
cd /d "%~dp0"
set "TAGOPS_PYTHON=%~dp0.runtime\python\python.exe"
if not exist "%TAGOPS_PYTHON%" (
  echo Python runtime is missing at: %TAGOPS_PYTHON%
  pause
  exit /b 1
)
start "Scovan Tag Translator" http://127.0.0.1:8770
"%TAGOPS_PYTHON%" tag_translator_server.py --port 8770
endlocal
