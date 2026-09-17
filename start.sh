#!/bin/bash

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$APP_DIR/.venv"
MAIN_SCRIPT="$APP_DIR/vnpatchmanager.py"

echo "Checking environment for VN Patch Manager..."

# Determine base python with Tkinter support
BASE_PY="python3"
if [ -x "$APP_DIR/.python/bin/python3" ] && "$APP_DIR/.python/bin/python3" -c "import tkinter" &>/dev/null; then
    BASE_PY="$APP_DIR/.python/bin/python3"
elif ! command -v python3 >/dev/null 2>&1 || ! python3 -c "import tkinter" &>/dev/null; then
    echo "ℹ️  System Python lacks Tkinter (standard on SteamOS). Downloading user-space Python runtime..."
    PY_TAR="$APP_DIR/python_runtime.tar.gz"
    PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20240415/cpython-3.11.9+20240415-x86_64-unknown-linux-gnu-install_only.tar.gz"
    if curl -fL -o "$PY_TAR" "$PY_URL"; then
        mkdir -p "$APP_DIR/.python_tmp"
        tar -xzf "$PY_TAR" -C "$APP_DIR/.python_tmp"
        rm -rf "$APP_DIR/.python"
        mv "$APP_DIR/.python_tmp/python" "$APP_DIR/.python"
        rm -rf "$APP_DIR/.python_tmp" "$PY_TAR"
        BASE_PY="$APP_DIR/.python/bin/python3"
        echo "✓ Provisioned standalone Python runtime"
    else
        echo "ERROR: Failed to download standalone Python runtime."
        exit 1
    fi
fi

# Create virtual environment if missing
if [ ! -d "$VENV_DIR" ] || [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "Creating Python virtual environment..."
    "$BASE_PY" -m venv "$VENV_DIR"
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to create virtual environment."
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
        "$VENV_DIR/bin/pip" install customtkinter vdf smbprotocol pillow requests
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
