@echo off
echo   Starting HeadshotScraper...
echo.
python "%~dp0launch.py"
if %ERRORLEVEL% neq 0 (
    echo.
    echo   Failed to start. Run install.bat first.
    pause
)
