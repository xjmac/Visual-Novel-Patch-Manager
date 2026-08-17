import time
import pytest
from unittest.mock import patch, MagicMock
import customtkinter as ctk
from vnpatchmanager import VNPatchManagerApp, PatchExecutionEngine, SteamScanner, PatchRepository, BackupManager


@pytest.fixture
def app_instance(temp_config_dir, mock_steam_structure, mock_patch_repo):
    """Instantiates VNPatchManagerApp with harmless initial setup."""
    orig_refresh = VNPatchManagerApp.refresh_data
    with patch.object(VNPatchManagerApp, "refresh_data"):
        app = VNPatchManagerApp()
    # Restore real refresh_data method on the app instance
    app.refresh_data = orig_refresh.__get__(app, VNPatchManagerApp)
    app.withdraw()
    yield app
    try:
        app.destroy()
    except Exception:
        pass


def test_app_init_and_layout(app_instance):
    assert app_instance.tabview is not None
    assert app_instance.tab_games is not None
    assert app_instance.tab_settings is not None
    assert app_instance.config_manager is not None
    assert app_instance.steam_scanner is not None
    assert app_instance.repo is not None
    assert app_instance.cover_manager is not None
    assert app_instance.progress_bar is not None


def test_steam_deck_screen_aware_geometry(app_instance):
    # Tests that the application properly initializes with compact handheld/deck minimum dimensions
    assert app_instance._min_width in (760, 800)
    assert app_instance._min_height in (480, 520)


def test_toggle_settings_fields(app_instance):
    from vnpatchmanager.gui import MODE_LOCAL_DISPLAY, MODE_SMB_DISPLAY
    # Test local mode: frame_local is visible, frame_smb is hidden
    app_instance._toggle_settings_fields("local")
    app_instance._toggle_settings_fields(MODE_SMB_DISPLAY)
    app_instance._toggle_settings_fields(MODE_LOCAL_DISPLAY)


def test_browse_local_path(app_instance):
    from unittest.mock import patch

    with patch("tkinter.filedialog.askdirectory", return_value="/selected/custom/path"):
        app_instance._browse_local_path()
        assert app_instance.entry_local_path.get() == "/selected/custom/path"

    # User cancels dialog -> path unchanged
    with patch("tkinter.filedialog.askdirectory", return_value=""):
        app_instance._browse_local_path()
        assert app_instance.entry_local_path.get() == "/selected/custom/path"


def test_save_settings(app_instance, temp_config_dir):
    cfg_dir, cfg_file = temp_config_dir

    app_instance.var_mode.set("🌐 Network Share (NAS)")
    app_instance.entry_local_path.delete(0, "end")
    app_instance.entry_local_path.insert(0, "/custom/local/path")

    app_instance.smb_entries["smb_server"].delete(0, "end")
    app_instance.smb_entries["smb_server"].insert(0, "192.168.99.1")

    with patch.object(app_instance, "refresh_data") as mock_refresh:
        app_instance.save_settings()
        mock_refresh.assert_called_once()

    assert app_instance.config_manager.config["mode"] == "smb"
    assert app_instance.config_manager.config["local_path"] == "/custom/local/path"
    assert app_instance.config_manager.config["smb_server"] == "192.168.99.1"
    assert cfg_file.exists()
    assert "v0.1." in app_instance.lbl_version.cget("text")


def test_refresh_data_filtering(app_instance, mock_steam_structure, mock_patch_repo):
    owned_games = {
        "900001": {
            "name": "Synthetic VN Alpha",
            "path": mock_steam_structure["game1"]["path"],
            "library_path": mock_steam_structure["game1"]["library_path"],
            "is_installed": True
        },
        "900002": {
            "name": "Synthetic VN Beta",
            "path": mock_steam_structure["game2"]["path"],
            "library_path": mock_steam_structure["game2"]["library_path"],
            "is_installed": True
        },
        "905555": {
            "name": "Steam App #905555",
            "path": "",
            "library_path": "",
            "is_installed": False
        },
        "907777": {
            "name": "Synthetic Passion (No 18+ Patch Required)",
            "path": "",
            "library_path": "",
            "is_installed": False
        },
        "909999": {
            "name": "Unrelated Non-VN Game",
            "path": "",
            "library_path": "",
            "is_installed": False
        }
    }
    available_patches = {
        "900001": mock_patch_repo["patch1_manifest"],
        "900002": mock_patch_repo["patch2_manifest"],
        "900003": mock_patch_repo["patch3_manifest"] # Game not installed
    }

    app_instance.steam_scanner.get_owned_games = MagicMock(return_value=owned_games)
    app_instance.steam_scanner.get_installed_games = MagicMock(return_value=owned_games)
    app_instance.repo.refresh_patches = MagicMock()
    app_instance.repo.available_patches = available_patches
    app_instance.cover_manager.download_cover = MagicMock(return_value=True)
    mock_vndb_data = {
        "900001": {"is_vn": True, "vn_id": "v90001", "vn_title": "Synthetic VN Alpha", "has_18plus_en_patch": False},
        "900002": {"is_vn": True, "vn_id": "v90002", "vn_title": "Synthetic VN Beta", "has_18plus_en_patch": False},
        "905555": {"is_vn": True, "vn_id": "v90555", "vn_title": "Synthetic Uninstalled VN", "has_18plus_en_patch": True},
        "907777": {"is_vn": True, "vn_id": "v90777", "vn_title": "Synthetic Passion", "has_18plus_en_patch": False}
    }
    app_instance.vndb_scanner.get_cached_vns = MagicMock(return_value=mock_vndb_data)
    app_instance.vndb_scanner.check_app_ids = MagicMock(return_value=mock_vndb_data)
    app_instance.vndb_scanner.sync_vndb_snapshot = MagicMock(return_value=True)

    # Synchronous thread runner to execute thread target immediately
    def sync_thread(target, daemon=None):
        target()
        mock_thread = MagicMock()
        return mock_thread

    with patch("vnpatchmanager.gui.threading.Thread", side_effect=sync_thread):
        app_instance.refresh_data()

        filtered = app_instance._all_supported_games

        # 900001, 900002 (in repo) and 905555 (18+ patch on VNDB, uninstalled) should be present
        assert "900001" in filtered
        assert "900002" in filtered
        assert "905555" in filtered
        assert filtered["905555"]["name"] == "Synthetic Uninstalled VN"

        # 907777 (VN without 18+ patch), 909999 (not VN), and 900003 (not installed) MUST NOT be present
        assert "907777" not in filtered
        assert "909999" not in filtered
        assert "900003" not in filtered


