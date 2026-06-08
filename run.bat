@echo off
title Stock News Event Core v23 - Run
cd /d "%~dp0"

py -3.11 --version >nul 2>nul
if "%ERRORLEVEL%"=="0" (
    py -3.11 app.py
    goto END
)

python --version >nul 2>nul
if "%ERRORLEVEL%"=="0" (
    python app.py
    goto END
)

echo Python was not found.
pause

:END
pause
