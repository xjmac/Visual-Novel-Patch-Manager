"""
Local IPC / JSON-RPC Service for VN Patch Manager.
Provides headless daemon operations for SteamOS Game Mode, Decky Loader plugins,
and local automation without requiring a GUI.
"""

import os
import json
import queue
import socket
import logging
import threading
import time
import uuid
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
from .types import GameData, PatchData, ScanGameSummary

logger = logging.getLogger(__name__)

DEFAULT_SOCKET_PATH = Path.home() / ".cache" / "vnpatchmanager" / "vnpm.sock"

_JOB_METHODS = frozenset({
    "scan_games",
    "apply_patch",
    "restore_backup",
    "restore_via_steam",
    "fix_codecs",
})
_FINISHED_JOB_CAP = 64


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

    def scan_games(self) -> Dict[str, ScanGameSummary]:
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

    def _engine_game(self, gdata: ScanGameSummary, app_id: str) -> GameData:
        """Game dict the engines accept, using the scanned library root."""
        return {
            "name": gdata.get("name", "Unknown"),
            "path": str(gdata.get("path") or ""),
            "library_path": self._library_path_value(gdata),
            "is_non_steam": gdata.get("is_non_steam", False),
            "steam_app_id": str(gdata.get("steam_app_id") or app_id or ""),
            "is_installed": gdata.get("is_installed", True),
        }

    def _use_provided_game(self, game_data: GameData) -> GameData:
        """Copy a caller-supplied game record and fill a missing library root."""
        resolved = dict(game_data)
        if resolved.get("library_path") in (None, ""):
            resolved["library_path"] = ""
        return resolved

    def _scanned_game(self, app_id: str) -> Optional[GameData]:
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
        game_data: Optional[GameData] = None,
        patch_data: Optional[PatchData] = None,
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
        game_data: Optional[GameData] = None,
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
        game_data: Optional[GameData] = None,
        patch_data: Optional[PatchData] = None,
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

    def fix_codecs(
        self,
        app_id: str,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
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

        result = self._run_mutation(str(game_data.get("path") or ""), log_callback, _apply)
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
        self._accepting = False
        self._server_sock = None
        self._thread = None
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._job_order: list[str] = []
        self._jobs_lock = threading.Lock()
        self._work: queue.Queue = queue.Queue()
        self._worker: Optional[threading.Thread] = None

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

        self._accepting = True
        self._worker = threading.Thread(target=self._worker_loop, name="VNPMJobQueue", daemon=True)
        self._worker.start()
        self.running = True
        logger.info(f"VNPM IPC server listening on {self.socket_path}")

        if background:
            self._thread = threading.Thread(target=self._accept_loop, daemon=True)
            self._thread.start()
        else:
            self._accept_loop()

    def stop(self):
        """Stops the IPC server and cleans up the socket.

        Queued work is left behind. The job already inside the engine is not
        cancelled. One sentinel asks the worker to exit once that job returns.
        """
        self._accepting = False
        self.running = False
        if self._worker is not None:
            self._work.put(None)
            self._worker = None
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
            if not isinstance(params, dict):
                params = {}
            if method == "get_status":
                res = self.service.get_status()
            elif method in _JOB_METHODS:
                res = self._enqueue(method, params)
            elif method == "get_job":
                res = self._get_job(params.get("job_id"))
            elif method == "list_jobs":
                res = self._list_jobs()
            elif method == "stop":
                threading.Thread(target=self.stop, daemon=True).start()
                res = {"status": "stopping"}
            else:
                return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method '{method}' not found"}}

            return {"jsonrpc": "2.0", "id": req_id, "result": res}
        except Exception as e:
            logger.error(f"Error handling RPC method {method}: {e}")
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": str(e)}}

    def _enqueue(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Record a job and hand it to the single worker. The caller returns now."""
        if not self._accepting:
            raise RuntimeError("server is stopping")
        job_id = uuid.uuid4().hex
        record = {
            "job_id": job_id,
            "method": method,
            "status": "queued",
            "result": None,
            "error": None,
            "logs": [],
            "params": dict(params),
        }
        with self._jobs_lock:
            self._jobs[job_id] = record
            self._job_order.append(job_id)
        self._work.put(job_id)
        return {"job_id": job_id, "method": method, "status": "queued"}

    def _worker_loop(self) -> None:
        while True:
            job_id = self._work.get()
            if job_id is None:
                return
            try:
                self._execute_job(job_id)
            except Exception as exc:
                logger.error("Job %s crashed outside the service call: %s", job_id, exc, exc_info=True)

    def _execute_job(self, job_id: str) -> None:
        with self._jobs_lock:
            record = self._jobs.get(job_id)
            if record is None:
                return
            record["status"] = "running"
            method = record["method"]
            params = dict(record["params"])

        def _log(message: str) -> None:
            with self._jobs_lock:
                current = self._jobs.get(job_id)
                if current is not None:
                    current["logs"].append(str(message))

        try:
            result = self._call_service(method, params, _log)
        except Exception as exc:
            logger.error("Job %s (%s) failed: %s", job_id, method, exc)
            with self._jobs_lock:
                current = self._jobs.get(job_id)
                if current is not None:
                    current["status"] = "failed"
                    current["error"] = str(exc)
                self._trim_finished_locked()
            return

        with self._jobs_lock:
            current = self._jobs.get(job_id)
            if current is not None:
                current["status"] = "succeeded"
                current["result"] = result
            self._trim_finished_locked()

    def _call_service(self, method: str, params: Dict[str, Any], log: Callable[[str], None]) -> Any:
        app_id = params.get("app_id")
        if method == "scan_games":
            return self.service.scan_games()
        if method == "apply_patch":
            return self.service.apply_patch(app_id, log_callback=log)
        if method == "restore_backup":
            return self.service.restore_backup(app_id, log_callback=log)
        if method == "restore_via_steam":
            return self.service.restore_via_steam(app_id, log_callback=log)
        if method == "fix_codecs":
            return self.service.fix_codecs(app_id, log_callback=log)
        raise RuntimeError(f"Method '{method}' is not a job")

    def _public_locked(self, record: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "job_id": record["job_id"],
            "method": record["method"],
            "status": record["status"],
            "result": record["result"],
            "error": record["error"],
            "logs": list(record["logs"]),
        }

    def _get_job(self, job_id: Any) -> Dict[str, Any]:
        if not isinstance(job_id, str) or not job_id:
            shown = job_id if isinstance(job_id, str) else None
            return {"job_id": shown, "status": "missing"}
        with self._jobs_lock:
            record = self._jobs.get(job_id)
            if record is None:
                return {"job_id": job_id, "status": "missing"}
            return self._public_locked(record)

    def _list_jobs(self) -> list:
        with self._jobs_lock:
            return [self._public_locked(self._jobs[job_id]) for job_id in reversed(self._job_order)]

    def _trim_finished_locked(self) -> None:
        finished = [
            job_id for job_id in self._job_order
            if self._jobs[job_id]["status"] in ("succeeded", "failed")
        ]
        extra = len(finished) - _FINISHED_JOB_CAP
        if extra <= 0:
            return
        for job_id in finished[:extra]:
            self._job_order.remove(job_id)
            del self._jobs[job_id]


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

    def submit(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 30.0) -> Dict[str, Any]:
        """Enqueue long work. Returns the job ticket without waiting for it."""
        return self.call(method, params, timeout=timeout)

    def get_job(self, job_id: str, timeout: float = 30.0) -> Dict[str, Any]:
        return self.call("get_job", {"job_id": job_id}, timeout=timeout)

    def list_jobs(self, timeout: float = 30.0) -> list:
        return self.call("list_jobs", timeout=timeout)

    def wait_job(self, job_id: str, timeout: float, poll_interval: float = 0.25) -> Dict[str, Any]:
        """Poll until the job is terminal. The Decky plugin does not call this."""
        deadline = time.monotonic() + timeout
        while True:
            record = self.get_job(job_id)
            status = record.get("status") if isinstance(record, dict) else None
            if status in ("succeeded", "failed", "missing"):
                return record
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Job {job_id} still {status} after {timeout} seconds")
            time.sleep(min(poll_interval, remaining))

    def get_status(self) -> Dict[str, Any]:
        return self.call("get_status")

    def scan_games(self) -> Dict[str, Any]:
        return self.submit("scan_games")

    def apply_patch(self, app_id: str) -> Dict[str, Any]:
        return self.submit("apply_patch", {"app_id": str(app_id)})

    def restore_backup(self, app_id: str) -> Dict[str, Any]:
        return self.submit("restore_backup", {"app_id": str(app_id)})

    def restore_via_steam(self, app_id: str) -> Dict[str, Any]:
        return self.submit("restore_via_steam", {"app_id": str(app_id)})

    def fix_codecs(self, app_id: str) -> Dict[str, Any]:
        return self.submit("fix_codecs", {"app_id": str(app_id)})


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
