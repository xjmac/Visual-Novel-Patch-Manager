import json
import os
import sys
import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".config" / "vnpatchmanager"
CONFIG_FILE = CONFIG_DIR / "config.json"

def _get_config_dir() -> Path:
    pkg = sys.modules.get("vnpatchmanager")
    if pkg and hasattr(pkg, "CONFIG_DIR"):
        return pkg.CONFIG_DIR
    return CONFIG_DIR

def _get_config_file() -> Path:
    pkg = sys.modules.get("vnpatchmanager")
    if pkg and hasattr(pkg, "CONFIG_FILE"):
        return pkg.CONFIG_FILE
    return CONFIG_FILE

class ConfigManager:
    """Handles saving and loading the user's settings, including NAS configurations."""

    def __init__(self) -> None:
        self.config: Dict[str, Any] = {
            "mode": "local", # 'local' or 'smb'
            "local_path": "",
            "smb_server": "",
            "smb_share": "",
            "smb_path": "",
            "smb_username": "",
            "smb_password": "",
            "steamgriddb_api_key": "",
            "steamgriddb_nsfw": True,
            "steamgriddb_animated": True
        }
        self.load_config()

    def load_config(self) -> None:
        cfg_file = _get_config_file()
        if cfg_file.exists():
            try:
                with open(cfg_file, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    self.config.update(loaded_config)
            except Exception as e:
                logger.warning(f"Failed to load config: {e}")

    def save_config(self) -> None:
        cfg_dir = _get_config_dir()
        cfg_file = _get_config_file()
        cfg_dir.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(cfg_file, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