def test_refresh_data_strictly_excludes_natively_adult_and_non_patch_games(app_instance, tmp_path):
    # Game with generic 'patch' file
    generic_dir = tmp_path / "SyntheticGeneric"
    generic_dir.mkdir()
    (generic_dir / "patch").write_text("dummy")

    # Game with assets.rpa but natively 18+
    native_dir = tmp_path / "SyntheticNativeAdult"
    native_dir.mkdir()
    (native_dir / "game").mkdir()
    (native_dir / "game" / "assets.rpa").write_bytes(b"rpa data")

    owned = {
        "906440": {"name": "Synthetic Generic Game", "path": generic_dir, "is_installed": True},
        "901770": {"name": "Synthetic Natively Adult VN", "path": native_dir, "is_installed": True}
    }
    app_instance.steam_scanner.get_owned_games = MagicMock(return_value=owned)
    app_instance.steam_scanner.get_installed_games = MagicMock(return_value=owned)
    app_instance.repo.available_patches = {}
    app_instance.vndb_scanner.get_cached_vns = MagicMock(return_value={
        "906440": {"is_vn": False, "has_18plus_en_patch": False},
        "901770": {"is_vn": True, "has_18plus_en_patch": False}
    })
    app_instance.vndb_scanner.sync_vndb_snapshot = MagicMock(return_value=True)

    def sync_thread(target, daemon=None):
        target()
        return MagicMock()

    with patch("vnpatchmanager.gui.threading.Thread", side_effect=sync_thread):
        app_instance.refresh_data()
        assert "906440" not in app_instance._all_supported_games
        assert "901770" not in app_instance._all_supported_games


def test_populate_game_list_empty(app_instance):
    app_instance._populate_game_list({})
    assert "No patchable visual novels found" in app_instance.lbl_status.cget("text")


def test_populate_game_list_with_items_grid(app_instance, mock_steam_structure, mock_patch_repo):
    filtered_games = {
        "900001": {
            "name": "Synthetic VN Alpha",
            "path": mock_steam_structure["game1"]["path"],
            "library_path": mock_steam_structure["game1"]["library_path"]
        },
        "900002": {
            "name": "Synthetic VN Beta",
            "path": mock_steam_structure["game2"]["path"],
            "library_path": mock_steam_structure["game2"]["library_path"]
        }
    }

    # Mark Game 1 as having a repo patch, patched, and backed up
    app_instance.repo.available_patches = {"900001": mock_patch_repo["patch1_manifest"]}
    (mock_steam_structure["game1"]["path"] / ".patch_applied.json").write_text("{}")
    BackupManager.create_backup(mock_steam_structure["game1"]["path"], "900001", "Synthetic VN Alpha")

    app_instance.view_var.set("Grid")
    app_instance._populate_game_list(filtered_games)
    assert "Showing 2 of 2 Visual Novel(s)" in app_instance.lbl_status.cget("text")
    assert "2 Patchable VNs" in app_instance.lbl_stats.cget("text")

    # 2 Hero cards in scrollable_games
    cards = app_instance.scrollable_games.winfo_children()
    assert len(cards) == 2

    # Find all buttons recursively across cards
    def find_buttons(widget):
        btns = []
        for child in widget.winfo_children():
            if isinstance(child, ctk.CTkButton):
                btns.append(child)
            btns.extend(find_buttons(child))
        return btns

    all_buttons = []
    for c in cards:
        all_buttons.extend(find_buttons(c))
    all_texts = [b.cget("text") for b in all_buttons]
    assert any("Verify / Re-apply" in t for t in all_texts)
    assert any("Restore (Backup)" in t for t in all_texts)
    assert any("Restore via Steam" in t for t in all_texts)


def test_search_and_status_filtering(app_instance, mock_steam_structure):
    games = {
        "900001": {
            "name": "Synthetic VN Alpha",
            "path": mock_steam_structure["game1"]["path"],
            "library_path": mock_steam_structure["game1"]["library_path"]
        },
        "900002": {
            "name": "Synthetic VN Beta",
            "path": mock_steam_structure["game2"]["path"],
            "library_path": mock_steam_structure["game2"]["library_path"]
        },
        "900003": {
            "name": "Synthetic VN Gamma",
            "path": mock_steam_structure["game2"]["path"],
            "library_path": mock_steam_structure["game2"]["library_path"],
            "vndb": {
                "vn_id": "v90003",
                "has_18plus_en_patch": True,
                "vndb_url": "https://vndb.org/v90003"
            }
        }
    }

    # Mark Game 1 as patched
    (mock_steam_structure["game1"]["path"] / ".patch_applied.json").write_text("{}")
    BackupManager.create_backup(mock_steam_structure["game1"]["path"], "900001", "Synthetic VN Alpha")

    app_instance._populate_game_list(games)
    assert len(app_instance.scrollable_games.winfo_children()) == 3

    # 1. Test search query
    app_instance.search_var.set("alpha")
    app_instance._apply_filters_and_render()
    assert len(app_instance.scrollable_games.winfo_children()) == 1
    assert "Showing 1 of 3" in app_instance.lbl_status.cget("text")

    # 2. Test search no match
    app_instance.search_var.set("nonexistent game")
    app_instance._apply_filters_and_render()
    assert "Filter active: 0 matches" in app_instance.lbl_status.cget("text")

    # Reset search
    app_instance.search_var.set("")
    app_instance._apply_filters_and_render()

    # 3. Test Filter: Patch Available
    app_instance.filter_var.set("Patch Available")
    app_instance._apply_filters_and_render()
    assert len(app_instance.scrollable_games.winfo_children()) == 1

    # 4. Test Filter: Patched
    app_instance.filter_var.set("Patched")
    app_instance._apply_filters_and_render()
    assert len(app_instance.scrollable_games.winfo_children()) == 1

    # 5. Test Filter: Missing 18+ (VNDB)
    app_instance.filter_var.set("Missing 18+ (VNDB)")
    app_instance._apply_filters_and_render()
    assert len(app_instance.scrollable_games.winfo_children()) == 1

    # 6. Test Filter: Backed Up
    app_instance.filter_var.set("Backed Up")
    app_instance._apply_filters_and_render()
    assert len(app_instance.scrollable_games.winfo_children()) == 1


def test_search_debouncing(app_instance):
    with patch.object(app_instance, "after") as mock_after, \
         patch.object(app_instance, "after_cancel") as mock_cancel:
        mock_after.return_value = "job_123"
        app_instance._on_search_changed()
        mock_after.assert_called_once_with(60, app_instance._apply_filters_and_render)

        # Triggering again should cancel the previous job
        app_instance._search_debounce_job = "job_123"
        app_instance._on_search_changed()
        mock_cancel.assert_called_once_with("job_123")


