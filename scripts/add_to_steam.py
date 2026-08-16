#!/usr/bin/env python3
"""Steam Game Mode Shortcut & Artwork Registration Helper for VN Patch Manager.

Safely registers VNPM into Steam's shortcuts.vdf and deploys custom grid artwork
(vertical capsule, wide capsule, hero banner, and app icon).
"""

import sys
import shutil
import zlib
from pathlib import Path
from typing import List, Optional

try:
    import vdf
except ImportError:
    print("Warning: 'vdf' package not installed. Skipping Steam shortcut registration.")
    sys.exit(0)

APP_NAME = "VN Patch Manager"


def calculate_shortcut_appid(exe_path: str, app_name: str) -> tuple[int, str]:
    """Calculates Valve's 64-bit internal AppID and 32-bit grid filename hash.

    Algorithm:
        crc = CRC32('"{exe_path}"{app_name}') | 0x80000000
        32-bit grid ID = crc
        64-bit VDF appid = (crc << 32) | 0x02000000
    """
    key = f'"{exe_path}"{app_name}'.encode("utf-8")
    crc = zlib.crc32(key) | 0x80000000
    appid_32 = str(crc & 0xFFFFFFFF)
    appid_64 = (crc << 32) | 0x02000000
    # In binary VDF, signed 32-bit integer conversion is used for the appid key
    signed_crc = crc - 0x100000000 if crc > 0x7FFFFFFF else crc
    return signed_crc, appid_32


def find_steam_userdata_dirs() -> List[Path]:
    """Discovers all Steam userdata directories across Native and Flatpak installations."""
    home = Path.home()
    candidates = [
        home / ".steam" / "steam" / "userdata",
        home / ".steam" / "root" / "userdata",
        home / ".local" / "share" / "Steam" / "userdata",
        home / ".var" / "app" / "com.valvesoftware.Steam" / ".steam" / "steam" / "userdata",
        home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam" / "userdata",
    ]
    found = []
    for cand in candidates:
        if cand.exists() and cand.is_dir():
            for user_dir in cand.iterdir():
                if user_dir.is_dir() and user_dir.name.isdigit() and user_dir.name != "0":
                    if user_dir not in found:
                        found.append(user_dir)
    return found


def register_shortcut(
    exe_path: Path,
    assets_dir: Path,
    userdata_dirs: Optional[List[Path]] = None
) -> int:
    """Registers VNPM as a Non-Steam Game and deploys grid artwork for all Steam profiles."""
    if userdata_dirs is None:
        userdata_dirs = find_steam_userdata_dirs()

    if not userdata_dirs:
        print("ℹ️ No active Steam profiles found in userdata. (Steam will register on next launch).")
        return 0

    signed_appid, appid_32 = calculate_shortcut_appid(str(exe_path), APP_NAME)
    icon_path = assets_dir / "steam_icon.jpg"

    registered_count = 0
    for user_dir in userdata_dirs:
        config_dir = user_dir / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        grid_dir = config_dir / "grid"
        grid_dir.mkdir(parents=True, exist_ok=True)

        shortcuts_file = config_dir / "shortcuts.vdf"
        shortcuts_data = {"shortcuts": {}}

        if shortcuts_file.exists():
            try:
                with open(shortcuts_file, "rb") as f:
                    content = f.read()
                    if content:
                        shortcuts_data = vdf.binary_loads(content)
            except Exception as e:
                print(f"Warning: Failed to parse {shortcuts_file}: {e}")
                shortcuts_data = {"shortcuts": {}}

        shortcuts = shortcuts_data.setdefault("shortcuts", {})

        # Check if already present
        existing_idx = None
        for idx, entry in shortcuts.items():
            if isinstance(entry, dict) and entry.get("AppName") == APP_NAME:
                existing_idx = idx
                break

        target_idx = existing_idx if existing_idx is not None else str(len(shortcuts))
        shortcuts[target_idx] = {
            "appid": signed_appid,
            "AppName": APP_NAME,
            "Exe": str(exe_path),
            "StartDir": str(exe_path.parent) + "/",
            "icon": str(icon_path) if icon_path.exists() else "",
            "ShortcutPath": "",
            "LaunchOptions": "",
            "IsHidden": 0,
            "AllowDesktopConfig": 1,
            "AllowOverlay": 1,
            "OpenVR": 0,
            "Devkit": 0,
            "DevkitGameID": "",
            "DevkitOverrideAppID": 0,
            "LastPlayTime": 0,
            "tags": {}
        }

        # Save binary shortcuts.vdf
        try:
            with open(shortcuts_file, "wb") as f:
                f.write(vdf.binary_dumps(shortcuts_data))
        except Exception as e:
            print(f"Error saving {shortcuts_file}: {e}")
            continue

        # Deploy Grid Artwork
        portrait_src = assets_dir / "steam_grid_portrait.jpg"
        landscape_src = assets_dir / "steam_grid_landscape.jpg"
        hero_src = assets_dir / "steam_hero.jpg"
        icon_src = assets_dir / "steam_icon.jpg"

        if portrait_src.exists():
            shutil.copy2(portrait_src, grid_dir / f"{appid_32}p.jpg")
        if landscape_src.exists():
            shutil.copy2(landscape_src, grid_dir / f"{appid_32}.jpg")
        if hero_src.exists():
            shutil.copy2(hero_src, grid_dir / f"{appid_32}_hero.jpg")
        if icon_src.exists():
            shutil.copy2(icon_src, grid_dir / f"{appid_32}_icon.jpg")

        registered_count += 1
        print(f"✅ Added '{APP_NAME}' to Steam profile {user_dir.name} with custom grid artwork.")

    return registered_count


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 add_to_steam.py <path_to_vnpm_executable> <path_to_assets_dir>")
        sys.exit(1)

    exe_path = Path(sys.argv[1]).resolve()
    assets_dir = Path(sys.argv[2]).resolve()
    register_shortcut(exe_path, assets_dir)


if __name__ == "__main__":
    main()
