"""
Main application window shell and service lifecycle coordinator for VNPM.
"""

import logging
import queue
import threading
from pathlib import Path
from tkinter import messagebox
from typing import Optional
from PIL import Image, ImageTk

try:
    import customtkinter as ctk
except ImportError:
    class _FallbackCTk:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("customtkinter is required to instantiate VNPatchManagerApp GUI")
    ctk = type("ctk", (), {"CTk": _FallbackCTk})

from ..config_manager import ConfigManager
from ..controller_manager import GamepadControllerManager
from ..cover_art_manager import CoverArtManager
from ..ipc_service import VNPMService
from ..non_steam_manager import NonSteamManager
from ..patch_repository import PatchRepository
from ..steam_scanner import SteamScanner
from ..steamgriddb_client import SteamGridDBClient
from ..steamos_helper import SteamOSHelper
from ..version import APP_NAME
from ..vndb_scanner import VNDBScanner

from .constants import (
    COLOR_BG_BLACK,
    COLOR_PRIMARY_BLUE,
    COLOR_PRIMARY_HOVER,
    COLOR_TEXT_WHITE,
    COLOR_STATUS_RED,
    MIN_WIDTH_DEFAULT,
    MIN_HEIGHT_DEFAULT,
    MIN_WIDTH_COMPACT,
    MIN_HEIGHT_COMPACT,
    STEAM_DECK_GEOMETRY,
    COMPACT_GEOMETRY,
    DEFAULT_GEOMETRY,
)
from .icons import icon
from .theme import COLOR_BORDER_2, COLOR_ELEVATION_1, COLOR_ELEVATION_2, COLOR_STATUS_PATCHED, MIN_TOUCH_TARGET
from .views.game_detail_view import GamePage
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
        self.service = VNPMService(config_manager=self.config_manager)
        self.steam_scanner = SteamScanner()
        self.repo = PatchRepository(self.config_manager)
        self.cover_manager = CoverArtManager()
        self.vndb_scanner = VNDBScanner()
        self.steamgriddb_client = SteamGridDBClient(
            api_key=self.config_manager.config.get("steamgriddb_api_key", "")
        )
        self.cover_manager.steamgriddb_client = self.steamgriddb_client
        self.non_steam_manager = NonSteamManager(
            steam_root=self.steam_scanner.get_steam_root(),
            vndb_scanner=self.vndb_scanner,
        )

        # UI State Variables
        self._all_supported_games = {}
        self._banner_widgets = {}
        self.search_var = ctk.StringVar(value="")
        self.filter_var = ctk.StringVar(value="all")
        self.sort_var = ctk.StringVar(value="A-Z")
        self.view_var = ctk.StringVar(value="Posters")
        self._search_debounce_job = None
        self._active_render_job = None

        # Controller & Spatial Focus State
        self._card_entries = []
        self._modal_controller_stack = []
        self._focused_zone = "LIBRARY"
        self._focus_band = "cards"
        self._focused_tab_idx = 0
        self._focused_card_idx = 0
        self._focused_btn_idx = -1
        self._focused_toolbar_idx = 0
        self._focused_chip_idx = 0
        self._focused_header_idx = 1
        self._settings_index = 0
        self._settings_open = False
        self._game_page = None
        self._selected_app_id = None
        self._library_scroll = (0.0, 1.0)
        self._empty_folder = False
        self._last_full = None
        self._search_frame = None
        self._filter_frame = None
        self._sort_frame = None
        self._view_frame = None

        # Trace search input with debounce
        self.search_var.trace_add("write", self._on_search_changed)

        # Thread-safe GUI Queue
        self._gui_queue = queue.Queue()
        self.after(50, self._process_gui_queue)

        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._build_shell()
        self._setup_settings_tab()
        self._setup_games_tab()
        self._sync_layout()
        self.bind("<Configure>", self._on_root_configure, add="+")

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

    def _build_shell(self):
        """Header, library body, detail slot, settings slot, status line, and hint row."""
        self.header = ctk.CTkFrame(self, fg_color="transparent", height=56)
        self.header.grid(row=0, column=0, sticky="ew", padx=16, pady=(8, 0))
        self.header.grid_columnconfigure(1, weight=1)

        brand = ctk.CTkFrame(self.header, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="w", padx=(0, 12))
        ctk.CTkLabel(brand, text="", image=icon("grid", 28)).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(
            brand,
            text="Patch Manager",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=COLOR_TEXT_WHITE,
        ).pack(side="left")

        self._search_frame = ctk.CTkFrame(
            self.header,
            fg_color=COLOR_ELEVATION_2,
            border_color=COLOR_BORDER_2,
            border_width=1,
            corner_radius=8,
            height=MIN_TOUCH_TARGET,
        )
        self._search_frame.grid(row=0, column=1, sticky="ew")
        self._search_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self._search_frame, text="", image=icon("search")).grid(row=0, column=0, padx=(10, 4), pady=6)
        self.entry_search = ctk.CTkEntry(
            self._search_frame,
            placeholder_text="Search titles",
            textvariable=self.search_var,
            fg_color="transparent",
            border_width=0,
            text_color=COLOR_TEXT_WHITE,
            font=ctk.CTkFont(size=15),
            height=36,
        )
        self.entry_search.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=4)
        self.entry_search.bind("<FocusIn>", self._on_search_focused)

        actions = ctk.CTkFrame(self.header, fg_color="transparent")
        actions.grid(row=0, column=2, sticky="e", padx=(12, 0))
        self.btn_refresh = ctk.CTkButton(
            actions,
            text="Scan",
            height=MIN_TOUCH_TARGET,
            width=88,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color=COLOR_PRIMARY_BLUE,
            hover_color=COLOR_PRIMARY_HOVER,
            border_width=1,
            border_color=COLOR_PRIMARY_BLUE,
            command=self.refresh_data,
        )
        self.btn_refresh.pack(side="left", padx=(0, 8))
        self.btn_add_non_steam = ctk.CTkButton(
            actions,
            text="Add",
            height=MIN_TOUCH_TARGET,
            width=72,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color=COLOR_ELEVATION_2,
            hover_color=COLOR_ELEVATION_1,
            border_width=1,
            border_color=COLOR_BORDER_2,
            text_color=COLOR_TEXT_WHITE,
            command=self.open_add_non_steam_modal,
        )
        self.btn_add_non_steam.pack(side="left", padx=(0, 8))
        self.btn_settings = ctk.CTkButton(
            actions,
            text="Settings",
            image=icon("gear"),
            compound="left",
            height=MIN_TOUCH_TARGET,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color=COLOR_ELEVATION_2,
            hover_color=COLOR_ELEVATION_1,
            border_width=1,
            border_color=COLOR_BORDER_2,
            text_color=COLOR_TEXT_WHITE,
            command=self._open_settings,
        )
        self.btn_settings.pack(side="left")

        self.chip_bar = ctk.CTkFrame(self, fg_color="transparent", height=52)
        self.chip_bar.grid(row=1, column=0, sticky="ew", padx=16, pady=(8, 4))

        self.body = ctk.CTkFrame(self, fg_color=COLOR_BG_BLACK, corner_radius=0)
        self.body.grid(row=2, column=0, sticky="nsew")
        self.body.grid_rowconfigure(0, weight=1)
        self.body.grid_columnconfigure(0, weight=1)
        self.body.grid_columnconfigure(1, weight=0)

        self.library_host = ctk.CTkFrame(self.body, fg_color=COLOR_BG_BLACK, corner_radius=0)
        self.library_host.grid(row=0, column=0, sticky="nsew")
        self.detail_host = ctk.CTkFrame(self.body, fg_color=COLOR_ELEVATION_1, corner_radius=0, width=420)
        self.settings_host = ctk.CTkFrame(self, fg_color=COLOR_ELEVATION_1, corner_radius=0)

        self.status_row = ctk.CTkFrame(self, fg_color="transparent")
        self.status_row.grid(row=3, column=0, sticky="ew", padx=16, pady=(4, 0))
        self.status_row.grid_columnconfigure(0, weight=1)
        self.lbl_status = ctk.CTkLabel(self.status_row, text="Ready", font=ctk.CTkFont(size=13), text_color="gray")
        self.lbl_status.grid(row=0, column=0, sticky="w")
        self.progress_bar = ctk.CTkProgressBar(
            self.status_row, width=160, height=8, mode="indeterminate", progress_color=COLOR_PRIMARY_BLUE
        )
        self.progress_bar.grid(row=0, column=1, sticky="e")
        self.progress_bar.set(0)

        self.hint_bar = ctk.CTkFrame(self, fg_color=COLOR_ELEVATION_1, height=48, corner_radius=0)
        self.hint_bar.grid(row=4, column=0, sticky="ew")
        self.lbl_prompt_hints = ctk.CTkLabel(
            self.hint_bar,
            text="A  View     X  Apply     Y  Search     Start  Scan",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#38bdf8",
        )
        self.lbl_prompt_hints.pack(pady=12)
        self._apply_header_compact()

    def _apply_header_compact(self):
        """Game Mode uses icon buttons for Scan and Add."""
        compact = SteamOSHelper.is_game_mode()
        if compact:
            self.btn_refresh.configure(text="", image=icon("scan"), width=MIN_TOUCH_TARGET)
            self.btn_add_non_steam.configure(text="", image=icon("plus"), width=MIN_TOUCH_TARGET)
        else:
            self.btn_refresh.configure(text="Scan", image=None, width=88)
            self.btn_add_non_steam.configure(text="Add", image=None, width=72)

    def _use_full_page(self) -> bool:
        if SteamOSHelper.is_game_mode():
            return True
        width = self.winfo_width()
        if width <= 1:
            try:
                width = self.winfo_screenwidth()
            except Exception:
                width = 1280
        return width < 1100

    def _should_show_hints(self) -> bool:
        if SteamOSHelper.is_game_mode():
            return True
        manager = getattr(self, "controller_manager", None)
        return bool(manager and manager.has_device())

    def _on_root_configure(self, event):
        if event.widget is not self:
            return
        full = self._use_full_page()
        if full == self._last_full:
            return
        self._last_full = full
        if self._game_page is not None and self._selected_app_id:
            self._remount_game_page()
        self._sync_layout()

    def _sync_layout(self):
        """Places the library, game page, settings, and hint row for the current width."""
        full = self._use_full_page()
        self._last_full = full
        show_detail = self._game_page is not None
        show_settings = self._settings_open
        cover_chrome = full and (show_detail or show_settings)
        if cover_chrome:
            self.header.grid_remove()
            self.chip_bar.grid_remove()
        else:
            self.header.grid()
            if self._empty_folder:
                self.chip_bar.grid_remove()
            else:
                self.chip_bar.grid()
        if show_detail and not (show_settings and full):
            if full:
                self.library_host.grid_remove()
                self.detail_host.grid(row=0, column=0, columnspan=2, sticky="nsew")
            else:
                self.library_host.grid(row=0, column=0, sticky="nsew")
                self.detail_host.grid(row=0, column=1, sticky="nsew")
                self.detail_host.configure(width=420)
        else:
            self.detail_host.grid_remove()
            self.library_host.grid(row=0, column=0, sticky="nsew")
        if show_settings:
            if full:
                self.settings_host.place(in_=self, relx=0, rely=0, relwidth=1, relheight=1)
            else:
                self.settings_host.place(in_=self.body, relx=1, rely=0, anchor="ne", relheight=1, width=480)
            self.settings_host.lift()
        else:
            self.settings_host.place_forget()
        if self._should_show_hints():
            self.hint_bar.grid()
        else:
            self.hint_bar.grid_remove()
        self._apply_header_compact()

    def _folder_missing(self) -> bool:
        config = self.config_manager.config
        if config.get("mode", "local") == "smb":
            return False
        return not str(config.get("local_path", "")).strip()

    def _open_game_page(self, app_id: str, game_data: dict, status_info: dict):
        if self._use_full_page():
            canvas = getattr(self.scrollable_games, "_parent_canvas", None)
            if canvas:
                self._library_scroll = canvas.yview()
        self._selected_app_id = str(app_id)
        self._selected_game = game_data
        self._selected_status = status_info
        self._mount_game_page()
        self._focused_zone = "DETAIL"
        self._settings_open = False
        self._sync_layout()
        self._apply_focus_visuals()
        return self._game_page

    def _mount_game_page(self):
        if self._game_page is not None:
            self._game_page.destroy()
            self._game_page = None
        page = GamePage(
            self.detail_host,
            self._selected_app_id,
            self._selected_game,
            self._selected_status,
            on_back=self._close_game_page,
            pinned=self._use_full_page(),
            host=self,
        )
        page.pack(fill="both", expand=True)
        self._game_page = page

    def _remount_game_page(self):
        if self._selected_app_id and self._selected_game is not None:
            self._mount_game_page()

    def _close_game_page(self):
        if self._game_page is not None:
            page = self._game_page
            self._game_page = None
            page.destroy()
        self._selected_app_id = None
        self._focused_zone = "LIBRARY"
        self._focus_band = "cards"
        self._sync_layout()
        canvas = getattr(self.scrollable_games, "_parent_canvas", None)
        if canvas and self._library_scroll:
            try:
                canvas.yview_moveto(self._library_scroll[0])
            except Exception:
                pass
        self._apply_focus_visuals()

    def _open_settings(self):
        self._settings_open = True
        self._settings_index = 0
        self._focused_zone = "SETTINGS"
        self._sync_layout()
        self._apply_focus_visuals()

    def _close_settings(self):
        self._settings_open = False
        if self._game_page is not None:
            self._focused_zone = "DETAIL"
        else:
            self._focused_zone = "LIBRARY"
            self._focus_band = "cards"
        self._sync_layout()
        self._apply_focus_visuals()

    def update_controller_prompts(self, active_zone: str = "LIBRARY"):
        """Updates the hint row for the focused zone."""
        if not hasattr(self, "lbl_prompt_hints") or not self.lbl_prompt_hints.winfo_exists():
            return
        if active_zone == "CHIPS":
            hints = "A  Select     Y  Search     L1/R1  Filter"
        elif active_zone in ("DETAIL", "SETTINGS", "CONFIRM"):
            hints = "A  Select     B  Back"
        elif active_zone == "HEADER":
            if getattr(self, "_focused_header_idx", 0) == 3:
                hints = "A  Settings     B  Back"
            else:
                hints = "A  Select     B  Back"
        else:
            hints = "A  View     X  Apply     Y  Search     Start  Scan"
        self.lbl_prompt_hints.configure(text=hints)

    def destroy(self):
        """Cleanly stops background controller listener before closing."""
        try:
            if hasattr(self, "controller_manager") and self.controller_manager:
                self.controller_manager.stop()
        except Exception:
            pass
        super().destroy()
        try:
            import tkinter as tk
            if getattr(tk, "_default_root", None) is self:
                tk._default_root = None
        except Exception:
            pass

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
        if self._folder_missing():
            self._show_empty_folder()
            self._stop_progress()
            self._sync_layout()
            return
        self._hide_empty_folder()
        self._sync_layout()
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
                    if not is_non_steam:
                        game_data.setdefault("steam_app_id", str(app_id))
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
                        if vn_info.get("steam_title"):
                            game_data["name"] = vn_info["steam_title"]
                        elif vn_info.get("vn_title"):
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
                        if hasattr(self.cover_manager, "download_hero"):
                            self.cover_manager.download_hero(app_id, game_data=gdata)
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

    def _status_log(self, message: str) -> None:
        """Mirror an engine log line onto the footer from a worker thread."""
        self.run_on_main_thread(lambda m=message: self.lbl_status.configure(text=m))

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

        app_id = str((patch_data or {}).get("steam_app_id") or game_data.get("steam_app_id") or "")

        def _patch_task():
            try:
                result = self.service.apply_patch(
                    app_id,
                    game_data=game_data,
                    patch_data=patch_data,
                    log_callback=self._status_log,
                )
                if not result.get("success"):
                    raise RuntimeError(result.get("error") or "Patch failed")
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

        app_id = str(game_data.get("steam_app_id") or "")

        def _rollback_task():
            try:
                result = self.service.restore_backup(
                    app_id,
                    game_data=game_data,
                    log_callback=self._status_log,
                )
                if not result.get("success"):
                    raise RuntimeError(result.get("error") or "Rollback failed")
                self.run_on_main_thread(lambda: self.after(2000, self.refresh_data))
            except Exception as e:
                logger.error(f"ROLLBACK ERROR: {e}", exc_info=True)
                self.run_on_main_thread(self._stop_progress)
                self.run_on_main_thread(
                    lambda: self.lbl_status.configure(text="Rollback Failed! Check terminal.", text_color=COLOR_STATUS_RED)
                )

        threading.Thread(target=_rollback_task, daemon=True).start()

    def run_steam_restore(self, game_data, patch_data=None, app_id=None):
        """Restores original vanilla game files via Steam depot redownload."""
        if not game_data.get("is_installed", True) or not game_data.get("path") or not Path(game_data["path"]).exists():
            messagebox.showwarning("Game Not Installed", f"'{game_data.get('name', 'Game')}' is not installed.")
            return

        resolved_app_id = app_id or game_data.get("steam_app_id")
        if not resolved_app_id and hasattr(self, "_all_supported_games"):
            for aid, gd in self._all_supported_games.items():
                if gd is game_data or (gd.get("path") and gd.get("path") == game_data.get("path")):
                    resolved_app_id = aid
                    break

        if resolved_app_id:
            game_data["steam_app_id"] = str(resolved_app_id)
            if patch_data is None and hasattr(self, "repo") and self.repo.available_patches:
                patch_data = self.repo.available_patches.get(str(resolved_app_id))

        self.lbl_status.configure(text=f"Restoring original {game_data.get('name', 'Game')} via Steam...", text_color="gray")
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()

        def _steam_task():
            try:
                result = self.service.restore_via_steam(
                    str(resolved_app_id or ""),
                    game_data=game_data,
                    patch_data=patch_data,
                    log_callback=self._status_log,
                )
                if not result.get("success"):
                    raise RuntimeError(result.get("error") or "Steam restore failed")
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

    def run_codec_fix(self, game_data: dict, app_id: Optional[str] = None):
        """Convenience alias for run_fix_video."""
        resolved_app_id = app_id or game_data.get("steam_app_id") or ""
        self.run_fix_video(str(resolved_app_id), game_data)

    def run_fix_video(self, app_id: str, game_data: dict):
        """Applies video codec / Media Foundation / Quartz fixes to the game's Proton prefix."""
        self.lbl_status.configure(text=f"Applying video fixes for {game_data['name']} (App #{app_id})...", text_color="gray")
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()

        def _fix_task():
            try:
                result = self.service.fix_codecs(str(app_id))
                if not result.get("success"):
                    raise RuntimeError(result.get("error") or result.get("message") or "Video fix failed")
                msg = result.get("message") or ""
                self.run_on_main_thread(self._stop_progress)
                self.run_on_main_thread(
                    lambda m=msg: self.lbl_status.configure(text=f"✅ {m}", text_color=COLOR_STATUS_PATCHED)
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
                        self.lbl_status.configure(text=f"✅ {msg}", text_color=COLOR_STATUS_PATCHED)
                        self.refresh_data()
                    else:
                        self.lbl_status.configure(text=f"❌ {msg}", text_color=COLOR_STATUS_RED)
                        messagebox.showerror("Error Removing Shortcut", msg, parent=self)
                self.run_on_main_thread(_done)
            except Exception as e:
                logger.error(f"Error removing non-steam game: {e}", exc_info=True)
                def _fail(err=e):
                    self._stop_progress()
                    self.lbl_status.configure(text=f"❌ Failed to remove game: {err}", text_color=COLOR_STATUS_RED)
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
