@echo off
REM Build a single-file exe with PyInstaller
cd /d "%~dp0"

echo ============================================
echo   Building Yumi L4D2 Toolbox (single exe)
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found.
    pause
    exit /b 1
)

python -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    echo Installing PyInstaller...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo [ERROR] PyInstaller install failed.
        pause
        exit /b 1
    )
)

if not exist assets\icon.ico (
    echo Generating icon...
    python tools\make_icon.py
)

echo Packaging, this may take 2-5 minutes...
python -m PyInstaller --noconfirm --clean --distpath dist --workpath build tools\build.spec
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed, see the log above.
    pause
    exit /b 1
)

echo.
echo Done! Single executable is here:
echo    %~dp0dist\Yumi的L4D2工具箱.exe
echo.
echo First run creates data\ sounds\ backgrounds\ next to the exe.
echo.
pause
