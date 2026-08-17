import os
import struct
import zlib
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

import vdf
from vnpatchmanager.non_steam_manager import NonSteamManager, calculate_shortcut_appid
from vnpatchmanager.codec_fixer import CodecFixer
from vnpatchmanager.gui import VNPatchManagerApp, ACTION_LEFT, ACTION_RIGHT, ACTION_SELECT


@pytest.fixture
def mock_steam_userdata(tmp_path):
    steam_root = tmp_path / "Steam"
    userdata_dir = steam_root / "userdata" / "12345678" / "config"
    grid_dir = userdata_dir / "grid"
    grid_dir.mkdir(parents=True, exist_ok=True)
    return {
        "steam_root": steam_root,
        "config_dir": userdata_dir,
        "grid_dir": grid_dir
    }


def test_calculate_shortcut_appid():
    exe_path = "/games/synthetic_vn/game.exe"
    app_name = "Synthetic Mystery Novel"
    signed_crc, appid_32 = calculate_shortcut_appid(exe_path, app_name)
    assert isinstance(signed_crc, int)
    assert isinstance(appid_32, int)
    assert appid_32 > 0


def test_find_game_executable(tmp_path):
    game_dir = tmp_path / "SyntheticVisualNovel"
    game_dir.mkdir()
    (game_dir / "unins000.exe").write_text("dummy")
    (game_dir / "UnityCrashHandler64.exe").write_text("dummy")
    target_exe = game_dir / "SyntheticVisualNovel.exe"
    target_exe.write_text("dummy_game")

    mgr = NonSteamManager(steam_root=tmp_path)
    found = mgr.find_game_executable(game_dir)
    assert found == target_exe


def test_find_game_executable_subfolder(tmp_path):
    game_dir = tmp_path / "SyntheticSubdirVN"
    sub_dir = game_dir / "game"
    sub_dir.mkdir(parents=True)
    target_exe = sub_dir / "synthetic_game.exe"
    target_exe.write_text("dummy")

    mgr = NonSteamManager(steam_root=tmp_path)
    found = mgr.find_game_executable(game_dir)
    assert found == target_exe


def test_clean_folder_name():
    assert NonSteamManager.clean_folder_name("PRIMAL HEARTS [JP-EN-CH]") == "PRIMAL HEARTS"
    assert NonSteamManager.clean_folder_name("[RJ123456] Synthetic Story [English] [v1.02]") == "Synthetic Story"
    assert NonSteamManager.clean_folder_name("Clannad_HD_Edition") == "Clannad"
    assert NonSteamManager.clean_folder_name("Fate_Stay_Night_(18+)") == "Fate Stay Night"


def test_match_vn_metadata_bundled():
    mock_vndb = MagicMock()
    mock_vndb.bundled_db = {
        "999999": {
            "vn_id": "v99999",
            "vn_title": "Synthetic Visual Romance",
            "rating": 8.7,
            "vndb_url": "https://vndb.org/v99999"
        },
        "888888": {
            "vn_id": "v14887",
            "vn_title": "Primal Hearts",
            "rating": 7.6,
            "vndb_url": "https://vndb.org/v14887"
        }
    }
    mgr = NonSteamManager(steam_root=None, vndb_scanner=mock_vndb)
    meta = mgr.match_vn_metadata("Synthetic_Visual_Romance")
    assert meta["vndb_id"] == "v99999"
    assert meta["title"] == "Synthetic Visual Romance"
    assert meta["rating"] == 8.7

    # Test folder with bracketed tags matches cleanly
    meta_bracketed = mgr.match_vn_metadata("PRIMAL HEARTS [JP-EN-CH]")
    assert meta_bracketed["vndb_id"] == "v14887"
    assert meta_bracketed["title"] == "Primal Hearts"


def test_match_vn_metadata_fallback():
    mock_vndb = MagicMock()
    mock_vndb.bundled_db = {}
    mgr = NonSteamManager(steam_root=None, vndb_scanner=mock_vndb)
    meta = mgr.match_vn_metadata("my_custom_indie_vn")
    assert meta["vndb_id"] is None
    assert meta["title"] == "My Custom Indie Vn"


def test_register_non_steam_game(mock_steam_userdata, tmp_path):
    steam_root = mock_steam_userdata["steam_root"]
    game_dir = tmp_path / "SyntheticNovelGame"
    game_dir.mkdir()
    game_exe = game_dir / "SyntheticNovelGame.exe"
    game_exe.write_text("binary")

    dummy_art = tmp_path / "art.jpg"
    dummy_art.write_text("art_data")

    mgr = NonSteamManager(steam_root=steam_root)
    success, msg, appid_32 = mgr.register_non_steam_game(
        game_path=game_dir,
        app_name="Synthetic Novel Game",
        custom_artwork={"portrait": dummy_art, "landscape": dummy_art}
    )

    assert success is True
    assert appid_32 is not None
    shortcuts_file = mock_steam_userdata["config_dir"] / "shortcuts.vdf"
    assert shortcuts_file.exists()

    with open(shortcuts_file, "rb") as f:
        data = vdf.binary_loads(f.read())
        shortcuts = data.get("shortcuts", {})
        assert len(shortcuts) >= 1
        entry = next(iter(shortcuts.values()))
        assert entry["AppName"] == "Synthetic Novel Game"
        assert "SyntheticNovelGame.exe" in entry["Exe"]

    # Verify artwork copied
    assert (mock_steam_userdata["grid_dir"] / f"{appid_32}p.jpg").exists()
    assert (mock_steam_userdata["grid_dir"] / f"{appid_32}.jpg").exists()


