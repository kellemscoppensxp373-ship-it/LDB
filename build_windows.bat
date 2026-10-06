@echo off
chcp 65001 >nul
rem ============================================================================
rem  LifeBoard AI - сборка под Windows
rem  --------------------------------------------------------------------------
rem  Запуск:
rem      build_windows.bat              сборка под CPU (работает везде)
rem      build_windows.bat --cuda       сборка llama-cpp-python под GPU (CUDA 12.1)
rem      build_windows.bat --clean-venv сначала удалить виртуальное окружение
rem
rem  Результат: dist\LifeBoard\LifeBoard.exe   (--onedir, без окна консоли)
rem ============================================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "CUDA=0"
set "CLEAN_VENV=0"
:parse_args
if "%~1"=="" goto :args_done
if /I "%~1"=="--cuda" set "CUDA=1"
if /I "%~1"=="--clean-venv" set "CLEAN_VENV=1"
shift
goto :parse_args
:args_done

echo.
echo  ================================================================
echo   LifeBoard AI - сборка под Windows
echo  ================================================================
echo.

rem ------------------------------------------------------------- 1. Python
set "PY="
py -3.13 -V >nul 2>&1 && set "PY=py -3.13"
if not defined PY py -3.12 -V >nul 2>&1 && set "PY=py -3.12"
if not defined PY py -3.11 -V >nul 2>&1 && set "PY=py -3.11"
if not defined PY py -3.10 -V >nul 2>&1 && set "PY=py -3.10"
if not defined PY python -V >nul 2>&1 && set "PY=python"
if not defined PY (
    echo [ОШИБКА] Интерпретатор Python не найден.
    echo          Установите Python 3.10+ с https://www.python.org/downloads/
    echo          и отметьте "Add python.exe to PATH" при установке.
    goto :fail
)
echo [1/7] Интерпретатор Python
%PY% -c "import sys; print('       %PY% ->', sys.version.split()[0])"
%PY% -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (
    echo [ОШИБКА] Нужен Python 3.10 или новее.
    goto :fail
)

rem --------------------------------------------------------------- 2. прокси
rem  Старый pip (до 22.x) падает на https://-прокси с ошибкой
rem      ValueError: check_hostname requires server_hostname
rem  Туннель CONNECT при этом остаётся тем же самым - меняется только схема.
rem  TLS до PyPI по-прежнему шифруется от конца до конца.
echo [2/7] Проверка прокси
set "PROXY_SEEN=0"
if defined HTTP_PROXY  set "PROXY_SEEN=1"
if defined http_proxy  set "PROXY_SEEN=1"
if defined HTTPS_PROXY set "PROXY_SEEN=1"
if defined https_proxy set "PROXY_SEEN=1"
if defined ALL_PROXY   set "PROXY_SEEN=1"
if defined all_proxy   set "PROXY_SEEN=1"
if "%PROXY_SEEN%"=="0" (
    echo        прокси в окружении не задан - работаем напрямую
) else (
    if defined HTTPS_PROXY set "HTTPS_PROXY=!HTTPS_PROXY:https://=http://!"
    if defined https_proxy set "https_proxy=!https_proxy:https://=http://!"
    if defined HTTP_PROXY  set "HTTP_PROXY=!HTTP_PROXY:https://=http://!"
    if defined http_proxy  set "http_proxy=!http_proxy:https://=http://!"
    if defined ALL_PROXY   set "ALL_PROXY=!ALL_PROXY:https://=http://!"
    if defined all_proxy   set "all_proxy=!all_proxy:https://=http://!"
    echo        прокси найден, схема https:// заменена на http:// ^(иначе pip падает^)
    if defined HTTP_PROXY  echo          HTTP_PROXY  = !HTTP_PROXY!
    if defined http_proxy  echo          http_proxy  = !http_proxy!
    if defined HTTPS_PROXY echo          HTTPS_PROXY = !HTTPS_PROXY!
    if defined https_proxy echo          https_proxy = !https_proxy!
    if defined ALL_PROXY   echo          ALL_PROXY   = !ALL_PROXY!
    if defined all_proxy   echo          all_proxy   = !all_proxy!
)

rem ---------------------------------------------------------------- 3. venv
if "%CLEAN_VENV%"=="1" if exist ".venv" (
    echo [3/7] удаляю существующее .venv
    rmdir /s /q ".venv"
)
if not exist ".venv\Scripts\python.exe" (
    echo [3/7] создаю виртуальное окружение .venv
    %PY% -m venv .venv
    if errorlevel 1 goto :fail
) else (
    echo [3/7] использую существующее .venv
)
set "VPY=.venv\Scripts\python.exe"
set "VPYI=.venv\Scripts\pyinstaller.exe"
rem  Важно: pip вызываем как модуль ("%VPY%" -m pip), а не как pip.exe -
rem  обновление pip через pip.exe на Windows не проходит (файл занят).
rem  Поэтому дальше везде используется PIPCMD (без кавычек вокруг всей строки).
set PIPCMD="%VPY%" -m pip --disable-pip-version-check

