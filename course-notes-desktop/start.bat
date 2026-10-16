@echo off
REM ===========================================================
REM  Course Notes Assistant - launcher
REM
REM  IMPORTANT: keep this file ASCII-only. Do NOT put Chinese
REM  text in it. cmd.exe decodes a .bat with the system OEM
REM  codepage (936/GBK on this PC) / the console codepage, so
REM  UTF-8 Chinese bytes become mojibake that swallows the
REM  following quote or newline. That corrupts the if/else
REM  block below, leaves PY unset, and the window closes
REM  without ever opening the UI.
REM  Chinese UI text belongs in Python (see src/ui.py).
REM
REM  Interpreter order matters. Bare "python" is ambiguous on
REM  this machine: it can resolve to a TRAE sandbox python or an
REM  Anaconda python that lack some deps. We therefore probe the
REM  candidates with an actual import test and pick the first one
REM  that can import everything the app needs (C-2/C-3).
REM ===========================================================
chcp 65001 >nul
title Course Notes Assistant
cd /d "%~dp0"

REM ---- candidates, most preferred first ----
REM 1) clean project venv at the repo root (has torch + all deps)
set "CAND1=%~dp0..\.venv\Scripts\python.exe"
REM 2) older local venv (kept as fallback; may be missing torch)
set "CAND2=%~dp0venv\Scripts\python.exe"
REM 3) whatever "python" resolves to on PATH (last resort)
set "CAND3=python"

set "PY="
for %%C in ("%CAND1%" "%CAND2%" "%CAND3%") do (
    if not defined PY (
        %%~C -c "import torch, funasr, tkinter, dotenv, xlrd, openai, notion_client" >nul 2>&1
        if not errorlevel 1 set "PY=%%~C"
    )
)

if not defined PY (
    echo [ERROR] No usable Python interpreter found.
    echo.
    echo Tried:
    echo   %CAND1%
    echo   %CAND2%
    echo   %CAND3%
    echo.
    echo None of them can import: torch, funasr, tkinter, dotenv, xlrd, openai, notion_client
    echo.
    echo Fix - run this once, then start again:
    echo   python -m venv "..\.venv" --system-site-packages
    echo   "..\.venv\Scripts\python.exe" -m pip install -r requirements.txt
    echo.
    echo See docs\????.md for details.
    echo Press any key to close this window...
    pause >nul
    exit /b 1
)

echo Using interpreter: %PY%
"%PY%" -u "main.py"
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
    echo [ERROR] main.py exited with code %RC%. Read the messages above.
) else (
    echo [OK] Application closed normally.
)
echo Press any key to close this window...
pause >nul
