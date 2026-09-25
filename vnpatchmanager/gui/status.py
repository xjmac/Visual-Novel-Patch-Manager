"""Shared library status words for cards, filters, and the game page."""

from .theme import (
    COLOR_STATUS_BACKUP,
    COLOR_STATUS_MISSING,
    COLOR_STATUS_MUTED,
    COLOR_STATUS_PATCHED,
    COLOR_STATUS_READY,
)

_COLORS = {
    "Patched": COLOR_STATUS_PATCHED,
    "Ready": COLOR_STATUS_READY,
    "Missing": COLOR_STATUS_MISSING,
    "Backup": COLOR_STATUS_BACKUP,
    "Clean": COLOR_STATUS_MUTED,
}


def status_word(status_info: dict) -> str:
    """One word for a game: Patched, Ready, Missing, Backup, or Clean."""
    if not status_info:
        return "Clean"
    if status_info.get("is_patched"):
        return "Patched"
    if status_info.get("has_local_patch"):
        return "Ready"
    if status_info.get("has_vndb_18_patch"):
        return "Missing"
    if status_info.get("has_clean_backup"):
        return "Backup"
    return "Clean"


def status_color(status_info: dict) -> str:
    return _COLORS[status_word(status_info)]


def show_backup_mark(status_info: dict) -> bool:
    """A clean backup sits beside Patched or Ready instead of replacing that word."""
    return bool(status_info.get("has_clean_backup")) and status_word(status_info) in ("Patched", "Ready")
