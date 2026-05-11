#!/bin/bash
# Elpis — Double-click launcher for macOS
# Makes itself executable on first run, launches GUI with no lingering terminal.

cd "$(dirname "$0")"

# Find Python 3.10+
for cmd in python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        ver=$("$cmd" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo "0.0")
        major=${ver%.*}; minor=${ver#*.}
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
            PY="$cmd"
            break
        fi
    fi
done

if [ -z "$PY" ]; then
    osascript -e 'display dialog "Python 3.10+ not found. Please install it from python.org" buttons {"OK"} default button "OK" with icon stop'
    exit 1
fi

# Ensure customtkinter is available for the GUI itself
"$PY" -m pip install --disable-pip-version-check -q customtkinter 2>/dev/null || true

# Run GUI (dependencies auto-installed inside gui.py)
"$PY" gui.py &

# Close the terminal window
osascript -e 'tell application "Terminal" to close front window' 2>/dev/null || true
