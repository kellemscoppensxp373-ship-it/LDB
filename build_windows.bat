@echo off
rem ============================================================================
rem  LifeBoard AI - Windows build script
rem  --------------------------------------------------------------------------
rem  Usage:
rem      build_windows.bat              CPU build (works everywhere)
rem      build_windows.bat --cuda       GPU build of llama-cpp-python (CUDA 12.1)
rem      build_windows.bat --clean-venv throw the virtual environment away first
rem
rem  Output: dist\LifeBoard\LifeBoard.exe   (--onedir, no console window)
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
echo   LifeBoard AI - build for Windows
echo  ================================================================
echo.

rem --------------------------------------------------------------- 1. Python
set "PY="
py -3.13 -V >nul 2>&1 && set "PY=py -3.13"
if not defined PY py -3.12 -V >nul 2>&1 && set "PY=py -3.12"
if not defined PY py -3.11 -V >nul 2>&1 && set "PY=py -3.11"
if not defined PY python -V >nul 2>&1 && set "PY=python"
if not defined PY (
    echo [ERROR] No Python interpreter found.
    echo         Install Python 3.12+ from https://www.python.org/downloads/
    echo         and tick "Add python.exe to PATH" during setup.
    goto :fail
)
echo [1/6] Python interpreter
%PY% -c "import sys; print('       %PY% ->', sys.version.split()[0])"
%PY% -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (
    echo [ERROR] Python 3.10 or newer is required.
    goto :fail
)

rem ------------------------------------------------------------------ 2. venv
if "%CLEAN_VENV%"=="1" if exist ".venv" (
    echo [2/6] removing existing .venv
    rmdir /s /q ".venv"
)
if not exist ".venv\Scripts\python.exe" (
    echo [2/6] creating virtual environment .venv
    %PY% -m venv .venv
    if errorlevel 1 goto :fail
) else (
    echo [2/6] reusing existing .venv
)
set "VPY=.venv\Scripts\python.exe"
set "VPIP=.venv\Scripts\pip.exe"
set "VPYI=.venv\Scripts\pyinstaller.exe"

rem --------------------------------------------------------- 3. requirements
echo [3/6] installing requirements (this can take a few minutes)
"%VPIP%" install --upgrade pip setuptools wheel >nul
"%VPIP%" install -r requirements.txt
if errorlevel 1 (
    echo        plain install failed, retrying with the llama.cpp wheel index
    "%VPIP%" install -r requirements.txt ^
        --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121
)
if errorlevel 1 (
    echo        [WARN] full requirements failed. Falling back to GUI-only.
    echo        [WARN] The app will run, but the advisor stays in heuristic mode.
    "%VPIP%" install PySide6 pyinstaller
    if errorlevel 1 goto :fail
)

rem ------------------------------------------------------------- 4. CUDA flag
if "%CUDA%"=="1" (
    echo [4/6] rebuilding llama-cpp-python with CUDA 12.1 support
    set "CMAKE_ARGS=-DGGML_CUDA=ON"
    "%VPIP%" install llama-cpp-python --force-reinstall --no-cache-dir ^
        --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121
    if errorlevel 1 (
        echo        [WARN] CUDA build failed. Keeping the CPU build.
        echo        [WARN] You need Visual Studio Build Tools + the CUDA 12.1 toolkit.
    )
) else (
    echo [4/6] CPU inference ^(pass --cuda to build with GPU support^)
)

rem ------------------------------------------------------------ 5. PyInstaller
echo [5/6] running PyInstaller (onedir, windowed)
if exist "dist\LifeBoard" rmdir /s /q "dist\LifeBoard"
"%VPYI%" LifeBoard.spec --noconfirm --clean
if errorlevel 1 (
    echo [ERROR] PyInstaller failed. Run "run_dev.bat" to see the traceback.
    goto :fail
)
if not exist "dist\LifeBoard\LifeBoard.exe" (
    echo [ERROR] the build finished but LifeBoard.exe is missing.
    goto :fail
)

rem ----------------------------------------------------------- 6. post-build
echo [6/6] preparing the distribution folder
if not exist "dist\LifeBoard\models" mkdir "dist\LifeBoard\models"
if exist "models\README.md" copy /Y "models\README.md" "dist\LifeBoard\models\README.md" >nul
if not exist "dist\LifeBoard\assets\images" mkdir "dist\LifeBoard\assets\images"
if exist "assets\icon.ico" copy /Y "assets\icon.ico" "dist\LifeBoard\assets\icon.ico" >nul

echo.
echo  ================================================================
echo   BUILD OK
echo.
echo   executable : dist\LifeBoard\LifeBoard.exe
echo   data file  : dist\LifeBoard\data.json   ^(created on first run^)
echo   models     : dist\LifeBoard\models\*.gguf
echo   backups    : dist\LifeBoard\backups\    ^(last 5 states^)
echo.
echo   Distribute the whole dist\LifeBoard folder.
echo   Then drop a GGUF model into models\ and press LOAD MODEL
echo   in "Rites ^& Config".
echo  ================================================================
echo.
goto :end

:fail
echo.
echo  ================================================================
echo   BUILD FAILED - read the messages above.
echo   Common causes:
echo     * no Python 3.12+ on PATH
echo     * no internet for pip
echo     * Visual Studio Build Tools missing (only needed to compile
echo       llama-cpp-python from source; prebuilt wheels normally exist)
echo  ================================================================
echo.

:end
endlocal
pause
