"""Standard-library JSON-RPC client for the Decky plugin.

Decky's Python must talk to the daemon without importing vnpatchmanager or Pillow.
"""

import json
import logging
import os
import socket
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import decky

    logger = decky.logger
except ImportError:
    logger = logging.getLogger("decky-vnpm")


def default_socket_path() -> Path:
    """Socket under the Deck user home, or Path.home() when Decky did not set it."""
    home = os.environ.get("DECKY_USER_HOME")
    base = Path(home) if home else Path.home()
    return base / ".cache" / "vnpatchmanager" / "vnpm.sock"


class PluginClient:
    """One JSON-RPC line out and one line back, matching VNPMClient.call."""

    def __init__(self, socket_path: Optional[Path] = None):
        self.socket_path = Path(socket_path) if socket_path is not None else default_socket_path()
        self._msg_id = 0

    def call(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 30.0) -> Any:
        """Send one JSON-RPC 2.0 request and return its result."""
        if not self.socket_path.exists():
            message = f"VNPM IPC socket not found at {self.socket_path}. Is 'vnpm --daemon' running?"
            logger.warning(message)
            raise ConnectionError(message)

        self._msg_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._msg_id,
            "method": method,
            "params": params or {},
        }

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(str(self.socket_path))
            sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))

            buffer = ""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")
                if "\n" in buffer:
                    line = buffer.split("\n", 1)[0]
                    resp = json.loads(line)
                    if "error" in resp:
                        err = resp["error"]
                        if isinstance(err, dict):
                            message = err.get("message", "Unknown RPC error")
                        else:
                            message = "Unknown RPC error"
                        logger.warning("RPC %s failed: %s", method, message)
                        raise RuntimeError(message)
                    return resp.get("result")

        message = "Connection closed without response"
        logger.warning(message)
        raise RuntimeError(message)

    def get_job(self, job_id: str, timeout: float = 30.0) -> Dict[str, Any]:
        return self.call("get_job", {"job_id": job_id}, timeout=timeout)

    def list_jobs(self, timeout: float = 30.0) -> list:
        return self.call("list_jobs", timeout=timeout)

    def get_status(self) -> Dict[str, Any]:
        return self.call("get_status")

    def scan_games(self) -> Dict[str, Any]:
        return self.call("scan_games")

    def apply_patch(self, app_id: str) -> Dict[str, Any]:
        return self.call("apply_patch", {"app_id": str(app_id)})

    def restore_backup(self, app_id: str) -> Dict[str, Any]:
        return self.call("restore_backup", {"app_id": str(app_id)})

    def restore_via_steam(self, app_id: str) -> Dict[str, Any]:
        return self.call("restore_via_steam", {"app_id": str(app_id)})

    def fix_codecs(self, app_id: str) -> Dict[str, Any]:
        return self.call("fix_codecs", {"app_id": str(app_id)})