def test_library_sorting_modes(app_instance, mock_steam_structure):
    games = {
        "900300": {
            "name": "Synthetic VN Medium",
            "path": mock_steam_structure["game2"]["path"],
            "library_path": mock_steam_structure["game2"]["library_path"],
            "is_installed": True,
            "vndb": {"rating": 8.6, "votecount": 9000, "has_18plus_en_patch": False}
        },
        "900100": {
            "name": "Synthetic VN Soaring",
            "path": "",
            "library_path": "",
            "is_installed": False,
            "vndb": {"rating": 8.1, "votecount": 4123, "has_18plus_en_patch": True}
        },
        "900200": {
            "name": "Synthetic VN Zenith",
            "path": mock_steam_structure["game1"]["path"],
            "library_path": mock_steam_structure["game1"]["library_path"],
            "is_installed": True,
            "vndb": {"rating": 6.5, "votecount": 120, "has_18plus_en_patch": False}
        }
    }
    app_instance.repo.available_patches = {"900200": {}} # Game 900200 has local patch
    app_instance.view_var.set("List")
    app_instance._all_supported_games = games

    # Helper to extract card titles in rendered order
    def get_rendered_titles():
        cards = app_instance.scrollable_games.winfo_children()
        titles = []
        for c in cards:
            for child in c.winfo_children():
                if isinstance(child, ctk.CTkFrame): # info_frame
                    for sub in child.winfo_children():
                        if isinstance(sub, ctk.CTkLabel) and sub.cget("font").cget("weight") == "bold":
                            titles.append(sub.cget("text"))
        return titles

    # 1. Test Sort: Title (A-Z)
    app_instance.sort_var.set("Title (A-Z)")
    app_instance._apply_filters_and_render()
    assert get_rendered_titles() == ["Synthetic VN Medium", "Synthetic VN Soaring", "Synthetic VN Zenith"]

    # 2. Test Sort: Title (Z-A)
    app_instance.sort_var.set("Title (Z-A)")
    app_instance._apply_filters_and_render()
    assert get_rendered_titles() == ["Synthetic VN Zenith", "Synthetic VN Soaring", "Synthetic VN Medium"]

    # 3. Test Sort: VNDB Rating (Highest First)
    app_instance.sort_var.set("VNDB Rating")
    app_instance._apply_filters_and_render()
    assert get_rendered_titles() == ["Synthetic VN Medium", "Synthetic VN Soaring", "Synthetic VN Zenith"]

    # 4. Test Sort: Status Priority (Available Local Patch -> Missing 18+ VNDB -> Other)
    app_instance.sort_var.set("Status Priority")
    app_instance._apply_filters_and_render()
    assert get_rendered_titles() == ["Synthetic VN Zenith", "Synthetic VN Soaring", "Synthetic VN Medium"]

    # 5. Test Sort: Installed First
    app_instance.sort_var.set("Installed First")
    app_instance._apply_filters_and_render()
    assert get_rendered_titles() == ["Synthetic VN Medium", "Synthetic VN Zenith", "Synthetic VN Soaring"]


def test_vndb_missing_18plus_patch_card_and_link(app_instance, mock_steam_structure):
    games = {
        "900004": {
            "name": "Synthetic VN Delta",
            "path": mock_steam_structure["game2"]["path"],
            "library_path": mock_steam_structure["game2"]["library_path"],
            "vndb": {
                "vn_id": "v90004",
                "vn_title": "Synthetic VN Delta: Wings of Destiny",
                "vndb_url": "https://vndb.org/v90004",
                "has_18plus_en_patch": True
            }
        }
    }

    app_instance.view_var.set("Grid")
    app_instance._populate_game_list(games)

    cards = app_instance.scrollable_games.winfo_children()
    assert len(cards) == 1

    def find_buttons(widget):
        btns = []
        for child in widget.winfo_children():
            if isinstance(child, ctk.CTkButton):
                btns.append(child)
            btns.extend(find_buttons(child))
        return btns

    card_buttons = find_buttons(cards[0])
    vndb_btn = next((b for b in card_buttons if "Open VNDB" in b.cget("text")), None)
    assert vndb_btn is not None

    # Test clicking the button opens the browser
    with patch("webbrowser.open") as mock_open:
        vndb_btn.invoke()
        mock_open.assert_called_once_with("https://vndb.org/v90004")


def test_uninstalled_game_badges_and_actions(app_instance):
    uninstalled_game = {
        "900005": {
            "name": "Synthetic VN Epsilon",
            "path": "",
            "library_path": "",
            "is_installed": False,
            "vndb": {
                "vn_id": "v90005",
                "vn_title": "Synthetic VN Epsilon",
                "vndb_url": "https://vndb.org/v90005",
                "has_18plus_en_patch": True
            }
        }
    }

    app_instance.view_var.set("Grid")
    app_instance._populate_game_list(uninstalled_game)

    cards = app_instance.scrollable_games.winfo_children()
    assert len(cards) == 1

    # Check for "Not Installed" label
    def find_labels(widget):
        lbls = []
        for child in widget.winfo_children():
            if isinstance(child, ctk.CTkLabel):
                lbls.append(child)
            lbls.extend(find_labels(child))
        return lbls

    labels = [l.cget("text") for l in find_labels(cards[0])]
    assert any("Not Installed" in l for l in labels)

    # Test that run_patch on uninstalled game warns and aborts
    with patch("tkinter.messagebox.showwarning") as mock_warn:
        app_instance.run_patch(uninstalled_game["900005"], {})
        mock_warn.assert_called_once()
        assert "Cannot patch" in app_instance.lbl_status.cget("text")

    # Test run_rollback on uninstalled game warns and aborts
    with patch("tkinter.messagebox.showwarning") as mock_warn:
        app_instance.run_rollback(uninstalled_game["900005"])
        mock_warn.assert_called_once()

    # Test run_steam_restore on uninstalled game warns and aborts
    with patch("tkinter.messagebox.showwarning") as mock_warn:
        app_instance.run_steam_restore(uninstalled_game["900005"], {})
        mock_warn.assert_called_once()


def test_view_mode_toggle(app_instance, mock_steam_structure):
    games = {
        "900001": {
            "name": "Synthetic VN Alpha",
            "path": mock_steam_structure["game1"]["path"],
            "library_path": mock_steam_structure["game1"]["library_path"]
        }
    }
    app_instance._populate_game_list(games)

    # Switch to List View
    app_instance.view_var.set("List")
    app_instance._apply_filters_and_render()
    list_rows = app_instance.scrollable_games.winfo_children()
    assert len(list_rows) == 1

    # Switch back to Grid View
    app_instance.view_var.set("Grid")
    app_instance._apply_filters_and_render()
    grid_cards = app_instance.scrollable_games.winfo_children()
    assert len(grid_cards) == 1


def test_run_patch_success(app_instance, mock_steam_structure, mock_patch_repo):
    game_data = {
        "name": "Synthetic VN Alpha",
        "path": mock_steam_structure["game1"]["path"],
        "library_path": mock_steam_structure["game1"]["library_path"]
    }
    patch_data = mock_patch_repo["patch1_manifest"]

    def sync_thread(target, daemon=None):
        target()
        return MagicMock()

    with patch("threading.Thread", side_effect=sync_thread), \
         patch.object(PatchExecutionEngine, "apply_patch", return_value=True) as mock_apply, \
         patch.object(app_instance, "refresh_data") as mock_refresh:
        app_instance.run_patch(game_data, patch_data)
        mock_apply.assert_called_once()


