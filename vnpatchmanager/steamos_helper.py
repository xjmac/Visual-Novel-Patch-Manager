import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)


class SteamOSHelper:
    """Helper utilities for SteamOS / Steam Deck Game Mode integration."""

    @staticmethod
    def is_steam_deck(os_release_path: str = "/etc/os-release") -> bool:
        """Returns True if running on SteamOS or Steam Deck hardware."""
        if os.environ.get("STEAM_DECK") == "1":
            return True
        if os.path.exists(os_release_path):
            try:
                with open(os_release_path, "r", encoding="utf-8") as f:
                    content = f.read().lower()
                    if "steamos" in content or "valve" in content:
                        return True
            except Exception:
                pass
        return False

    @staticmethod
    def show_onscreen_keyboard() -> bool:
        """
        Triggers the SteamOS Game Mode On-Screen Keyboard (OSK).
        Non-blocking invocation via Steam URL protocol or DBus.
        """
        try:
            if shutil.which("steam"):
                subprocess.Popen(
                    ["steam", "-ifrunning", "steam://open/keyboard"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                logger.info("Triggered SteamOS On-Screen Keyboard via steam://open/keyboard")
                return True
            elif shutil.which("xdg-open"):
                subprocess.Popen(
                    ["xdg-open", "steam://open/keyboard"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                logger.info("Triggered SteamOS On-Screen Keyboard via xdg-open")
                return True
        except Exception as e:
            logger.debug(f"Could not trigger SteamOS On-Screen Keyboard: {e}")
        return False

    @staticmethod
    def hide_onscreen_keyboard() -> bool:
        """Dismisses the SteamOS On-Screen Keyboard."""
        try:
            if shutil.which("steam"):
                subprocess.Popen(
                    ["steam", "-ifrunning", "steam://close/keyboard"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                return True
        except Exception as e:
            logger.debug(f"Could not dismiss SteamOS On-Screen Keyboard: {e}")
        return False
