"""
Shared utilities for Visual Novel Patch Manager (VNPM).
"""

import logging
from pathlib import Path
from typing import Optional
from unittest.mock import Mock

logger = logging.getLogger(__name__)


def find_database_file(explicit_path: Optional[Path] = None) -> Path:
    """
    Locates the bundled or cached VNDB visual novel database file.
    Searches standard installation, repository, and user cache locations.
    """
    if explicit_path and explicit_path.exists():
        return explicit_path

    candidates = [
        Path(__file__).parent.parent / "vndb_steam_database.json",
        Path(__file__).parent / "vndb_steam_database.json",
        Path.home() / ".local/share/vnpm/vndb_steam_database.json",
        Path.home() / ".cache/vnpatchmanager/vndb_cache.json"
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def is_mocked(func) -> bool:
    """Returns True if the target function or method has been mocked by unittest.mock."""
    return isinstance(func, Mock)
