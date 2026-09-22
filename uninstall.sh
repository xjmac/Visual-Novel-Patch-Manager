#!/usr/bin/env bash
set -e

# ==============================================================================
#  🎮 Visual Novel Patch Manager (VNPM) - Uninstaller
# ==============================================================================

INSTALL_DIR="${HOME}/.local/share/vnpm"
BIN_DIR="${HOME}/.local/bin"
APPS_DIR="${HOME}/.local/share/applications"
DESKTOP_DIR="${HOME}/Desktop"
CONFIG_DIR="${HOME}/.config/vnpatchmanager"
CACHE_DIR="${HOME}/.cache/vnpatchmanager"

# 0. Parse arguments
PURGE_DATA=false
for arg in "$@"; do
    case "$arg" in
        --purge|-y)
            PURGE_DATA=true
            ;;
        --help|-h)
            echo "Usage: ./uninstall.sh [--purge | -y]"
            echo "  --purge, -y   Automatically remove user configuration and cover art cache"
            exit 0
            ;;
    esac
done

echo ""
echo "========================================================"
echo "  🗑️ Visual Novel Patch Manager (VNPM) Uninstaller"
echo "========================================================"
echo ""

# 1. Remove Steam shortcut and artwork
echo "🎮 Checking and removing Steam Game Mode shortcuts..."
if [ -f "${INSTALL_DIR}/scripts/add_to_steam.py" ] && [ -x "${INSTALL_DIR}/venv/bin/python3" ]; then
    "${INSTALL_DIR}/venv/bin/python3" "${INSTALL_DIR}/scripts/add_to_steam.py" --remove || true
elif command -v python3 >/dev/null 2>&1 && [ -f "${INSTALL_DIR}/scripts/add_to_steam.py" ]; then
    python3 "${INSTALL_DIR}/scripts/add_to_steam.py" --remove || true
fi

# 2. Remove application files
echo "Removing application files from ${INSTALL_DIR}..."
rm -rf "${INSTALL_DIR}"

# 3. Remove executable symlink
echo "Removing executable symlink..."
rm -f "${BIN_DIR}/vnpm"

# 4. Remove desktop shortcuts
echo "Removing desktop shortcuts..."
rm -f "${APPS_DIR}/vnpm.desktop"
if [ -d "${DESKTOP_DIR}" ]; then
    rm -f "${DESKTOP_DIR}/vnpm.desktop"
fi

# 5. Optional cleanup of config and cache

if [ "$PURGE_DATA" = false ] && [ -t 0 ]; then
    read -p "Do you want to delete user configuration and cover art cache? (~/.config/vnpatchmanager and ~/.cache/vnpatchmanager) [y/N]: " confirm
    case "$confirm" in
        [yY][eE][sS]|[yY]) PURGE_DATA=true ;;
        *) PURGE_DATA=false ;;
    esac
fi

if [ "$PURGE_DATA" = true ]; then
    echo "Purging configuration directory ${CONFIG_DIR}..."
    rm -rf "${CONFIG_DIR}"
    echo "Purging cover art cache directory ${CACHE_DIR}..."
    rm -rf "${CACHE_DIR}"
    echo "✓ Configuration and cache files removed."
else
    echo "ℹ️  Configuration and cache preserved in ~/.config/vnpatchmanager and ~/.cache/vnpatchmanager"
fi

echo ""
echo "✓ VN Patch Manager has been uninstalled successfully."
echo "Note: Any downloaded patches and saved backups remain in your configured folders."
echo ""
