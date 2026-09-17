#!/usr/bin/env python3
"""
Visual Novel Patch Manager (VNPM)
Automated visual novel patch manager for Linux and Steam Deck.
"""

import sys
from pathlib import Path

# Ensure package directory is importable even if run directly
sys.path.insert(0, str(Path(__file__).resolve().parent))

from vnpatchmanager.cli import (
    main,
    setup_logging,
    cmd_list_games,
    cmd_export_licenses,
    cmd_sync_vndb,
    VERSION,
)

if __name__ == "__main__":
    main()

