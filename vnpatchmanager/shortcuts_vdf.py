"""Load and atomically replace Steam's binary shortcuts.vdf."""

import os
from pathlib import Path

try:
    import vdf
except ImportError:
    vdf = None

from .exceptions import ShortcutsVdfError

__all__ = ["ShortcutsVdfError", "load_shortcuts_vdf", "write_shortcuts_vdf"]


def load_shortcuts_vdf(path: Path) -> dict:
    """Load a binary shortcuts file.

    A missing path or an empty file returns ``{"shortcuts": {}}``.
    Non-empty bytes that cannot be parsed raise ``ShortcutsVdfError``.
    A parsed value that is not a dict, or whose ``shortcuts`` value is not a dict,
    raises ``ShortcutsVdfError``. Other top-level keys are preserved. A dict with
    no ``shortcuts`` key is returned with that key set to ``{}``.
    """
    path = Path(path)
    if vdf is None:
        raise ShortcutsVdfError("vdf module not available")
    if not path.exists():
        return {"shortcuts": {}}

    payload = path.read_bytes()
    if not payload:
        return {"shortcuts": {}}

    try:
        parsed = vdf.binary_loads(payload)
    except Exception as exc:
        raise ShortcutsVdfError(f"Failed to parse {path}: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ShortcutsVdfError(f"shortcuts.vdf at {path} is not a dictionary")

    shortcuts = parsed.get("shortcuts")
    if shortcuts is None and "shortcuts" not in parsed:
        parsed = dict(parsed)
        parsed["shortcuts"] = {}
        return parsed
    if not isinstance(shortcuts, dict):
        raise ShortcutsVdfError(f"shortcuts.vdf at {path} has a non-dict 'shortcuts' value")
    return parsed


def write_shortcuts_vdf(path: Path, data: dict) -> None:
    """Replace ``path`` with a binary dump of ``data`` via a same-directory temp file."""
    if vdf is None:
        raise ShortcutsVdfError("vdf module not available")

    path = Path(path)
    payload = vdf.binary_dumps(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".vnpm-partial")
    try:
        with open(partial, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(partial, path)
    finally:
        if partial.exists():
            try:
                partial.unlink()
            except OSError:
                pass