def test_run_patch_failure(app_instance, mock_steam_structure, mock_patch_repo):
    game_data = {
        "name": "Synthetic VN Alpha",
        "path": mock_steam_structure["game1"]["path"],
        "library_path": mock_steam_structure["game1"]["library_path"]
    }
    patch_data = mock_patch_repo["patch1_manifest"]

    def sync_thread(target, daemon=None):
        target()
        return MagicMock()

    with patch("threading.Thread", side_effect=sync_thread), \
         patch.object(PatchExecutionEngine, "apply_patch", side_effect=Exception("Failed patch")):
        app_instance.run_patch(game_data, patch_data)
        app_instance.update()
        assert "Patch Failed" in app_instance.lbl_status.cget("text")


def test_run_rollback_success(app_instance, mock_steam_structure):
    game_data = {
        "name": "Synthetic VN Alpha",
        "path": mock_steam_structure["game1"]["path"],
        "library_path": mock_steam_structure["game1"]["library_path"]
    }

    def sync_thread(target, daemon=None):
        target()
        return MagicMock()

    with patch("threading.Thread", side_effect=sync_thread), \
         patch.object(PatchExecutionEngine, "rollback_patch", return_value=True) as mock_rollback:
        app_instance.run_rollback(game_data)
        mock_rollback.assert_called_once()


def test_run_rollback_failure(app_instance, mock_steam_structure):
    game_data = {
        "name": "Synthetic VN Alpha",
        "path": mock_steam_structure["game1"]["path"],
        "library_path": mock_steam_structure["game1"]["library_path"]
    }

    def sync_thread(target, daemon=None):
        target()
        return MagicMock()

    with patch("threading.Thread", side_effect=sync_thread), \
         patch.object(PatchExecutionEngine, "rollback_patch", side_effect=Exception("Rollback error")):
        app_instance.run_rollback(game_data)
        app_instance.update()
        assert "Rollback Failed" in app_instance.lbl_status.cget("text")


def test_run_steam_restore_success(app_instance, mock_steam_structure):
    game_data = {
        "name": "Synthetic VN Alpha",
        "path": mock_steam_structure["game1"]["path"],
        "library_path": mock_steam_structure["game1"]["library_path"],
        "steam_app_id": "900001"
    }

    def sync_thread(target, daemon=None):
        target()
        return MagicMock()

    with patch("threading.Thread", side_effect=sync_thread), \
         patch.object(PatchExecutionEngine, "restore_via_steam", return_value=True) as mock_steam_restore:
        app_instance.run_steam_restore(game_data, None)
        mock_steam_restore.assert_called_once()


def test_run_steam_restore_failure(app_instance, mock_steam_structure):
    game_data = {
        "name": "Synthetic VN Alpha",
        "path": mock_steam_structure["game1"]["path"],
        "library_path": mock_steam_structure["game1"]["library_path"],
        "steam_app_id": "900001"
    }

    def sync_thread(target, daemon=None):
        target()
        return MagicMock()

    with patch("threading.Thread", side_effect=sync_thread), \
         patch.object(PatchExecutionEngine, "restore_via_steam", side_effect=Exception("Steam error")):
        app_instance.run_steam_restore(game_data, None)
        app_instance.update()
        assert "Steam Restore Failed" in app_instance.lbl_status.cget("text")


def test_ui_button_presence_all_vn_states(app_instance, mock_steam_structure, mock_patch_repo):
    """Regression test ensuring action buttons (Apply, Restore, VNDB Link) are ALWAYS packed across all VN states."""
    app_instance.repo.available_patches = {
        "900001": mock_patch_repo["patch1_manifest"],
        "900002": mock_patch_repo["patch2_manifest"]
    }

    games = {
        # 1. Uninstalled VN with 18+ patch on VNDB
        "900004": {
            "name": "Synthetic VN Delta",
            "path": "",
            "library_path": "",
            "is_installed": False,
            "vndb": {
                "vn_id": "v90004",
                "vn_title": "Synthetic VN Delta: Wings of Destiny",
                "has_18plus_en_patch": True,
                "vndb_url": "https://vndb.org/v90004"
            }
        },
        # 2. Installed VN with patch available locally
        "900001": {
            "name": "Synthetic VN Alpha",
            "path": mock_steam_structure["game1"]["path"],
            "library_path": mock_steam_structure["game1"]["library_path"],
            "is_installed": True,
            "vndb": {"vn_id": "v90001", "has_18plus_en_patch": True}
        },
        # 3. Installed & Patched VN with clean backup
        "900002": {
            "name": "Synthetic VN Beta",
            "path": mock_steam_structure["game2"]["path"],
            "library_path": mock_steam_structure["game2"]["library_path"],
            "is_installed": True,
            "vndb": {"vn_id": "v90002", "has_18plus_en_patch": False}
        }
    }

    # Mark 900002 as patched and create backup
    BackupManager.create_backup(mock_steam_structure["game2"]["path"], "900002", "Synthetic VN Beta")
    (mock_steam_structure["game2"]["path"] / ".patch_applied.json").write_text("{}")

    def find_buttons(widget):
        btns = []
        if isinstance(widget, ctk.CTkButton):
            btns.append(widget)
        for child in widget.winfo_children():
            btns.extend(find_buttons(child))
        return btns

    def get_card_button_map(container):
        result = {}
        for card in container.winfo_children():
            # Find labels to identify card
            title = ""
            for widget in card.winfo_children():
                if isinstance(widget, ctk.CTkFrame):
                    for sub in widget.winfo_children():
                        if isinstance(sub, ctk.CTkLabel) and sub.cget("text") in ("Synthetic VN Delta", "Synthetic VN Alpha", "Synthetic VN Beta"):
                            title = sub.cget("text")
                            break
            if not title:
                for widget in card.winfo_children():
                    if isinstance(widget, ctk.CTkLabel) and widget.cget("text") in ("Synthetic VN Delta", "Synthetic VN Alpha", "Synthetic VN Beta"):
                        title = widget.cget("text")
                        break
            btns = [b.cget("text") for b in find_buttons(card)]
            if title:
                result[title] = btns
        return result

    # --- Test Grid View Button Packing ---
    app_instance.view_var.set("Grid")
    app_instance._populate_game_list(games)
    app_instance.update()

    grid_map = get_card_button_map(app_instance.scrollable_games)
    assert len(grid_map) == 3

    # Check Synthetic VN Delta (Uninstalled with VNDB patch): MUST have "🔗 Open VNDB (Get Patch)" button packed
    assert any("Open VNDB (Get Patch)" in t for t in grid_map["Synthetic VN Delta"])

    # Check Synthetic VN Alpha (Installed with local patch): MUST have "Apply Patch" button packed
    assert any("Apply Patch" in t for t in grid_map["Synthetic VN Alpha"])

    # Check Synthetic VN Beta (Patched with clean backup): MUST have "Verify / Re-apply", "Restore (Backup)", "Restore via Steam"
    beta_btns = grid_map["Synthetic VN Beta"]
    assert any("Verify / Re-apply" in t for t in beta_btns)
    assert any("Restore (Backup)" in t for t in beta_btns)
    assert any("Restore via Steam" in t for t in beta_btns)

    # --- Test List View Button Packing ---
    app_instance.view_var.set("List")
    app_instance._apply_filters_and_render()
    app_instance.update()

    list_map = get_card_button_map(app_instance.scrollable_games)
    assert len(list_map) == 3
    assert any("Open VNDB (Get Patch)" in t for t in list_map["Synthetic VN Delta"])
    assert any("Apply Patch" in t for t in list_map["Synthetic VN Alpha"])


