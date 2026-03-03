#!/bin/bash
echo "================================================"
echo "  HeadshotScraper - Mac/Linux Setup"
echo "================================================"
echo ""

# Check for Python 3
if command -v python3 &> /dev/null; then
    PYTHON=python3
elif command -v python &> /dev/null; then
    PYTHON=python
else
    echo "  ERROR: Python is not installed."
    echo "  Install Python 3.10+ from https://www.python.org/downloads/"
    exit 1
fi

echo "  Python found:"
$PYTHON --version
echo ""

# Check for Chrome
if [[ "$OSTYPE" == "darwin"* ]]; then
    if [ -d "/Applications/Google Chrome.app" ]; then
        echo "  Chrome found."
    else
        echo "  WARNING: Google Chrome not found."
        echo "  Chrome is needed for web scraping. Install from https://www.google.com/chrome/"
    fi
else
    if command -v google-chrome &> /dev/null || command -v chromium-browser &> /dev/null; then
        echo "  Chrome/Chromium found."
    else
        echo "  WARNING: Chrome/Chromium not found."
        echo "  Install Chrome: https://www.google.com/chrome/"
    fi
fi
echo ""

# Navigate to script directory
cd "$(dirname "$0")"

# Install dependencies
echo "  Installing Python dependencies..."
echo ""
$PYTHON -m pip install -r requirements.txt

if [ $? -ne 0 ]; then
    echo ""
    echo "  ERROR: Failed to install dependencies."
    echo "  Try: $PYTHON -m pip install -r requirements.txt"
    exit 1
fi

echo ""
echo "================================================"
echo "  Setup complete!"
echo ""
echo "  To run the app:"
echo "    Double-click: run.command (Mac)"
echo "    Or run: $PYTHON launch.py"
echo "================================================"
echo ""