def test_codec_fixer_apply_video_fixes(tmp_path, monkeypatch):
    pfx_dir = tmp_path / "compatdata" / "123456" / "pfx"
    pfx_dir.mkdir(parents=True)
    user_reg = pfx_dir / "user.reg"
    user_reg.write_text('WINE REGISTRY Version 2\n\n[Software\\\\Wine]\n"Version"="1.0"\n', encoding="utf-8")

    monkeypatch.setattr(CodecFixer, "find_game_prefix", lambda app_id: pfx_dir)

    success, msg = CodecFixer.apply_video_fixes("123456")
    assert success is True
    assert "Successfully applied" in msg

    content = user_reg.read_text(encoding="utf-8")
    assert "[Software\\\\Wine\\\\DllOverrides]" in content
    assert '"mfplay"="native,builtin"' in content
    assert '"quartz"="native,builtin"' in content

    # Test backup created
    bak = pfx_dir / "user.reg.vnpm_bak"
    assert bak.exists()

    # Test idempotency (re-applying updates existing section without duplicating)
    success2, _ = CodecFixer.apply_video_fixes("123456")
    assert success2 is True
    content2 = user_reg.read_text(encoding="utf-8")
    assert content2.count("[Software\\\\Wine\\\\DllOverrides]") == 1


def test_codec_fixer_missing_prefix(monkeypatch):
    monkeypatch.setattr(CodecFixer, "find_game_prefix", lambda app_id: None)
    success, msg = CodecFixer.apply_video_fixes("999999")
    assert success is False
    assert "Proton prefix not found" in msg


def test_cover_art_set_custom_artwork(mock_steam_userdata, tmp_path):
    from vnpatchmanager.cover_art_manager import CoverArtManager
    from PIL import Image

    dummy_img_path = tmp_path / "custom_cover.png"
    img = Image.new("RGB", (300, 300), color="blue")
    img.save(dummy_img_path)

    mgr = CoverArtManager(cache_dir=tmp_path / "covers")
    success = mgr.set_custom_artwork("555555", dummy_img_path, steam_root=mock_steam_userdata["steam_root"])
    assert success is True

    # Check cache updated
    assert mgr.get_cached_path("555555").exists()

    # Check Steam grid files created
    grid_dir = mock_steam_userdata["grid_dir"]
    assert (grid_dir / "555555.jpg").exists()
    assert (grid_dir / "555555p.jpg").exists()
    assert (grid_dir / "555555_hero.jpg").exists()
    assert (grid_dir / "555555_icon.jpg").exists()


def test_remove_non_steam_game(mock_steam_userdata, tmp_path):
    steam_root = mock_steam_userdata["steam_root"]
    game_dir = tmp_path / "SyntheticNovelGame"
    game_dir.mkdir(exist_ok=True)
    game_exe = game_dir / "SyntheticNovelGame.exe"
    game_exe.write_text("binary")

    mgr = NonSteamManager(steam_root=steam_root)
    success, _, appid_32 = mgr.register_non_steam_game(
        game_path=game_dir,
        app_name="Synthetic Novel Game"
    )
    assert success is True

    # Now remove the game
    rem_success, rem_msg = mgr.remove_non_steam_game(
        app_name="Synthetic Novel Game",
        appid_32=appid_32
    )
    assert rem_success is True
    assert "Successfully removed" in rem_msg

    shortcuts_file = mock_steam_userdata["config_dir"] / "shortcuts.vdf"
    with open(shortcuts_file, "rb") as f:
        data = vdf.binary_loads(f.read())
        shortcuts = data.get("shortcuts", {})
        assert len(shortcuts) == 0


def test_gui_header_navigation_and_modal_flow(tmp_path):
    with patch.object(VNPatchManagerApp, "refresh_data"):
        app = VNPatchManagerApp()
        app._focused_zone = "HEADER"
        app._focused_header_idx = 1

        # Press Left to focus Add Non-Steam button
        app._handle_controller_action(ACTION_LEFT)
        assert app._focused_header_idx == 0

        # Press Right to focus Scan button
        app._handle_controller_action(ACTION_RIGHT)
        assert app._focused_header_idx == 1

        # Test run_fix_video method dispatch
        mock_game = {"name": "Synthetic Mystery Novel", "is_installed": True, "is_non_steam": True}
        with patch.object(CodecFixer, "apply_video_fixes", return_value=(True, "Fixed")):
            app.run_fix_video("123456", mock_game)

        # Test run_custom_artwork method dispatch
        with patch.object(app, "open_artwork_browser_modal") as mock_modal:
            app.run_custom_artwork("123456", mock_game)
            mock_modal.assert_called_once_with("123456", mock_game)

        # Test run_remove_non_steam
        with patch("tkinter.messagebox.askyesno", return_value=True), \
             patch.object(app.non_steam_manager, "remove_non_steam_game", return_value=(True, "Removed")):
            app.run_remove_non_steam("123456", mock_game)

        app.destroy()
