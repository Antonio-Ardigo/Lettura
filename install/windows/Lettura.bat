@echo off
rem Launch Lettura. This file lives at the install root next to .venv\.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment not found.
  echo Run install\windows\Install-Lettura.ps1 first.
  pause
  exit /b 1
)

echo Starting Lettura on http://127.0.0.1:8000 ...
echo Close this window to stop the server.
start "" http://127.0.0.1:8000
".venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
