#!/usr/bin/env bash
set -e

# ==============================================================================
#  🎮 Visual Novel Patch Manager (VNPM) - Uninstaller
# ==============================================================================

INSTALL_DIR="${HOME}/.local/share/vnpm"
BIN_DIR="${HOME}/.local/bin"
APPS_DIR="${HOME}/.local/share/applications"
DESKTOP_DIR="${HOME}/Desktop"

echo ""
echo "========================================================"
echo "  🗑️ Visual Novel Patch Manager (VNPM) Uninstaller"
echo "========================================================"
echo ""

echo "Removing application files from ${INSTALL_DIR}..."
rm -rf "${INSTALL_DIR}"

echo "Removing executable symlink..."
rm -f "${BIN_DIR}/vnpm"

echo "Removing desktop shortcuts..."
rm -f "${APPS_DIR}/vnpm.desktop"
if [ -d "${DESKTOP_DIR}" ]; then
    rm -f "${DESKTOP_DIR}/vnpm.desktop"
fi

echo ""
echo "✓ VN Patch Manager has been uninstalled successfully."
echo "Note: Any downloaded patches and saved backups remain in your configured folders."
echo ""
