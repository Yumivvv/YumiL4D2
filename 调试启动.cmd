@echo off
REM Debug launcher: keeps the console open so you can see errors
cd /d "%~dp0"
echo Starting with console output...
python main.py
echo.
echo Program exited with code %errorlevel%
pause