def test_oled_pure_black_theming_and_card_styling(app_instance, mock_steam_structure):
    """Verifies that all GUI containers conform to OLED pure black (#000000) and elevated surface (#121212) standards."""
    games = {
        "900001": {
            "name": "Synthetic VN Alpha",
            "path": mock_steam_structure["game1"]["path"],
            "library_path": mock_steam_structure["game1"]["library_path"],
            "is_installed": True
        }
    }
    app_instance.view_var.set("Grid")
    app_instance._populate_game_list(games)
    app_instance.update()

    # Verify root container & scrollable pure black colors
    assert app_instance.tabview.cget("fg_color") == "#000000"
    assert app_instance.scrollable_games.cget("fg_color") == "#000000"

    # Verify focused card styling (prominent blue border + elevated surface)
    cards = app_instance.scrollable_games.winfo_children()
    assert len(cards) == 1
    card = cards[0]
    assert card.cget("fg_color") == "#1e293b"
    assert card.cget("border_color") == "#3b82f6"
    assert card.cget("border_width") == 3

    # Switch focus to Toolbar -> card returns to unfocused #121212 and #27272a
    app_instance._focused_zone = "TOOLBAR"
    app_instance._apply_focus_visuals()
    assert card.cget("fg_color") == "#121212"
    assert card.cget("border_color") == "#27272a"
    assert card.cget("border_width") == 1


def test_multi_field_search_indexing(app_instance, mock_steam_structure):
    """Verifies in-memory multi-field search against Steam title, VNDB title, Steam AppID, and VNDB ID."""
    games = {
        "900004": {
            "name": "Synthetic VN Delta",
            "path": "",
            "library_path": "",
            "is_installed": False,
            "vndb": {
                "vn_id": "v90004",
                "vn_title": "Synthetic VN Delta: Wings of Destiny",
                "has_18plus_en_patch": True
            }
        },
        "900001": {
            "name": "Synthetic VN Alpha",
            "path": mock_steam_structure["game1"]["path"],
            "library_path": mock_steam_structure["game1"]["library_path"],
            "is_installed": True,
            "vndb": {
                "vn_id": "v90001",
                "vn_title": "Synthetic Visual Novel: Blue Moon",
                "has_18plus_en_patch": False
            }
        }
    }
    app_instance._populate_game_list(games)
    app_instance.update()

    # 1. Search by Steam Title
    app_instance.search_var.set("delta")
    app_instance._apply_filters_and_render()
    assert len(app_instance.scrollable_games.winfo_children()) == 1

    # 2. Search by VNDB Romaji/Alternative Title
    app_instance.search_var.set("destiny")
    app_instance._apply_filters_and_render()
    assert len(app_instance.scrollable_games.winfo_children()) == 1

    # 3. Search by Steam AppID
    app_instance.search_var.set("900004")
    app_instance._apply_filters_and_render()
    assert len(app_instance.scrollable_games.winfo_children()) == 1

    # 4. Search by VNDB ID
    app_instance.search_var.set("v90004")
    app_instance._apply_filters_and_render()
    assert len(app_instance.scrollable_games.winfo_children()) == 1

    # 5. Clear Search
    app_instance.search_var.set("")
    app_instance._apply_filters_and_render()
    assert len(app_instance.scrollable_games.winfo_children()) == 2


def test_controller_card_navigation_and_visual_focus(app_instance, mock_steam_structure):
    games = {
        "900001": {
            "name": "Synthetic VN Alpha",
            "path": mock_steam_structure["game1"]["path"],
            "library_path": mock_steam_structure["game1"]["library_path"],
            "is_installed": True
        },
        "900002": {
            "name": "Synthetic VN Beta",
            "path": mock_steam_structure["game2"]["path"],
            "library_path": mock_steam_structure["game2"]["library_path"],
            "is_installed": True
        }
    }
    app_instance.view_var.set("Grid")
    app_instance._populate_game_list(games)
    app_instance.update()

    # Initial focus should be on card 0
    app_instance._focused_zone = "LIBRARY"
    app_instance._focused_card_idx = 0
    app_instance._focused_btn_idx = -1
    app_instance._apply_focus_visuals()

    assert len(app_instance._card_entries) == 2
    card0 = app_instance._card_entries[0]["card"]
    card1 = app_instance._card_entries[1]["card"]

    # Focused Card 0: Must have 3px bright blue border and elevated surface
    assert card0.cget("border_width") == 3
    assert card0.cget("border_color") == "#3b82f6"
    assert card0.cget("fg_color") == "#1e293b"

    # Unfocused Card 1: Must have 1px dark border
    assert card1.cget("border_width") == 1
    assert card1.cget("border_color") == "#27272a"
    assert card1.cget("fg_color") == "#121212"

    # Move Right -> Focus moves to card 1
    from vnpatchmanager.controller_manager import ACTION_RIGHT, ACTION_LEFT, ACTION_UP, ACTION_DOWN
    app_instance._handle_controller_action(ACTION_RIGHT)
    assert app_instance._focused_card_idx == 1
    assert card1.cget("border_width") == 3
    assert card1.cget("border_color") == "#3b82f6"

    # Move Left -> Returns to card 0
    app_instance._handle_controller_action(ACTION_LEFT)
    assert app_instance._focused_card_idx == 0

    # Move Up from row 0 -> Jumps focus to Toolbar
    app_instance._handle_controller_action(ACTION_UP)
    assert app_instance._focused_zone == "TOOLBAR"
    assert app_instance._search_frame.cget("border_width") == 2
    assert app_instance._search_frame.cget("border_color") == "#3b82f6"


def test_controller_search_bar_osk_trigger(app_instance, mock_steam_structure):
    from vnpatchmanager.controller_manager import ACTION_SEARCH, ACTION_SELECT
    from vnpatchmanager.steamos_helper import SteamOSHelper

    with patch.object(SteamOSHelper, "show_onscreen_keyboard") as mock_osk:
        # Trigger quick search via Y button action
        app_instance._handle_controller_action(ACTION_SEARCH)
        assert app_instance._focused_zone == "TOOLBAR"
        assert app_instance._focused_toolbar_idx == 0
        mock_osk.assert_called_once()


