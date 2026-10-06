@echo off
chcp 65001 >nul
rem ============================================================================
rem  LifeBoard AI - диагностический запуск из исходников
rem  --------------------------------------------------------------------------
rem  Запускает "сырую" точку входа Python С подключённой консолью, чтобы были
rem  видны traceback'и, предупреждения Qt и логи llama.cpp. Пользуйтесь этим
rem  скриптом, когда собранный .exe ведёт себя странно: он сразу показывает,
rem  проблема в коде или в упаковке.
rem
rem  Запуск:
rem      run_dev.bat                 диагностика окружения, затем запуск программы
rem      run_dev.bat --no-diagnose   пропустить отчёт об окружении
rem      run_dev.bat --tests         вместо программы запустить тесты pytest
rem      run_dev.bat --demo          заполнить журнал демонстрационными данными
rem ============================================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title LifeBoard AI - диагностическая консоль

set "DIAGNOSE=1"
set "RUN_TESTS=0"
set "DEMO=0"
:parse_args
if "%~1"=="" goto :args_done
if /I "%~1"=="--no-diagnose" set "DIAGNOSE=0"
if /I "%~1"=="--tests" set "RUN_TESTS=1"
if /I "%~1"=="--demo" set "DEMO=1"
shift
goto :parse_args
:args_done

rem ---- выбор интерпретатора: сначала виртуальное окружение проекта ----------
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY="
    py -3.13 -V >nul 2>&1 && set "PY=py -3.13"
    if not defined PY py -3.12 -V >nul 2>&1 && set "PY=py -3.12"
    if not defined PY py -3.11 -V >nul 2>&1 && set "PY=py -3.11"
    if not defined PY py -3.10 -V >nul 2>&1 && set "PY=py -3.10"
    if not defined PY set "PY=python"
)
if not defined PY (
    echo [ОШИБКА] интерпретатор Python не найден. Сначала установите Python 3.10+.
    goto :end
)

echo.
echo  ================================================================
echo   LifeBoard AI - запуск из исходников с выводом в консоль
echo  ================================================================
echo   интерпретатор : %PY%
echo.

if "%DEMO%"=="1" (
    echo --- создаю демонстрационные данные ---
    "%PY%" tools\seed_demo.py
    echo.
)

if "%DIAGNOSE%"=="1" (
    "%PY%" tools\diagnose.py
    echo.
)

if "%RUN_TESTS%"=="1" (
    echo --- запускаю набор тестов ---
    "%PY%" -m pytest tests -q
    goto :end
)

echo --- запускаю приложение (закройте окно, чтобы остановить) ---
echo     логи Qt и traceback'и Python появятся ниже.
echo.

rem Пусть Qt громко сообщает о проблемах с плагинами и шейдерами,
rem а не падает молча.
set "QT_LOGGING_RULES=qt.qpa.*=true"
set "PYTHONFAULTHANDLER=1"
set "PYTHONUNBUFFERED=1"

"%PY%" main.py
set "RC=%ERRORLEVEL%"

echo.
echo  ================================================================
echo   приложение завершилось с кодом %RC%
if exist "crash.log" (
    echo.
    echo   --- последние 40 строк crash.log -----------------------------
    powershell -NoProfile -Command "Get-Content -Tail 40 'crash.log'" 2>nul
)
echo  ================================================================
echo.

:end
endlocal
pause
