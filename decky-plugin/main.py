import sys
import logging
from pathlib import Path
from typing import Any, Callable, Dict

logger = logging.getLogger("decky-vnpm")

_MISSING_CLIENT = "vnpatchmanager not found in environment"


def _existing_site_packages() -> list[Path]:
    """User site-packages and the installer venv, newest-relevant paths first."""
    home = Path.home()
    candidates: list[Path] = []
    venv_lib = home / ".local" / "share" / "vnpm" / "venv" / "lib"
    if venv_lib.is_dir():
        candidates.extend(sorted(venv_lib.glob("python3.*/site-packages")))
    for version in ("3.11", "3.12", "3.13", "3.14"):
        candidates.append(home / ".local" / "lib" / f"python{version}" / "site-packages")
    return candidates


for _site in reversed(_existing_site_packages()):
    if _site.is_dir():
        _location = str(_site)
        if _location not in sys.path:
            sys.path.insert(0, _location)

try:
    from vnpatchmanager.ipc_service import VNPMClient
except ImportError:
    VNPMClient = None


def _failure(message: str) -> Dict[str, Any]:
    return {"success": False, "error": message}


class Plugin:
    """Decky Loader Plugin backend connecting to VNPM headless daemon."""

    async def _main(self):
        self.client = VNPMClient() if VNPMClient else None
        logger.info("Decky VNPM plugin initialized")

    async def _unload(self):
        logger.info("Decky VNPM plugin unloaded")

    def _call(self, fn: Callable[[], Any]) -> Dict[str, Any]:
        if not self.client:
            return _failure(_MISSING_CLIENT)
        try:
            result = fn()
        except Exception as exc:
            return _failure(str(exc))
        if isinstance(result, dict) and "success" in result:
            return result
        if isinstance(result, dict):
            return {"success": True, **result}
        return {"success": True, "result": result}

    async def get_status(self) -> Dict[str, Any]:
        return self._call(lambda: self.client.get_status())

    async def get_library_games(self) -> Dict[str, Any]:
        if not self.client:
            return _failure(_MISSING_CLIENT)
        try:
            games = self.client.scan_games()
        except Exception as exc:
            return _failure(str(exc))
        return {"success": True, "games": games}

    async def apply_patch(self, app_id: str) -> Dict[str, Any]:
        return self._call(lambda: self.client.apply_patch(app_id))

    async def restore_backup(self, app_id: str) -> Dict[str, Any]:
        return self._call(lambda: self.client.restore_backup(app_id))

    async def fix_codecs(self, app_id: str) -> Dict[str, Any]:
        return self._call(lambda: self.client.fix_codecs(app_id))
