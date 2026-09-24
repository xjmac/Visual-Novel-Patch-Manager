"""
Unit tests for SteamOS console-grade UX overhaul, theme system,
poster card, game detail modal, and IPC service.
"""

import hashlib
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image
import customtkinter as ctk

from vnpatchmanager.gui.theme import (
    COLOR_CANVAS,
    COLOR_ELEVATION_1,
    COLOR_BORDER_1,
    COLOR_ELEVATION_2,
    COLOR_BORDER_2,
    COLOR_BORDER_FOCUSED,
    POSTER_CARD_SIZE,
    HERO_BANNER_SIZE,
    MIN_TOUCH_TARGET,
)
from vnpatchmanager.gui.views.poster_card import create_poster_card
from vnpatchmanager.gui.views.game_detail_view import show_game_detail_modal
from vnpatchmanager.codec_fixer import CodecFixer
from vnpatchmanager.install_lock import LOCK_DIR
from vnpatchmanager.ipc_service import VNPMService, IPCServer, VNPMClient
from vnpatchmanager.patch_execution import PatchExecutionEngine


def test_theme_system_tokens():
    """Verifies color tokens and dimension rules in the SteamOS theme system."""
    assert COLOR_CANVAS.startswith("#")
    assert COLOR_ELEVATION_1.startswith("#")
    assert COLOR_BORDER_1.startswith("#")
    assert COLOR_ELEVATION_2.startswith("#")
    assert COLOR_BORDER_2.startswith("#")
    assert COLOR_BORDER_FOCUSED == "#38bdf8"
    assert POSTER_CARD_SIZE == (180, 270)
    assert HERO_BANNER_SIZE == (640, 220)
    assert MIN_TOUCH_TARGET >= 44


def test_create_poster_card(tmp_path):
    """Tests poster card component generation and click handler binding."""
    root = ctk.CTk()
    root.withdraw()

    cover_mgr = MagicMock()
    pil_dummy = Image.new("RGB", (20, 20), color="blue")
    ctk_img = ctk.CTkImage(light_image=pil_dummy, dark_image=pil_dummy, size=(20, 20))
    cover_mgr.get_cover_image.return_value = ctk_img

    selected_calls = []

    def on_select(aid, gdata):
        selected_calls.append((aid, gdata))

    game_data = {"name": "Synthetic Romance VN", "path": str(tmp_path)}
    status_info = {
        "is_patched": False,
        "has_local_patch": True,
        "has_vndb_18_patch": True,
        "has_clean_backup": True,
        "rating": 8.45,
    }

    entry = create_poster_card(
        parent=root,
        app_id="900010",
        game_data=game_data,
        status_info=status_info,
        cover_manager=cover_mgr,
        on_select=on_select,
        row_idx=0,
        col_idx=0,
    )

    assert entry["app_id"] == "900010"
    assert entry["game_data"] == game_data
    assert callable(entry["open_detail"])
    assert entry["buttons"] == []

    # Invoke open_detail callback
    entry["open_detail"]()
    assert len(selected_calls) == 1
    assert selected_calls[0][0] == "900010"

    root.destroy()


