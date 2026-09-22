"""
Visual Novel Patch Manager GUI Package.
Decomposed modular GUI architecture with backward-compatible facade exports.
"""

import threading
from ..controller_manager import (
    ACTION_UP,
    ACTION_DOWN,
    ACTION_LEFT,
    ACTION_RIGHT,
    ACTION_SELECT,
    ACTION_BACK,
    ACTION_QUICK_ACTION,
    ACTION_SEARCH,
    ACTION_PREV_TAB,
    ACTION_NEXT_TAB,
    ACTION_SCROLL_UP,
    ACTION_SCROLL_DOWN,
)
from ..version import APP_NAME, APP_VERSION
from .app_window import VNPatchManagerApp
from .constants import MODE_LOCAL_DISPLAY, MODE_SMB_DISPLAY

__all__ = [
    "VNPatchManagerApp",
    "MODE_LOCAL_DISPLAY",
    "MODE_SMB_DISPLAY",
    "APP_NAME",
    "APP_VERSION",
    "ACTION_UP",
    "ACTION_DOWN",
    "ACTION_LEFT",
    "ACTION_RIGHT",
    "ACTION_SELECT",
    "ACTION_BACK",
    "ACTION_QUICK_ACTION",
    "ACTION_SEARCH",
    "ACTION_PREV_TAB",
    "ACTION_NEXT_TAB",
    "ACTION_SCROLL_UP",
    "ACTION_SCROLL_DOWN",
    "threading",
]


if __name__ == "__main__":
    try:
        import customtkinter as ctk
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")
    except Exception:
        pass
    app = VNPatchManagerApp()
    app.mainloop()
