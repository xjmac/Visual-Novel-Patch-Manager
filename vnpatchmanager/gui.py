import logging
import threading
import queue
import time
import webbrowser
from tkinter import messagebox, filedialog
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import customtkinter as ctk
except ImportError:
    pass

from .config_manager import ConfigManager
from .steam_scanner import SteamScanner
from .patch_repository import PatchRepository
from .cover_art_manager import CoverArtManager
from .vndb_scanner import VNDBScanner
from .patch_execution import PatchExecutionEngine
from .backup_manager import BackupManager
from .steamos_helper import SteamOSHelper
from .controller_manager import (
    GamepadControllerManager,
    ACTION_UP,
    ACTION_DOWN,
    ACTION_LEFT,
    ACTION_RIGHT,
    ACTION_SELECT,
    ACTION_BACK,
    ACTION_QUICK_ACTION,
    ACTION_SEARCH,
    ACTION_PREV_TAB,
    ACTION_NEXT_TAB,
    ACTION_SCROLL_UP,
    ACTION_SCROLL_DOWN,
)

from .version import get_version

APP_NAME = "VN Patch Manager"
APP_VERSION = get_version()

MODE_LOCAL_DISPLAY = "📁 Local Storage"
MODE_SMB_DISPLAY = "🌐 Network Share (NAS)"


class VNPatchManagerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(f"{APP_NAME} - Steam Deck & Linux Native")
        
        # Screen-aware responsive geometry (optimized for Steam Deck 1280x800 and handhelds)
        try:
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()
        except Exception:
            screen_w, screen_h = 1280, 800

        if screen_h <= 800 or screen_w <= 1280:
            self.geometry("1000x610")
            self.minsize(760, 480)
        else:
            self.geometry("1060x680")
            self.minsize(800, 520)

        # OLED Pitch Black Window Background
        self.configure(fg_color="#000000")

        # Initialize Core Systems
        self.config_manager = ConfigManager()
        self.steam_scanner = SteamScanner()
        self.repo = PatchRepository(self.config_manager)
        self.cover_manager = CoverArtManager()
        self.vndb_scanner = VNDBScanner()

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
        self._card_entries = []  # List of rendered card dictionaries
        self._focused_zone = "LIBRARY"  # "LIBRARY", "TOOLBAR", "TABS", "SETTINGS"
        self._focused_tab_idx = 0  # 0: Games Library, 1: Settings
        self._focused_card_idx = 0
        self._focused_btn_idx = -1  # -1 = whole card, >= 0 = specific button in card
        self._focused_toolbar_idx = 0  # 0: Search, 1: Filter, 2: Sort, 3: View, 4: Scan
        self._search_frame = None
        self._filter_frame = None
        self._sort_frame = None
        self._view_frame = None

        # Trace search input with debounce
        self.search_var.trace_add("write", self._on_search_changed)

        # Configure Root Grid Layout
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Top Header Bar
        self._setup_top_header()

        # Create Tabview (Games Library & Settings) - OLED Optimized
        self.tabview = ctk.CTkTabview(
            self,
            corner_radius=10,
            fg_color="#000000",
            segmented_button_fg_color="#121212",
            segmented_button_selected_color="#2563eb",
            segmented_button_selected_hover_color="#1d4ed8",
            segmented_button_unselected_hover_color="#1e1e1e",
            text_color="#f1f5f9",
            border_width=1,
            border_color="#27272a"
        )
        self.tabview.grid(row=1, column=0, padx=16, pady=(4, 8), sticky="nsew")

        self.tab_games = self.tabview.add("Games Library")
        self.tab_settings = self.tabview.add("Settings")

        # Setup Tab Contents
        self._setup_settings_tab()
        self._setup_games_tab()

        # Bottom Status & Progress Footer
        self._setup_bottom_footer()

        # Thread-safe GUI Dispatch Queue
        self._gui_queue = queue.Queue()
        self.after(50, self._process_gui_queue)

        # Gamepad & Keyboard Navigation Initialization
        self.controller_manager = GamepadControllerManager(
            action_callback=lambda act: self.run_on_main_thread(self._handle_controller_action, act)
        )
        self.controller_manager.start()
        self._bind_controller_and_keyboard_events()

        # Initial Data Load
        self.refresh_data()

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

    def _bind_controller_and_keyboard_events(self):
        """Binds universal keyboard and Steam Input shortcut keys."""
        self.bind_all("<Up>", lambda e: self._on_key_event(ACTION_UP, e))
        self.bind_all("<Down>", lambda e: self._on_key_event(ACTION_DOWN, e))
        self.bind_all("<Left>", lambda e: self._on_key_event(ACTION_LEFT, e))
        self.bind_all("<Right>", lambda e: self._on_key_event(ACTION_RIGHT, e))
        self.bind_all("<Return>", lambda e: self._on_key_event(ACTION_SELECT, e))
        self.bind_all("<Escape>", lambda e: self._on_key_event(ACTION_BACK, e))
        self.bind_all("<F1>", lambda e: self._on_key_event(ACTION_PREV_TAB, e))
        self.bind_all("<F2>", lambda e: self._on_key_event(ACTION_NEXT_TAB, e))
        self.bind_all("<Prior>", lambda e: self._on_key_event(ACTION_SCROLL_UP, e))
        self.bind_all("<Next>", lambda e: self._on_key_event(ACTION_SCROLL_DOWN, e))

    def _on_key_event(self, action: str, event=None):
        """Filters keyboard events if user is currently typing in an Entry widget."""
        focused_widget = self.focus_get()
        if isinstance(focused_widget, (ctk.CTkEntry,)):
            # If in entry, let standard typing happen except for Escape / Return
            if action == ACTION_BACK:
                self._handle_controller_action(ACTION_BACK)
                return "break"
            elif action == ACTION_SELECT:
                self._handle_controller_action(ACTION_SELECT)
                return "break"
            elif action in (ACTION_UP, ACTION_DOWN):
                self._handle_controller_action(action)
                return "break"
            return None

        self._handle_controller_action(action)
        return "break"

    def _on_search_changed(self, *args):
        """Debounces search input to prevent UI lag during typing."""
        if hasattr(self, 'btn_clear_search'):
            query = self.search_var.get().strip()
            if query:
                self.btn_clear_search.configure(text_color="#f1f5f9", state="normal")
            else:
                self.btn_clear_search.configure(text_color="#52525b", state="disabled")

        if self._search_debounce_job:
            try:
                self.after_cancel(self._search_debounce_job)
            except Exception:
                pass
        self._search_debounce_job = self.after(60, self._apply_filters_and_render)

    def _setup_top_header(self):
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
            text_color="#f1f5f9"
        )
        lbl_app_title.pack(anchor="w")

        self.lbl_stats = ctk.CTkLabel(
            title_block,
            text="Scanning library...",
            font=ctk.CTkFont(size=12),
            text_color="gray"
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
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self.refresh_data
        )
        self.btn_refresh.pack(side="right", padx=(8, 0))

    def _browse_local_path(self):
        """Opens a folder picker to choose local patch repository directory."""
        curr_path = self.entry_local_path.get().strip() or str(Path.home())
        selected = filedialog.askdirectory(
            parent=self,
            title="Select Local Patch Folder",
            initialdir=curr_path
        )
        if selected:
            self.entry_local_path.delete(0, "end")
            self.entry_local_path.insert(0, selected)

    def _setup_settings_tab(self):
        self.tab_settings.grid_columnconfigure(0, weight=1)

        # Connection Mode Header Frame (Row 0)
        mode_header = ctk.CTkFrame(self.tab_settings, fg_color="transparent")
        mode_header.grid(row=0, column=0, padx=12, pady=(12, 6), sticky="w")

        ctk.CTkLabel(mode_header, text="Connection Mode:", font=ctk.CTkFont(weight="bold"), text_color="#f1f5f9").pack(side="left", padx=(0, 12))
        curr_mode = self.config_manager.config.get("mode", "local")
        initial_mode_display = MODE_SMB_DISPLAY if curr_mode == "smb" else MODE_LOCAL_DISPLAY
        self.var_mode = ctk.StringVar(value=initial_mode_display)
        self.opt_mode = ctk.CTkSegmentedButton(
            mode_header,
            values=[MODE_LOCAL_DISPLAY, MODE_SMB_DISPLAY],
            variable=self.var_mode,
            command=self._toggle_settings_fields,
            fg_color="#121212",
            selected_color="#2563eb",
            selected_hover_color="#1d4ed8",
            unselected_hover_color="#1e1e1e",
            text_color="#f1f5f9"
        )
        self.opt_mode.pack(side="left")

        # Dynamic Content Container (Row 1) - unified slot
        self.frame_mode_container = ctk.CTkFrame(self.tab_settings, fg_color="transparent")
        self.frame_mode_container.grid(row=1, column=0, padx=12, pady=4, sticky="nsew")
        self.frame_mode_container.grid_columnconfigure(0, weight=1)

        # Local Settings Frame
        self.frame_local = ctk.CTkFrame(self.frame_mode_container, fg_color="#121212", border_width=1, border_color="#27272a", corner_radius=10)
        self.frame_local.grid(row=0, column=0, sticky="nsew")
        self.frame_local.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self.frame_local, text="Patch Folder Path:", font=ctk.CTkFont(weight="bold"), text_color="#f1f5f9").grid(row=0, column=0, padx=12, pady=12, sticky="w")
        self.entry_local_path = ctk.CTkEntry(
            self.frame_local,
            placeholder_text="/home/deck/Games/Patches or MicroSD path",
            fg_color="#18181b",
            border_color="#27272a",
            border_width=1,
            text_color="#f1f5f9"
        )
        self.entry_local_path.insert(0, self.config_manager.config.get("local_path", ""))
        self.entry_local_path.grid(row=0, column=1, padx=(0, 8), pady=12, sticky="ew")

        btn_browse = ctk.CTkButton(
            self.frame_local,
            text="📂 Browse...",
            width=90,
            fg_color="#27272a",
            hover_color="#3f3f46",
            command=self._browse_local_path
        )
        btn_browse.grid(row=0, column=2, padx=(0, 12), pady=12)

        # SMB Settings Frame
        self.frame_smb = ctk.CTkFrame(self.frame_mode_container, fg_color="#121212", border_width=1, border_color="#27272a", corner_radius=10)
        self.frame_smb.grid(row=0, column=0, sticky="nsew")
        self.frame_smb.grid_columnconfigure(1, weight=1)

        # SMB Fields (Friendlier Labels & Helpful Placeholders)
        smb_fields = [
            ("Server Address / IP:", "smb_server", "e.g. 192.168.1.100 or truenas.local"),
            ("Share Name:", "smb_share", "e.g. Patches or Games"),
            ("Subfolder Path (Optional):", "smb_path", "e.g. Visual Novel Patches/ (leave blank for root)"),
            ("Username (Optional):", "smb_username", "Account or guest username"),
            ("Password (Optional):", "smb_password", "Account password")
        ]

        self.smb_entries = {}
        for idx, (label_text, key, placeholder) in enumerate(smb_fields):
            ctk.CTkLabel(self.frame_smb, text=label_text, text_color="#f1f5f9").grid(row=idx, column=0, padx=12, pady=6, sticky="w")
            entry = ctk.CTkEntry(
                self.frame_smb,
                placeholder_text=placeholder,
                show="*" if "password" in key else "",
                fg_color="#18181b",
                border_color="#27272a",
                border_width=1,
                text_color="#f1f5f9"
            )
            entry.insert(0, self.config_manager.config.get(key, ""))
            entry.grid(row=idx, column=1, padx=12, pady=6, sticky="ew")
            self.smb_entries[key] = entry

        # Stable Footer Container (Row 2)
        frame_actions = ctk.CTkFrame(self.tab_settings, fg_color="transparent")
        frame_actions.grid(row=2, column=0, pady=(24, 10))

        # Save Button
        self.btn_save = ctk.CTkButton(
            frame_actions,
            text="Save Settings & Refresh",
            font=ctk.CTkFont(weight="bold"),
            height=34,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self.save_settings
        )
        self.btn_save.pack(pady=(0, 10))

        # Version Info Label
        self.lbl_version = ctk.CTkLabel(
            frame_actions,
            text=f"{APP_NAME} v{APP_VERSION}",
            font=ctk.CTkFont(size=12),
            text_color="#71717a"
        )
        self.lbl_version.pack()

        self._toggle_settings_fields(self.var_mode.get())

    def _toggle_settings_fields(self, mode):
        """Show/Hide frames based on selected mode."""
        if mode in ("local", MODE_LOCAL_DISPLAY):
            self.frame_local.grid()
            self.frame_smb.grid_remove()
        else:
            self.frame_local.grid_remove()
            self.frame_smb.grid()

    def save_settings(self):
        """Commits GUI inputs to the config manager."""
        mode_val = self.var_mode.get()
        self.config_manager.config["mode"] = "smb" if mode_val in ("smb", MODE_SMB_DISPLAY) else "local"
        self.config_manager.config["local_path"] = self.entry_local_path.get()
        for key, entry in self.smb_entries.items():
            self.config_manager.config[key] = entry.get()

        self.config_manager.save_config()
        self.refresh_data()

    def _setup_games_tab(self):
        self.tab_games.grid_rowconfigure(1, weight=1)
        self.tab_games.grid_columnconfigure(0, weight=1)

        # Toolbar Frame (Search + Filter + View Toggle)
        toolbar_frame = ctk.CTkFrame(self.tab_games, fg_color="transparent")
        toolbar_frame.grid(row=0, column=0, sticky="ew", padx=4, pady=(0, 10))
        toolbar_frame.grid_columnconfigure(0, weight=1)

        # Prominent Search Bar Container
        search_frame = ctk.CTkFrame(
            toolbar_frame,
            fg_color="#18181b",
            border_color="#3f3f46",
            border_width=1,
            corner_radius=8,
            height=34
        )
        search_frame.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        search_frame.grid_columnconfigure(1, weight=1)
        self._search_frame = search_frame

        lbl_search_icon = ctk.CTkLabel(
            search_frame,
            text="🔍",
            font=ctk.CTkFont(size=13),
            text_color="#94a3b8"
        )
        lbl_search_icon.grid(row=0, column=0, padx=(8, 4), pady=2)

        self.entry_search = ctk.CTkEntry(
            search_frame,
            placeholder_text="Search visual novels by title...",
            placeholder_text_color="#71717a",
            textvariable=self.search_var,
            fg_color="transparent",
            border_width=0,
            text_color="#f1f5f9",
            font=ctk.CTkFont(size=12),
            height=30
        )
        self.entry_search.grid(row=0, column=1, sticky="ew", padx=(0, 4), pady=2)
        self.entry_search.bind("<FocusIn>", self._on_search_focused)

        self.btn_clear_search = ctk.CTkButton(
            search_frame,
            text="✕",
            width=26,
            height=26,
            corner_radius=13,
            fg_color="transparent",
            hover_color="#27272a",
            text_color="#52525b",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self.search_var.set("")
        )
        self.btn_clear_search.grid(row=0, column=2, padx=(2, 6), pady=2)

        # Status Filter Container
        filter_frame = ctk.CTkFrame(
            toolbar_frame,
            fg_color="#18181b",
            border_color="#3f3f46",
            border_width=1,
            corner_radius=8
        )
        filter_frame.grid(row=0, column=1, padx=(0, 10))
        self._filter_frame = filter_frame

        self.opt_filter = ctk.CTkSegmentedButton(
            filter_frame,
            values=["All", "Patch Available", "Patched", "Missing 18+ (VNDB)", "Backed Up"],
            variable=self.filter_var,
            command=lambda v: self._apply_filters_and_render(),
            fg_color="#121212",
            selected_color="#2563eb",
            selected_hover_color="#1d4ed8",
            unselected_hover_color="#1e1e1e",
            text_color="#f1f5f9"
        )
        self.opt_filter.pack(padx=2, pady=2)

        # Sort Dropdown Container
        sort_frame = ctk.CTkFrame(
            toolbar_frame,
            fg_color="#18181b",
            border_color="#3f3f46",
            border_width=1,
            corner_radius=8
        )
        sort_frame.grid(row=0, column=2, padx=(0, 10))
        self._sort_frame = sort_frame

        self.opt_sort = ctk.CTkOptionMenu(
            sort_frame,
            values=["Title (A-Z)", "Title (Z-A)", "VNDB Rating", "Status Priority", "Installed First"],
            variable=self.sort_var,
            command=lambda v: self._apply_filters_and_render(),
            width=135,
            fg_color="#121212",
            button_color="#1e1e1e",
            button_hover_color="#27272a",
            text_color="#f1f5f9"
        )
        self.opt_sort.pack(padx=2, pady=2)

        # View Mode Toggle Container
        view_frame = ctk.CTkFrame(
            toolbar_frame,
            fg_color="#18181b",
            border_color="#3f3f46",
            border_width=1,
            corner_radius=8
        )
        view_frame.grid(row=0, column=3)
        self._view_frame = view_frame

        self.opt_view = ctk.CTkSegmentedButton(
            view_frame,
            values=["Grid", "List"],
            variable=self.view_var,
            command=lambda v: self._apply_filters_and_render(),
            fg_color="#121212",
            selected_color="#2563eb",
            selected_hover_color="#1d4ed8",
            unselected_hover_color="#1e1e1e",
            text_color="#f1f5f9"
        )
        self.opt_view.pack(padx=2, pady=2)

        # Scrollable Game Area - OLED Pure Black Surface
        self.scrollable_games = ctk.CTkScrollableFrame(
            self.tab_games,
            fg_color="#000000",
            corner_radius=10,
            border_width=1,
            border_color="#18181b"
        )
        self.scrollable_games.grid(row=1, column=0, sticky="nsew")
        self.scrollable_games.grid_columnconfigure(0, weight=1)

    def _setup_bottom_footer(self):
        footer_frame = ctk.CTkFrame(self, fg_color="transparent")
        footer_frame.grid(row=2, column=0, padx=20, pady=(4, 12), sticky="ew")
        footer_frame.grid_columnconfigure(0, weight=1)

        self.lbl_status = ctk.CTkLabel(footer_frame, text="Ready", font=ctk.CTkFont(size=12), text_color="gray")
        self.lbl_status.grid(row=0, column=0, sticky="w")

        self.progress_bar = ctk.CTkProgressBar(footer_frame, width=200, height=8, mode="indeterminate", progress_color="#2563eb")
        self.progress_bar.grid(row=0, column=1, sticky="e")
        self.progress_bar.set(0)

    def _on_search_focused(self, event=None):
        """Invoked when the search entry receives focus; automatically opens the SteamOS OSK."""
        self._focused_zone = "TOOLBAR"
        self._focused_toolbar_idx = 0
        SteamOSHelper.show_onscreen_keyboard()
        self._apply_focus_visuals()

    def _on_search_submit(self):
        """Dismisses the OSK and returns focus to the game library."""
        SteamOSHelper.hide_onscreen_keyboard()
        self.focus_set()
        self._focused_zone = "LIBRARY"
        self._focused_card_idx = 0
        self._focused_btn_idx = -1
        self._apply_focus_visuals()

    def _handle_controller_action(self, action: str):
        """Processes virtual controller and keyboard navigation actions."""
        # 1. Global Tab Switching (L1 / R1)
        if action == ACTION_PREV_TAB:
            self.tabview.set("Games Library")
            self._focused_tab_idx = 0
            self._focused_zone = "LIBRARY"
            self._apply_focus_visuals()
            return
        elif action == ACTION_NEXT_TAB:
            self.tabview.set("Settings")
            self._focused_tab_idx = 1
            self._focused_zone = "SETTINGS"
            self._apply_focus_visuals()
            return

        # 2. Global Quick Search (Y Button)
        if action == ACTION_SEARCH:
            self.tabview.set("Games Library")
            self._focused_tab_idx = 0
            self._focused_zone = "TOOLBAR"
            self._focused_toolbar_idx = 0
            self.entry_search.focus_set()
            SteamOSHelper.show_onscreen_keyboard()
            self._apply_focus_visuals()
            return

        # 3. Fast Page Scrolling (L2 / R2 / Right Stick)
        if action == ACTION_SCROLL_UP:
            try:
                self.scrollable_games._parent_canvas.yview_scroll(-4, "units")
            except Exception:
                pass
            return
        elif action == ACTION_SCROLL_DOWN:
            try:
                self.scrollable_games._parent_canvas.yview_scroll(4, "units")
            except Exception:
                pass
            return

        # 4. Zone: HEADER (Top Header - Scan Games & Patches button)
        if self._focused_zone == "HEADER":
            if action == ACTION_LEFT:
                self._focused_zone = "TABS"
                self._focused_tab_idx = 1 if self.tabview.get() == "Settings" else 0
                self._apply_focus_visuals()
            elif action == ACTION_DOWN:
                if self.tabview.get() == "Settings":
                    self._focused_zone = "SETTINGS"
                else:
                    self._focused_zone = "TOOLBAR"
                    self._focused_toolbar_idx = 3
                self._apply_focus_visuals()
            elif action in (ACTION_SELECT, ACTION_QUICK_ACTION):
                self.refresh_data()
            elif action == ACTION_BACK:
                self._focused_zone = "TABS"
                self._focused_tab_idx = 0
                self._apply_focus_visuals()
            return

        # 5. Zone: TABS (Top Tab Bar)
        if self._focused_zone == "TABS":
            if action == ACTION_LEFT:
                if self._focused_tab_idx == 1:
                    self._focused_tab_idx = 0
                    self.tabview.set("Games Library")
                    self._apply_focus_visuals()
            elif action == ACTION_RIGHT:
                if self._focused_tab_idx == 0:
                    self._focused_tab_idx = 1
                    self.tabview.set("Settings")
                    self._apply_focus_visuals()
                else:
                    self._focused_zone = "HEADER"
                    self._apply_focus_visuals()
            elif action == ACTION_UP:
                self._focused_zone = "HEADER"
                self._apply_focus_visuals()
            elif action == ACTION_SELECT:
                if self._focused_tab_idx == 0:
                    self.tabview.set("Games Library")
                    self._focused_zone = "TOOLBAR"
                    self._focused_toolbar_idx = 0
                else:
                    self.tabview.set("Settings")
                    self._focused_zone = "SETTINGS"
                self._apply_focus_visuals()
            elif action == ACTION_DOWN:
                if self.tabview.get() == "Games Library":
                    self._focused_zone = "TOOLBAR"
                    self._focused_toolbar_idx = 0
                else:
                    self._focused_zone = "SETTINGS"
                self._apply_focus_visuals()
            elif action == ACTION_BACK:
                if self.tabview.get() == "Games Library":
                    self._focused_zone = "LIBRARY"
                else:
                    self._focused_zone = "SETTINGS"
                self._apply_focus_visuals()
            return

        # 6. Zone: TOOLBAR
        if self._focused_zone == "TOOLBAR":
            filter_options = ["All", "Patch Available", "Patched", "Missing 18+ (VNDB)", "Backed Up"]
            sort_options = ["Title (A-Z)", "Title (Z-A)", "VNDB Rating", "Status Priority", "Installed First"]
            view_options = ["Grid", "List"]

            if action == ACTION_UP:
                self._focused_zone = "TABS"
                self._focused_tab_idx = 0
                self.focus_set()
                SteamOSHelper.hide_onscreen_keyboard()
                self._apply_focus_visuals()
            elif action == ACTION_LEFT:
                self._focused_toolbar_idx = (self._focused_toolbar_idx - 1) % 4
                self._apply_focus_visuals()
            elif action == ACTION_RIGHT:
                self._focused_toolbar_idx = (self._focused_toolbar_idx + 1) % 4
                self._apply_focus_visuals()
            elif action == ACTION_DOWN:
                self._focused_zone = "LIBRARY"
                self._focused_card_idx = 0
                self._focused_btn_idx = -1
                self.focus_set()
                SteamOSHelper.hide_onscreen_keyboard()
                self._apply_focus_visuals()
            elif action == ACTION_SELECT:
                if self._focused_toolbar_idx == 0:  # Search
                    self.entry_search.focus_set()
                    SteamOSHelper.show_onscreen_keyboard()
                elif self._focused_toolbar_idx == 1:  # Filter
                    curr_filter = self.filter_var.get()
                    curr_idx = filter_options.index(curr_filter) if curr_filter in filter_options else 0
                    next_idx = (curr_idx + 1) % len(filter_options)
                    self.filter_var.set(filter_options[next_idx])
                    self._apply_filters_and_render()
                elif self._focused_toolbar_idx == 2:  # Sort
                    curr_sort = self.sort_var.get()
                    curr_idx = sort_options.index(curr_sort) if curr_sort in sort_options else 0
                    next_idx = (curr_idx + 1) % len(sort_options)
                    self.sort_var.set(sort_options[next_idx])
                    self._apply_filters_and_render()
                elif self._focused_toolbar_idx == 3:  # View
                    curr_view = self.view_var.get()
                    curr_idx = view_options.index(curr_view) if curr_view in view_options else 0
                    next_idx = (curr_idx + 1) % len(view_options)
                    self.view_var.set(view_options[next_idx])
                    self._apply_filters_and_render()
            elif action == ACTION_BACK:
                self._on_search_submit()
            return

        # 6. Zone: SETTINGS
        if self._focused_zone == "SETTINGS":
            if action == ACTION_UP:
                self._focused_zone = "TABS"
                self._focused_tab_idx = 1
                self._apply_focus_visuals()
            elif action == ACTION_LEFT:
                self.var_mode.set(MODE_LOCAL_DISPLAY)
                self._toggle_settings_fields(MODE_LOCAL_DISPLAY)
            elif action == ACTION_RIGHT:
                self.var_mode.set(MODE_SMB_DISPLAY)
                self._toggle_settings_fields(MODE_SMB_DISPLAY)
            elif action == ACTION_SELECT or action == ACTION_QUICK_ACTION:
                self.save_settings()
            elif action == ACTION_BACK:
                self.tabview.set("Games Library")
                self._focused_zone = "LIBRARY"
                self._focused_tab_idx = 0
                self._apply_focus_visuals()
            return

        # 7. Zone: LIBRARY
        if self._focused_zone == "LIBRARY":
            num_cards = len(self._card_entries)
            if num_cards == 0:
                if action == ACTION_UP:
                    self._focused_zone = "TOOLBAR"
                    self._focused_toolbar_idx = 0
                    self._apply_focus_visuals()
                return

            is_grid = ("Grid" in self.view_var.get())
            current_entry = self._card_entries[self._focused_card_idx] if 0 <= self._focused_card_idx < num_cards else None
            num_buttons = len(current_entry["buttons"]) if current_entry else 0

            if action == ACTION_UP:
                if self._focused_btn_idx >= 0:
                    # Move focus back to card container
                    self._focused_btn_idx = -1
                    self._apply_focus_visuals()
                else:
                    if is_grid:
                        if self._focused_card_idx in (0, 1):
                            self._focused_zone = "TOOLBAR"
                            self._focused_toolbar_idx = 0
                            self._apply_focus_visuals()
                        else:
                            self._focused_card_idx = max(0, self._focused_card_idx - 2)
                            self._apply_focus_visuals()
                    else:
                        if self._focused_card_idx == 0:
                            self._focused_zone = "TOOLBAR"
                            self._focused_toolbar_idx = 0
                            self._apply_focus_visuals()
                        else:
                            self._focused_card_idx = max(0, self._focused_card_idx - 1)
                            self._apply_focus_visuals()

            elif action == ACTION_DOWN:
                if self._focused_btn_idx == -1 and num_buttons > 0:
                    # Step down into the action button row
                    self._focused_btn_idx = 0
                    self._apply_focus_visuals()
                else:
                    self._focused_btn_idx = -1
                    if is_grid:
                        self._focused_card_idx = min(num_cards - 1, self._focused_card_idx + 2)
                    else:
                        self._focused_card_idx = min(num_cards - 1, self._focused_card_idx + 1)
                    self._apply_focus_visuals()

            elif action == ACTION_LEFT:
                if self._focused_btn_idx > 0:
                    self._focused_btn_idx -= 1
                    self._apply_focus_visuals()
                elif is_grid and self._focused_btn_idx == -1 and (self._focused_card_idx % 2 == 1):
                    self._focused_card_idx -= 1
                    self._apply_focus_visuals()

            elif action == ACTION_RIGHT:
                if self._focused_btn_idx >= 0 and self._focused_btn_idx < num_buttons - 1:
                    self._focused_btn_idx += 1
                    self._apply_focus_visuals()
                elif is_grid and self._focused_btn_idx == -1 and (self._focused_card_idx % 2 == 0) and (self._focused_card_idx + 1 < num_cards):
                    self._focused_card_idx += 1
                    self._apply_focus_visuals()

            elif action == ACTION_SELECT:
                if current_entry:
                    if self._focused_btn_idx >= 0 and self._focused_btn_idx < num_buttons:
                        current_entry["buttons"][self._focused_btn_idx].invoke()
                    elif current_entry.get("default_button"):
                        current_entry["default_button"].invoke()

            elif action == ACTION_QUICK_ACTION:  # X Button
                if current_entry and current_entry.get("default_button"):
                    current_entry["default_button"].invoke()

            elif action == ACTION_BACK:
                if self._focused_btn_idx >= 0:
                    self._focused_btn_idx = -1
                    self._apply_focus_visuals()
                elif self.search_var.get():
                    self.search_var.set("")
                    self._apply_focus_visuals()

    def _apply_focus_visuals(self):
        """Updates high-contrast OLED visual focus borders across all UI components."""
        # 1. Update Tabview and Toolbar Focus Highlights
        is_tabs_focused = (self._focused_zone == "TABS")
        if hasattr(self, 'tabview') and self.tabview.winfo_exists():
            self.tabview.configure(
                border_color="#3b82f6" if is_tabs_focused else "#27272a",
                border_width=2 if is_tabs_focused else 1
            )

        if hasattr(self, 'btn_save') and self.btn_save.winfo_exists():
            is_settings_focused = (self._focused_zone == "SETTINGS")
            self.btn_save.configure(
                border_color="#60a5fa" if is_settings_focused else "#1d4ed8",
                border_width=2 if is_settings_focused else 0
            )

        if self._search_frame and self._search_frame.winfo_exists():
            is_search_focused = (self._focused_zone == "TOOLBAR" and self._focused_toolbar_idx == 0)
            self._search_frame.configure(
                border_color="#3b82f6" if is_search_focused else "#3f3f46",
                border_width=2 if is_search_focused else 1
            )

        if hasattr(self, '_filter_frame') and self._filter_frame and self._filter_frame.winfo_exists():
            is_filter_focused = (self._focused_zone == "TOOLBAR" and self._focused_toolbar_idx == 1)
            self._filter_frame.configure(
                border_color="#3b82f6" if is_filter_focused else "#3f3f46",
                border_width=2 if is_filter_focused else 1
            )

        if hasattr(self, '_sort_frame') and self._sort_frame and self._sort_frame.winfo_exists():
            is_sort_focused = (self._focused_zone == "TOOLBAR" and self._focused_toolbar_idx == 2)
            self._sort_frame.configure(
                border_color="#3b82f6" if is_sort_focused else "#3f3f46",
                border_width=2 if is_sort_focused else 1
            )

        if hasattr(self, '_view_frame') and self._view_frame and self._view_frame.winfo_exists():
            is_view_focused = (self._focused_zone == "TOOLBAR" and self._focused_toolbar_idx == 3)
            self._view_frame.configure(
                border_color="#3b82f6" if is_view_focused else "#3f3f46",
                border_width=2 if is_view_focused else 1
            )

        if hasattr(self, 'btn_refresh') and self.btn_refresh.winfo_exists():
            is_refresh_focused = (self._focused_zone == "HEADER")
            self.btn_refresh.configure(
                border_color="#60a5fa" if is_refresh_focused else "#1d4ed8",
                border_width=2 if is_refresh_focused else 0,
                fg_color="#1d4ed8" if is_refresh_focused else "#2563eb"
            )

        # 2. Update Card Focus Highlights
        for idx, entry in enumerate(self._card_entries):
            card = entry.get("card")
            if not card or not card.winfo_exists():
                continue

            is_card_focused = (self._focused_zone == "LIBRARY" and idx == self._focused_card_idx)

            if is_card_focused:
                # Vibrant Glowing Blue Focus Outline + Elevated Surface
                card.configure(
                    border_color="#3b82f6",
                    border_width=3,
                    fg_color="#1e293b"
                )
                self._scroll_card_into_view(card)
            else:
                card.configure(
                    border_color="#27272a",
                    border_width=1,
                    fg_color="#121212"
                )

            # Update Button Highlights inside this card
            buttons = entry.get("buttons", [])
            for b_idx, btn in enumerate(buttons):
                if not btn.winfo_exists():
                    continue
                if is_card_focused and b_idx == self._focused_btn_idx:
                    # Highlighted active button
                    btn.configure(border_color="#93c5fd", border_width=2)
                else:
                    btn.configure(border_width=0 if btn.cget("fg_color") != "transparent" else 1)

    def _scroll_card_into_view(self, card_widget):
        """Auto-scrolls the scrollable frame viewport so the focused card is fully visible."""
        try:
            canvas = self.scrollable_games._parent_canvas
            card_y = card_widget.winfo_y()
            card_h = card_widget.winfo_height() or 120
            canvas_h = canvas.winfo_height() or 500
            total_h = self.scrollable_games.winfo_height() or 1000

            if total_h > canvas_h and total_h > 0:
                fraction = max(0.0, min(1.0, (card_y - 20) / max(total_h - canvas_h, 1)))
                canvas.yview_moveto(fraction)
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
                    vn_info = cached_vndb.get(app_id, {})
                    game_data["vndb"] = vn_info
                    has_local_patch = app_id in self.repo.available_patches
                    has_vndb_18_patch = vn_info.get("has_18plus_en_patch", False)
                    is_installed = bool(game_data.get("is_installed", True)) and bool(game_data.get("path"))

                    if has_local_patch:
                        supported[app_id] = game_data
                    elif has_vndb_18_patch and (not is_installed or (is_installed and vn_info.get("is_vn", False))):
                        if vn_info.get("is_vn", False):
                            if not is_installed and vn_info.get("vn_title"):
                                game_data["name"] = vn_info["vn_title"]
                            supported[app_id] = game_data

                # Pre-compute status & search index for each supported game in background
                for aid, gdata in supported.items():
                    gdata["status_info"] = self._compute_status_info(aid, gdata)

                # Pre-fetch cover arts
                for app_id, gdata in supported.items():
                    try:
                        is_new = self.cover_manager.download_cover(app_id)
                        if is_new:
                            self.run_on_main_thread(lambda aid=app_id: self._refresh_banner(aid))
                    except Exception:
                        pass

                self.run_on_main_thread(lambda: self._populate_game_list(supported))

            except Exception as e:
                logger.error(f"Error during refresh: {e}", exc_info=True)
                self.run_on_main_thread(lambda: self.lbl_status.configure(text=f"Error: {e}", text_color="#ff4444"))
            finally:
                self.run_on_main_thread(self._stop_progress)

        threading.Thread(target=_worker, daemon=True).start()

    def _stop_progress(self):
        self.progress_bar.stop()
        self.progress_bar.configure(mode="determinate")
        self.progress_bar.set(0)

    def _populate_game_list(self, supported_games: dict):
        self._all_supported_games = supported_games
        self._apply_filters_and_render()

    def _apply_filters_and_render(self):
        if self._active_render_job:
            try:
                self.after_cancel(self._active_render_job)
            except Exception:
                pass
            self._active_render_job = None

        for widget in self.scrollable_games.winfo_children():
            widget.destroy()

        self._card_entries.clear()

        if not self._all_supported_games:
            ctk.CTkLabel(self.scrollable_games, text="No patchable visual novels found.", font=ctk.CTkFont(size=14)).pack(pady=40)
            self.lbl_status.configure(text="Scan complete. No patchable visual novels found.", text_color="gray")
            self.lbl_stats.configure(text="0 Patchable VNs Found")
            return

        search_query = self.search_var.get().strip().lower()
        active_filter = self.filter_var.get()
        view_mode = self.view_var.get()

        matched_games = {}
        total_patched = 0
        total_backed_up = 0
        total_local_available = 0
        total_missing_18 = 0

        for app_id, game_data in self._all_supported_games.items():
            s_info = game_data.get("status_info")
            if not s_info:
                s_info = self._compute_status_info(app_id, game_data)
                game_data["status_info"] = s_info

            is_patched = s_info["is_patched"]
            has_backup = s_info["has_backup"]
            has_local_patch = s_info["has_local_patch"]
            has_vndb_18_patch = s_info["has_vndb_18_patch"]

            if is_patched:
                total_patched += 1
            elif has_local_patch:
                total_local_available += 1
            elif has_vndb_18_patch:
                total_missing_18 += 1

            if has_backup:
                total_backed_up += 1

            # Check Search query across comprehensive pre-computed haystack
            if search_query and search_query not in s_info["search_haystack"]:
                continue

            # Check Status Filter
            if active_filter == "Patch Available" and (is_patched or not has_local_patch):
                continue
            if active_filter == "Patched" and not is_patched:
                continue
            if active_filter == "Missing 18+ (VNDB)" and (is_patched or has_local_patch or not has_vndb_18_patch):
                continue
            if active_filter == "Backed Up" and not has_backup:
                continue

            matched_games[app_id] = game_data

        total_vns = len(self._all_supported_games)
        self.lbl_stats.configure(
            text=f"{total_vns} Patchable VNs • {total_local_available} Local Patches • {total_missing_18} Missing 18+ (VNDB) • {total_patched} Patched"
        )

        if not matched_games:
            ctk.CTkLabel(self.scrollable_games, text="No Visual Novels match the current search/filter.", font=ctk.CTkFont(size=13)).pack(pady=40)
            self.lbl_status.configure(text="Filter active: 0 matches.", text_color="gray")
            return

        # Apply Library Sorting
        sort_mode = self.sort_var.get()

        if sort_mode == "Title (Z-A)":
            sorted_games = dict(sorted(matched_games.items(), key=lambda x: x[1]["name"].lower(), reverse=True))
        elif sort_mode == "VNDB Rating":
            sorted_games = dict(sorted(
                matched_games.items(),
                key=lambda x: (
                    x[1].get("vndb", {}).get("rating") is not None,
                    x[1].get("vndb", {}).get("rating") or 0.0,
                    x[1].get("vndb", {}).get("votecount") or 0,
                    x[1]["name"].lower()
                ),
                reverse=True
            ))
        elif sort_mode == "Status Priority":
            sorted_games = dict(sorted(
                matched_games.items(),
                key=lambda x: (x[1].get("status_info", {}).get("status_priority", 3), x[1]["name"].lower())
            ))
        elif sort_mode == "Installed First":
            sorted_games = dict(sorted(
                matched_games.items(),
                key=lambda x: (not x[1].get("is_installed", False), x[1]["name"].lower())
            ))
        else:  # Default: Title (A-Z)
            sorted_games = dict(sorted(matched_games.items(), key=lambda x: x[1]["name"].lower()))

        self._banner_widgets.clear()
        if "Grid" in view_mode:
            self._render_grid_view(sorted_games)
        else:
            self._render_list_view(sorted_games)

        self.lbl_status.configure(text=f"Showing {len(matched_games)} of {total_vns} Visual Novel(s).", text_color="gray")

    def _compute_status_info(self, app_id: str, game_data: dict) -> dict:
        """Computes installation, patch, backup, and rating status for a game once and caches it."""
        vn_info = game_data.get("vndb", {})
        patch_info = self.repo.available_patches.get(app_id)
        is_installed = bool(game_data.get("is_installed", True)) and bool(game_data.get("path"))
        is_patched = is_installed and PatchExecutionEngine.get_patch_status(game_data["path"], patch_info, vn_info)
        has_backup = is_installed and BackupManager.has_backup(game_data["path"])
        has_clean_backup = is_installed and BackupManager.has_clean_backup(game_data["path"])
        has_local_patch = app_id in self.repo.available_patches
        has_vndb_18_patch = vn_info.get("has_18plus_en_patch", False)

        if is_patched:
            status_text = "● Patched (Verified)"
            status_color = "#10b981"
            status_priority = 2
        elif has_local_patch:
            status_text = "● Patch Available"
            status_color = "#f59e0b"
            status_priority = 0 if is_installed else 3
        elif has_vndb_18_patch:
            status_text = "● Missing 18+ Patch (VNDB)"
            status_color = "#f43f5e"
            status_priority = 1
        else:
            status_text = ""
            status_color = "#94a3b8"
            status_priority = 3

        # Pre-compute unified lowercase search index
        name_str = game_data.get("name", "").lower()
        vn_title_str = vn_info.get("vn_title", "").lower()
        vn_id_str = vn_info.get("vn_id", "").lower()
        search_haystack = f"{name_str} {vn_title_str} {str(app_id)} {vn_id_str}".strip()

        return {
            "is_installed": is_installed,
            "is_patched": is_patched,
            "has_backup": has_backup,
            "has_clean_backup": has_clean_backup,
            "has_local_patch": has_local_patch,
            "has_vndb_18_patch": has_vndb_18_patch,
            "status_text": status_text,
            "status_color": status_color,
            "status_priority": status_priority,
            "rating": vn_info.get("rating"),
            "vn_info": vn_info,
            "patch_info": patch_info,
            "search_haystack": search_haystack
        }

    def _get_game_status_info(self, app_id: str, game_data: dict) -> dict:
        """Returns pre-computed status info or computes on demand."""
        return game_data.get("status_info") or self._compute_status_info(app_id, game_data)

    def _refresh_banner(self, app_id: str):
        """Refreshes active banner widgets for a newly downloaded game cover."""
        app_id = str(app_id)
        if app_id in self._banner_widgets:
            for lbl, title, sz in self._banner_widgets[app_id]:
                try:
                    if lbl.winfo_exists():
                        new_img = self.cover_manager.get_cover_image(app_id, title=title, size=sz)
                        lbl.configure(image=new_img)
                except Exception:
                    pass

    def _render_badges(self, parent_frame, status_info: dict):
        """Renders status and attribute badges in the provided container."""
        lbl_status_badge = ctk.CTkLabel(
            parent_frame,
            text=status_info["status_text"],
            text_color=status_info["status_color"],
            font=ctk.CTkFont(size=12, weight="bold")
        )
        lbl_status_badge.pack(side="left", padx=(0, 6))

        if status_info["rating"] is not None:
            ctk.CTkLabel(
                parent_frame,
                text=f"★ {status_info['rating']:.1f}",
                text_color="#fbbf24",
                font=ctk.CTkFont(size=11, weight="bold")
            ).pack(side="left", padx=(0, 6))

        if not status_info["is_installed"]:
            ctk.CTkLabel(parent_frame, text="💾 Not Installed", text_color="#94a3b8", font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 4))
        elif status_info["has_clean_backup"]:
            ctk.CTkLabel(parent_frame, text="💾 Clean Backup", text_color="#38bdf8", font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 4))
        elif status_info["has_backup"]:
            ctk.CTkLabel(parent_frame, text="⚠️ Pre-Patched Backup", text_color="#fbbf24", font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 4))

        if status_info["has_vndb_18_patch"] and not status_info["is_patched"] and status_info["has_local_patch"]:
            ctk.CTkLabel(parent_frame, text="🔞 18+ on VNDB", text_color="#ec4899", font=ctk.CTkFont(size=11)).pack(side="left")

    def _render_grid_view(self, games_dict):
        self.scrollable_games.grid_columnconfigure(0, weight=1)
        self.scrollable_games.grid_columnconfigure(1, weight=1)

        items = list(games_dict.items())

        def render_batch(start_idx, batch_size=10):
            if start_idx >= len(items):
                self._apply_focus_visuals()
                return
            end_idx = min(start_idx + batch_size, len(items))
            for idx in range(start_idx, end_idx):
                app_id, game_data = items[idx]
                row_idx = idx // 2
                col_idx = idx % 2

                card = ctk.CTkFrame(
                    self.scrollable_games,
                    corner_radius=12,
                    fg_color="#121212",
                    border_width=1,
                    border_color="#27272a"
                )
                card.grid(row=row_idx, column=col_idx, padx=8, pady=8, sticky="nsew")
                card.grid_columnconfigure(0, weight=1)
                card.grid_rowconfigure(1, weight=1)

                # 1. Top Cover Banner
                cover_img = self.cover_manager.get_cover_image(app_id, title=game_data["name"], size=(280, 130))
                lbl_banner = ctk.CTkLabel(card, text="", image=cover_img, corner_radius=8)
                lbl_banner.grid(row=0, column=0, padx=10, pady=(10, 6), sticky="ew")
                self._banner_widgets.setdefault(str(app_id), []).append((lbl_banner, game_data["name"], (280, 130)))

                # 2. Content Info Frame
                info_frame = ctk.CTkFrame(card, fg_color="transparent")
                info_frame.grid(row=1, column=0, padx=12, pady=4, sticky="ew")
                info_frame.grid_columnconfigure(0, weight=1)

                # Game Title
                ctk.CTkLabel(
                    info_frame,
                    text=game_data["name"],
                    font=ctk.CTkFont(size=14, weight="bold"),
                    text_color="#f1f5f9",
                    wraplength=270,
                    justify="left"
                ).pack(anchor="w", pady=(0, 4))

                # Badges Row
                status_info = self._get_game_status_info(app_id, game_data)
                is_patched = status_info["is_patched"]
                has_clean_backup = status_info["has_clean_backup"]
                has_backup = status_info["has_backup"]
                has_local_patch = status_info["has_local_patch"]
                vn_info = status_info["vn_info"]

                badges_row = ctk.CTkFrame(info_frame, fg_color="transparent")
                badges_row.pack(anchor="w", fill="x", pady=2)
                self._render_badges(badges_row, status_info)

                # 3. Actions Button Row
                actions_frame = ctk.CTkFrame(card, fg_color="transparent")
                actions_frame.grid(row=2, column=0, padx=10, pady=(6, 12), sticky="sew")

                patch_data = self.repo.available_patches.get(app_id)
                card_buttons = []
                default_btn = None

                if has_local_patch:
                    btn_text = "Verify / Re-apply" if is_patched else "Apply Patch"
                    btn_apply = ctk.CTkButton(
                        actions_frame,
                        text=btn_text,
                        font=ctk.CTkFont(size=12, weight="bold"),
                        height=32,
                        fg_color="#2563eb",
                        hover_color="#1d4ed8",
                        command=lambda g=game_data, p=patch_data: self.run_patch(g, p)
                    )
                    if is_patched:
                        btn_apply.configure(fg_color="transparent", border_width=1)
                    btn_apply.pack(side="left", fill="x", expand=True, padx=(0, 4))
                    card_buttons.append(btn_apply)
                    default_btn = btn_apply

                    if has_clean_backup:
                        btn_rollback = ctk.CTkButton(
                            actions_frame,
                            text="Restore (Backup)",
                            font=ctk.CTkFont(size=11),
                            height=32,
                            fg_color="#c0392b",
                            hover_color="#e74c3c",
                            command=lambda g=game_data: self.run_rollback(g)
                        )
                        btn_rollback.pack(side="left", fill="x", expand=True, padx=2)
                        card_buttons.append(btn_rollback)

                    if is_patched or has_backup:
                        btn_steam = ctk.CTkButton(
                            actions_frame,
                            text="Restore via Steam",
                            font=ctk.CTkFont(size=11),
                            height=32,
                            fg_color="#4f46e5",
                            hover_color="#6366f1",
                            command=lambda g=game_data, p=patch_data: self.run_steam_restore(g, p)
                        )
                        btn_steam.pack(side="left", fill="x", expand=True, padx=(4, 0))
                        card_buttons.append(btn_steam)

                else:
                    # Missing local patch (has 18+ patch on VNDB)
                    if is_patched:
                        btn_steam = ctk.CTkButton(
                            actions_frame,
                            text="Restore via Steam",
                            font=ctk.CTkFont(size=11),
                            height=32,
                            fg_color="#4f46e5",
                            hover_color="#6366f1",
                            command=lambda g=game_data, p=patch_data: self.run_steam_restore(g, p)
                        )
                        btn_steam.pack(side="left", fill="x", expand=True, padx=(0, 4))
                        card_buttons.append(btn_steam)
                        default_btn = btn_steam

                    vndb_url = vn_info.get("vndb_url") or (f"https://vndb.org/{vn_info.get('vn_id')}" if vn_info.get("vn_id") else None)
                    if vndb_url:
                        btn_vndb = ctk.CTkButton(
                            actions_frame,
                            text="🔗 Open VNDB (Get Patch)",
                            font=ctk.CTkFont(size=12, weight="bold"),
                            height=32,
                            fg_color="#0284c7",
                            hover_color="#0369a1",
                            command=lambda u=vndb_url: webbrowser.open(u)
                        )
                        btn_vndb.pack(side="left", fill="x", expand=True)
                        card_buttons.append(btn_vndb)
                        if not default_btn:
                            default_btn = btn_vndb

                self._card_entries.append({
                    "card": card,
                    "app_id": app_id,
                    "game_data": game_data,
                    "buttons": card_buttons,
                    "default_button": default_btn
                })

            if end_idx < len(items):
                self._active_render_job = self.after(16, lambda: render_batch(end_idx, batch_size))
            else:
                self._active_render_job = None
                self._apply_focus_visuals()
        
        render_batch(0)

    def _render_list_view(self, games_dict):
        self.scrollable_games.grid_columnconfigure(0, weight=1)
        self.scrollable_games.grid_columnconfigure(1, weight=0)

        items = list(games_dict.items())

        def render_batch(start_idx, batch_size=15):
            if start_idx >= len(items):
                self._apply_focus_visuals()
                return
            end_idx = min(start_idx + batch_size, len(items))
            for row_idx in range(start_idx, end_idx):
                app_id, game_data = items[row_idx]
                card = ctk.CTkFrame(
                    self.scrollable_games,
                    corner_radius=8,
                    fg_color="#121212",
                    border_width=1,
                    border_color="#27272a"
                )
                card.grid(row=row_idx, column=0, padx=6, pady=4, sticky="ew")
                card.grid_columnconfigure(1, weight=1)

                # 1. Mini Thumbnail
                cover_img = self.cover_manager.get_cover_image(app_id, title=game_data["name"], size=(80, 44))
                lbl_thumb = ctk.CTkLabel(card, text="", image=cover_img)
                lbl_thumb.grid(row=0, column=0, padx=(10, 12), pady=8)
                self._banner_widgets.setdefault(str(app_id), []).append((lbl_thumb, game_data["name"], (80, 44)))

                # 2. Title & Path Info
                info_frame = ctk.CTkFrame(card, fg_color="transparent")
                info_frame.grid(row=0, column=1, sticky="w", pady=6)

                ctk.CTkLabel(
                    info_frame,
                    text=game_data["name"],
                    font=ctk.CTkFont(size=14, weight="bold"),
                    text_color="#f1f5f9"
                ).pack(anchor="w")

                # Badges Row
                status_info = self._get_game_status_info(app_id, game_data)
                is_patched = status_info["is_patched"]
                has_clean_backup = status_info["has_clean_backup"]
                has_backup = status_info["has_backup"]
                has_local_patch = status_info["has_local_patch"]
                vn_info = status_info["vn_info"]

                badges_row = ctk.CTkFrame(info_frame, fg_color="transparent")
                badges_row.pack(anchor="w", pady=(2, 0))
                self._render_badges(badges_row, status_info)

                # 3. Actions Row
                actions_frame = ctk.CTkFrame(card, fg_color="transparent")
                actions_frame.grid(row=0, column=2, padx=12, pady=8, sticky="e")

                patch_data = self.repo.available_patches.get(app_id)
                card_buttons = []
                default_btn = None

                if has_local_patch:
                    btn_text = "Verify / Re-apply" if is_patched else "Apply Patch"
                    btn_apply = ctk.CTkButton(
                        actions_frame,
                        text=btn_text,
                        font=ctk.CTkFont(size=12),
                        height=30,
                        fg_color="#2563eb",
                        hover_color="#1d4ed8",
                        command=lambda g=game_data, p=patch_data: self.run_patch(g, p)
                    )
                    if is_patched:
                        btn_apply.configure(fg_color="transparent", border_width=1)
                    btn_apply.pack(side="left", padx=(0, 4))
                    card_buttons.append(btn_apply)
                    default_btn = btn_apply

                    if has_clean_backup:
                        btn_rollback = ctk.CTkButton(
                            actions_frame,
                            text="Restore (Backup)",
                            font=ctk.CTkFont(size=11),
                            height=30,
                            fg_color="#c0392b",
                            hover_color="#e74c3c",
                            command=lambda g=game_data: self.run_rollback(g)
                        )
                        btn_rollback.pack(side="left", padx=(0, 4))
                        card_buttons.append(btn_rollback)

                    if is_patched or has_backup:
                        btn_steam = ctk.CTkButton(
                            actions_frame,
                            text="Restore via Steam",
                            font=ctk.CTkFont(size=11),
                            height=30,
                            fg_color="#4f46e5",
                            hover_color="#6366f1",
                            command=lambda g=game_data, p=patch_data: self.run_steam_restore(g, p)
                        )
                        btn_steam.pack(side="left")
                        card_buttons.append(btn_steam)

                else:
                    # Missing local patch (has 18+ patch on VNDB)
                    if is_patched:
                        btn_steam = ctk.CTkButton(
                            actions_frame,
                            text="Restore via Steam",
                            font=ctk.CTkFont(size=11),
                            height=30,
                            fg_color="#4f46e5",
                            hover_color="#6366f1",
                            command=lambda g=game_data, p=patch_data: self.run_steam_restore(g, p)
                        )
                        btn_steam.pack(side="left", padx=(0, 4))
                        card_buttons.append(btn_steam)
                        default_btn = btn_steam

                    vndb_url = vn_info.get("vndb_url") or (f"https://vndb.org/{vn_info.get('vn_id')}" if vn_info.get("vn_id") else None)
                    if vndb_url:
                        btn_vndb = ctk.CTkButton(
                            actions_frame,
                            text="🔗 Open VNDB (Get Patch)",
                            font=ctk.CTkFont(size=12, weight="bold"),
                            height=30,
                            fg_color="#0284c7",
                            hover_color="#0369a1",
                            command=lambda u=vndb_url: webbrowser.open(u)
                        )
                        btn_vndb.pack(side="left")
                        card_buttons.append(btn_vndb)
                        if not default_btn:
                            default_btn = btn_vndb

                self._card_entries.append({
                    "card": card,
                    "app_id": app_id,
                    "game_data": game_data,
                    "buttons": card_buttons,
                    "default_button": default_btn
                })

            if end_idx < len(items):
                self._active_render_job = self.after(16, lambda: render_batch(end_idx, batch_size))
            else:
                self._active_render_job = None
                self._apply_focus_visuals()

        render_batch(0)

    def run_patch(self, game_data, patch_data):
        if not game_data.get("is_installed", True) or not game_data.get("path") or not Path(game_data["path"]).exists():
            messagebox.showwarning(
                "Game Not Installed",
                f"'{game_data['name']}' is not currently installed on this device.\n\nPlease install the game via Steam before applying the patch."
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
                    lambda msg: self.run_on_main_thread(lambda m=msg: self.lbl_status.configure(text=m))
                )
                self.run_on_main_thread(lambda: self.after(2000, self.refresh_data))
            except Exception as e:
                self.run_on_main_thread(self._stop_progress)
                self.run_on_main_thread(lambda: self.lbl_status.configure(text="Patch Failed! Check terminal.", text_color="#ff4444"))

        threading.Thread(target=_patch_task, daemon=True).start()

    def run_rollback(self, game_data):
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
                    lambda msg: self.run_on_main_thread(lambda m=msg: self.lbl_status.configure(text=m))
                )
                self.run_on_main_thread(lambda: self.after(2000, self.refresh_data))
            except Exception as e:
                logger.error(f"ROLLBACK ERROR: {e}")
                self.run_on_main_thread(self._stop_progress)
                self.run_on_main_thread(lambda: self.lbl_status.configure(text="Rollback Failed! Check terminal.", text_color="#ff4444"))

        threading.Thread(target=_rollback_task, daemon=True).start()

    def run_steam_restore(self, game_data, patch_data):
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
                    lambda msg: self.run_on_main_thread(lambda m=msg: self.lbl_status.configure(text=m))
                )
                self.run_on_main_thread(lambda: self.after(2000, self.refresh_data))
            except Exception as e:
                logger.error(f"STEAM RESTORE ERROR: {e}")
                self.run_on_main_thread(self._stop_progress)
                self.run_on_main_thread(lambda: self.lbl_status.configure(text="Steam Restore Failed! Check terminal.", text_color="#ff4444"))

        threading.Thread(target=_steam_task, daemon=True).start()


if __name__ == "__main__":
    try:
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")
    except Exception:
        pass
    app = VNPatchManagerApp()
    app.mainloop()