def test_controller_bumper_tab_switching(app_instance):
    from vnpatchmanager.controller_manager import ACTION_NEXT_TAB, ACTION_PREV_TAB

    # L1 / R1 bumper switching
    app_instance._handle_controller_action(ACTION_NEXT_TAB)
    assert app_instance.tabview.get() == "Settings"
    assert app_instance._focused_zone == "SETTINGS"

    app_instance._handle_controller_action(ACTION_PREV_TAB)
    assert app_instance.tabview.get() == "Games Library"
    assert app_instance._focused_zone == "LIBRARY"


def test_controller_quick_action_x_button(app_instance, mock_steam_structure, mock_patch_repo):
    from vnpatchmanager.controller_manager import ACTION_QUICK_ACTION

    app_instance.repo.available_patches = {"900001": mock_patch_repo["patch1_manifest"]}
    games = {
        "900001": {
            "name": "Synthetic VN Alpha",
            "path": mock_steam_structure["game1"]["path"],
            "library_path": mock_steam_structure["game1"]["library_path"],
            "is_installed": True
        }
    }
    app_instance.view_var.set("Grid")
    app_instance._populate_game_list(games)
    app_instance.update()

    with patch.object(app_instance, "run_patch") as mock_run:
        app_instance._handle_controller_action(ACTION_QUICK_ACTION)
        mock_run.assert_called_once()


def test_gui_run_patch_uninstalled_and_execution_flows(app_instance, mock_steam_structure, mock_patch_repo):
    from vnpatchmanager.patch_execution import PatchExecutionEngine

    # 1. Uninstalled Game -> Warning
    uninstalled_game = {"name": "Uninstalled VN", "path": "", "is_installed": False}
    with patch("tkinter.messagebox.showwarning") as mock_warn:
        app_instance.run_patch(uninstalled_game, {})
        mock_warn.assert_called_once()
        assert "Game not installed" in app_instance.lbl_status.cget("text")

    # 2. Installed Game -> Background Thread Success
    installed_game = {
        "name": "Synthetic VN Alpha",
        "path": str(mock_steam_structure["game1"]["path"]),
        "is_installed": True
    }
    patch_data = mock_patch_repo["patch1_manifest"]

    with patch.object(PatchExecutionEngine, "apply_patch") as mock_apply:
        app_instance.run_patch(installed_game, patch_data)
        time.sleep(0.1)
        app_instance.update()
        mock_apply.assert_called_once()

    # 3. Installed Game -> Background Thread Exception
    with patch.object(PatchExecutionEngine, "apply_patch", side_effect=RuntimeError("Disk full")):
        app_instance.run_patch(installed_game, patch_data)
        time.sleep(0.1)
        app_instance.update()
        assert "Patch Failed" in app_instance.lbl_status.cget("text")


def test_gui_run_rollback_uninstalled_and_execution_flows(app_instance, mock_steam_structure):
    from vnpatchmanager.patch_execution import PatchExecutionEngine

    # 1. Uninstalled Game -> Warning
    uninstalled_game = {"name": "Uninstalled VN", "path": "", "is_installed": False}
    with patch("tkinter.messagebox.showwarning") as mock_warn:
        app_instance.run_rollback(uninstalled_game)
        mock_warn.assert_called_once()

    # 2. Installed Game -> Success
    installed_game = {
        "name": "Synthetic VN Alpha",
        "path": str(mock_steam_structure["game1"]["path"]),
        "is_installed": True
    }
    with patch.object(PatchExecutionEngine, "rollback_patch") as mock_rb:
        app_instance.run_rollback(installed_game)
        time.sleep(0.1)
        app_instance.update()
        mock_rb.assert_called_once()

    # 3. Installed Game -> Exception
    with patch.object(PatchExecutionEngine, "rollback_patch", side_effect=RuntimeError("Rollback error")):
        app_instance.run_rollback(installed_game)
        time.sleep(0.1)
        app_instance.update()
        assert "Rollback Failed" in app_instance.lbl_status.cget("text")


def test_gui_run_steam_restore_uninstalled_and_execution_flows(app_instance, mock_steam_structure):
    from vnpatchmanager.patch_execution import PatchExecutionEngine

    # 1. Uninstalled Game -> Warning
    uninstalled_game = {"name": "Uninstalled VN", "path": "", "is_installed": False}
    with patch("tkinter.messagebox.showwarning") as mock_warn:
        app_instance.run_steam_restore(uninstalled_game, {})
        mock_warn.assert_called_once()

    # 2. Installed Game -> Success
    installed_game = {
        "name": "Synthetic VN Alpha",
        "path": str(mock_steam_structure["game1"]["path"]),
        "is_installed": True
    }
    with patch.object(PatchExecutionEngine, "restore_via_steam") as mock_sr:
        app_instance.run_steam_restore(installed_game, {})
        time.sleep(0.1)
        app_instance.update()
        mock_sr.assert_called_once()

    # 3. Installed Game -> Exception
    with patch.object(PatchExecutionEngine, "restore_via_steam", side_effect=RuntimeError("Steam API failed")):
        app_instance.run_steam_restore(installed_game, {})
        time.sleep(0.1)
        app_instance.update()
        assert "Steam Restore Failed" in app_instance.lbl_status.cget("text")


def test_gui_settings_tab_toggle_and_save(app_instance, tmp_path):
    # Test toggling between local and smb modes
    app_instance._toggle_settings_fields("smb")
    app_instance.var_mode.set("smb")
    app_instance.entry_local_path.delete(0, "end")
    app_instance.entry_local_path.insert(0, str(tmp_path / "custom_patches"))
    app_instance.smb_entries["smb_server"].delete(0, "end")
    app_instance.smb_entries["smb_server"].insert(0, "192.168.1.200")

    with patch.object(app_instance, "refresh_data"):
        app_instance.save_settings()
        assert app_instance.config_manager.config["mode"] == "smb"
        assert app_instance.config_manager.config["smb_server"] == "192.168.1.200"

    app_instance._toggle_settings_fields("local")
    app_instance.var_mode.set("local")
    with patch.object(app_instance, "refresh_data"):
        app_instance.save_settings()
        assert app_instance.config_manager.config["mode"] == "local"


