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

# 1. Check Python 3
if ! command -v python3 >/dev/null 2>&1; then
    echo "❌ Error: Python 3 was not found on this system."
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "✓ Found Python ${PYTHON_VERSION}"

# 2. Create Directory Structure
mkdir -p "${INSTALL_DIR}/bin" "${BIN_DIR}" "${APPS_DIR}"

# 3. Create / Update Virtual Environment
echo "📦 Setting up isolated Python virtual environment..."
python3 -m venv "${INSTALL_DIR}/venv"
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

if [ -t 1 ]; then
    exec "${SCRIPT_DIR}/venv/bin/python3" -m vnpatchmanager "$@"
else
    exec "${SCRIPT_DIR}/venv/bin/python3" -m vnpatchmanager "$@" >> "${SCRIPT_DIR}/vnpm.log" 2>&1
fi
EOF
chmod +x "${LAUNCHER}"

# Symlink into ~/.local/bin/vnpm for CLI access
ln -sf "${LAUNCHER}" "${BIN_DIR}/vnpm"

# 6. Create Desktop Shortcuts (.desktop)
ICON_PATH="${INSTALL_DIR}/assets/steam_icon.jpg"
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
