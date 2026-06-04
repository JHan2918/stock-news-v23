@echo off
title Stock News Event Core v24 Render Local
cd /d "%~dp0"
set PORT=8765

py -3.11 --version >nul 2>nul
if "%ERRORLEVEL%"=="0" (
    py -3.11 app.py
    goto END
)

python app.py

:END
pause
