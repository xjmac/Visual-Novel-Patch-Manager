import re
import json
import logging
import shutil
import struct
import zlib
from pathlib import Path
from typing import Optional

try:
    import vdf
except ImportError:
    vdf = None

from .steam_scanner import SteamScanner
from .vndb_scanner import VNDBScanner
from .cover_art_manager import CoverArtManager

logger = logging.getLogger(__name__)


def calculate_shortcut_appid(exe_path: str, app_name: str) -> tuple[int, int]:
    """
    Calculates Steam's 64-bit and 32-bit AppID hashes for non-Steam shortcuts.
    Algorithm: CRC32(exe_path + app_name) with high bit set.
    """
    combined = f"{exe_path}{app_name}".encode("utf-8")
    crc = zlib.crc32(combined)
    signed_crc = struct.unpack("i", struct.pack("I", crc))[0]
    appid_64 = (crc | 0x80000000) << 32 | 0x02000000
    appid_32 = appid_64 >> 32
    return signed_crc, appid_32


class NonSteamManager:
    """
    Manages discovering standalone non-Steam visual novels, matching them with VNDB,
    and registering them into Steam's shortcuts.vdf with full 5-slot grid artwork.
    """

    EXECUTABLE_EXTENSIONS = (".exe", ".sh", ".x86_64", ".bin", ".py")

    def __init__(self, steam_root: Optional[Path] = None, vndb_scanner: Optional[VNDBScanner] = None):
        self.steam_root = steam_root or SteamScanner.get_steam_root()
        self.vndb_scanner = vndb_scanner or VNDBScanner()
        self.cover_manager = CoverArtManager()

    @staticmethod
    def clean_folder_name(name: str) -> str:
        """
        Strips release tags, bracketed metadata, version numbers, and edition tags.
        Example: 'PRIMAL HEARTS [JP-EN-CH]' -> 'PRIMAL HEARTS'
                 '[RJ123456] Fate Stay Night [English] [v1.0]' -> 'Fate Stay Night'
        """
        if not name:
            return ""
        # 1. Remove bracketed / parenthetical / curly tags: [...], (...), {...}
        cleaned = re.sub(r'\[.*?\]|\(.*?\)|{.*?}', ' ', name)

        # 2. Normalize separators to spaces for clean word boundary matching
        cleaned = re.sub(r'[\-_+.]+', ' ', cleaned)

        # 3. Remove common release tags and suffixes
        tags_to_strip = [
            r'\b(v|ver|version)\s*\d+(\.\d+)*\b',
            r'\b(uncensored|censored|repack|remastered|hd|edition|directors cut|complete edition)\b',
            r'\brj\d+\b',
            r'\bdlsite\b',
            r'\bjast\b',
            r'\bmangagamer\b',
            r'\bfanza\b',
            r'\bdmm\b',
            r'\bsteam\b',
            r'\bjp\b',
            r'\ben\b',
            r'\bch\b',
            r'\bchs\b',
            r'\bcht\b',
            r'\beng\b',
            r'\benglish\b',
            r'\bjapanese\b',
            r'\bchinese\b'
        ]
        for pattern in tags_to_strip:
            cleaned = re.sub(pattern, ' ', cleaned, flags=re.IGNORECASE)

        # 4. Clean up extra whitespace
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return cleaned or name

    def find_game_executable(self, game_dir: Path) -> Optional[Path]:
        """Finds the primary game executable in a directory."""
        if not game_dir.is_dir():
            if game_dir.is_file() and any(game_dir.name.lower().endswith(ext) for ext in self.EXECUTABLE_EXTENSIONS):
                return game_dir
            return None

        # 1. Look for obvious game executables
        candidates = []
        for item in game_dir.iterdir():
            if item.is_file():
                lname = item.name.lower()
                # Skip uninstaller/setup
                if any(x in lname for x in ("unins", "setup", "patch", "crash", "unitycrash", "config")):
                    continue
                if any(lname.endswith(ext) for ext in self.EXECUTABLE_EXTENSIONS):
                    candidates.append(item)

        if not candidates:
            # Check 1 level deeper (e.g. game/ directory or bin/)
            for sub in game_dir.iterdir():
                if sub.is_dir() and sub.name.lower() in ("game", "bin", "app"):
                    for item in sub.iterdir():
                        if item.is_file() and any(item.name.lower().endswith(ext) for ext in self.EXECUTABLE_EXTENSIONS):
                            candidates.append(item)

        if candidates:
            # Prefer .exe over .sh / scripts, prefer matching folder name
            candidates.sort(key=lambda p: (
                0 if p.suffix.lower() == ".exe" else 1,
                0 if p.stem.lower() in game_dir.name.lower() else 1
            ))
            return candidates[0]

        return None

    def match_vn_metadata(self, folder_name: str, exe_name: str = "") -> dict:
        """Matches a folder or executable name against the VNDB database with multi-stage normalization."""
        cleaned_folder = self.clean_folder_name(folder_name)
        cleaned_exe = self.clean_folder_name(exe_name) if exe_name else ""

        queries_to_try = [
            cleaned_folder,
            folder_name,
            cleaned_exe,
            exe_name
        ]
        # Deduplicate non-empty queries
        seen = set()
        candidates = []
        for q in queries_to_try:
            if q and q.strip() and q.lower() not in seen:
                seen.add(q.lower())
                candidates.append(q.strip())

        db = self.vndb_scanner.bundled_db

        # Stage 1: Exact / Normalized Match
        for query in candidates:
            q_clean = query.lower()
            q_alpha = re.sub(r'\W+', '', q_clean)
            if not q_alpha:
                continue

            for aid_str, entry in db.items():
                if not isinstance(entry, dict):
                    continue
                vn_title = entry.get("vn_title", "")
                t_clean = vn_title.lower()
                t_alpha = re.sub(r'\W+', '', t_clean)

                if q_clean == t_clean or q_alpha == t_alpha:
                    return {
                        "vndb_id": entry.get("vn_id"),
                        "title": vn_title,
                        "rating": entry.get("rating"),
                        "vndb_url": entry.get("vndb_url"),
                        "matched_app_id": aid_str
                    }

        # Stage 2: Substring / Sub-phrase Match (favoring exact phrase start)
        for query in candidates:
            q_clean = query.lower()
            q_alpha = re.sub(r'\W+', '', q_clean)
            if len(q_alpha) < 3:
                continue

            for aid_str, entry in db.items():
                if not isinstance(entry, dict):
                    continue
                vn_title = entry.get("vn_title", "")
                t_clean = vn_title.lower()
                t_alpha = re.sub(r'\W+', '', t_clean)

                if q_alpha in t_alpha or t_alpha in q_alpha:
                    return {
                        "vndb_id": entry.get("vn_id"),
                        "title": vn_title,
                        "rating": entry.get("rating"),
                        "vndb_url": entry.get("vndb_url"),
                        "matched_app_id": aid_str
                    }

        fallback_title = (cleaned_folder or folder_name).replace("_", " ").replace("-", " ").title()
        return {
            "vndb_id": None,
            "title": fallback_title,
            "rating": None,
            "vndb_url": None,
            "matched_app_id": None
        }

    def register_non_steam_game(
        self,
        game_path: Path,
        app_name: str,
        custom_artwork: Optional[dict] = None
    ) -> tuple[bool, str, Optional[int]]:
        """
        Creates a Steam shortcut in shortcuts.vdf and deploys grid artwork.
        Returns: (success: bool, message: str, appid_32: Optional[int])
        """
        if vdf is None:
            return False, "vdf module not available", None

        exe_file = self.find_game_executable(game_path)
        if not exe_file:
            return False, f"No executable found in {game_path}", None

        if not self.steam_root:
            return False, "Steam installation directory not found", None

        userdata_dir = self.steam_root / "userdata"
        if not userdata_dir.exists():
            return False, f"Steam userdata directory not found at {userdata_dir}", None

        signed_crc, appid_32 = calculate_shortcut_appid(str(exe_file), app_name)
        start_dir = str(exe_file.parent) + "/"

        user_dirs = [d for d in userdata_dir.iterdir() if d.is_dir() and d.name.isdigit()]
        if not user_dirs:
            return False, "No active Steam user profiles found in userdata/", None

        added_profiles = 0
        for user_dir in user_dirs:
            config_dir = user_dir / "config"
            grid_dir = config_dir / "grid"
            config_dir.mkdir(parents=True, exist_ok=True)
            grid_dir.mkdir(parents=True, exist_ok=True)

            shortcuts_file = config_dir / "shortcuts.vdf"
            shortcuts_dict = {"shortcuts": {}}

            if shortcuts_file.exists():
                try:
                    with open(shortcuts_file, "rb") as f:
                        data = vdf.binary_loads(f.read())
                        if isinstance(data, dict) and "shortcuts" in data:
                            shortcuts_dict = data
                except Exception as e:
                    logger.warning(f"Failed to read existing shortcuts.vdf in {user_dir}: {e}")

            shortcuts = shortcuts_dict.get("shortcuts", {})

            # Check if entry already exists (by exe and appname)
            target_idx = None
            for idx, entry in shortcuts.items():
                if entry.get("Exe") == f'"{exe_file}"' or entry.get("Exe") == str(exe_file) or entry.get("AppName") == app_name:
                    target_idx = idx
                    break

            if target_idx is None:
                numeric_keys = [int(k) for k in shortcuts.keys() if k.isdigit()]
                target_idx = str(max(numeric_keys) + 1 if numeric_keys else 0)

            # Define new non-Steam shortcut entry
            new_entry = {
                "appid": signed_crc,
                "AppName": app_name,
                "Exe": f'"{exe_file}"',
                "StartDir": f'"{start_dir}"',
                "icon": str(grid_dir / f"{appid_32}_icon.jpg"),
                "ShortcutPath": "",
                "LaunchOptions": "",
                "IsHidden": 0,
                "AllowDesktopConfig": 1,
                "AllowOverlay": 1,
                "OpenVR": 0,
                "Devkit": 0,
                "DevkitGameID": "",
                "DevkitOverrideAppId": 0,
                "LastPlayTime": 0,
                "FlatpakAppID": "",
                "tags": {"0": "Visual Novel", "1": "VNPM"}
            }

            shortcuts[target_idx] = new_entry
            shortcuts_dict["shortcuts"] = shortcuts

            try:
                with open(shortcuts_file, "wb") as f:
                    f.write(vdf.binary_dumps(shortcuts_dict))
                added_profiles += 1
            except Exception as e:
                logger.error(f"Error saving {shortcuts_file}: {e}")
                continue

            # Deploy Artwork (Default or Custom)
            if custom_artwork:
                if custom_artwork.get("portrait") and Path(custom_artwork["portrait"]).exists():
                    shutil.copy2(custom_artwork["portrait"], grid_dir / f"{appid_32}p.jpg")
                if custom_artwork.get("landscape") and Path(custom_artwork["landscape"]).exists():
                    shutil.copy2(custom_artwork["landscape"], grid_dir / f"{appid_32}.jpg")
                if custom_artwork.get("hero") and Path(custom_artwork["hero"]).exists():
                    shutil.copy2(custom_artwork["hero"], grid_dir / f"{appid_32}_hero.jpg")
                if custom_artwork.get("logo") and Path(custom_artwork["logo"]).exists():
                    shutil.copy2(custom_artwork["logo"], grid_dir / f"{appid_32}_logo.png")
                if custom_artwork.get("icon") and Path(custom_artwork["icon"]).exists():
                    shutil.copy2(custom_artwork["icon"], grid_dir / f"{appid_32}_icon.jpg")

        # Auto-fetch VNDB/Steam cover artwork if no custom artwork provided
        if not custom_artwork and appid_32:
            try:
                from .cover_art_manager import CoverArtManager
                cam = CoverArtManager()
                meta = self.match_vn_metadata(app_name)
                mock_game_data = {
                    "name": app_name,
                    "is_non_steam": True,
                    "vndb": {
                        "vn_id": meta.get("vndb_id"),
                        "matched_app_id": meta.get("matched_app_id")
                    }
                }
                cam.download_cover(str(appid_32), game_data=mock_game_data)
            except Exception as ex:
                logger.warning(f"Failed to auto-fetch cover art for non-Steam game '{app_name}': {ex}")

        return True, f"Successfully registered '{app_name}' into {added_profiles} Steam profile(s).", appid_32

    def remove_non_steam_game(
        self,
        app_name: str,
        appid_32: Optional[int] = None
    ) -> tuple[bool, str]:
        """
        Removes a non-Steam game shortcut from Steam's shortcuts.vdf across all profiles.
        """
        if vdf is None:
            return False, "vdf module not available"

        if not self.steam_root:
            return False, "Steam installation directory not found"

        userdata_dir = self.steam_root / "userdata"
        if not userdata_dir.exists():
            return False, f"Steam userdata directory not found at {userdata_dir}"

        user_dirs = [d for d in userdata_dir.iterdir() if d.is_dir() and d.name.isdigit()]
        if not user_dirs:
            return False, "No active Steam user profiles found in userdata/"

        removed_profiles = 0
        for user_dir in user_dirs:
            config_dir = user_dir / "config"
            shortcuts_file = config_dir / "shortcuts.vdf"
            grid_dir = config_dir / "grid"

            if not shortcuts_file.exists():
                continue

            try:
                with open(shortcuts_file, "rb") as f:
                    shortcuts_dict = vdf.binary_loads(f.read())
            except Exception as e:
                logger.warning(f"Failed to read {shortcuts_file}: {e}")
                continue

            shortcuts = shortcuts_dict.get("shortcuts", {})
            new_shortcuts = {}
            matched = False

            cur_idx = 0
            for idx, entry in sorted(shortcuts.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 9999):
                entry_name = entry.get("AppName", "")
                entry_exe = entry.get("Exe", "").strip('"')
                is_match = False

                if entry_name == app_name:
                    is_match = True
                elif appid_32 and entry_exe:
                    _, calc_32 = calculate_shortcut_appid(entry_exe, entry_name)
                    if calc_32 == appid_32:
                        is_match = True

                if is_match:
                    matched = True
                else:
                    new_shortcuts[str(cur_idx)] = entry
                    cur_idx += 1

            if matched:
                shortcuts_dict["shortcuts"] = new_shortcuts
                try:
                    with open(shortcuts_file, "wb") as f:
                        f.write(vdf.binary_dumps(shortcuts_dict))
                    removed_profiles += 1
                except Exception as e:
                    logger.error(f"Failed to write updated {shortcuts_file}: {e}")

            # Clean up grid artwork if appid_32 known
            if appid_32 and grid_dir.exists():
                for art_pattern in (
                    f"{appid_32}p.jpg",
                    f"{appid_32}.jpg",
                    f"{appid_32}_hero.jpg",
                    f"{appid_32}_logo.png",
                    f"{appid_32}_icon.jpg"
                ):
                    art_f = grid_dir / art_pattern
                    if art_f.exists():
                        try:
                            art_f.unlink()
                        except Exception:
                            pass

        if removed_profiles > 0:
            return True, f"Successfully removed '{app_name}' from {removed_profiles} Steam profile(s)."
        return False, f"Shortcut for '{app_name}' not found in Steam profiles."
