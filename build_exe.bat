@echo off
title Stock News Event Core v23 - Build EXE
cd /d "%~dp0"

py -3.11 --version >nul 2>nul
if "%ERRORLEVEL%"=="0" (
    set PY=py -3.11
) else (
    set PY=python
)

%PY% -m pip install --upgrade pip
%PY% -m pip install pyinstaller
%PY% -m pip install kiwipiepy
%PY% -m PyInstaller --onefile --name StockNewsEventCore_v23 app.py

echo Done: dist\StockNewsEventCore_v23.exe
pause
