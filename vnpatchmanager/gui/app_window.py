"""
Main application window shell and service lifecycle coordinator for VNPM.
"""

import logging
import queue
import threading
from pathlib import Path
from tkinter import messagebox
from PIL import Image, ImageTk

try:
    import customtkinter as ctk
except ImportError:
    class _FallbackCTk:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("customtkinter is required to instantiate VNPatchManagerApp GUI")
    ctk = type("ctk", (), {"CTk": _FallbackCTk})

from ..backup_manager import BackupManager
from ..codec_fixer import CodecFixer
from ..config_manager import ConfigManager
from ..controller_manager import GamepadControllerManager
from ..cover_art_manager import CoverArtManager
from ..non_steam_manager import NonSteamManager
from ..patch_execution import PatchExecutionEngine
from ..patch_repository import PatchRepository
from ..steam_scanner import SteamScanner
from ..steamgriddb_client import SteamGridDBClient
from ..steamos_helper import SteamOSHelper
from ..version import APP_NAME, APP_VERSION
from ..vndb_scanner import VNDBScanner

from .constants import (
    COLOR_BG_BLACK,
    COLOR_PRIMARY_BLUE,
    COLOR_PRIMARY_HOVER,
    COLOR_ACCENT_GREEN,
    COLOR_ACCENT_GREEN_HOVER,
    COLOR_TEXT_WHITE,
    COLOR_STATUS_GREEN,
    COLOR_STATUS_YELLOW,
    COLOR_STATUS_RED,
    MIN_WIDTH_DEFAULT,
    MIN_HEIGHT_DEFAULT,
    MIN_WIDTH_COMPACT,
    MIN_HEIGHT_COMPACT,
    STEAM_DECK_GEOMETRY,
    COMPACT_GEOMETRY,
    DEFAULT_GEOMETRY,
)
from .game_card import GameCardMixin
from .games_tab import GamesTabMixin
from .modals.artwork_browser import show_artwork_browser_modal
from .modals.non_steam_modal import show_add_non_steam_modal
from .navigation import NavigationMixin
from .settings_tab import SettingsTabMixin

logger = logging.getLogger(__name__)


