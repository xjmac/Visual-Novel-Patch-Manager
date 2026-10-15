import sys
import logging
from pathlib import Path
from typing import Any, Callable, Dict

_PLUGIN_DIR = Path(__file__).resolve().parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))


def _load_plugin_client():
    """Import the sibling client after the plugin directory is on sys.path."""
    from ipc_client import PluginClient
    return PluginClient


PluginClient = _load_plugin_client()

logger = logging.getLogger("decky-vnpm")


def _failure(message: str) -> Dict[str, Any]:
    return {"success": False, "error": message}


class Plugin:
    """Decky Loader plugin backend. It speaks to the VNPM daemon over a UNIX socket."""

    async def _main(self):
        self.client = PluginClient()
        logger.info("Decky VNPM plugin initialized")

    async def _unload(self):
        logger.info("Decky VNPM plugin unloaded")

    def _call(self, fn: Callable[[], Any]) -> Dict[str, Any]:
        if not self.client:
            return _failure("VNPM daemon client is not ready")
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
        """Queue a library scan and return its job id. The panel polls get_job."""
        return self._call(lambda: self.client.scan_games())

    async def get_job(self, job_id: str) -> Dict[str, Any]:
        return self._call(lambda: self.client.get_job(job_id))

    async def list_jobs(self) -> Dict[str, Any]:
        if not self.client:
            return _failure("VNPM daemon client is not ready")
        try:
            jobs = self.client.list_jobs()
        except Exception as exc:
            return _failure(str(exc))
        if not isinstance(jobs, list):
            return _failure("Job list was not returned")
        return {"success": True, "jobs": jobs}

    async def apply_patch(self, app_id: str) -> Dict[str, Any]:
        return self._call(lambda: self.client.apply_patch(app_id))

    async def restore_backup(self, app_id: str) -> Dict[str, Any]:
        return self._call(lambda: self.client.restore_backup(app_id))

    async def fix_codecs(self, app_id: str) -> Dict[str, Any]:
        return self._call(lambda: self.client.fix_codecs(app_id))
