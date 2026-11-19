@echo off
REM Yumi L4D2 toolbox (Yumi de L4D2 gongjuxiang) - launcher (ASCII only for cmd compatibility)
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+ and add it to PATH.
    pause
    exit /b 1
)

python -c "import PySide6" >nul 2>nul
if errorlevel 1 (
    echo [INFO] First run: installing PySide6 and requests, please wait...
    python -m pip install PySide6 requests --upgrade
    if errorlevel 1 (
        echo [ERROR] Dependency install failed. Run manually:
        echo         python -m pip install PySide6 requests
        pause
        exit /b 1
    )
)

start "" pythonw main.py
exit /b 0
