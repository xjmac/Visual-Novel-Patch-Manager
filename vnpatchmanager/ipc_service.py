"""
Local IPC / JSON-RPC Service for VN Patch Manager.
Provides headless daemon operations for SteamOS Game Mode, Decky Loader plugins,
and local automation without requiring a GUI.
"""

import os
import json
import socket
import logging
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .version import APP_NAME, APP_VERSION
from .config_manager import ConfigManager
from .steam_scanner import SteamScanner
from .patch_repository import PatchRepository
from .backup_manager import BackupManager
from .patch_execution import PatchExecutionEngine
from .codec_fixer import CodecFixer
from .install_lock import install_lock
from .vndb_scanner import VNDBScanner

logger = logging.getLogger(__name__)

DEFAULT_SOCKET_PATH = Path.home() / ".cache" / "vnpatchmanager" / "vnpm.sock"


class VNPMService:
    """Core service providing headless game scanning, patching, and status methods."""

    def __init__(self, config_manager: Optional[ConfigManager] = None):
        self.config_manager = config_manager or ConfigManager()
        self.steam_scanner = SteamScanner()
        self.repo = PatchRepository(self.config_manager)
        self.vndb_scanner = VNDBScanner()

    def get_status(self) -> Dict[str, Any]:
        """Returns daemon status and system environment info."""
        return {
            "status": "running",
            "app_name": APP_NAME,
            "version": APP_VERSION,
            "mode": self.config_manager.config.get("mode", "local"),
            "steam_root": str(self.steam_scanner.get_steam_root() or ""),
        }

    def scan_games(self) -> Dict[str, Any]:
        """Scans visual novels and available patches, returning full library state."""
        self.repo.refresh_patches()
        installed_steam = self.steam_scanner.get_installed_games()
        owned_steam = self.steam_scanner.get_owned_games()

        all_games = {}
        all_games.update(owned_steam)
        all_games.update(installed_steam)

        summary = {}
        for app_id, gdata in all_games.items():
            install_path = gdata.get("path")
            patch_data = self.repo.available_patches.get(app_id)
            vn_info = gdata.get("vndb", {})
            is_patched = bool(install_path and PatchExecutionEngine.get_patch_status(install_path, patch_data, vn_info))
            has_backup = bool(install_path and BackupManager.has_backup(install_path))
            has_clean = bool(install_path and BackupManager.has_clean_backup(install_path))

            summary[str(app_id)] = {
                "app_id": str(app_id),
                "name": gdata.get("name", "Unknown"),
                "is_non_steam": gdata.get("is_non_steam", False),
                "is_installed": gdata.get("is_installed", True),
                "path": str(install_path or ""),
                "library_path": self._library_path_value(gdata),
                "has_local_patch": app_id in self.repo.available_patches,
                "is_patched": is_patched,
                "has_backup": has_backup,
                "has_clean_backup": has_clean,
                "vndb_rating": vn_info.get("rating"),
                "developer": vn_info.get("developer"),
                "released": vn_info.get("released"),
            }
        return summary

    @staticmethod
    def _library_path_value(gdata: Dict[str, Any]) -> str:
        """Scanner library root, or an empty string when the record has none.

        Steam records store the library root (the directory that contains
        ``steamapps``). Non-Steam records store the executable parent.
        Callers must not rebuild this as ``Path(install).parent.parent``.
        """
        if "library_path" not in gdata:
            return ""
        raw = gdata.get("library_path")
        if raw is None or raw == "":
            return ""
        return str(raw)

    def _engine_game(self, gdata: Dict[str, Any], app_id: str) -> Dict[str, Any]:
        """Game dict the engines accept, using the scanned library root."""
        return {
            "name": gdata.get("name", "Unknown"),
            "path": str(gdata.get("path") or ""),
            "library_path": self._library_path_value(gdata),
            "is_non_steam": gdata.get("is_non_steam", False),
            "steam_app_id": str(gdata.get("steam_app_id") or app_id or ""),
            "is_installed": gdata.get("is_installed", True),
        }

    def _use_provided_game(self, game_data: Dict[str, Any]) -> Dict[str, Any]:
        """Copy a caller-supplied game record and fill a missing library root."""
        resolved = dict(game_data)
        if resolved.get("library_path") in (None, ""):
            resolved["library_path"] = ""
        return resolved

    def _scanned_game(self, app_id: str) -> Optional[Dict[str, Any]]:
        games = self.scan_games()
        gdata = games.get(str(app_id))
        if not gdata or not gdata.get("path"):
            return None
        return self._engine_game(gdata, str(app_id))

    def _run_mutation(
        self,
        install_path: str,
        log_callback: Optional[Callable[[str], None]],
        operation: Callable[[Callable[[str], None]], Any],
    ) -> Dict[str, Any]:
        """Hold the per-install lock around one engine call and collect logs."""
        if not install_path:
            return {"success": False, "error": "Game install path is missing", "logs": []}

        logs: list[str] = []

        def _log(message: str) -> None:
            logs.append(str(message))
            if log_callback is not None:
                log_callback(message)

        try:
            with install_lock(Path(install_path)):
                success = operation(_log)
        except Exception as exc:
            logger.error("VNPMService mutation failed: %s", exc, exc_info=True)
            return {"success": False, "error": str(exc), "logs": logs}
        return {"success": bool(success), "logs": logs}

    def apply_patch(
        self,
        app_id: str,
        game_data: Optional[Dict[str, Any]] = None,
        patch_data: Optional[Dict[str, Any]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """Applies available patch for the specified app_id.

        IPC callers pass only ``app_id``. The desktop window passes the game
        record and patch manifest it has already resolved.
        """
        if game_data is None:
            self.repo.refresh_patches()
            if patch_data is None:
                patch_data = self.repo.available_patches.get(str(app_id))
            if not patch_data:
                return {"success": False, "error": f"No patch available for app {app_id}"}
            game_data = self._scanned_game(app_id)
            if game_data is None:
                return {"success": False, "error": f"Game {app_id} is not installed"}
        else:
            if not patch_data:
                return {"success": False, "error": f"No patch available for app {app_id}"}
            game_data = self._use_provided_game(game_data)

        install_path = str(game_data.get("path") or "")
        return self._run_mutation(
            install_path,
            log_callback,
            lambda _log: PatchExecutionEngine.apply_patch(
                game_data,
                patch_data,
                self.config_manager,
                log_callback=_log,
            ),
        )

    def restore_backup(
        self,
        app_id: str,
        game_data: Optional[Dict[str, Any]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """Rolls back a game to its clean pre-patch backup state."""
        if game_data is None:
            game_data = self._scanned_game(app_id)
            if game_data is None:
                return {"success": False, "error": f"Game {app_id} not found"}
        else:
            game_data = self._use_provided_game(game_data)

        install_path = str(game_data.get("path") or "")
        return self._run_mutation(
            install_path,
            log_callback,
            lambda _log: PatchExecutionEngine.rollback_patch(game_data, log_callback=_log),
        )

    def restore_via_steam(
        self,
        app_id: str,
        game_data: Optional[Dict[str, Any]] = None,
        patch_data: Optional[Dict[str, Any]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """Purges patch artifacts and initiates Steam validation for a game."""
        if game_data is None:
            game_data = self._scanned_game(app_id)
            if game_data is None:
                return {"success": False, "error": f"Game {app_id} not found"}
            if patch_data is None:
                patch_data = self.repo.available_patches.get(str(app_id))
        else:
            game_data = self._use_provided_game(game_data)

        install_path = str(game_data.get("path") or "")
        return self._run_mutation(
            install_path,
            log_callback,
            lambda _log: PatchExecutionEngine.restore_via_steam(
                game_data,
                patch_data=patch_data,
                log_callback=_log,
            ),
        )

    def fix_codecs(self, app_id: str) -> Dict[str, Any]:
        """Applies Proton video codec fixes for a game prefix."""
        game_data = self._scanned_game(app_id)
        if game_data is None:
            return {"success": False, "error": f"Game {app_id} not found"}

        steam_root = self.steam_scanner.get_steam_root()
        if not steam_root:
            return {"success": False, "error": "Steam root directory not found"}

        outcome: Dict[str, Any] = {}

        def _apply(_log: Callable[[str], None]) -> bool:
            success, message = CodecFixer.apply_video_fixes(str(app_id))
            outcome["success"] = success
            outcome["message"] = message
            return success

        result = self._run_mutation(str(game_data.get("path") or ""), None, _apply)
        if "message" not in outcome:
            return result
        success = bool(outcome["success"])
        message = outcome["message"]
        return {"success": success, "message": message, "error": None if success else message, "logs": result.get("logs", [])}


class IPCServer:
    """UNIX Domain Socket JSON-RPC 2.0 Server for VNPM."""

    def __init__(self, service: Optional[VNPMService] = None, socket_path: Optional[Path] = None):
        self.service = service or VNPMService()
        self.socket_path = socket_path or DEFAULT_SOCKET_PATH
        self.running = False
        self._server_sock = None
        self._thread = None

    def start(self, background: bool = False):
        """Starts the socket server listening for connections."""
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            try:
                self.socket_path.unlink()
            except OSError:
                pass

        self._server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_sock.bind(str(self.socket_path))
        self._server_sock.listen(5)
        # 0o600 permissions so only local user can invoke
        try:
            os.chmod(self.socket_path, 0o600)
        except OSError:
            pass

        self.running = True
        logger.info(f"VNPM IPC server listening on {self.socket_path}")

        if background:
            self._thread = threading.Thread(target=self._accept_loop, daemon=True)
            self._thread.start()
        else:
            self._accept_loop()

    def stop(self):
        """Stops the IPC server and cleans up the socket."""
        self.running = False
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass
        if self.socket_path.exists():
            try:
                self.socket_path.unlink()
            except OSError:
                pass

    def _accept_loop(self):
        while self.running:
            try:
                conn, _ = self._server_sock.accept()
                threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()
            except (OSError, socket.error):
                break

    def _handle_client(self, conn: socket.socket):
        with conn:
            buffer = ""
            while self.running:
                data = conn.recv(4096)
                if not data:
                    break
                buffer += data.decode("utf-8", errors="replace")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    response = self._dispatch_rpc(line)
                    conn.sendall((json.dumps(response) + "\n").encode("utf-8"))

    def _dispatch_rpc(self, raw_line: str) -> Dict[str, Any]:
        try:
            req = json.loads(raw_line)
        except Exception as e:
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {e}"}}

        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        try:
            if method == "get_status":
                res = self.service.get_status()
            elif method == "scan_games":
                res = self.service.scan_games()
            elif method == "apply_patch":
                res = self.service.apply_patch(params.get("app_id"))
            elif method == "restore_backup":
                res = self.service.restore_backup(params.get("app_id"))
            elif method == "restore_via_steam":
                res = self.service.restore_via_steam(params.get("app_id"))
            elif method == "fix_codecs":
                res = self.service.fix_codecs(params.get("app_id"))
            elif method == "stop":
                threading.Thread(target=self.stop, daemon=True).start()
                res = {"status": "stopping"}
            else:
                return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method '{method}' not found"}}

            return {"jsonrpc": "2.0", "id": req_id, "result": res}
        except Exception as e:
            logger.error(f"Error handling RPC method {method}: {e}")
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": str(e)}}


class VNPMClient:
    """Python client for Decky plugins and external processes to communicate with VNPM."""

    def __init__(self, socket_path: Optional[Path] = None):
        self.socket_path = socket_path or DEFAULT_SOCKET_PATH
        self._msg_id = 0

    def call(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 30.0) -> Any:
        """Sends a JSON-RPC 2.0 request over the UNIX socket and returns the result."""
        if not self.socket_path.exists():
            raise ConnectionError(f"VNPM IPC socket not found at {self.socket_path}. Is 'vnpm --daemon' running?")

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
                        raise RuntimeError(resp["error"].get("message", "Unknown RPC error"))
                    return resp.get("result")

        raise RuntimeError("Connection closed without response")

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


def run_ipc_server():
    """Starts the VNPM IPC server in foreground mode."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    server = IPCServer()
    try:
        server.start(background=False)
    except KeyboardInterrupt:
        logger.info("Shutting down VNPM IPC server...")
    finally:
        server.stop()