def test_game_detail_modal_lifecycle_and_controller(tmp_path):
    """Tests GameDetailModal construction, action button generation, and gamepad navigation."""
    root = ctk.CTk()
    root.withdraw()

    cover_mgr = MagicMock()
    pil_dummy = Image.new("RGB", (20, 20), color="blue")
    ctk_img = ctk.CTkImage(light_image=pil_dummy, dark_image=pil_dummy, size=(20, 20))
    cover_mgr.get_cover_image.return_value = ctk_img
    root.cover_manager = cover_mgr
    root.repo = MagicMock()
    root.repo.available_patches = {"900010": {"steam_app_id": "900010", "actions": []}}

    patch_called = []
    root.run_patch = lambda g, p: patch_called.append((g, p))
    root.run_rollback = MagicMock()
    root.run_steam_restore = MagicMock()
    root.run_codec_fix = MagicMock()
    root.run_fix_video = MagicMock()
    root.run_custom_artwork = MagicMock()
    root.run_remove_non_steam = MagicMock()

    modal_handlers = []
    root.push_modal_controller_handler = lambda h: modal_handlers.append(h)
    root.pop_modal_controller_handler = lambda h: modal_handlers.remove(h) if h in modal_handlers else None

    closed_flag = []

    game_data = {
        "name": "Test Novel",
        "path": str(tmp_path),
        "is_non_steam": True,
    }
    status_info = {
        "is_patched": False,
        "has_local_patch": True,
        "has_clean_backup": True,
        "has_backup": True,
        "vn_info": {"rating": 8.2, "developer": "Key", "released": "2004-04-28", "description": "A story of town and people."},
    }

    modal = show_game_detail_modal(
        parent=root,
        app_id="900010",
        game_data=game_data,
        status_info=status_info,
        on_close=lambda: closed_flag.append(True),
    )

    assert modal is not None
    assert len(modal_handlers) == 1
    assert len(modal._action_buttons) >= 4

    # Test controller navigation
    from vnpatchmanager.controller_manager import ACTION_LEFT, ACTION_RIGHT, ACTION_SELECT

    # Move right then left
    modal._handle_controller_input(ACTION_RIGHT)
    assert modal._focused_btn_idx == 1
    modal._handle_controller_input(ACTION_LEFT)
    assert modal._focused_btn_idx == 0

    # Test selecting the primary action button ([A] Apply Patch)
    modal._handle_controller_input(ACTION_SELECT)
    assert len(patch_called) == 1
    assert len(closed_flag) == 1

    root.destroy()


def test_game_detail_modal_steam_restore_and_codec_fix(tmp_path):
    """Tests GameDetailModal 'Restore via Steam' and 'Video Codec Fix' button actions."""
    root = ctk.CTk()
    root.withdraw()

    cover_mgr = MagicMock()
    pil_dummy = Image.new("RGB", (20, 20), color="blue")
    ctk_img = ctk.CTkImage(light_image=pil_dummy, dark_image=pil_dummy, size=(20, 20))
    cover_mgr.get_cover_image.return_value = ctk_img
    root.cover_manager = cover_mgr
    root.repo = MagicMock()
    root.repo.available_patches = {"900020": {"steam_app_id": "900020", "actions": []}}

    root.run_steam_restore = MagicMock()
    root.run_fix_video = MagicMock()
    root.push_modal_controller_handler = MagicMock()
    root.pop_modal_controller_handler = MagicMock()

    game_data = {
        "name": "Steam Test VN",
        "path": str(tmp_path),
        "is_non_steam": False,
        "steam_app_id": "900020",
    }
    status_info = {
        "is_patched": True,
        "has_local_patch": True,
        "has_clean_backup": False,
        "has_backup": True,
        "vn_info": {},
    }

    modal = show_game_detail_modal(
        parent=root,
        app_id="900020",
        game_data=game_data,
        status_info=status_info,
    )

    # Locate Restore via Steam button
    steam_btn = next((b for b in modal._action_buttons if "Restore via Steam" in b.cget("text")), None)
    assert steam_btn is not None
    steam_btn._command()
    root.run_steam_restore.assert_called_once_with(
        game_data,
        patch_data={"steam_app_id": "900020", "actions": []},
        app_id="900020",
    )

    # Re-open modal to test Codec Fix button
    modal2 = show_game_detail_modal(
        parent=root,
        app_id="900020",
        game_data=game_data,
        status_info=status_info,
    )
    codec_btn = next((b for b in modal2._action_buttons if "Video Codec Fix" in b.cget("text")), None)
    assert codec_btn is not None
    codec_btn._command()
    root.run_fix_video.assert_called_once_with("900020", game_data)

    # Test when game has no patch manifest in repo (patch_data=None)
    root.repo.available_patches = {}
    modal3 = show_game_detail_modal(
        parent=root,
        app_id="900020",
        game_data=game_data,
        status_info=status_info,
    )
    steam_btn3 = next((b for b in modal3._action_buttons if "Restore via Steam" in b.cget("text")), None)
    assert steam_btn3 is not None
    root.run_steam_restore.reset_mock()
    steam_btn3._command()
    root.run_steam_restore.assert_called_once_with(
        game_data,
        patch_data=None,
        app_id="900020",
    )

    root.destroy()


