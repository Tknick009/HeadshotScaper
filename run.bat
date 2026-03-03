@echo off
echo   Starting HeadshotScraper...
echo.

:: Try 'python' first, then 'py' (Windows launcher)
python --version >nul 2>&1
if %ERRORLEVEL% equ 0 (
    python "%~dp0launch.py"
) else (
    py "%~dp0launch.py"
)

if %ERRORLEVEL% neq 0 (
    echo.
    echo   Failed to start. Run install.bat first.
    pause
)
