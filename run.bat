@echo off
REM ================================================================================
REM   Intelligent Cache Optimization - Windows Launcher
REM ================================================================================

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not found in PATH. Please install Python 3.9+ and add to PATH.
    pause
    exit /b 1
)

if not exist .venv (
    echo [INFO] Creating Python virtual environment...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    echo [INFO] Installing package and dependencies...
    python -m pip install --upgrade pip
    pip install -e .
    if exist requirements.txt (
        pip install -r requirements.txt
    )
) else (
    call .venv\Scripts\activate.bat
)

python run.py %*