def test_gui_controller_toolbar_and_button_navigation(app_instance, mock_steam_structure, mock_patch_repo):
    from vnpatchmanager.controller_manager import (
        ACTION_LEFT,
        ACTION_RIGHT,
        ACTION_UP,
        ACTION_DOWN,
        ACTION_SELECT,
        ACTION_BACK,
        ACTION_SCROLL_UP,
        ACTION_SCROLL_DOWN
    )

    app_instance.repo.available_patches = {"900001": mock_patch_repo["patch1_manifest"]}
    games = {
        "900001": {
            "name": "Synthetic VN Alpha",
            "path": mock_steam_structure["game1"]["path"],
            "library_path": mock_steam_structure["game1"]["library_path"],
            "is_installed": True
        }
    }
    app_instance.view_var.set("List")
    app_instance._populate_game_list(games)
    app_instance.update()

    # Fast Scroll test
    app_instance._handle_controller_action(ACTION_SCROLL_UP)
    app_instance._handle_controller_action(ACTION_SCROLL_DOWN)

    # 1. Start in Toolbar
    app_instance._focused_zone = "TOOLBAR"
    app_instance._focused_toolbar_idx = 0
    app_instance._apply_focus_visuals()

    # Toolbar Right traversal
    app_instance._handle_controller_action(ACTION_RIGHT)
    assert app_instance._focused_toolbar_idx == 1
    app_instance._handle_controller_action(ACTION_LEFT)
    assert app_instance._focused_toolbar_idx == 0

    # Down into Library
    app_instance._handle_controller_action(ACTION_DOWN)
    assert app_instance._focused_zone == "LIBRARY"
    assert app_instance._focused_card_idx == 0
    assert app_instance._focused_btn_idx == -1

    # Press A (SELECT) to enter Action Mode on the card's buttons
    app_instance._handle_controller_action(ACTION_SELECT)
    assert app_instance._focused_btn_idx == 0

    # Select active button with A
    with patch.object(app_instance, "run_patch") as mock_p:
        app_instance._handle_controller_action(ACTION_SELECT)
        mock_p.assert_called_once()

    # Press B (BACK) to return to card browsing level
    app_instance._handle_controller_action(ACTION_BACK)
    assert app_instance._focused_btn_idx == -1


def test_gui_controller_grid_multi_card_navigation(app_instance, mock_steam_structure, mock_patch_repo):
    from vnpatchmanager.controller_manager import (
        ACTION_LEFT,
        ACTION_RIGHT,
        ACTION_UP,
        ACTION_DOWN,
        ACTION_SELECT,
        ACTION_BACK
    )

    app_instance.repo.available_patches = {
        "900001": mock_patch_repo["patch1_manifest"],
        "900002": mock_patch_repo["patch2_manifest"],
        "900003": mock_patch_repo["patch3_manifest"]
    }
    games = {
        "900001": {"name": "Synthetic VN Alpha", "path": mock_steam_structure["game1"]["path"], "library_path": mock_steam_structure["game1"]["library_path"], "is_installed": True},
        "900002": {"name": "Synthetic VN Beta", "path": mock_steam_structure["game2"]["path"], "library_path": mock_steam_structure["game2"]["library_path"], "is_installed": True},
        "900003": {"name": "Synthetic VN Gamma", "path": mock_steam_structure["game1"]["path"], "library_path": mock_steam_structure["game1"]["library_path"], "is_installed": True},
        "900004": {"name": "Synthetic VN Delta", "path": mock_steam_structure["game2"]["path"], "library_path": mock_steam_structure["game2"]["library_path"], "is_installed": True}
    }
    app_instance.view_var.set("Grid")
    app_instance._populate_game_list(games)
    app_instance.update()

    # 1. Start at card 0
    app_instance._focused_zone = "LIBRARY"
    app_instance._focused_card_idx = 0
    app_instance._focused_btn_idx = -1
    app_instance._apply_focus_visuals()

    # Move right to card 1
    app_instance._handle_controller_action(ACTION_RIGHT)
    assert app_instance._focused_card_idx == 1

    # Single-press DOWN moves directly to card 3 (row 1, col 1)
    app_instance._handle_controller_action(ACTION_DOWN)
    assert app_instance._focused_card_idx == 3
    assert app_instance._focused_btn_idx == -1

    # Single-press UP moves back to card 1
    app_instance._handle_controller_action(ACTION_UP)
    assert app_instance._focused_card_idx == 1

    # Move up from card 1 to Toolbar
    app_instance._handle_controller_action(ACTION_UP)
    assert app_instance._focused_zone == "TOOLBAR"


def test_gui_refresh_banner_and_search_handlers(app_instance, mock_steam_structure):
    games = {
        "900001": {"name": "Synthetic VN Alpha", "path": mock_steam_structure["game1"]["path"], "library_path": mock_steam_structure["game1"]["library_path"], "is_installed": True}
    }
    app_instance._populate_game_list(games)
    app_instance.update()

    # 1. Test _refresh_banner
    app_instance._refresh_banner("900001")

    # 2. Test search focus and submit handlers
    with patch("vnpatchmanager.steamos_helper.SteamOSHelper.show_onscreen_keyboard") as mock_show:
        app_instance._on_search_focused()
        assert app_instance._focused_zone == "TOOLBAR"
        assert app_instance._focused_toolbar_idx == 0
        mock_show.assert_called_once()

    with patch("vnpatchmanager.steamos_helper.SteamOSHelper.hide_onscreen_keyboard") as mock_hide:
        app_instance._on_search_submit()
        assert app_instance._focused_zone == "LIBRARY"
        mock_hide.assert_called_once()


def test_gui_destroy_and_refresh_error_handling(app_instance):
    # Test destroy stopping controller manager
    app_instance.destroy()
    assert app_instance.controller_manager._running is False


def test_gui_controller_filter_and_sort_selection(app_instance, mock_steam_structure):
    from vnpatchmanager.controller_manager import (
        ACTION_LEFT,
        ACTION_RIGHT,
        ACTION_SELECT
    )

    games = {
        "900001": {"name": "Synthetic VN Alpha", "path": mock_steam_structure["game1"]["path"], "library_path": mock_steam_structure["game1"]["library_path"], "is_installed": True}
    }
    app_instance._populate_game_list(games)
    app_instance.update()

    # 1. Focus on Filter (Toolbar idx 1)
    app_instance._focused_zone = "TOOLBAR"
    app_instance._focused_toolbar_idx = 1
    app_instance._apply_focus_visuals()

    # Verify visual focus outline on filter
    assert app_instance._filter_frame.cget("border_width") == 2
    assert app_instance._filter_frame.cget("border_color") == "#3b82f6"

    # Press A (SELECT) to cycle filter: "All" -> "Patch Available"
    assert app_instance.filter_var.get() == "All"
    app_instance._handle_controller_action(ACTION_SELECT)
    assert app_instance.filter_var.get() == "Patch Available"

    # Press A (SELECT) again -> "Patched"
    app_instance._handle_controller_action(ACTION_SELECT)
    assert app_instance.filter_var.get() == "Patched"

    # 2. Move Right to Sort (Toolbar idx 2)
    app_instance._handle_controller_action(ACTION_RIGHT)
    assert app_instance._focused_toolbar_idx == 2
    assert app_instance._sort_frame.cget("border_width") == 2
    assert app_instance._sort_frame.cget("border_color") == "#3b82f6"

    # Press A (SELECT) to cycle sort
    assert app_instance.sort_var.get() == "Title (A-Z)"
    app_instance._handle_controller_action(ACTION_SELECT)
    assert app_instance.sort_var.get() == "Title (Z-A)"

    # 3. Move Right to View Mode (Toolbar idx 3)
    app_instance._handle_controller_action(ACTION_RIGHT)
    assert app_instance._focused_toolbar_idx == 3
    assert app_instance._view_frame.cget("border_width") == 2
    assert app_instance._view_frame.cget("border_color") == "#3b82f6"

    # Press A (SELECT) to toggle view mode
    assert app_instance.view_var.get() == "Grid"
    app_instance._handle_controller_action(ACTION_SELECT)
    assert app_instance.view_var.get() == "List"


