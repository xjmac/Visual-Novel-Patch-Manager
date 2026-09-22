"""
Unit tests for SteamOS console-grade UX overhaul, theme system,
poster card, game detail modal, and IPC service.
"""

import time
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
from vnpatchmanager.ipc_service import VNPMService, IPCServer, VNPMClient


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

    # Test fix_codecs on missing app
    res_c = service.fix_codecs("999999")
    assert res_c["success"] is False


def test_ipc_server_client_roundtrip(tmp_path):
    """Tests full JSON-RPC 2.0 communication over UNIX domain socket."""
    sock_path = tmp_path / "test_vnpm.sock"

    service = MagicMock()
    service.get_status.return_value = {"status": "ok", "version": "0.2.0"}
    service.scan_games.return_value = {"123": {"name": "Game 123"}}

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
    finally:
        server.stop()
        time.sleep(0.05)
        assert not sock_path.exists()
