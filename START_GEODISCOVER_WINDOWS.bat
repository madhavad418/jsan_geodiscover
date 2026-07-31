@echo off
setlocal
cd /d "%~dp0backend"

echo ============================================================
echo JSAN GeoDiscover - Executive Customer Demo v5.0
echo Open in browser: http://localhost:8000
echo ============================================================

where python >nul 2>&1
if errorlevel 1 (
  echo Python was not found. Install Python 3.11 or 3.12 and select "Add Python to PATH".
  pause
  exit /b 1
)

if not exist .env (
  copy .env.example .env >nul
  echo.
  echo First-time settings file created at backend\.env.
  echo Change JWT_SECRET and DEMO_ADMIN_PASSWORD, save the file,
  echo then run this startup file again.
  notepad .env
  pause
  exit /b 0
)

if not exist .venv\Scripts\python.exe (
  echo Creating the local Python environment...
  python -m venv .venv
  if errorlevel 1 goto :error
)

echo Installing or checking required components...
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo Applying database migrations...
.venv\Scripts\python.exe -m alembic upgrade head
if errorlevel 1 goto :error

echo Preparing the Denpasar executive demonstration...
.venv\Scripts\python.exe bootstrap.py
if errorlevel 1 goto :error

echo.
echo GeoDiscover is starting. Keep this window open during the customer demo.
start "" http://localhost:8000
.venv\Scripts\python.exe -m uvicorn gateway:app --host 127.0.0.1 --port 8000
exit /b 0

:error
echo.
echo GeoDiscover could not start. Review the error above.
pause
exit /b 1
