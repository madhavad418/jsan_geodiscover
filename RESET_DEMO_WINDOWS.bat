@echo off
setlocal
cd /d "%~dp0backend"
echo This resets both local workspaces and reloads the Denpasar controlled-run data.
choice /M "Continue"
if errorlevel 2 exit /b 0
if exist customer_demo.db del /Q customer_demo.db
if exist discovery_engine.db del /Q discovery_engine.db
if exist evidence_storage_customer rmdir /S /Q evidence_storage_customer
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -m alembic upgrade head
  .venv\Scripts\python.exe bootstrap.py
)
echo Integrated GeoDiscover demonstration reset completed.
pause