def test_ipc_service_methods(tmp_path):
    """Tests VNPMService headless methods."""
    cm = MagicMock()
    cm.config = {"mode": "local", "local_path": str(tmp_path)}

    service = VNPMService(config_manager=cm)

    status = service.get_status()
    assert status["status"] == "running"
    assert status["mode"] == "local"

    with patch.object(service.steam_scanner, "get_installed_games", return_value={}), \
         patch.object(service.steam_scanner, "get_owned_games", return_value={}):
        games = service.scan_games()
        assert isinstance(games, dict)

    # Test apply_patch on missing app
    res = service.apply_patch("999999")
    assert res["success"] is False
    assert "No patch available" in res["error"]

    # Test restore_backup on missing app
    res_b = service.restore_backup("999999")
    assert res_b["success"] is False

    # Test restore_via_steam on missing app
    res_s = service.restore_via_steam("999999")
    assert res_s["success"] is False

    # Test fix_codecs on missing app
    with patch.object(CodecFixer, "apply_video_fixes") as mock_fix:
        res_c = service.fix_codecs("999999")
        assert res_c["success"] is False
        mock_fix.assert_not_called()


def _steam_library_game(tmp_path, app_id="100"):
    """One installed game whose library root is the Steam directory, not steamapps."""
    steam_root = tmp_path / "Steam"
    install = steam_root / "steamapps" / "common" / "Game"
    install.mkdir(parents=True)
    games = {
        app_id: {
            "name": "Game",
            "path": install,
            "library_path": steam_root,
            "is_installed": True,
            "is_non_steam": False,
        }
    }
    patch_data = {
        "steam_app_id": app_id,
        "actions": [],
        "patch_source_dir": str(tmp_path),
    }
    return steam_root, install, app_id, games, patch_data


def _service_for_games(tmp_path, app_id, games, patch_data):
    cm = MagicMock()
    cm.config = {"mode": "local", "local_path": str(tmp_path)}
    service = VNPMService(config_manager=cm)
    service.repo.refresh_patches = MagicMock()
    service.repo.available_patches = {str(app_id): patch_data}
    service.steam_scanner.get_installed_games = MagicMock(return_value=games)
    service.steam_scanner.get_owned_games = MagicMock(return_value={})
    return service


def test_apply_patch_uses_scanner_library_root(tmp_path):
    """Proton's library root is the scanner value, not install.parent.parent."""
    steam_root, install, app_id, games, patch_data = _steam_library_game(tmp_path)
    service = _service_for_games(tmp_path, app_id, games, patch_data)
    recorded = {}

    def _record(game_data, patch, config_manager, log_callback=None):
        recorded.update(game_data)
        if log_callback:
            log_callback("staged")
        return True

    with patch.object(PatchExecutionEngine, "apply_patch", side_effect=_record):
        result = service.apply_patch(app_id)

    assert result["success"] is True
    assert result["logs"] == ["staged"]
    assert Path(recorded["library_path"]) == steam_root
    assert Path(recorded["library_path"]) != steam_root / "steamapps"
    assert Path(recorded["library_path"]) != install.parent.parent


def test_fix_codecs_calls_apply_video_fixes(tmp_path):
    """fix_codecs uses CodecFixer.apply_video_fixes and no removed helpers."""
    _steam_root, _install, app_id, games, patch_data = _steam_library_game(tmp_path, app_id="222")
    service = _service_for_games(tmp_path, app_id, games, patch_data)
    service.steam_scanner.get_steam_root = MagicMock(return_value=tmp_path / "Steam")

    assert not hasattr(CodecFixer, "get_compat_data_path")
    assert not hasattr(CodecFixer, "apply_all_fixes")

    with patch.object(CodecFixer, "apply_video_fixes", return_value=(True, "fixed")) as mock_fix:
        result = service.fix_codecs(app_id)

    assert result["success"] is True
    assert result["message"] == "fixed"
    assert result["error"] is None
    mock_fix.assert_called_once_with(str(app_id))


