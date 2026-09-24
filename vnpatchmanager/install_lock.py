"""Exclusive per-install lock shared by the desktop window and the daemon."""

import hashlib
import os
from contextlib import contextmanager
from pathlib import Path

import fcntl

LOCK_DIR = Path.home() / ".cache" / "vnpatchmanager" / "locks"


@contextmanager
def install_lock(install_path: Path):
    """Exclusive fcntl.flock on ~/.cache/vnpatchmanager/locks/<sha256>.lock.

    The hash is of Path(install_path).resolve(). The same process or another
    process blocks until the holder exits the context. Linux only, which is
    the supported platform.
    """
    resolved = str(Path(install_path).resolve())
    digest = hashlib.sha256(resolved.encode()).hexdigest()
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = LOCK_DIR / f"{digest}.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