rem ------------------------------------------------- 4. обновление самого pip
echo [4/7] обновляю pip / setuptools / wheel
%PIPCMD% install --upgrade pip setuptools wheel
if errorlevel 1 (
    echo        не удалось обновить pip. Пробую ещё раз без кэша...
    %PIPCMD% install --upgrade --no-cache-dir pip setuptools wheel
)
if errorlevel 1 (
    echo [ОШИБКА] pip не может выйти в сеть.
    echo          Проверьте прокси ^(шаг 2^) и выполните: "%VPY%" tools\diagnose.py
    echo          Если прокси не нужен, очистите переменные HTTP_PROXY/HTTPS_PROXY
    echo          и запустите скрипт заново.
    goto :fail
)
%PIPCMD% --version

rem --------------------------------------------------------- 5. зависимости
echo [5/7] ставлю зависимости (это может занять несколько минут)
%PIPCMD% install -r requirements.txt
if errorlevel 1 (
    echo        обычная установка не прошла, пробую индекс колёс llama.cpp
    %PIPCMD% install -r requirements.txt ^
        --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121
)
if errorlevel 1 (
    echo        [ВНИМ] Полные зависимости не установились. Откат к версии только с GUI.
    echo        [ВНИМ] Программа запустится, но советник останется в режиме эвристики.
    %PIPCMD% install PySide6 pyinstaller
    if errorlevel 1 goto :fail
)

rem -------------------------------------------------------------- 6. CUDA
if "%CUDA%"=="1" (
    echo [6/7] пересобираю llama-cpp-python с поддержкой CUDA 12.1
    set "CMAKE_ARGS=-DGGML_CUDA=ON"
    %PIPCMD% install llama-cpp-python --force-reinstall --no-cache-dir ^
        --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121
    if errorlevel 1 (
        echo        [ВНИМ] Сборка под CUDA не удалась. Оставляю CPU-версию.
        echo        [ВНИМ] Нужны Visual Studio Build Tools и CUDA Toolkit 12.1.
    )
) else (
    echo [6/7] Вывод на CPU ^(запустите с --cuda для поддержки GPU^)
)

rem ------------------------------------------------------------ 7. PyInstaller
echo [7/7] запускаю PyInstaller (onedir, без консоли)
if exist "dist\LifeBoard" rmdir /s /q "dist\LifeBoard"
if exist "%VPYI%" (
    "%VPYI%" LifeBoard.spec --noconfirm --clean
) else (
    "%VPY%" -m PyInstaller LifeBoard.spec --noconfirm --clean
)
if errorlevel 1 (
    echo [ОШИБКА] PyInstaller завершился с ошибкой. Запустите "run_dev.bat", чтобы увидеть traceback.
    goto :fail
)
if not exist "dist\LifeBoard\LifeBoard.exe" (
    echo [ОШИБКА] сборка завершилась, но LifeBoard.exe отсутствует.
    goto :fail
)

echo.
echo  ================================================================
echo   СБОРКА ГОТОВА
echo.
echo   исполняемый файл : dist\LifeBoard\LifeBoard.exe
echo   файл данных      : dist\LifeBoard\data.json   ^(создаётся при первом запуске^)
echo   модели           : dist\LifeBoard\models\*.gguf
echo   резервные копии  : dist\LifeBoard\backups\    ^(последние 5 состояний^)
echo.
echo   Распространяйте всю папку dist\LifeBoard целиком.
echo   Затем положите GGUF-модель в models\ и нажмите "ЗАГРУЗИТЬ МОДЕЛЬ"
echo   на странице "Обряды и настройки".
echo  ================================================================
echo.
goto :end

:fail
echo.
echo  ================================================================
echo   СБОРКА НЕ УДАЛАСЬ - читайте сообщения выше.
echo   Частые причины:
echo     * нет Python 3.10+ в PATH
echo     * нет доступа в сеть для pip ^(см. шаг 2 про прокси^)
echo     * отсутствуют Visual Studio Build Tools ^(нужны только для
echo       компиляции llama-cpp-python из исходников; обычно есть
echo       готовые колёса^)
echo.
echo   Диагностика: "%VPY%" tools\diagnose.py
echo  ================================================================
echo.

:end
endlocal
pause
