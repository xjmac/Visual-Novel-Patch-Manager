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


def extract_part_numbers(title: str) -> set[int]:
    """
    Extracts integer part numbers from title string (e.g. Part I -> 1, Part 2 -> 2, 1st offence -> 1).
    Returns a set of extracted integer part numbers.
    """
    if not title:
        return set()
    import re

    roman_map = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10}
    parts = set()
    for m in re.finditer(r"\b(?:part|vol(?:ume)?|ch(?:apter)?|offence|episode)\s+([ivx]+)\b", title, re.I):
        val = roman_map.get(m.group(1).lower())
        if val:
            parts.add(val)
    for m in re.finditer(r"\b(?:part|vol(?:ume)?|ch(?:apter)?|offence|episode)\s+(\d+)\b", title, re.I):
        parts.add(int(m.group(1)))
    for m in re.finditer(r"\b(\d+)(?:st|nd|rd|th)\s+(?:part|vol(?:ume)?|ch(?:apter)?|offence|episode)\b", title, re.I):
        parts.add(int(m.group(1)))
    return parts
