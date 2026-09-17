#!/usr/bin/env bash
set -e

# ==============================================================================
#  🎮 Visual Novel Patch Manager (VNPM) - Steam Deck & Linux Installer
# ==============================================================================
#  Installs completely into user-space (~/.local/share/vnpm)
#  100% persistent across SteamOS system updates (No sudo or read-only bypass required)
# ==============================================================================

REPO_URL="https://github.com/xjmac/Visual-Novel-Patch-Manager"
TARBALL_URL="${REPO_URL}/archive/refs/heads/main.tar.gz"

INSTALL_DIR="${HOME}/.local/share/vnpm"
BIN_DIR="${HOME}/.local/bin"
APPS_DIR="${HOME}/.local/share/applications"
DESKTOP_DIR="${HOME}/Desktop"

echo ""
echo "========================================================"
echo "  🎮 Visual Novel Patch Manager (VNPM) Installer"
echo "========================================================"
echo "  Target: ${INSTALL_DIR}"
echo ""

# 1. Check Python and Tkinter availability
BASE_PY=""
if command -v python3 >/dev/null 2>&1 && python3 -c "import tkinter" &>/dev/null; then
    BASE_PY="python3"
    PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    echo "✓ Found System Python ${PYTHON_VERSION} with Tkinter"
elif [ -x "${INSTALL_DIR}/python/bin/python3" ] && "${INSTALL_DIR}/python/bin/python3" -c "import tkinter" &>/dev/null; then
    BASE_PY="${INSTALL_DIR}/python/bin/python3"
    echo "✓ Found existing standalone Python runtime"
else
    echo "ℹ️  System Python lacks Tkinter (standard on SteamOS). Downloading user-space Python runtime..."
    mkdir -p "${INSTALL_DIR}"
    PY_TAR="${INSTALL_DIR}/python_runtime.tar.gz"
    PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20240415/cpython-3.11.9+20240415-x86_64-unknown-linux-gnu-install_only.tar.gz"
    if curl -fL -o "${PY_TAR}" "${PY_URL}"; then
        tar -xzf "${PY_TAR}" -C "${INSTALL_DIR}"
        rm -f "${PY_TAR}"
        BASE_PY="${INSTALL_DIR}/python/bin/python3"
        echo "✓ Provisioned standalone Python runtime"
    else
        echo "❌ Error: Failed to download standalone Python runtime. Please check your internet connection."
        exit 1
    fi
fi

# 2. Create Directory Structure
mkdir -p "${INSTALL_DIR}/bin" "${BIN_DIR}" "${APPS_DIR}"

# 3. Create / Update Virtual Environment
echo "📦 Setting up isolated Python virtual environment..."
"${BASE_PY}" -m venv "${INSTALL_DIR}/venv"
"${INSTALL_DIR}/venv/bin/pip" install --upgrade pip --quiet
"${INSTALL_DIR}/venv/bin/pip" install customtkinter vdf smbprotocol pillow requests --quiet

# 4. Populate App Files
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
if [ -d "${SCRIPT_DIR}/vnpatchmanager" ] && [ -d "${SCRIPT_DIR}/assets" ]; then
    echo "📂 Installing from local source..."
    cp -r "${SCRIPT_DIR}/vnpatchmanager" "${INSTALL_DIR}/"
    cp -r "${SCRIPT_DIR}/assets" "${INSTALL_DIR}/"
    [ -f "${SCRIPT_DIR}/vnpatchmanager.py" ] && cp "${SCRIPT_DIR}/vnpatchmanager.py" "${INSTALL_DIR}/"
    [ -f "${SCRIPT_DIR}/vndb_steam_database.json" ] && cp "${SCRIPT_DIR}/vndb_steam_database.json" "${INSTALL_DIR}/"
    mkdir -p "${INSTALL_DIR}/scripts"
    if [ -d "${SCRIPT_DIR}/scripts" ]; then
        cp -r "${SCRIPT_DIR}/scripts/"* "${INSTALL_DIR}/scripts/"
    fi
else
    echo "🌐 Downloading latest VNPM release from GitHub..."
    TMP_DIR=$(mktemp -d)
    curl -sSL "${TARBALL_URL}" | tar -xz -C "${TMP_DIR}"
    SRC_EXTRACT=$(find "${TMP_DIR}" -maxdepth 1 -type d -name "Visual-Novel-Patch-Manager*" | head -n 1)
    if [ -z "${SRC_EXTRACT}" ]; then
        echo "❌ Error: Failed to download and extract VNPM archive."
        rm -rf "${TMP_DIR}"
        exit 1
    fi
    cp -r "${SRC_EXTRACT}/vnpatchmanager" "${INSTALL_DIR}/"
    cp -r "${SRC_EXTRACT}/assets" "${INSTALL_DIR}/"
    [ -f "${SRC_EXTRACT}/vnpatchmanager.py" ] && cp "${SRC_EXTRACT}/vnpatchmanager.py" "${INSTALL_DIR}/"
    [ -f "${SRC_EXTRACT}/vndb_steam_database.json" ] && cp "${SRC_EXTRACT}/vndb_steam_database.json" "${INSTALL_DIR}/"
    mkdir -p "${INSTALL_DIR}/scripts"
    if [ -d "${SRC_EXTRACT}/scripts" ]; then
        cp -r "${SRC_EXTRACT}/scripts/"* "${INSTALL_DIR}/scripts/"
    fi
    rm -rf "${TMP_DIR}"