class VNPatchManagerApp(
    ctk.CTk,
    NavigationMixin,
    GamesTabMixin,
    SettingsTabMixin,
    GameCardMixin,
):
    """
    Primary desktop & Steam Deck GUI window for Visual Novel Patch Manager.
    Orchestrates scan workers, controller navigation, tab views, and modal dialogs.
    """

    def __init__(self):
        super().__init__(className="VNPatchManager")

        self.title(f"{APP_NAME} - Steam Deck & Linux Native")
        self._setup_window_icon()

        # Screen-aware responsive geometry (optimized for Steam Deck 1280x800 and handhelds)
        try:
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()
        except Exception:
            screen_w, screen_h = 1280, 800

        if SteamOSHelper.is_game_mode():
            self.geometry(STEAM_DECK_GEOMETRY)
            self.minsize(MIN_WIDTH_DEFAULT, MIN_HEIGHT_DEFAULT)
            self._min_width = MIN_WIDTH_DEFAULT
            self._min_height = MIN_HEIGHT_DEFAULT
        elif screen_h <= 800 or screen_w <= 1280:
            self.geometry(COMPACT_GEOMETRY)
            self.minsize(MIN_WIDTH_COMPACT, MIN_HEIGHT_COMPACT)
            self._min_width = MIN_WIDTH_COMPACT
            self._min_height = MIN_HEIGHT_COMPACT
        else:
            self.geometry(DEFAULT_GEOMETRY)
            self.minsize(MIN_WIDTH_DEFAULT, MIN_HEIGHT_DEFAULT)
            self._min_width = MIN_WIDTH_DEFAULT
            self._min_height = MIN_HEIGHT_DEFAULT

        # OLED Pitch Black Window Background
        self.configure(fg_color=COLOR_BG_BLACK)

        # Initialize Core Systems
        self.config_manager = ConfigManager()
        self.steam_scanner = SteamScanner()
        self.repo = PatchRepository(self.config_manager)
        self.cover_manager = CoverArtManager()
        self.vndb_scanner = VNDBScanner()
        self.steamgriddb_client = SteamGridDBClient(
            api_key=self.config_manager.config.get("steamgriddb_api_key", "")
        )
        self.non_steam_manager = NonSteamManager(
            steam_root=self.steam_scanner.get_steam_root(),
            vndb_scanner=self.vndb_scanner,
        )

        # UI State Variables
        self._all_supported_games = {}
        self._banner_widgets = {}
        self.search_var = ctk.StringVar(value="")
        self.filter_var = ctk.StringVar(value="All")
        self.sort_var = ctk.StringVar(value="Title (A-Z)")
        self.view_var = ctk.StringVar(value="Grid")
        self._search_debounce_job = None
        self._active_render_job = None

        # Controller & Spatial Focus State
        self._card_entries = []
        self._modal_controller_stack = []
        self._focused_zone = "LIBRARY"
        self._focused_tab_idx = 0
        self._focused_card_idx = 0
        self._focused_btn_idx = -1
        self._focused_toolbar_idx = 0
        self._focused_header_idx = 1
        self._search_frame = None
        self._filter_frame = None
        self._sort_frame = None
        self._view_frame = None

        # Trace search input with debounce
        self.search_var.trace_add("write", self._on_search_changed)

        # Thread-safe GUI Queue
        self._gui_queue = queue.Queue()
        self.after(50, self._process_gui_queue)

        # Configure Root Grid Layout
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Top Header Bar
        self._setup_top_header()

        # Create Tabview (Games Library & Settings) - OLED Optimized
        self.tabview = ctk.CTkTabview(
            self,
            corner_radius=10,
            fg_color=COLOR_BG_BLACK,
            segmented_button_fg_color="#121212",
            segmented_button_selected_color=COLOR_PRIMARY_BLUE,
            segmented_button_selected_hover_color=COLOR_PRIMARY_HOVER,
            segmented_button_unselected_hover_color="#1e1e1e",
            text_color=COLOR_TEXT_WHITE,
            border_width=1,
            border_color="#27272a",
        )
        self.tabview.grid(row=1, column=0, padx=16, pady=(4, 8), sticky="nsew")

        self.tab_games = self.tabview.add("Games Library")
        self.tab_settings = self.tabview.add("Settings")

        # Setup Tab Contents
        self._setup_settings_tab()
        self._setup_games_tab()

        # Bottom Status & Progress Footer
        self._setup_bottom_footer()

        # Bind controller navigation & keyboard shortcuts
        self._bind_controller_and_keyboard_events()

        # Start Background Gamepad Controller Listener
        try:
            self.controller_manager = GamepadControllerManager(
                action_callback=lambda act: self.run_on_main_thread(lambda a=act: self._handle_controller_action(a))
            )
            self.controller_manager.start()
        except Exception as e:
            logger.warning(f"Could not initialize GamepadControllerManager: {e}")
            self.controller_manager = None

        # Initial Scan & SteamOS Game Mode Window Focus
        self.after(200, self.refresh_data)
        self.after(500, self._ensure_game_mode_focus)

    def _setup_window_icon(self):
        """Sets high-resolution window titlebar and taskbar icon for Linux/Steam Deck."""
        try:
            candidates = [
                Path(__file__).parent.parent / "assets" / "app_icon.png",
                Path(__file__).parent / "assets" / "app_icon.png",
                Path.home() / ".local/share/vnpm/assets/app_icon.png",
                Path(__file__).parent.parent / "assets" / "steam_icon.jpg",
            ]
            for icon_path in candidates:
                if icon_path.exists():
                    pil_img = Image.open(icon_path).resize((64, 64), Image.Resampling.LANCZOS)
                    self._window_icon = ImageTk.PhotoImage(pil_img)
                    self.iconphoto(True, self._window_icon)
                    break
        except Exception as e:
            logger.debug(f"Failed to set window icon: {e}")

    def _setup_top_header(self):
        """Constructs the application top header."""
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.grid(row=0, column=0, padx=20, pady=(12, 4), sticky="ew")
        header_frame.grid_columnconfigure(0, weight=1)

        # Title and Subtitle Block
        title_block = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_block.grid(row=0, column=0, sticky="w")

        lbl_app_title = ctk.CTkLabel(
            title_block,
            text=f"🎮 {APP_NAME.upper()}",
            font=ctk.CTkFont(size=19, weight="bold"),
            text_color=COLOR_TEXT_WHITE,
        )
        lbl_app_title.pack(anchor="w")

        self.lbl_stats = ctk.CTkLabel(
            title_block,
            text="Scanning library...",
            font=ctk.CTkFont(size=12),
            text_color="gray",
        )
        self.lbl_stats.pack(anchor="w")

        # Header Action Buttons
        btn_block = ctk.CTkFrame(header_frame, fg_color="transparent")
        btn_block.grid(row=0, column=1, sticky="e")

        self.btn_refresh = ctk.CTkButton(
            btn_block,
            text="🔄 Scan Games & Patches",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=32,
            fg_color=COLOR_PRIMARY_BLUE,
            hover_color=COLOR_PRIMARY_HOVER,
            command=self.refresh_data,
        )
        self.btn_refresh.pack(side="right", padx=(8, 0))

        self.btn_add_non_steam = ctk.CTkButton(
            btn_block,
            text="➕ Add Non-Steam VN",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=32,
            fg_color=COLOR_ACCENT_GREEN,
            hover_color=COLOR_ACCENT_GREEN_HOVER,
            command=self.open_add_non_steam_modal,
        )
        self.btn_add_non_steam.pack(side="right", padx=(0, 0))

    def _setup_bottom_footer(self):
        """Constructs the status label and progress bar footer."""
        footer_frame = ctk.CTkFrame(self, fg_color="transparent")
        footer_frame.grid(row=2, column=0, padx=20, pady=(4, 12), sticky="ew")
        footer_frame.grid_columnconfigure(0, weight=1)

        self.lbl_status = ctk.CTkLabel(footer_frame, text="Ready", font=ctk.CTkFont(size=12), text_color="gray")
        self.lbl_status.grid(row=0, column=0, sticky="w")

        self.progress_bar = ctk.CTkProgressBar(
            footer_frame, width=200, height=8, mode="indeterminate", progress_color=COLOR_PRIMARY_BLUE
        )
        self.progress_bar.grid(row=0, column=1, sticky="e")
        self.progress_bar.set(0)

    def destroy(self):
        """Cleanly stops background controller listener before closing."""
        try:
            if hasattr(self, "controller_manager") and self.controller_manager:
                self.controller_manager.stop()
        except Exception:
            pass
        super().destroy()

    def run_on_main_thread(self, func, *args, **kwargs):
        """Thread-safe dispatch to execute a function on the main Tkinter thread."""
        if threading.current_thread() is threading.main_thread():
            try:
                func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error executing GUI action on main thread: {e}")
        else:
            self._gui_queue.put((func, args, kwargs))

    def _process_gui_queue(self):
        """Processes pending GUI actions dispatched from background worker threads."""
        try:
            while not self._gui_queue.empty():
                func, args, kwargs = self._gui_queue.get_nowait()
                try:
                    func(*args, **kwargs)
                except Exception as e:
                    logger.error(f"Error executing GUI action on main thread: {e}")
        finally:
            try:
                self.after(50, self._process_gui_queue)
            except Exception:
                pass

    def refresh_data(self):
        """Scans Steam installations, updates patches from local/SMB, and populates the library."""
        self.lbl_status.configure(text="Scanning Steam library & patch repository...", text_color="gray")
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()

        def _worker():
            try:
                # 1. Scan Installed & Owned Steam Games
                installed_games = self.steam_scanner.get_installed_games()
                owned_games = self.steam_scanner.get_owned_games()
                all_games = {**owned_games, **installed_games}

                # 2. Refresh Patch Definitions from Local or SMB
                self.repo.refresh_patches()

                # 3. Synchronize / Pre-cache VNDB Catalog Data
                self.vndb_scanner.sync_vndb_snapshot(timeout_sec=8, force=False)
                cached_vndb = self.vndb_scanner.get_cached_vns()

                # Find un-cached AppIDs
                uncached_ids = [aid for aid in all_games.keys() if aid not in cached_vndb]
                if uncached_ids:
                    fresh_vndb = self.vndb_scanner.check_app_ids(uncached_ids)
                    cached_vndb.update(fresh_vndb)

                # 4. Filter supported Visual Novels
                supported = {}
                for app_id, game_data in all_games.items():
                    is_non_steam = game_data.get("is_non_steam", False)
                    game_path = Path(game_data["path"]) if game_data.get("path") else None
                    if is_non_steam:
                        game_data["is_installed"] = bool(game_path and game_path.exists())

                    vn_info = cached_vndb.get(app_id, {})

                    # If non-Steam, query VNDB metadata by title
                    if is_non_steam and game_data.get("name"):
                        matched_meta = self.non_steam_manager.match_vn_metadata(game_data["name"])
                        if matched_meta.get("vndb_id"):
                            matched_aid = matched_meta.get("matched_app_id")
                            if matched_aid and matched_aid in cached_vndb:
                                vn_info = dict(cached_vndb[matched_aid])

                    game_data["vndb"] = vn_info
                    patch_info = self.repo.available_patches.get(app_id)
                    has_local_patch = patch_info is not None
                    has_vndb_18_patch = vn_info.get("has_18plus_en_patch", False)
                    is_installed = bool(game_data.get("is_installed", True)) and bool(game_data.get("path"))

                    # Resolve human-readable game title if currently placeholder or empty
                    cur_name = game_data.get("name", "")
                    if not cur_name or cur_name.startswith("Steam App #"):
                        if vn_info.get("vn_title"):
                            game_data["name"] = vn_info["vn_title"]
                        elif patch_info and patch_info.get("game_name"):
                            game_data["name"] = patch_info["game_name"]

                    if is_non_steam:
                        gname = (game_data.get("name") or "").strip().lower()
                        if gname and not (
                            gname == APP_NAME.lower()
                            or "vn patch manager" in gname
                            or "visual novel patch manager" in gname
                        ):
                            supported[app_id] = game_data
                    elif has_local_patch:
                        supported[app_id] = game_data
                    elif has_vndb_18_patch and (not is_installed or (is_installed and vn_info.get("is_vn", False))):
                        if vn_info.get("is_vn", False):
                            supported[app_id] = game_data

                # Pre-compute status & search index for each supported game in background
                for aid, gdata in supported.items():
                    gdata["status_info"] = self._compute_status_info(aid, gdata)

                # Pre-fetch cover arts
                for app_id, gdata in supported.items():
                    try:
                        is_new = self.cover_manager.download_cover(app_id, game_data=gdata)
                        if is_new:
                            self.run_on_main_thread(lambda aid=app_id: self._refresh_banner(aid))
                    except Exception:
                        pass

                self.run_on_main_thread(lambda: self._populate_game_list(supported))

            except Exception as e:
                err_msg = str(e)
                logger.error(f"Error during refresh: {err_msg}", exc_info=True)
                self.run_on_main_thread(
                    lambda err=err_msg: self.lbl_status.configure(text=f"Error: {err}", text_color=COLOR_STATUS_RED)
                )
            finally:
                self.run_on_main_thread(self._stop_progress)

        threading.Thread(target=_worker, daemon=True).start()

    def _stop_progress(self):
        """Stops progress bar activity."""
        self.progress_bar.stop()
        self.progress_bar.configure(mode="determinate")
        self.progress_bar.set(0)

    def run_patch(self, game_data, patch_data):
        """Executes patch installation on a background worker thread."""
        if not game_data.get("is_installed", True) or not game_data.get("path") or not Path(game_data["path"]).exists():
            messagebox.showwarning(
                "Game Not Installed",
                f"'{game_data['name']}' is not currently installed on this device.\n\nPlease install the game via Steam before applying the patch.",
            )
            self.lbl_status.configure(text=f"Cannot patch '{game_data['name']}': Game not installed.", text_color="#f87171")
            return

        self.lbl_status.configure(text=f"Patching {game_data['name']}...", text_color="gray")
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()

        def _patch_task():
            try:
                PatchExecutionEngine.apply_patch(
                    game_data,
                    patch_data,
                    self.config_manager,
                    lambda msg: self.run_on_main_thread(lambda m=msg: self.lbl_status.configure(text=m)),
                )
                self.run_on_main_thread(lambda: self.after(2000, self.refresh_data))
            except Exception:
                logger.error("Patch task failed", exc_info=True)
                self.run_on_main_thread(self._stop_progress)
                self.run_on_main_thread(
                    lambda: self.lbl_status.configure(text="Patch Failed! Check terminal.", text_color=COLOR_STATUS_RED)
                )

        threading.Thread(target=_patch_task, daemon=True).start()

    def run_rollback(self, game_data):
        """Restores a game from local backup on a background worker thread."""
        if not game_data.get("is_installed", True) or not game_data.get("path") or not Path(game_data["path"]).exists():
            messagebox.showwarning("Game Not Installed", f"'{game_data['name']}' is not installed.")
            return

        self.lbl_status.configure(text=f"Restoring original {game_data['name']} from backup...", text_color="gray")
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()

        def _rollback_task():
            try:
                PatchExecutionEngine.rollback_patch(
                    game_data,
                    lambda msg: self.run_on_main_thread(lambda m=msg: self.lbl_status.configure(text=m)),
                )
                self.run_on_main_thread(lambda: self.after(2000, self.refresh_data))
            except Exception as e:
                logger.error(f"ROLLBACK ERROR: {e}", exc_info=True)
                self.run_on_main_thread(self._stop_progress)
                self.run_on_main_thread(
                    lambda: self.lbl_status.configure(text="Rollback Failed! Check terminal.", text_color=COLOR_STATUS_RED)
                )

        threading.Thread(target=_rollback_task, daemon=True).start()

    def run_steam_restore(self, game_data, patch_data):
        """Restores original vanilla game files via Steam depot redownload."""
        if not game_data.get("is_installed", True) or not game_data.get("path") or not Path(game_data["path"]).exists():
            messagebox.showwarning("Game Not Installed", f"'{game_data['name']}' is not installed.")
            return

        self.lbl_status.configure(text=f"Restoring original {game_data['name']} via Steam...", text_color="gray")
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()

        def _steam_task():
            try:
                PatchExecutionEngine.restore_via_steam(
                    game_data,
                    patch_data,
                    lambda msg: self.run_on_main_thread(lambda m=msg: self.lbl_status.configure(text=m)),
                )
                self.run_on_main_thread(lambda: self.after(2000, self.refresh_data))
            except Exception as e:
                logger.error(f"STEAM RESTORE ERROR: {e}", exc_info=True)
                self.run_on_main_thread(self._stop_progress)
                self.run_on_main_thread(
                    lambda: self.lbl_status.configure(
                        text="Steam Restore Failed! Check terminal.", text_color=COLOR_STATUS_RED
                    )
                )

        threading.Thread(target=_steam_task, daemon=True).start()

    def run_fix_video(self, app_id: str, game_data: dict):
        """Applies video codec / Media Foundation / Quartz fixes to the game's Proton prefix."""
        self.lbl_status.configure(text=f"Applying video fixes for {game_data['name']} (App #{app_id})...", text_color="gray")
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()

        def _fix_task():
            try:
                success, msg = CodecFixer.apply_video_fixes(str(app_id))
                self.run_on_main_thread(self._stop_progress)
                if success:
                    self.run_on_main_thread(
                        lambda m=msg: self.lbl_status.configure(text=f"✅ {m}", text_color=COLOR_STATUS_GREEN)
                    )
                else:
                    self.run_on_main_thread(
                        lambda m=msg: self.lbl_status.configure(text=f"⚠️ {m}", text_color=COLOR_STATUS_YELLOW)
                    )
            except Exception as e:
                err_msg = str(e)
                logger.error(f"Error applying video fixes: {err_msg}", exc_info=True)
                self.run_on_main_thread(self._stop_progress)
                self.run_on_main_thread(
                    lambda err=err_msg: self.lbl_status.configure(
                        text=f"Failed to apply video fixes: {err}", text_color=COLOR_STATUS_RED
                    )
                )

        threading.Thread(target=_fix_task, daemon=True).start()

    def run_remove_non_steam(self, app_id: str, game_data: dict):
        """Confirms and removes a non-Steam visual novel shortcut from Steam and VNPM on background thread."""
        confirmed = messagebox.askyesno(
            "Remove Non-Steam Shortcut?",
            f"Are you sure you want to remove '{game_data['name']}' from Steam and VNPM?\n\n(This will remove the Steam shortcut and artwork, but will not delete your game files.)",
            parent=self,
        )
        if not confirmed:
            return

        aid_32 = int(app_id) if str(app_id).isdigit() else None
        self.lbl_status.configure(text=f"Removing non-Steam game '{game_data['name']}'...", text_color="gray")
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()

        def _worker():
            try:
                success, msg = self.non_steam_manager.remove_non_steam_game(
                    app_name=game_data["name"],
                    appid_32=aid_32,
                )
                def _done():
                    self._stop_progress()
                    if success:
                        self.lbl_status.configure(text=f"✅ {msg}", text_color=COLOR_STATUS_GREEN)
                        self.refresh_data()
                    else:
                        self.lbl_status.configure(text=f"❌ {msg}", text_color=COLOR_STATUS_RED)
                        messagebox.showerror("Error Removing Shortcut", msg, parent=self)
                self.run_on_main_thread(_done)
            except Exception as e:
                logger.error(f"Error removing non-steam game: {e}", exc_info=True)
                def _fail():
                    self._stop_progress()
                    self.lbl_status.configure(text=f"❌ Failed to remove game: {e}", text_color=COLOR_STATUS_RED)
                self.run_on_main_thread(_fail)

        threading.Thread(target=_worker, daemon=True).start()

    def run_custom_artwork(self, app_id: str, game_data: dict):
        """Opens the visual artwork browser modal for this game."""
        self.open_artwork_browser_modal(app_id, game_data)

    def open_artwork_browser_modal(self, app_id: str, game_data: dict):
        """Opens an interactive artwork browser modal."""
        show_artwork_browser_modal(self, app_id, game_data)

    def open_add_non_steam_modal(self):
        """Opens modal dialog to register a non-Steam visual novel."""
        show_add_non_steam_modal(self)
