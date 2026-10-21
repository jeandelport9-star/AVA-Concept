@echo off
cd /d "%~dp0"
title AVA reset
echo Stopping any AVA server that is already running...
taskkill /f /t /fi "WINDOWTITLE eq AVA server*" >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8780 ^| findstr LISTENING') do taskkill /f /pid %%a >nul 2>&1
timeout /t 3 >nul
echo Updating requirements...
python -m pip install -q -r requirements.txt
title AVA server
set AVA_RESEED=1
python run.py
if errorlevel 1 pause
