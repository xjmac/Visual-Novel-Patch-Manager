"""
Unit tests for GUI modal dialogs: Non-Steam Registration Modal and Artwork Browser Modal.
"""

import time
from unittest.mock import patch
import pytest

from vnpatchmanager.gui import (
    VNPatchManagerApp,
    ACTION_UP,
    ACTION_DOWN,
    ACTION_LEFT,
    ACTION_RIGHT,
    ACTION_PREV_TAB,
    ACTION_NEXT_TAB,
)
from vnpatchmanager.gui.modals.non_steam_modal import show_add_non_steam_modal
from vnpatchmanager.gui.modals.artwork_browser import show_artwork_browser_modal


@pytest.fixture
def mock_app(temp_config_dir):
    with patch.object(VNPatchManagerApp, "refresh_data"):
        app = VNPatchManagerApp()
    app.withdraw()
    yield app
    try:
        app.destroy()
    except Exception:
        pass


def test_show_add_non_steam_modal_lifecycle(mock_app, tmp_path):
    """Tests opening the Add Non-Steam Modal, updating fields, searching VNDB, and registering."""
    modal = show_add_non_steam_modal(mock_app)
    assert modal is not None
    mock_app.update()

    # Find widgets inside modal
    entry_path = modal._entry_path
    entry_title = modal._entry_title
    lbl_matched_meta = modal._lbl_matched_meta

    # Test path setting via browse
    test_exe = tmp_path / "Clannad" / "Clannad.exe"
    test_exe.parent.mkdir(parents=True)
    test_exe.write_text("binary")

    with patch("tkinter.filedialog.askdirectory", return_value=""), \
         patch("tkinter.filedialog.askopenfilename", return_value=str(test_exe)):
        modal._on_browse()
        assert entry_path.get() == str(test_exe)
        assert entry_title.get().lower() == "clannad"

    # Test typing new title
    entry_title.delete(0, "end")
    entry_title.insert(0, "Clannad HD")
    mock_vn = {
        "vn_id": "v4",
        "title": "CLANNAD",
        "developer": "Key",
        "rating": 8.7,
        "image_url": "https://example.com/clannad.jpg",
    }
    with patch.object(mock_app.non_steam_manager, "match_vn_metadata", return_value=mock_vn):
        entry_title.event_generate("<KeyRelease>")
        mock_app.update()
        assert "CLANNAD" in lbl_matched_meta.cget("text")

    # Test controller navigation in modal
    handler = modal._controller_handler
    assert handler is not None
    handler(ACTION_DOWN)
    handler(ACTION_UP)
    handler(ACTION_LEFT)
    handler(ACTION_RIGHT)

    # Test register execution
    with patch.object(mock_app.non_steam_manager, "register_non_steam_game", return_value=(True, "Success", 12345)) as mock_reg, \
         patch.object(mock_app, "refresh_data") as mock_refresh:
        modal._on_register()
        time.sleep(0.1)
        mock_app.update()
        mock_reg.assert_called_once()
        mock_refresh.assert_called_once()

    # Test close/back
    if modal.winfo_exists():
        modal._close_add_modal()
        mock_app.update()


def test_show_artwork_browser_modal_lifecycle(mock_app, tmp_path):
    """Tests opening the Artwork Browser Modal, tab switching, and asset downloading."""
    game_data = {
        "name": "Fate/Stay Night",
        "path": "/games/fate",
        "is_installed": True,
        "is_non_steam": False,
    }

    import io
    from PIL import Image
    img_io = io.BytesIO()
    Image.new("RGB", (10, 10), color="blue").save(img_io, format="PNG")
    real_png_bytes = img_io.getvalue()

    mock_client = mock_app.steamgriddb_client
    with patch.object(mock_client, "has_api_key", return_value=True), \
         patch.object(mock_client, "get_game_by_steam_appid", return_value=100), \
         patch.object(mock_client, "search_games", return_value=[{"id": 100, "name": "Fate/Stay Night"}]), \
         patch.object(mock_client, "get_assets", return_value=[{"id": 1, "url": "https://example.com/thumb1.jpg", "thumb": "https://example.com/thumb1.jpg", "width": 600, "height": 900}]), \
         patch.object(mock_client, "get_fallback_assets", return_value=[]), \
         patch.object(mock_client, "download_image_bytes", return_value=real_png_bytes):

        modal = show_artwork_browser_modal(mock_app, "12345", game_data)
        assert modal is not None
        time.sleep(0.1)
        mock_app.update()

        handler = modal._controller_handler
        assert handler is not None
        handler(ACTION_NEXT_TAB)
        mock_app.update()
        handler(ACTION_PREV_TAB)
        mock_app.update()
        handler(ACTION_DOWN)
        handler(ACTION_UP)

        # Test tab change
        modal._set_tab("wide")
        mock_app.update()
        modal._set_tab("capsule")
        mock_app.update()

        # Test apply selected asset
        with patch.object(mock_app.cover_manager, "download_and_set_specific_asset", return_value=True) as mock_set:
            modal._apply_selected_asset("https://example.com/thumb1.jpg", "capsule")
            time.sleep(0.1)
            mock_app.update()
            mock_set.assert_called_once()

        # Test local file upload
        local_img = tmp_path / "custom.png"
        local_img.write_bytes(real_png_bytes)
        with patch("tkinter.filedialog.askopenfilename", return_value=str(local_img)), \
             patch.object(mock_app.cover_manager, "set_specific_grid_asset", return_value=True) as mock_local_set:
            modal._on_local_file_upload()
            mock_local_set.assert_called_once()

        if modal.winfo_exists():
            modal._close_modal()
            mock_app.update()
