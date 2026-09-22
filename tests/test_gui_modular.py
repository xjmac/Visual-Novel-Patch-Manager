"""
Unit tests for modular GUI package structure, constants, and service layer download methods.
"""

import time
from unittest.mock import patch, MagicMock

from vnpatchmanager.gui import (
    VNPatchManagerApp,
    MODE_LOCAL_DISPLAY,
    MODE_SMB_DISPLAY,
    APP_NAME,
    APP_VERSION,
    ACTION_UP,
    ACTION_DOWN,
    ACTION_LEFT,
    ACTION_RIGHT,
    ACTION_SELECT,
    ACTION_BACK,
)
from vnpatchmanager.gui.constants import (
    COLOR_BG_BLACK,
    COLOR_SURFACE_DARK,
    COLOR_PRIMARY_BLUE,
    THUMB_SIZE_CAPSULE,
    GRID_CARD_BANNER_SIZE,
)
from vnpatchmanager.steamgriddb_client import SteamGridDBClient
from vnpatchmanager.cover_art_manager import CoverArtManager
from vnpatchmanager.patch_execution import PatchExecutionEngine


def test_gui_package_exports():
    """Verifies that vnpatchmanager.gui re-exports all required classes, constants, and actions."""
    assert VNPatchManagerApp is not None
    assert MODE_LOCAL_DISPLAY == "📁 Local Storage"
    assert MODE_SMB_DISPLAY == "🌐 Network Share (NAS)"
    assert APP_NAME == "VN Patch Manager"
    assert APP_VERSION is not None
    assert ACTION_UP == "UP"
    assert ACTION_DOWN == "DOWN"
    assert ACTION_LEFT == "LEFT"
    assert ACTION_RIGHT == "RIGHT"
    assert ACTION_SELECT == "SELECT"
    assert ACTION_BACK == "BACK"


def test_gui_constants():
    """Verifies constant values in constants.py."""
    assert COLOR_BG_BLACK == "#000000"
    assert COLOR_SURFACE_DARK == "#121212"
    assert COLOR_PRIMARY_BLUE == "#2563eb"
    assert THUMB_SIZE_CAPSULE == (180, 270)
    assert GRID_CARD_BANNER_SIZE == (280, 130)


def test_steamgriddb_client_download_image_bytes():
    """Tests download_image_bytes on SteamGridDBClient."""
    client = SteamGridDBClient(api_key="test_key")

    # Empty URL returns None
    assert client.download_image_bytes("") is None

    # Success case
    mock_resp = MagicMock(status_code=200, content=b"fake_image_data")
    with patch.object(client, "_get", return_value=mock_resp):
        data = client.download_image_bytes("https://example.com/art.jpg")
        assert data == b"fake_image_data"

    # HTTP Error case
    mock_err_resp = MagicMock(status_code=404, content=b"")
    with patch.object(client, "_get", return_value=mock_err_resp):
        assert client.download_image_bytes("https://example.com/missing.jpg") is None

    # Exception case
    with patch.object(client, "_get", side_effect=RuntimeError("Network offline")):
        assert client.download_image_bytes("https://example.com/err.jpg") is None


def test_cover_art_manager_download_and_set_specific_asset(tmp_path):
    """Tests download_image_bytes and download_and_set_specific_asset on CoverArtManager."""
    cm = CoverArtManager(cache_dir=tmp_path / "covers")

    # Empty URL
    assert cm.download_image_bytes("") is None

    # Successful download
    mock_resp = MagicMock(status_code=200, content=b"cover_bytes")
    with patch.object(cm, "_get", return_value=mock_resp):
        assert cm.download_image_bytes("https://example.com/cover.jpg") == b"cover_bytes"

    # download_and_set_specific_asset with client
    mock_client = MagicMock()
    mock_client.download_image_bytes.return_value = b"client_bytes"
    with patch.object(cm, "set_specific_grid_asset", return_value=True) as mock_set:
        success = cm.download_and_set_specific_asset(
            app_id="12345",
            asset_type="capsule",
            url="https://example.com/cap.png",
            steamgriddb_client=mock_client,
        )
        assert success is True
        mock_set.assert_called_once_with(
            app_id="12345",
            asset_type="capsule",
            image_bytes=b"client_bytes",
            steam_root=None,
        )


def test_gui_patch_failure_logging(temp_config_dir, mock_steam_structure, mock_patch_repo):
    """Verifies that patch failure logs error with exc_info (H8)."""
    with patch.object(VNPatchManagerApp, "refresh_data"):
        app = VNPatchManagerApp()
    app.withdraw()

    installed_game = {
        "name": "Synthetic VN Test",
        "path": str(mock_steam_structure["game1"]["path"]),
        "is_installed": True,
    }
    patch_data = mock_patch_repo["patch1_manifest"]

    with patch.object(PatchExecutionEngine, "apply_patch", side_effect=RuntimeError("Disk I/O error")), \
         patch("vnpatchmanager.gui.app_window.logger.error") as mock_log:
        app.run_patch(installed_game, patch_data)
        time.sleep(0.1)
        app.update()

        # Check logger.error was called with exc_info=True
        mock_log.assert_called_with("Patch task failed", exc_info=True)
        assert "Patch Failed" in app.lbl_status.cget("text")

    app.destroy()


def test_gui_run_remove_non_steam_threaded():
    """Verifies that run_remove_non_steam executes via background worker (H9)."""
    with patch.object(VNPatchManagerApp, "refresh_data"):
        app = VNPatchManagerApp()
    app.withdraw()

    mock_game = {"name": "Test VN", "is_installed": True, "is_non_steam": True}

    with patch("tkinter.messagebox.askyesno", return_value=True), \
         patch.object(app.non_steam_manager, "remove_non_steam_game", return_value=(True, "Shortcut removed")) as mock_remove:
        app.run_remove_non_steam("99999", mock_game)
        time.sleep(0.1)
        app.update()
        mock_remove.assert_called_once_with(app_name="Test VN", appid_32=99999)

    app.destroy()
