import os
import sys
import logging
from pathlib import Path
import vdf

logger = logging.getLogger(__name__)

class SteamScanner:
    """Parses Steam's VDF files to locate library folders and installed games."""

    @staticmethod
    def get_steam_root() -> Path:
        paths = []
        if sys.platform == "win32":
            import winreg
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                    steam_path = winreg.QueryValueEx(key, "SteamPath")[0]
                    paths.append(Path(steam_path))
            except (OSError, PermissionError):
                pass
        elif sys.platform == "darwin":
            paths.append(Path.home() / "Library/Application Support/Steam")
        else:
            paths.extend([
                Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
                Path.home() / ".local/share/Steam",
                Path.home() / ".steam/steam",
                Path.home() / ".steam/root"
            ])

        for p in paths:
            if p.exists() and (p / "steamapps").exists():
                return p
        return None

    @staticmethod
    def _is_dlc_or_addon(name: str) -> bool:
        """Identifies whether an item is a DLC, Soundtrack, Artbook, Demo, or Tool rather than a base game."""
        if not name:
            return False
        name_l = name.lower().strip()
        dlc_keywords = [
            " - dlc",
            " - soundtrack",
            " soundtrack",
            " - artbook",
            " artbook",
            " - wallpapers",
            " season pass",
            " (demo)",
            " - demo",
            " - extra fluffy edition",
            " dedicated server",
            " steam linux runtime",
            "proton ",
            "steamworks common redistributables"
        ]
        return any(kw in name_l for kw in dlc_keywords)

    @staticmethod
    def get_installed_games():
        """Returns a dict mapping Steam AppID to game metadata (name, install path) for installed games."""
        steam_root = SteamScanner.get_steam_root()
        if not steam_root:
            logger.warning("Steam installation not found.")
            return {}

        library_vdf = steam_root / "steamapps" / "libraryfolders.vdf"
        if not library_vdf.exists():
            return {}

        installed_games = {}

        try:
            with open(library_vdf, 'r') as f:
                data = vdf.load(f)

            # libraryfolders.vdf has numeric keys (0, 1, 2) for each library location
            for key, library in data.get("libraryfolders", {}).items():
                lib_path = Path(library.get("path"))
                steamapps_path = lib_path / "steamapps"

                if not steamapps_path.exists():
                    continue

                # Parse all appmanifest_*.acf files in this library folder
                for acf_file in steamapps_path.glob("appmanifest_*.acf"):
                    try:
                        with open(acf_file, 'r') as acf_f:
                            acf_data = vdf.load(acf_f)
                            app_state = acf_data.get("AppState", {})
                            app_id = app_state.get("appid")
                            name = app_state.get("name")
                            install_dir = app_state.get("installdir")

                            if app_id and name and install_dir:
                                if SteamScanner._is_dlc_or_addon(name):
                                    continue
                                full_install_path = steamapps_path / "common" / install_dir
                                installed_games[str(app_id)] = {
                                    "name": name,
                                    "path": full_install_path,
                                    "library_path": lib_path,
                                    "is_installed": True
                                }
                    except Exception as e:
                        logger.warning(f"Failed to parse {acf_file}: {e}")

        except Exception as e:
            logger.error(f"Error reading libraryfolders.vdf: {e}")

        # Parse non-Steam shortcuts from userdata/*/config/shortcuts.vdf
        userdata_dir = steam_root / "userdata"
        if userdata_dir.exists():
            for user_folder in userdata_dir.iterdir():
                if not user_folder.is_dir() or not user_folder.name.isdigit():
                    continue
                shortcuts_file = user_folder / "config" / "shortcuts.vdf"
                if shortcuts_file.exists():
                    try:
                        with open(shortcuts_file, "rb") as f:
                            s_data = vdf.binary_loads(f.read())
                            shortcuts = s_data.get("shortcuts", {})
                            for s_entry in shortcuts.values():
                                app_name = s_entry.get("AppName")
                                exe = s_entry.get("Exe", "").strip('"')
                                if app_name and exe:
                                    from .non_steam_manager import calculate_shortcut_appid
                                    _, appid_32 = calculate_shortcut_appid(exe, app_name)
                                    aid_str = str(appid_32)
                                    if aid_str not in installed_games:
                                        exe_path = Path(exe)
                                        installed_games[aid_str] = {
                                            "name": app_name,
                                            "path": exe_path.parent if exe_path.is_file() else exe_path,
                                            "library_path": exe_path.parent,
                                            "is_installed": exe_path.exists(),
                                            "is_non_steam": True
                                        }
                    except Exception as e:
                        logger.debug(f"Error parsing shortcuts.vdf in {user_folder}: {e}")

        return installed_games

    @staticmethod
    def get_owned_games():
        """Returns a dict of all owned games (installed and uninstalled) from the Steam library and cache."""
        owned_games = SteamScanner.get_installed_games()
        steam_root = SteamScanner.get_steam_root()
        if not steam_root:
            return owned_games

        userdata_dir = steam_root / "userdata"
        if userdata_dir.exists():
            for user_folder in userdata_dir.iterdir():
                if not user_folder.is_dir():
                    continue
                localconfig_path = user_folder / "config" / "localconfig.vdf"
                if localconfig_path.exists():
                    try:
                        with open(localconfig_path, 'r', encoding='utf-8', errors='ignore') as f:
                            data = vdf.parse(f)
                            store = data.get("UserLocalConfigStore", {})
                            steam_sec = store.get("Software", {})
                            if isinstance(steam_sec, dict):
                                steam_sec = steam_sec.get("Valve", {})
                            if isinstance(steam_sec, dict):
                                steam_sec = steam_sec.get("Steam", {})
                            if not isinstance(steam_sec, dict):
                                steam_sec = {}

                            # Check apps sections
                            for k in ["apps", "Apps"]:
                                for aid, app_info in steam_sec.get(k, {}).items():
                                    aid_str = str(aid)
                                    if aid_str.isdigit() and aid_str not in owned_games:
                                        app_name = app_info.get("name") if isinstance(app_info, dict) else None
                                        if app_name and SteamScanner._is_dlc_or_addon(app_name):
                                            continue
                                        owned_games[aid_str] = {
                                            "name": app_name or f"Steam App #{aid_str}",
                                            "path": "",
                                            "library_path": "",
                                            "is_installed": False
                                        }

                            # Also check store level app sections
                            for k in ["apps", "UserAppConfig", "apptickets"]:
                                for aid in store.get(k, {}).keys():
                                    aid_str = str(aid)
                                    if aid_str.isdigit() and aid_str not in owned_games:
                                        owned_games[aid_str] = {
                                            "name": f"Steam App #{aid_str}",
                                            "path": "",
                                            "library_path": "",
                                            "is_installed": False
                                        }
                    except Exception as e:
                        logger.warning(f"Error reading {localconfig_path}: {e}")

        # Also inspect librarycache directory artwork
        cache_dirs = [steam_root / "appcache" / "librarycache"]
        if userdata_dir.exists():
            for user_folder in userdata_dir.iterdir():
                if user_folder.is_dir():
                    cache_dirs.append(user_folder / "config" / "librarycache")

        for c_dir in cache_dirs:
            if c_dir.exists():
                for item in c_dir.glob("*"):
                    parts = item.name.split("_")
                    if parts and parts[0].isdigit():
                        aid_str = parts[0]
                        if aid_str not in owned_games:
                            owned_games[aid_str] = {
                                "name": f"Steam App #{aid_str}",
                                "path": "",
                                "library_path": "",
                                "is_installed": False
                            }

        return owned_games
