"""Type definitions and TypedDict schemas for Visual Novel Patch Manager."""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypedDict, Union

LogCallback = Callable[[str], None]


class PatchAction(TypedDict, total=False):
    type: str  # e.g., "copy_file", "extract_archive", "innoextract"
    source: str
    destination: str
    target: str
    source_dir: str
    args: List[str]


class PatchData(TypedDict, total=False):
    steam_app_id: Union[int, str]
    title: str
    game_name: str
    patch_source_dir: str
    actions: List[PatchAction]
    vndb_id: Optional[str]
    notes: Optional[str]
    version: Optional[str]


class VNInfo(TypedDict, total=False):
    vn_id: str
    title: str
    developer: str
    rating: Optional[float]
    vote_count: Optional[int]
    description: str
    image_url: str
    tags: List[str]
    has_18plus_en_patch: bool
    patch_releases: List[Dict[str, Any]]


class GameData(TypedDict, total=False):
    name: str
    path: Union[str, Path]
    library_path: Union[str, Path]
    is_installed: bool
    is_non_steam: bool
    appid: str
    steam_app_id: str
    has_backup: bool
    is_clean: bool
    has_patch: bool
    is_patched: bool
    patch_data: Optional[PatchData]
    vn_info: Optional[VNInfo]


class ScanGameSummary(TypedDict, total=False):
    """One entry from VNPMService.scan_games. This is not a GameData record."""

    app_id: str
    name: str
    is_non_steam: bool
    is_installed: bool
    path: str
    library_path: str
    has_local_patch: bool
    is_patched: bool
    has_backup: bool
    has_clean_backup: bool
    vndb_rating: Optional[float]
    developer: Optional[str]
    released: Optional[str]
