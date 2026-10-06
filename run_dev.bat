@echo off
rem ============================================================================
rem  LifeBoard AI - diagnostic run from source
rem  --------------------------------------------------------------------------
rem  Runs the raw Python entry point WITH a console attached, so tracebacks,
rem  Qt warnings and llama.cpp logs are visible.  Use this whenever the packaged
rem  .exe misbehaves: it tells you immediately whether the problem is the code
rem  or the packaging.
rem
rem  Usage:
rem      run_dev.bat                 diagnose the environment, then start the app
rem      run_dev.bat --no-diagnose   skip the environment report
rem      run_dev.bat --tests         run the pytest suite instead of the app
rem ============================================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title LifeBoard AI - diagnostic console

set "DIAGNOSE=1"
set "RUN_TESTS=0"
:parse_args
if "%~1"=="" goto :args_done
if /I "%~1"=="--no-diagnose" set "DIAGNOSE=0"
if /I "%~1"=="--tests" set "RUN_TESTS=1"
shift
goto :parse_args
:args_done

rem ---- pick the interpreter: prefer the project venv ------------------------
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY="
    py -3.13 -V >nul 2>&1 && set "PY=py -3.13"
    if not defined PY py -3.12 -V >nul 2>&1 && set "PY=py -3.12"
    if not defined PY set "PY=python"
)
if not defined PY (
    echo [ERROR] no Python interpreter found. Install Python 3.12+ first.
    goto :end
)

echo.
echo  ================================================================
echo   LifeBoard AI - source run with console output
echo  ================================================================
echo   interpreter : %PY%
echo.

if "%DIAGNOSE%"=="1" (
    "%PY%" tools\diagnose.py
    echo.
)

if "%RUN_TESTS%"=="1" (
    echo --- running the test suite ---
    "%PY%" -m pytest tests -q
    goto :end
)

echo --- starting the application (close the window to stop) ---
echo     Qt logs and Python tracebacks appear below.
echo.

rem Make Qt shout about plugin and shader problems instead of failing quietly.
set "QT_LOGGING_RULES=qt.qpa.*=true"
set "PYTHONFAULTHANDLER=1"
set "PYTHONUNBUFFERED=1"

"%PY%" main.py
set "RC=%ERRORLEVEL%"

echo.
echo  ================================================================
echo   application exited with code %RC%
if exist "crash.log" (
    echo.
    echo   --- last 40 lines of crash.log -----------------------------
    powershell -NoProfile -Command "Get-Content -Tail 40 'crash.log'" 2>nul
)
echo  ================================================================
echo.

:end
endlocal
pause
