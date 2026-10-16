@echo off
REM ===========================================================
REM  SenseVoice Recording Watcher - launcher
REM
REM  ASCII-only on purpose (see course-notes-desktop\start.bat
REM  for the codepage explanation).
REM
REM  This launcher probes candidate interpreters with a real
REM  import test instead of trusting bare "python", which is
REM  ambiguous on this machine (C-3).
REM ===========================================================
chcp 65001 >nul
title SenseVoice Recording Watcher
cd /d "%~dp0"

set "CAND1=%~dp0.venv\Scripts\python.exe"
set "CAND2=%~dp0course-notes-desktop\venv\Scripts\python.exe"
set "CAND3=python"

set "PY="
for %%C in ("%CAND1%" "%CAND2%" "%CAND3%") do (
    if not defined PY (
        %%~C -c "import torch, funasr" >nul 2>&1
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
    echo None of them can import torch + funasr.
    echo.
    echo Fix - run this once, then start again:
    echo   python -m venv ".venv" --system-site-packages
    echo   ".venv\Scripts\python.exe" -m pip install -r course-notes-desktop\requirements.txt
    echo.
    echo Press any key to close this window...
    pause >nul
    exit /b 1
)

echo ================================================
echo   SenseVoice Recording Watcher
echo ------------------------------------------------
echo   Interpreter: %PY%
echo   Drop recordings into:  sounds\
echo   Results saved to:      txt\
echo   Press Ctrl+C to stop.
echo ================================================
echo.

"%PY%" -u "entry\watch.py"
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
    echo [ERROR] watch.py exited with code %RC%.
) else (
    echo [stopped] Finished normally.
)
echo Press any key to close this window...
pause >nul
