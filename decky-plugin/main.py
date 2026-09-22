import os
import sys
import logging
from pathlib import Path
from typing import Dict, Any

# Ensure vnpatchmanager can be imported if installed in ~/.local or system
sys.path.insert(0, str(Path.home() / ".local" / "lib" / "python3.11" / "site-packages"))
sys.path.insert(0, str(Path.home() / ".local" / "lib" / "python3.12" / "site-packages"))

try:
    from vnpatchmanager.ipc_service import VNPMClient
except ImportError:
    VNPMClient = None

logger = logging.getLogger("decky-vnpm")


class Plugin:
    """Decky Loader Plugin backend connecting to VNPM headless daemon."""

    async def _main(self):
        self.client = VNPMClient() if VNPMClient else None
        logger.info("Decky VNPM plugin initialized")

    async def _unload(self):
        logger.info("Decky VNPM plugin unloaded")

    async def get_status(self) -> Dict[str, Any]:
        if not self.client:
            return {"error": "vnpatchmanager not found in environment"}
        try:
            return self.client.get_status()
        except Exception as e:
            return {"error": str(e)}

    async def get_library_games(self) -> Dict[str, Any]:
        if not self.client:
            return {"error": "vnpatchmanager not found in environment"}
        try:
            return self.client.scan_games()
        except Exception as e:
            return {"error": str(e)}

    async def apply_patch(self, app_id: str) -> Dict[str, Any]:
        if not self.client:
            return {"error": "vnpatchmanager not found in environment"}
        try:
            return self.client.apply_patch(app_id)
        except Exception as e:
            return {"error": str(e)}

    async def restore_backup(self, app_id: str) -> Dict[str, Any]:
        if not self.client:
            return {"error": "vnpatchmanager not found in environment"}
        try:
            return self.client.restore_backup(app_id)
        except Exception as e:
            return {"error": str(e)}

    async def fix_codecs(self, app_id: str) -> Dict[str, Any]:
        if not self.client:
            return {"error": "vnpatchmanager not found in environment"}
        try:
            return self.client.fix_codecs(app_id)
        except Exception as e:
            return {"error": str(e)}
