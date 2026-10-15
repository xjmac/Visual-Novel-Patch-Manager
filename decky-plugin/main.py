import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import fcntl

_PLUGIN_DIR = Path(__file__).resolve().parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

_DAEMON_WAIT_SECONDS = 5.0


def _load_plugin_client():
    """Import the sibling client after the plugin directory is on sys.path."""
    from ipc_client import PluginClient
    return PluginClient


PluginClient = _load_plugin_client()

logger = logging.getLogger("decky-vnpm")


def _failure(message: str) -> Dict[str, Any]:
    return {"success": False, "error": message}


def _user_home() -> Path:
    raw = os.environ.get("DECKY_USER_HOME")
    return Path(raw) if raw else Path.home()


def _install_root() -> Path:
    return _user_home() / ".local" / "share" / "vnpm"


def _launcher_path() -> Path:
    return _install_root() / "bin" / "vnpm"


def _cache_dir() -> Path:
    return _user_home() / ".cache" / "vnpatchmanager"


def _config_file() -> Path:
    return _user_home() / ".config" / "vnpatchmanager" / "config.json"


def _last_line(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()
    return ""


def _pid_is_ours(pid: int) -> bool:
    """True when the recorded pid is still a VNPM daemon, not a reused pid."""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False
    text = raw.replace(b"\x00", b" ").decode("utf-8", errors="replace")
    return "--daemon" in text and ("vnpm" in text or "vnpatchmanager" in text)


def _socket_failure(message: str) -> bool:
    text = message.lower()
    return "socket" in text or "connection" in text


class Plugin:
    """Decky Loader plugin backend. It speaks to the VNPM daemon over a UNIX socket."""

    def __init__(self) -> None:
        self.client = None
        self.log_line = ""
        self._restarted = False
        self._install_proc: Optional[subprocess.Popen] = None
        self._install_status = "idle"
        self._install_error = ""
        self._install_log_handle = None
        self.install_script: Optional[Path] = None

    async def _main(self):
        self.client = PluginClient()
        self._restarted = False
        self.ensure_daemon()
        logger.info("Decky VNPM plugin initialized")

    async def _unload(self):
        logger.info("Decky VNPM plugin unloaded")

    async def _uninstall(self):
        self._stop_recorded_daemon()
        logger.info("Decky VNPM plugin uninstalled")

    def _daemon_status(self) -> Optional[Dict[str, Any]]:
        if not self.client:
            return None
        try:
            result = self.client.get_status()
        except Exception:
            return None
        if isinstance(result, dict):
            return result
        return None

    def ensure_daemon(self) -> bool:
        """Use a running daemon, or start the installed launcher as its own session."""
        cache = _cache_dir()
        cache.mkdir(parents=True, exist_ok=True)
        lock_path = cache / "daemon.lock"
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            os.fchmod(fd, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                return self._ensure_daemon_locked()
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def _ensure_daemon_locked(self) -> bool:
        if self._daemon_status() is not None:
            return True
        launcher = _launcher_path()
        if not launcher.is_file() or not os.access(launcher, os.X_OK):
            self.log_line = _last_line(_install_root() / "vnpm.log") or "VNPM is not installed"
            return False
        proc = subprocess.Popen(
            [str(launcher), "--daemon"],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=os.environ.copy(),
        )
        self._write_pid(proc.pid)
        deadline = time.monotonic() + _DAEMON_WAIT_SECONDS
        while time.monotonic() < deadline:
            if self._daemon_status() is not None:
                return True
            if proc.poll() is not None:
                break
            time.sleep(0.05)
        self.log_line = _last_line(_install_root() / "vnpm.log") or "Daemon did not start"
        return False

    def _write_pid(self, pid: int) -> None:
        path = _cache_dir() / "daemon.pid"
        fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(str(pid))

    def _stop_recorded_daemon(self) -> None:
        path = _cache_dir() / "daemon.pid"
        if not path.is_file():
            return
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        path.unlink(missing_ok=True)
        if not text.isdigit():
            return
        pid = int(text)
        if not _pid_is_ours(pid):
            return
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                return

    def _invoke(self, fn: Callable[[], Any]) -> Dict[str, Any]:
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

    def _call(self, fn: Callable[[], Any]) -> Dict[str, Any]:
        result = self._invoke(fn)
        if self._restarted or not _socket_failure(str(result.get("error") or "")):
            return result
        if result.get("success") is not False:
            return result
        self._restarted = True
        if self.ensure_daemon():
            return self._invoke(fn)
        return result

    def _read_local_path(self) -> str:
        path = _config_file()
        if not path.is_file():
            return ""
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        if not isinstance(loaded, dict):
            return ""
        return str(loaded.get("local_path") or "")

    def _poll_install(self) -> None:
        proc = self._install_proc
        if proc is None or self._install_status != "running":
            return
        code = proc.poll()
        if code is None:
            return
        handle = self._install_log_handle
        if handle is not None:
            handle.close()
            self._install_log_handle = None
        if code == 0:
            self._install_status = "succeeded"
            self.ensure_daemon()
            return
        self._install_status = "failed"
        self._install_error = _last_line(_cache_dir() / "install.log") or f"Installer exited {code}"
        self.log_line = self._install_error

    async def get_setup(self) -> Dict[str, Any]:
        self._poll_install()
        status = self._daemon_status()
        local_path = ""
        if isinstance(status, dict):
            local_path = str(status.get("local_path") or "")
        if not local_path:
            local_path = self._read_local_path()
        launcher = _launcher_path()
        return {
            "success": True,
            "installed": launcher.is_file() and os.access(launcher, os.X_OK),
            "daemon": status is not None,
            "local_path": local_path,
            "home": str(_user_home()),
            "log_line": self.log_line,
            "install_status": self._install_status,
            "install_error": self._install_error,
        }

    async def install_vnpm(self) -> Dict[str, Any]:
        self._poll_install()
        if self._install_status == "running":
            return {"success": True, "status": "running"}
        script = Path(self.install_script) if self.install_script else _PLUGIN_DIR / "install.sh"
        if not script.is_file():
            return _failure("install.sh is missing")
        if not os.access(script, os.X_OK):
            try:
                script.chmod(script.stat().st_mode | 0o111)
            except OSError as exc:
                return _failure(f"install.sh is not executable: {exc}")
        log_path = _cache_dir() / "install.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(log_path, "w", encoding="utf-8")
        self._install_log_handle = handle
        self._install_error = ""
        self._install_proc = subprocess.Popen(
            [str(script)],
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=os.environ.copy(),
        )
        self._install_status = "running"
        return {"success": True, "status": "running"}

    async def get_install_status(self) -> Dict[str, Any]:
        self._poll_install()
        return {
            "success": True,
            "status": self._install_status,
            "log_line": _last_line(_cache_dir() / "install.log"),
            "error": self._install_error,
        }

    async def set_patch_folder(self, path: str) -> Dict[str, Any]:
        folder = str(path or "").strip()
        if not folder:
            return _failure("Choose a patch folder")
        cfg_path = _config_file()
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        data: Dict[str, Any] = {}
        if cfg_path.is_file():
            try:
                loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                loaded = {}
            if isinstance(loaded, dict):
                data = loaded
        data["local_path"] = folder
        fd = os.open(cfg_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=4)
            handle.write("\n")
        return {"success": True, "local_path": folder}

    async def get_status(self) -> Dict[str, Any]:
        return self._call(lambda: self.client.get_status())

    async def get_library_games(self) -> Dict[str, Any]:
        """Queue a library scan and return its job id. The panel polls get_job."""
        return self._call(lambda: self.client.scan_games())

    async def get_job(self, job_id: str) -> Dict[str, Any]:
        return self._call(lambda: self.client.get_job(job_id))

    async def list_jobs(self) -> Dict[str, Any]:
        def read() -> Dict[str, Any]:
            jobs = self.client.list_jobs()
            if not isinstance(jobs, list):
                raise RuntimeError("Job list was not returned")
            return {"success": True, "jobs": jobs}

        return self._call(read)

    async def apply_patch(self, app_id: str) -> Dict[str, Any]:
        return self._call(lambda: self.client.apply_patch(app_id))

    async def restore_backup(self, app_id: str) -> Dict[str, Any]:
        return self._call(lambda: self.client.restore_backup(app_id))

    async def restore_via_steam(self, app_id: str) -> Dict[str, Any]:
        return self._call(lambda: self.client.restore_via_steam(app_id))

    async def fix_codecs(self, app_id: str) -> Dict[str, Any]:
        return self._call(lambda: self.client.fix_codecs(app_id))
