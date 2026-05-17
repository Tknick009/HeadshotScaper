#!/usr/bin/env python3
"""
HeadshotScraper Desktop Launcher
Double-click this file (or run `python launch.py`) to start the app.
Automatically opens your browser to the web interface.
"""
import os
import sys
import time
import socket
import webbrowser
import subprocess
import threading

# Default port (change if 5000 is taken on your machine)
DEFAULT_PORT = 8080


def find_free_port(start_port=DEFAULT_PORT):
    """Find the first available port starting from start_port."""
    port = start_port
    while port < start_port + 100:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                port += 1
    return start_port  # fallback


def wait_for_server(port, timeout=30):
    """Wait until the Flask server is responding."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                s.connect(('127.0.0.1', port))
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.5)
    return False


def open_browser(port):
    """Open the default browser after a short delay."""
    url = f'http://localhost:{port}'
    if wait_for_server(port):
        print(f"\n  App is running at: {url}")
        print(f"  Opening browser...\n")
        webbrowser.open(url)
    else:
        print(f"\n  Server may still be starting. Try opening manually: {url}\n")


def check_dependencies():
    """Check if required packages are installed."""
    missing = []
    required = ['flask', 'requests', 'bs4', 'selenium', 'PIL', 'rapidfuzz']
    
    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    
    if missing:
        print(f"\n  Missing packages detected: {', '.join(missing)}")
        print(f"  Installing dependencies...\n")
        
        # Find requirements.txt
        app_dir = os.path.dirname(os.path.abspath(__file__))
        req_file = os.path.join(app_dir, 'requirements.txt')
        
        if os.path.exists(req_file):
            subprocess.check_call([
                sys.executable, '-m', 'pip', 'install', '-r', req_file
            ])
            print("\n  Dependencies installed successfully!\n")
        else:
            print(f"  Could not find requirements.txt at {req_file}")
            print(f"  Run: pip install -r requirements.txt")
            sys.exit(1)


def main():
    # Change to the app directory so Flask can find templates/
    app_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(app_dir)
    
    print("\n" + "=" * 50)
    print("  HeadshotScraper - Athlete Headshot Tool")
    print("=" * 50)
    
    # Check dependencies on first run
    check_dependencies()
    
    # Find available port
    port = find_free_port(DEFAULT_PORT)
    os.environ['PORT'] = str(port)
    
    print(f"\n  Starting server on port {port}...")
    print(f"  Press Ctrl+C to stop the server.\n")
    
    # Open browser in background thread
    browser_thread = threading.Thread(target=open_browser, args=(port,), daemon=True)
    browser_thread.start()
    
    # Start Flask app
    try:
        from app import app
        app.run(host='127.0.0.1', port=port, debug=False)
    except KeyboardInterrupt:
        print("\n\n  Server stopped. Goodbye!\n")
    except Exception as e:
        print(f"\n  Error starting server: {e}")
        print(f"  Make sure all dependencies are installed: pip install -r requirements.txt\n")
        sys.exit(1)


if __name__ == '__main__':
    main()
