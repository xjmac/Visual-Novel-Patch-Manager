"""VN Patch Manager Package"""

from pathlib import Path

from .config_manager import (
    CONFIG_DIR,
    CONFIG_FILE,
    ConfigManager
)
from .steam_scanner import SteamScanner
from .patch_repository import PatchRepository
from .backup_manager import BackupManager
from .cover_art_manager import CoverArtManager
from .vndb_scanner import VNDBScanner
from .patch_execution import PatchExecutionEngine
from .steamos_helper import SteamOSHelper
from .controller_manager import GamepadControllerManager
from .non_steam_manager import NonSteamManager, calculate_shortcut_appid
from .codec_fixer import CodecFixer
from .version import get_version
from .gui import VNPatchManagerApp, APP_NAME, APP_VERSION

__version__ = APP_VERSION

__all__ = [
    "CONFIG_DIR",
    "CONFIG_FILE",
    "ConfigManager",
    "SteamScanner",
    "PatchRepository",
    "BackupManager",
    "CoverArtManager",
    "VNDBScanner",
    "PatchExecutionEngine",
    "SteamOSHelper",
    "GamepadControllerManager",
    "NonSteamManager",
    "calculate_shortcut_appid",
    "CodecFixer",
    "VNPatchManagerApp",
    "APP_NAME",
    "APP_VERSION",
    "__version__",
    "get_version",
]
