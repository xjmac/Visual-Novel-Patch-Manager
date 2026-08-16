import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)


class SteamOSHelper:
    """Helper utilities for SteamOS / Steam Deck Game Mode integration."""

    @staticmethod
    def is_steam_deck(
        os_release_path: str = "/etc/os-release",
        dmi_product_path: str = "/sys/devices/virtual/dmi/id/product_name"
    ) -> bool:
        """Returns True if running on SteamOS or Steam Deck hardware (Jupiter/Galileo)."""
        if os.environ.get("STEAM_DECK") in ("1", "true", "True") or os.environ.get("SteamDeck") == "1":
            return True

        # Check DMI Product Name (Steam Deck LCD: Jupiter, Steam Deck OLED: Galileo)
        if os.path.exists(dmi_product_path):
            try:
                with open(dmi_product_path, "r", encoding="utf-8") as f:
                    prod = f.read().strip().lower()
                    if prod in ("jupiter", "galileo"):
                        return True
            except Exception:
                pass

        # Check /etc/os-release
        if os.path.exists(os_release_path):
            try:
                with open(os_release_path, "r", encoding="utf-8") as f:
                    content = f.read().lower()
                    if "steamos" in content or "variant_id=steamdeck" in content:
                        return True
            except Exception:
                pass

        return False

    @staticmethod
    def is_game_mode() -> bool:
        """Returns True if running inside Steam Game Mode (gamescope session)."""
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        if desktop == "gamescope" or os.environ.get("SteamGamepadUI") == "1":
            return True
        return False

    @classmethod
    def show_onscreen_keyboard(cls, only_if_deck: bool = True) -> bool:
        """
        Triggers the SteamOS Game Mode On-Screen Keyboard (OSK).
        Non-blocking invocation via Steam URL protocol.
        If only_if_deck is True, skips invocation on non-Steam Deck desktop environments.
        """
        if only_if_deck and not (cls.is_steam_deck() or cls.is_game_mode()):
            logger.debug("Skipping OSK invocation on standard desktop environment.")
            return False

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

    @classmethod
    def hide_onscreen_keyboard(cls) -> bool:
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
