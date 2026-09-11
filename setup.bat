@echo off
REM vlc-ai-subs — setup & install (Windows)
REM
REM Usage:
REM   setup.bat              Full setup
REM   setup.bat --install    Only install VLC extension

setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "VENV_DIR=%SCRIPT_DIR%venv"
set "SRC=%SCRIPT_DIR%aisubs.lua"
set "LUA_SRC_DIR=%SCRIPT_DIR%lua"
set "PY_DATA_DIR=%APPDATA%\vlc-ai-subs"

REM ── Install-only mode ──────────────────────────────────────

if "%~1"=="--install" goto :install_only

REM ── Full setup ─────────────────────────────────────────────

echo.
echo   vlc-ai-subs setup
echo   -----------------
echo.

REM 1. Check Python
echo   Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    python3 --version >nul 2>&1
    if errorlevel 1 (
        echo.
        echo   Python 3 is not installed.
        echo   Download it from https://www.python.org/downloads/
        echo   Make sure to check "Add Python to PATH" during install.
        exit /b 1
    )
    set "PYTHON=python3"
) else (
    set "PYTHON=python"
)

for /f "tokens=*" %%i in ('%PYTHON% --version 2^>^&1') do echo   Found %%i

REM 2. Create virtual environment
if not exist "%VENV_DIR%\Scripts\pip.exe" (
    echo   Creating virtual environment...
    %PYTHON% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo   Failed to create venv. Make sure Python 3.8+ is installed.
        exit /b 1
    )
    echo   Virtual environment created.
) else (
    echo   Virtual environment already exists.
)

REM 3. Install faster-whisper
echo   Installing faster-whisper (this may take a few minutes)...
"%VENV_DIR%\Scripts\pip.exe" install --quiet --upgrade pip
"%VENV_DIR%\Scripts\pip.exe" install --quiet faster-whisper
"%VENV_DIR%\Scripts\python.exe" -c "from faster_whisper import WhisperModel; print('  faster-whisper installed!')"
if errorlevel 1 (
    echo   Failed to install faster-whisper.
    exit /b 1
)

REM 3b. Install CUDA dependencies if GPU is available
echo   Checking for CUDA GPU...
set "CUDA_AVAILABLE=0"
where nvidia-smi >nul 2>&1
if not errorlevel 1 (
    nvidia-smi >nul 2>&1
    if not errorlevel 1 (
        nvidia-smi --query-gpu=name --format=csv,noheader 2>nul | findstr /r "." >nul 2>&1
        if not errorlevel 1 set "CUDA_AVAILABLE=1"
    )
)
REM Fallback: check via ctranslate2
if "%CUDA_AVAILABLE%"=="0" (
    "%VENV_DIR%\Scripts\python.exe" -c "import ctranslate2; import sys; sys.exit(0 if ctranslate2.get_cuda_device_count() > 0 else 1)" >nul 2>&1
    if not errorlevel 1 set "CUDA_AVAILABLE=1"
)

if "%CUDA_AVAILABLE%"=="1" (
    echo   CUDA GPU detected — ensuring CUDA libraries...
    "%VENV_DIR%\Scripts\pip.exe" show nvidia-cublas-cu12 >nul 2>&1
    if errorlevel 1 (
        echo   Installing nvidia-cublas-cu12...
        "%VENV_DIR%\Scripts\pip.exe" install --quiet "nvidia-cublas-cu12"
        if errorlevel 1 echo   Warning: Failed to install nvidia-cublas-cu12
    ) else (
        echo   nvidia-cublas-cu12 already installed.
    )
    "%VENV_DIR%\Scripts\pip.exe" show nvidia-cuda-nvrtc-cu12 >nul 2>&1
    if errorlevel 1 (
        echo   Installing nvidia-cuda-nvrtc-cu12...
        "%VENV_DIR%\Scripts\pip.exe" install --quiet "nvidia-cuda-nvrtc-cu12"
    ) else (
        echo   nvidia-cuda-nvrtc-cu12 already installed.
    )
    "%VENV_DIR%\Scripts\pip.exe" show nvidia-cuda-runtime-cu12 >nul 2>&1
    if errorlevel 1 (
        echo   Installing nvidia-cuda-runtime-cu12...
        "%VENV_DIR%\Scripts\pip.exe" install --quiet "nvidia-cuda-runtime-cu12"
    ) else (
        echo   nvidia-cuda-runtime-cu12 already installed.
    )
    "%VENV_DIR%\Scripts\pip.exe" show nvidia-cudnn-cu12 >nul 2>&1
    if errorlevel 1 (
        echo   Installing nvidia-cudnn-cu12 (optional, may take a minute)...
        "%VENV_DIR%\Scripts\pip.exe" install --quiet "nvidia-cudnn-cu12" >nul 2>&1
        if errorlevel 1 echo   Warning: nvidia-cudnn-cu12 install failed — continuing without it
    ) else (
        echo   nvidia-cudnn-cu12 already installed.
    )
    "%VENV_DIR%\Scripts\python.exe" -c "import ctranslate2; assert ctranslate2.get_cuda_device_count() > 0" >nul 2>&1
    if not errorlevel 1 (
        echo   CUDA libraries verified.
    ) else (
        echo   Warning: CUDA libraries installed but GPU not yet usable — will fallback to CPU
    )
) else (
    echo   No CUDA GPU detected — skipping CUDA libraries (CPU mode)
)

