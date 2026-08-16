import zlib
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
import vdf

from scripts.add_to_steam import (
    calculate_shortcut_appid,
    find_steam_userdata_dirs,
    register_shortcut,
    APP_NAME,
)


def test_calculate_shortcut_appid():
    exe_path = "/home/deck/.local/share/vnpm/bin/vnpm"
    signed_crc, appid_32 = calculate_shortcut_appid(exe_path, APP_NAME)

    assert isinstance(signed_crc, int)
    assert isinstance(appid_32, str)
    assert appid_32.isdigit()

    # Deterministic check
    signed_crc2, appid_32_2 = calculate_shortcut_appid(exe_path, APP_NAME)
    assert signed_crc == signed_crc2
    assert appid_32 == appid_32_2


def test_find_steam_userdata_dirs(tmp_path):
    mock_userdata = tmp_path / ".steam" / "steam" / "userdata"
    mock_userdata.mkdir(parents=True)
    (mock_userdata / "12345678").mkdir()
    (mock_userdata / "0").mkdir()  # Should be skipped (anonymous ID)
    (mock_userdata / "not_a_num").mkdir()

    with patch("pathlib.Path.home", return_value=tmp_path):
        found = find_steam_userdata_dirs()
        assert len(found) == 1
        assert found[0].name == "12345678"


def test_register_shortcut_and_grid_artwork(tmp_path):
    # Setup mock steam userdata directory
    user_dir = tmp_path / "userdata" / "98765432"
    user_dir.mkdir(parents=True)

    # Setup mock assets
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir(parents=True)
    (assets_dir / "steam_grid_portrait.jpg").write_bytes(b"mock_portrait")
    (assets_dir / "steam_grid_landscape.jpg").write_bytes(b"mock_landscape")
    (assets_dir / "steam_hero.jpg").write_bytes(b"mock_hero")
    (assets_dir / "steam_logo.png").write_bytes(b"mock_logo")
    (assets_dir / "steam_icon.jpg").write_bytes(b"mock_icon")

    exe_path = tmp_path / "bin" / "vnpm"
    exe_path.parent.mkdir(parents=True)
    exe_path.write_text("#!/bin/bash\necho vnpm")

    # 1. Register shortcut when shortcuts.vdf doesn't exist yet
    registered = register_shortcut(exe_path, assets_dir, [user_dir])
    assert registered == 1

    shortcuts_file = user_dir / "config" / "shortcuts.vdf"
    assert shortcuts_file.exists()

    with open(shortcuts_file, "rb") as f:
        data = vdf.binary_loads(f.read())
    shortcuts = data.get("shortcuts", {})
    assert len(shortcuts) == 1
    entry = shortcuts["0"]
    assert entry["AppName"] == APP_NAME
    assert entry["Exe"] == str(exe_path)
    assert entry["StartDir"] == str(exe_path.parent) + "/"

    # Verify grid artwork copied with appid hash
    _, appid_32 = calculate_shortcut_appid(str(exe_path), APP_NAME)
    grid_dir = user_dir / "config" / "grid"
    assert (grid_dir / f"{appid_32}p.jpg").read_bytes() == b"mock_portrait"
    assert (grid_dir / f"{appid_32}.jpg").read_bytes() == b"mock_landscape"
    assert (grid_dir / f"{appid_32}_hero.jpg").read_bytes() == b"mock_hero"
    assert (grid_dir / f"{appid_32}_logo.png").read_bytes() == b"mock_logo"
    assert (grid_dir / f"{appid_32}_icon.jpg").read_bytes() == b"mock_icon"

    # 2. Re-register (update existing entry without duplicating)
    registered_2 = register_shortcut(exe_path, assets_dir, [user_dir])
    assert registered_2 == 1

    with open(shortcuts_file, "rb") as f:
        data_2 = vdf.binary_loads(f.read())
    assert len(data_2.get("shortcuts", {})) == 1


def test_register_shortcut_no_profiles():
    with patch("scripts.add_to_steam.find_steam_userdata_dirs", return_value=[]):
        registered = register_shortcut(Path("/bin/vnpm"), Path("/assets"))
        assert registered == 0
