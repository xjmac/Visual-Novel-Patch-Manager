import os
import re
import logging
from pathlib import Path
from typing import Optional

from .steam_scanner import SteamScanner

logger = logging.getLogger(__name__)


class CodecFixer:
    """
    Automates fixing broken video cutscenes / opening movies for Visual Novels
    running under Steam Proton prefixes (Media Foundation, Quartz, DirectShow, WMP).
    """

    # Common registry overrides for Japanese VN engines (KiriKiri, CatSystem2, Siglus, Unity)
    DLL_OVERRIDES = {
        "mfplay": "native,builtin",
        "quartz": "native,builtin",
        "amstream": "native,builtin",
        "devenum": "native,builtin",
        "wmp": "native,builtin"
    }

    @staticmethod
    def find_game_prefix(app_id: str) -> Optional[Path]:
        """Locates the Steam Proton compatdata prefix for a given AppID."""
        steam_root = SteamScanner.get_steam_root()
        if not steam_root:
            return None

        # Check standard Steam compatdata paths across library folders
        candidates = [
            steam_root / "steamapps" / "compatdata" / str(app_id) / "pfx",
            Path.home() / ".local/share/Steam/steamapps/compatdata" / str(app_id) / "pfx"
        ]

        # Also search custom steam library folders from libraryfolders.vdf
        vdf_path = steam_root / "steamapps" / "libraryfolders.vdf"
        if vdf_path.exists():
            try:
                import vdf
                with open(vdf_path, "r", encoding="utf-8") as f:
                    data = vdf.load(f)
                    folders = data.get("libraryfolders", {})
                    for folder in folders.values():
                        if isinstance(folder, dict) and "path" in folder:
                            candidates.append(Path(folder["path"]) / "steamapps" / "compatdata" / str(app_id) / "pfx")
            except Exception as e:
                logger.debug(f"Error reading libraryfolders.vdf in CodecFixer: {e}")

        for pfx in candidates:
            if pfx.exists() and (pfx / "user.reg").exists():
                return pfx

        return None

    @staticmethod
    def apply_video_fixes(app_id: str) -> tuple[bool, str]:
        """
        Configures Media Foundation and DirectShow DLL overrides inside the game's Proton user.reg.
        Returns: (success: bool, message: str)
        """
        prefix = CodecFixer.find_game_prefix(app_id)
        if not prefix:
            return False, f"Proton prefix not found for App #{app_id}. Launch the game once through Steam first to generate its prefix."

        user_reg = prefix / "user.reg"
        if not user_reg.exists():
            return False, f"user.reg not found in {prefix}"

        try:
            content = user_reg.read_text(encoding="utf-8", errors="ignore")

            # Section: [Software\\Wine\\DllOverrides]
            section_header = '[Software\\\\Wine\\\\DllOverrides]'
            overrides_block = "\n".join([f'"{dll}"="{mode}"' for dll, mode in CodecFixer.DLL_OVERRIDES.items()])

            if section_header in content:
                # Update existing section
                lines = content.splitlines()
                new_lines = []
                in_section = False
                section_updated = False

                for line in lines:
                    if line.strip() == section_header:
                        in_section = True
                        new_lines.append(line)
                        continue

                    if in_section and line.startswith("["):
                        # Reached next section, insert overrides if not added
                        if not section_updated:
                            for dll, mode in CodecFixer.DLL_OVERRIDES.items():
                                new_lines.append(f'"{dll}"="{mode}"')
                            section_updated = True
                        in_section = False

                    if in_section:
                        # Replace matching DLL lines or keep
                        is_override = any(line.strip().startswith(f'"{dll}"=') for dll in CodecFixer.DLL_OVERRIDES)
                        if not is_override:
                            new_lines.append(line)
                    else:
                        new_lines.append(line)

                if in_section and not section_updated:
                    for dll, mode in CodecFixer.DLL_OVERRIDES.items():
                        new_lines.append(f'"{dll}"="{mode}"')

                content = "\n".join(new_lines)
            else:
                # Append section to end of user.reg
                content += f"\n\n{section_header}\n{overrides_block}\n"

            # Create safety backup of user.reg
            bak_path = user_reg.with_suffix(".reg.vnpm_bak")
            if not bak_path.exists():
                user_reg.rename(bak_path)
            else:
                user_reg.unlink()

            user_reg.write_text(content, encoding="utf-8")
            return True, f"Successfully applied video playback and Media Foundation fixes to Proton prefix (App #{app_id})."

        except Exception as e:
            logger.error(f"Failed to apply video fixes to prefix {prefix}: {e}")
            return False, f"Failed to apply fixes: {e}"