REM 4. Install VLC extension + Python backend
:install_vlc
echo.
echo   Installing VLC extension...
echo.

set "INSTALLED=0"

REM Helper to copy lua/ submodules
REM Standard VLC install
set "VLC_DIR=%APPDATA%\vlc\lua\extensions"
if not exist "%VLC_DIR%" mkdir "%VLC_DIR%"
copy /y "%SRC%" "%VLC_DIR%\aisubs.lua" >nul 2>&1
if not errorlevel 1 (
    echo   Installed to %VLC_DIR%
    set "INSTALLED=1"
    if exist "%LUA_SRC_DIR%" (
        if not exist "%VLC_DIR%\lua" mkdir "%VLC_DIR%\lua" 2>nul
        copy /y "%LUA_SRC_DIR%\*.lua" "%VLC_DIR%\lua\" >nul 2>&1
        if not errorlevel 1 echo   Installed lua modules to %VLC_DIR%\lua
    )
)

REM VLC Program Files (requires admin for system-wide)
set "VLC_SYS=C:\Program Files\VideoLAN\VLC\lua\extensions"
if exist "C:\Program Files\VideoLAN\VLC" (
    if not exist "%VLC_SYS%" mkdir "%VLC_SYS%" 2>nul
    copy /y "%SRC%" "%VLC_SYS%\aisubs.lua" >nul 2>&1
    if not errorlevel 1 (
        echo   Installed to %VLC_SYS%
        set "INSTALLED=1"
        if exist "%LUA_SRC_DIR%" (
            if not exist "%VLC_SYS%\lua" mkdir "%VLC_SYS%\lua" 2>nul
            copy /y "%LUA_SRC_DIR%\*.lua" "%VLC_SYS%\lua\" >nul 2>&1
        )
    ) else (
        echo   Note: Run as Administrator to install to Program Files.
    )
)

REM VLC Program Files (x86)
set "VLC_SYS86=C:\Program Files (x86)\VideoLAN\VLC\lua\extensions"
if exist "C:\Program Files (x86)\VideoLAN\VLC" (
    if not exist "%VLC_SYS86%" mkdir "%VLC_SYS86%" 2>nul
    copy /y "%SRC%" "%VLC_SYS86%\aisubs.lua" >nul 2>&1
    if not errorlevel 1 (
        echo   Installed to %VLC_SYS86%
        set "INSTALLED=1"
        if exist "%LUA_SRC_DIR%" (
            if not exist "%VLC_SYS86%\lua" mkdir "%VLC_SYS86%\lua" 2>nul
            copy /y "%LUA_SRC_DIR%\*.lua" "%VLC_SYS86%\lua\" >nul 2>&1
        )
    )
)

if "%INSTALLED%"=="0" (
    echo   WARNING: No VLC directory found.
    echo   Copy aisubs.lua and lua\ folder manually to your VLC lua\extensions folder.
)

REM Also install Python backend to %APPDATA%\vlc-ai-subs
echo.
echo   Installing Python backend to %PY_DATA_DIR% ...
if not exist "%PY_DATA_DIR%" mkdir "%PY_DATA_DIR%" 2>nul
copy /y "%SCRIPT_DIR%aisubs.py" "%PY_DATA_DIR%\" >nul 2>&1
copy /y "%SCRIPT_DIR%launch.py" "%PY_DATA_DIR%\" >nul 2>&1
copy /y "%SCRIPT_DIR%boundaries.py" "%PY_DATA_DIR%\" >nul 2>&1
if exist "%SCRIPT_DIR%src" (
    if not exist "%PY_DATA_DIR%\src" mkdir "%PY_DATA_DIR%\src" 2>nul
    xcopy /s /y /i "%SCRIPT_DIR%src" "%PY_DATA_DIR%\src" >nul 2>&1
    echo   Python package installed to %PY_DATA_DIR%\src
)
REM Copy venv if present and not already at target
if exist "%VENV_DIR%\Scripts\pip.exe" (
    if not exist "%PY_DATA_DIR%\venv\Scripts\pip.exe" (
        echo   Copying venv to %PY_DATA_DIR%\venv ...
        xcopy /s /y /i "%VENV_DIR%" "%PY_DATA_DIR%\venv" >nul 2>&1
    )
)

echo.
echo   Setup complete!
echo.
echo   1. Restart VLC
echo   2. Go to View ^> AI Subs Generator
echo   3. Play a video and click Generate
echo.
pause
exit /b 0

:install_only
goto :install_vlc
