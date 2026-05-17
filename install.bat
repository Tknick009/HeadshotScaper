@echo off
echo ================================================
echo   HeadshotScraper - Windows Setup
echo ================================================
echo.

:: Check for Python - try 'python' first, then 'py' (Windows launcher)
set PYTHON_CMD=python
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    py --version >nul 2>&1
    if %ERRORLEVEL% neq 0 (
        echo   ERROR: Python is not installed or not in PATH.
        echo   Download Python 3.10+ from https://www.python.org/downloads/
        echo   IMPORTANT: Check "Add Python to PATH" during installation.
        echo.
        pause
        exit /b 1
    )
    set PYTHON_CMD=py
)

echo   Python found:
%PYTHON_CMD% --version
echo.

:: Check for Chrome
echo   Checking for Google Chrome...
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    echo   Chrome found.
) else if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    echo   Chrome found.
) else (
    echo   WARNING: Google Chrome not detected in default location.
    echo   Chrome is needed for web scraping. Install from https://www.google.com/chrome/
)
echo.

:: Install dependencies using python -m pip (works even when pip isn't in PATH)
echo   Installing Python dependencies...
echo.
%PYTHON_CMD% -m pip install -r requirements.txt
echo.

if %ERRORLEVEL% neq 0 (
    echo   ERROR: Failed to install dependencies.
    echo   Try running: %PYTHON_CMD% -m pip install -r requirements.txt
    pause
    exit /b 1
)

echo ================================================
echo   Setup complete!
echo.
echo   To run the app, double-click: run.bat
echo   Or run: %PYTHON_CMD% launch.py
echo ================================================
echo.
pause