def test_install_lock_blocks_second_caller(tmp_path):
    """A second apply_patch for the same install waits until the first releases."""
    _steam_root, install, app_id, games, patch_data = _steam_library_game(tmp_path, app_id="333")
    first = _service_for_games(tmp_path, app_id, games, patch_data)
    second = _service_for_games(tmp_path, app_id, games, patch_data)

    first_inside = threading.Event()
    release_first = threading.Event()
    second_inside = threading.Event()
    entered_early = threading.Event()
    results = []

    def _engine(*_args, **_kwargs):
        if not first_inside.is_set():
            first_inside.set()
            release_first.wait(timeout=3)
            return True
        if not release_first.is_set():
            entered_early.set()
        second_inside.set()
        return True

    def _run(service):
        results.append(service.apply_patch(app_id))

    with patch.object(PatchExecutionEngine, "apply_patch", side_effect=_engine):
        holder = threading.Thread(target=_run, args=(first,))
        waiter = threading.Thread(target=_run, args=(second,))
        holder.start()
        assert first_inside.wait(timeout=3)
        waiter.start()
        time.sleep(0.25)
        assert not second_inside.is_set()
        assert not entered_early.is_set()
        release_first.set()
        assert second_inside.wait(timeout=3)
        holder.join(timeout=3)
        waiter.join(timeout=3)

    assert not holder.is_alive()
    assert not waiter.is_alive()
    assert not entered_early.is_set()
    assert len(results) == 2
    assert all(item["success"] is True for item in results)

    digest_path = LOCK_DIR / f"{hashlib.sha256(str(Path(install).resolve()).encode()).hexdigest()}.lock"
    assert digest_path.exists()
    assert os.stat(digest_path).st_mode & 0o777 == 0o600


def test_ipc_server_client_roundtrip(tmp_path):
    """Tests full JSON-RPC 2.0 communication over UNIX domain socket."""
    sock_path = tmp_path / "test_vnpm.sock"

    service = MagicMock()
    service.get_status.return_value = {"status": "ok", "version": "0.2.0"}
    service.scan_games.return_value = {"123": {"name": "Game 123"}}
    service.restore_via_steam.return_value = {"success": True, "logs": []}

    server = IPCServer(service=service, socket_path=sock_path)
    server.start(background=True)
    time.sleep(0.1)

    try:
        assert sock_path.exists()

        client = VNPMClient(socket_path=sock_path)
        status_res = client.get_status()
        assert status_res["status"] == "ok"
        assert status_res["version"] == "0.2.0"

        games_res = client.scan_games()
        assert "123" in games_res
        assert games_res["123"]["name"] == "Game 123"

        steam_res = client.restore_via_steam("123")
        assert steam_res["success"] is True
    finally:
        server.stop()
        time.sleep(0.05)
        assert not sock_path.exists()


def test_game_detail_modal_uses_get_hero_image(tmp_path):
    """Verifies that GameDetailModal calls get_hero_image for its landscape banner."""
    root = ctk.CTk()
    root.withdraw()

    cover_mgr = MagicMock()
    pil_dummy = Image.new("RGB", (640, 220), color="purple")
    ctk_img = ctk.CTkImage(light_image=pil_dummy, dark_image=pil_dummy, size=(640, 220))
    cover_mgr.get_hero_image.return_value = ctk_img
    root.cover_manager = cover_mgr
    root.repo = MagicMock()
    root.repo.available_patches = {}

    game_data = {"name": "Muv-Luv photonflowers*", "path": str(tmp_path)}
    status_info = {"is_patched": False, "vn_info": {}}

    modal = show_game_detail_modal(
        parent=root,
        app_id="889700",
        game_data=game_data,
        status_info=status_info,
    )

    assert modal is not None
    cover_mgr.get_hero_image.assert_called_once()
    call_args, call_kwargs = cover_mgr.get_hero_image.call_args
    assert call_args[0] == "889700"
    assert call_kwargs.get("title") == "Muv-Luv photonflowers*"
    assert call_kwargs.get("size") == (640, 220)

    root.destroy()

