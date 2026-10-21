@echo off
cd /d "%~dp0"
title AVA server
where python >nul 2>nul || goto :nopython
python -c "import fastapi, uvicorn, multipart, openpyxl, PIL, httpx, numpy" >nul 2>nul
if errorlevel 1 (
  echo First run on this PC - installing what AVA needs. This needs internet and takes about a minute...
  python -m pip install -r requirements.txt || goto :err
)
python run.py
if errorlevel 1 pause
goto :eof
:nopython
echo.
echo Python is not installed on this PC.
echo Install Python 3.11 or newer from https://www.python.org/downloads/
echo IMPORTANT: on the first screen of the installer, tick "Add python.exe to PATH".
echo Then double-click start.bat again.
pause
goto :eof
:err
echo.
echo Could not install the requirements. Check the internet connection and try again.
pause