def test_gui_controller_tab_bar_spatial_navigation(app_instance, mock_steam_structure):
    from vnpatchmanager.controller_manager import (
        ACTION_LEFT,
        ACTION_RIGHT,
        ACTION_UP,
        ACTION_DOWN,
        ACTION_SELECT,
        ACTION_BACK
    )

    games = {
        "900001": {"name": "Synthetic VN Alpha", "path": mock_steam_structure["game1"]["path"], "library_path": mock_steam_structure["game1"]["library_path"], "is_installed": True}
    }
    app_instance._populate_game_list(games)
    app_instance.update()

    # 1. Start on Search in Toolbar
    app_instance._focused_zone = "TOOLBAR"
    app_instance._focused_toolbar_idx = 0
    app_instance._apply_focus_visuals()

    # Move UP into TABS zone
    app_instance._handle_controller_action(ACTION_UP)
    assert app_instance._focused_zone == "TABS"
    assert app_instance._focused_tab_idx == 0
    assert app_instance.tabview.get() == "Games Library"
    assert app_instance.tabview.cget("border_width") == 2
    assert app_instance.tabview.cget("border_color") == "#3b82f6"

    # Press RIGHT in TABS -> switches to Settings tab
    app_instance._handle_controller_action(ACTION_RIGHT)
    assert app_instance._focused_tab_idx == 1
    assert app_instance.tabview.get() == "Settings"

    # Press LEFT in TABS -> switches back to Games Library
    app_instance._handle_controller_action(ACTION_LEFT)
    assert app_instance._focused_tab_idx == 0
    assert app_instance.tabview.get() == "Games Library"

    # Press DOWN from TABS -> enters Toolbar Search
    app_instance._handle_controller_action(ACTION_DOWN)
    assert app_instance._focused_zone == "TOOLBAR"
    assert app_instance._focused_toolbar_idx == 0
    assert app_instance.tabview.cget("border_width") == 1

    # Move UP again into TABS, switch to Settings, and press DOWN into Settings
    app_instance._handle_controller_action(ACTION_UP)
    app_instance._handle_controller_action(ACTION_RIGHT)
    assert app_instance.tabview.get() == "Settings"
    app_instance._handle_controller_action(ACTION_DOWN)
    assert app_instance._focused_zone == "SETTINGS"

    # In Settings, press UP -> returns to TABS on Settings tab
    app_instance._handle_controller_action(ACTION_UP)
    assert app_instance._focused_zone == "TABS"
    assert app_instance._focused_tab_idx == 1

    # In Settings, toggle mode left/right
    from vnpatchmanager.gui import MODE_LOCAL_DISPLAY, MODE_SMB_DISPLAY
    app_instance._handle_controller_action(ACTION_DOWN)
    app_instance._handle_controller_action(ACTION_RIGHT)
    assert app_instance.var_mode.get() == MODE_SMB_DISPLAY
    app_instance._handle_controller_action(ACTION_LEFT)
    assert app_instance.var_mode.get() == MODE_LOCAL_DISPLAY

    # In Settings, press BACK -> returns to Games Library
    app_instance._handle_controller_action(ACTION_BACK)
    assert app_instance.tabview.get() == "Games Library"
    assert app_instance._focused_zone == "LIBRARY"


def test_gui_controller_header_scan_button_navigation(app_instance):
    from unittest.mock import patch
    from vnpatchmanager.controller_manager import (
        ACTION_LEFT,
        ACTION_RIGHT,
        ACTION_UP,
        ACTION_DOWN,
        ACTION_SELECT,
        ACTION_BACK
    )

    # 1. Start in TABS zone on Games Library
    app_instance._focused_zone = "TABS"
    app_instance._focused_tab_idx = 0
    app_instance._apply_focus_visuals()

    # Move UP into HEADER (Scan Games & Patches button)
    app_instance._handle_controller_action(ACTION_UP)
    assert app_instance._focused_zone == "HEADER"
    assert app_instance.btn_refresh.cget("border_width") == 2
    assert app_instance.btn_refresh.cget("border_color") == "#60a5fa"

    # Press A (SELECT) in HEADER -> triggers refresh_data
    with patch.object(app_instance, "refresh_data") as mock_refresh:
        app_instance._handle_controller_action(ACTION_SELECT)
        mock_refresh.assert_called_once()

    # Press LEFT in HEADER -> moves from Scan button (idx 1) to Add Non-Steam button (idx 0)
    app_instance._handle_controller_action(ACTION_LEFT)
    assert app_instance._focused_zone == "HEADER"
    assert app_instance._focused_header_idx == 0
    assert app_instance.btn_add_non_steam.cget("border_width") == 2

    # Press LEFT again in HEADER -> returns to TABS
    app_instance._handle_controller_action(ACTION_LEFT)
    assert app_instance._focused_zone == "TABS"
    assert app_instance.btn_refresh.cget("border_width") == 0

    # In TABS, move RIGHT to Settings, then RIGHT again into HEADER
    app_instance._handle_controller_action(ACTION_RIGHT)
    assert app_instance._focused_tab_idx == 1
    app_instance._handle_controller_action(ACTION_RIGHT)
    assert app_instance._focused_zone == "HEADER"

    # In HEADER, press DOWN -> drops into SETTINGS
    app_instance._handle_controller_action(ACTION_DOWN)
    assert app_instance._focused_zone == "SETTINGS"


def test_placeholder_steam_app_name_resolution(app_instance):
    """Verifies that uninstalled or local patch games with 'Steam App #xxxx' names resolve to canonical titles."""
    synthetic_game = {
        "name": "Steam App #990001",
        "path": "",
        "library_path": "",
        "is_installed": False,
        "vndb": {
            "vn_id": "v99999",
            "vn_title": "Synthetic Mystery Novel",
            "is_vn": True,
            "has_18plus_en_patch": True,
            "rating": 8.5
        }
    }

    # Verify status info resolution
    status_info = app_instance._compute_status_info("990001", synthetic_game)
    assert synthetic_game["name"] == "Synthetic Mystery Novel"
    assert "synthetic mystery novel" in status_info["search_haystack"]

    # Test patch repository game_name fallback when vndb title is missing
    synthetic_patch_game = {
        "name": "Steam App #990002",
        "path": "",
        "library_path": "",
        "is_installed": False,
        "vndb": {}
    }
    app_instance.repo.available_patches["990002"] = {
        "steam_app_id": "990002",
        "game_name": "Synthetic Fantasy Chronicle"
    }
    status_info_2 = app_instance._compute_status_info("990002", synthetic_patch_game)
    assert synthetic_patch_game["name"] == "Synthetic Fantasy Chronicle"
    assert "synthetic fantasy chronicle" in status_info_2["search_haystack"]







