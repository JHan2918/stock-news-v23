@echo off
title Install Kiwi for Stock News Event Core v23
cd /d "%~dp0"

py -3.11 --version >nul 2>nul
if "%ERRORLEVEL%"=="0" (
    set PY=py -3.11
) else (
    set PY=python
)

echo Installing kiwipiepy...
%PY% -m pip install --upgrade pip
%PY% -m pip install kiwipiepy

echo.
echo Done. Now run run.bat again.
pause
