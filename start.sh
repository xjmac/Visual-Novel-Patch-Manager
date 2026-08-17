#!/bin/bash

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$APP_DIR/.venv"
MAIN_SCRIPT="$APP_DIR/vnpatchmanager.py"

echo "Checking environment for VN Patch Manager..."

# Create virtual environment if missing
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv "$VENV_DIR"
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to create virtual environment with python3 -m venv."
        exit 1
    fi
fi

# Verify dependencies in venv; install/repair if missing
if ! "$VENV_DIR/bin/python" -c "import customtkinter, vdf, smbprotocol, PIL, requests" &>/dev/null; then
    echo "Installing/updating required dependencies (this will only happen once)..."
    "$VENV_DIR/bin/pip" install --upgrade pip
    if [ -f "$APP_DIR/requirements.txt" ]; then
        "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"
        if [ $? -ne 0 ]; then
            echo "ERROR: Failed to install dependencies. Please check your internet connection."
            exit 1
        fi
    else
        echo "ERROR: requirements.txt not found in $APP_DIR!"
        exit 1
    fi
    echo "Dependencies successfully installed!"
fi

if [ ! -f "$MAIN_SCRIPT" ]; then
    echo "ERROR: Could not find '$MAIN_SCRIPT'"
    exit 1
fi

echo "Launching application..."
"$VENV_DIR/bin/python" "$MAIN_SCRIPT" "$@"
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "ERROR: Application exited with code $EXIT_CODE."
    exit $EXIT_CODE
fi
