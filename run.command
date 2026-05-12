#!/bin/bash
# Double-click this file on Mac to launch HeadshotScraper
cd "$(dirname "$0")"

# Try python3 first, then python
if command -v python3 &> /dev/null; then
    python3 launch.py
elif command -v python &> /dev/null; then
    python launch.py
else
    echo "ERROR: Python not found. Run install.sh first."
    echo "Press any key to close..."
    read -n 1
fi