fi

# 5. Create Executable Launch Wrapper
LAUNCHER="${INSTALL_DIR}/bin/vnpm"
cat << 'EOF' > "${LAUNCHER}"
#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH}"
cd "${SCRIPT_DIR}"

# Locate Python in virtual environment and actively verify import health
VENV_PYTHON="${SCRIPT_DIR}/venv/bin/python3"
if [ ! -x "${VENV_PYTHON}" ] && [ -x "${SCRIPT_DIR}/.venv/bin/python3" ]; then
    VENV_PYTHON="${SCRIPT_DIR}/.venv/bin/python3"
fi

if [ ! -x "${VENV_PYTHON}" ] || ! "${VENV_PYTHON}" -c "import customtkinter, vdf, smbprotocol, PIL, requests" &>/dev/null; then
    echo "Environment check failed or dependencies missing. Repairing virtual environment..."
    BASE_PY="python3"
    if [ -x "${SCRIPT_DIR}/python/bin/python3" ]; then
        BASE_PY="${SCRIPT_DIR}/python/bin/python3"
    elif ! python3 -c "import tkinter" &>/dev/null; then
        PY_TAR="${SCRIPT_DIR}/python_runtime.tar.gz"
        curl -fL -o "${PY_TAR}" "https://github.com/astral-sh/python-build-standalone/releases/download/20240415/cpython-3.11.9+20240415-x86_64-unknown-linux-gnu-install_only.tar.gz" 2>/dev/null
        if [ -f "${PY_TAR}" ]; then
            tar -xzf "${PY_TAR}" -C "${SCRIPT_DIR}" 2>/dev/null
            rm -f "${PY_TAR}"
            [ -x "${SCRIPT_DIR}/python/bin/python3" ] && BASE_PY="${SCRIPT_DIR}/python/bin/python3"
        fi
    fi

    rm -rf "${SCRIPT_DIR}/venv"
    "${BASE_PY}" -m venv "${SCRIPT_DIR}/venv"
    "${SCRIPT_DIR}/venv/bin/pip" install --upgrade pip --quiet
    "${SCRIPT_DIR}/venv/bin/pip" install customtkinter vdf smbprotocol pillow requests --quiet
    VENV_PYTHON="${SCRIPT_DIR}/venv/bin/python3"
fi

if [ -t 1 ]; then
    exec "${VENV_PYTHON}" -m vnpatchmanager "$@"
else
    exec "${VENV_PYTHON}" -m vnpatchmanager "$@" >> "${SCRIPT_DIR}/vnpm.log" 2>&1
fi
EOF
chmod +x "${LAUNCHER}"

# Symlink into ~/.local/bin/vnpm for CLI access
ln -sf "${LAUNCHER}" "${BIN_DIR}/vnpm"

# 6. Create Desktop Shortcuts (.desktop)
ICON_PATH="${INSTALL_DIR}/assets/app_icon.png"
DESKTOP_FILE="${APPS_DIR}/vnpm.desktop"

cat << EOF > "${DESKTOP_FILE}"
[Desktop Entry]
Name=VN Patch Manager
GenericName=Visual Novel Patch Manager
Comment=Automated Visual Novel patch manager for Linux and Steam Deck
Exec=${LAUNCHER}
Icon=${ICON_PATH}
Terminal=false
Type=Application
Categories=Game;Utility;
Keywords=visual;novel;patch;steam;vndb;
StartupWMClass=VN Patch Manager
EOF
chmod +x "${DESKTOP_FILE}"

if [ -d "${DESKTOP_DIR}" ]; then
    cp "${DESKTOP_FILE}" "${DESKTOP_DIR}/vnpm.desktop"
    chmod +x "${DESKTOP_DIR}/vnpm.desktop"
fi

# 7. Add to Steam Game Mode with Custom Artwork
echo "🎮 Registering VN Patch Manager into Steam Game Mode..."
if [ -f "${INSTALL_DIR}/scripts/add_to_steam.py" ]; then
    "${INSTALL_DIR}/venv/bin/python3" "${INSTALL_DIR}/scripts/add_to_steam.py" "${LAUNCHER}" "${INSTALL_DIR}/assets" || true
fi

# 8. Success Banner
echo ""
echo "========================================================"
echo "  ✨ Installation Complete!"
echo "========================================================"
echo "  • Launch in Steam Game Mode under 'Non-Steam' games"
echo "  • Launch from Desktop icon or Application Menu"
echo "  • Command line: ~/.local/bin/vnpm"
echo "========================================================"
echo ""
