import io
import logging
import threading
import queue
import time
import webbrowser
import requests
from tkinter import messagebox, filedialog
from pathlib import Path
from PIL import Image, ImageTk, ImageSequence

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
from .non_steam_manager import NonSteamManager
from .codec_fixer import CodecFixer
from .steamgriddb_client import SteamGridDBClient
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
        self._setup_window_icon()
        
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
        self.steamgriddb_client = SteamGridDBClient(
            api_key=self.config_manager.config.get("steamgriddb_api_key", "")
        )
        self.non_steam_manager = NonSteamManager(
            steam_root=self.steam_scanner.get_steam_root(),
            vndb_scanner=self.vndb_scanner
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
        self._card_entries = []  # List of rendered card dictionaries
        self._focused_zone = "LIBRARY"  # "LIBRARY", "TOOLBAR", "TABS", "SETTINGS", "HEADER"
        self._focused_tab_idx = 0  # 0: Games Library, 1: Settings
        self._focused_card_idx = 0
        self._focused_btn_idx = -1  # -1 = whole card, >= 0 = specific button in card
        self._focused_toolbar_idx = 0  # 0: Search, 1: Filter, 2: Sort, 3: View, 4: Scan
        self._focused_header_idx = 1  # 0: Add Non-Steam VN, 1: Scan Games & Patches
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

        # Modal Controller Navigation Stack
        self._modal_controller_stack = []

        # Gamepad & Keyboard Navigation Initialization
        self.controller_manager = GamepadControllerManager(
            action_callback=lambda act: self.run_on_main_thread(self._handle_controller_action, act)
        )
        self.controller_manager.start()
        self._bind_controller_and_keyboard_events()

        # Initial Data Load
        self.refresh_data()

    def push_modal_controller_handler(self, handler):
        """Pushes a modal controller action handler onto the active controller stack."""
        self._modal_controller_stack.append(handler)

    def pop_modal_controller_handler(self, handler=None):
        """Pops a modal controller action handler from the controller stack."""
        if handler:
            if handler in self._modal_controller_stack:
                self._modal_controller_stack.remove(handler)
        elif self._modal_controller_stack:
            self._modal_controller_stack.pop()

    def _setup_window_icon(self):
        """Sets the high-resolution window titlebar and taskbar icon for Linux/Steam Deck."""
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

        self.btn_add_non_steam = ctk.CTkButton(
            btn_block,
            text="➕ Add Non-Steam VN",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=32,
            fg_color="#10b981",
            hover_color="#059669",
            command=self.open_add_non_steam_modal
        )
        self.btn_add_non_steam.pack(side="right", padx=(0, 0))

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

        # SteamGridDB Integration Card
        frame_sgdb = ctk.CTkFrame(self.tab_settings, fg_color="#121212", border_width=1, border_color="#27272a", corner_radius=10)
        frame_sgdb.grid(row=2, column=0, padx=20, pady=(12, 0), sticky="ew")
        frame_sgdb.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            frame_sgdb,
            text="🎨 SteamGridDB Community Integration (Optional):",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#f1f5f9"
        ).grid(row=0, column=0, columnspan=3, padx=12, pady=(10, 4), sticky="w")

        ctk.CTkLabel(
            frame_sgdb,
            text="API Key:",
            text_color="#f1f5f9"
        ).grid(row=1, column=0, padx=12, pady=(0, 10), sticky="w")

        self.entry_sgdb_key = ctk.CTkEntry(
            frame_sgdb,
            placeholder_text="Paste your free SteamGridDB API key...",
            fg_color="#18181b",
            border_color="#27272a",
            border_width=1,
            text_color="#f1f5f9"
        )
        self.entry_sgdb_key.insert(0, self.config_manager.config.get("steamgriddb_api_key", ""))
        self.entry_sgdb_key.grid(row=1, column=1, padx=(0, 8), pady=(0, 10), sticky="ew")

        btn_get_key = ctk.CTkButton(
            frame_sgdb,
            text="🔑 Get Key",
            width=90,
            fg_color="#27272a",
            hover_color="#3f3f46",
            command=lambda: webbrowser.open("https://www.steamgriddb.com/profile/preferences/api")
        )
        btn_get_key.grid(row=1, column=2, padx=(0, 12), pady=(0, 10))

        self.switch_sgdb_nsfw = ctk.CTkSwitch(
            frame_sgdb,
            text="🔞 Allow 18+ / NSFW Community Artwork from SteamGridDB",
            font=ctk.CTkFont(size=12),
            text_color="#f1f5f9",
            progress_color="#ec4899"
        )
        if self.config_manager.config.get("steamgriddb_nsfw", True):
            self.switch_sgdb_nsfw.select()
        else:
            self.switch_sgdb_nsfw.deselect()
        self.switch_sgdb_nsfw.grid(row=2, column=0, columnspan=3, padx=12, pady=(0, 6), sticky="w")

        self.switch_sgdb_animated = ctk.CTkSwitch(
            frame_sgdb,
            text="✨ Allow Animated Community Artwork from SteamGridDB",
            font=ctk.CTkFont(size=12),
            text_color="#f1f5f9",
            progress_color="#a855f7"
        )
        if self.config_manager.config.get("steamgriddb_animated", True):
            self.switch_sgdb_animated.select()
        else:
            self.switch_sgdb_animated.deselect()
        self.switch_sgdb_animated.grid(row=3, column=0, columnspan=3, padx=12, pady=(0, 12), sticky="w")

        # Stable Footer Container (Row 3)
        frame_actions = ctk.CTkFrame(self.tab_settings, fg_color="transparent")
        frame_actions.grid(row=3, column=0, pady=(20, 10))

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
        self.config_manager.config["steamgriddb_api_key"] = self.entry_sgdb_key.get().strip()
        self.config_manager.config["steamgriddb_nsfw"] = bool(self.switch_sgdb_nsfw.get())
        self.config_manager.config["steamgriddb_animated"] = bool(self.switch_sgdb_animated.get())
        self.steamgriddb_client.set_api_key(self.entry_sgdb_key.get().strip())
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
        # Check if an active modal dialog is currently handling controller events
        if self._modal_controller_stack:
            try:
                self._modal_controller_stack[-1](action)
                return
            except Exception as ex:
                logger.warning(f"Error in modal controller handler: {ex}")

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

        # 4. Zone: HEADER (Top Header - Add Non-Steam VN & Scan buttons)
        if self._focused_zone == "HEADER":
            if action == ACTION_LEFT:
                if self._focused_header_idx == 1:
                    self._focused_header_idx = 0
                    self._apply_focus_visuals()
                else:
                    self._focused_zone = "TABS"
                    self._focused_tab_idx = 1 if self.tabview.get() == "Settings" else 0
                    self._apply_focus_visuals()
            elif action == ACTION_RIGHT:
                if self._focused_header_idx == 0:
                    self._focused_header_idx = 1
                    self._apply_focus_visuals()
            elif action == ACTION_DOWN:
                if self.tabview.get() == "Settings":
                    self._focused_zone = "SETTINGS"
                else:
                    self._focused_zone = "TOOLBAR"
                    self._focused_toolbar_idx = 3
                self._apply_focus_visuals()
            elif action in (ACTION_SELECT, ACTION_QUICK_ACTION):
                if self._focused_header_idx == 0:
                    self.open_add_non_steam_modal()
                else:
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

            # -------------------------------------------------------------
            # Case A: In Action Mode (A button was pressed to enter buttons)
            # -------------------------------------------------------------
            if self._focused_btn_idx >= 0:
                if action == ACTION_LEFT:
                    if self._focused_btn_idx > 0:
                        self._focused_btn_idx -= 1
                        self._apply_focus_visuals()
                elif action == ACTION_RIGHT:
                    if self._focused_btn_idx < num_buttons - 1:
                        self._focused_btn_idx += 1
                        self._apply_focus_visuals()
                elif action == ACTION_SELECT:
                    if current_entry and 0 <= self._focused_btn_idx < num_buttons:
                        current_entry["buttons"][self._focused_btn_idx].invoke()
                elif action in (ACTION_BACK, ACTION_UP, ACTION_DOWN):
                    # Exit Action Mode and return to Card Browsing Mode
                    self._focused_btn_idx = -1
                    self._apply_focus_visuals()
                return

            # -------------------------------------------------------------
            # Case B: In Card Browsing Mode (_focused_btn_idx == -1)
            # -------------------------------------------------------------
            if action == ACTION_UP:
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
                if is_grid:
                    self._focused_card_idx = min(num_cards - 1, self._focused_card_idx + 2)
                else:
                    self._focused_card_idx = min(num_cards - 1, self._focused_card_idx + 1)
                self._apply_focus_visuals()

            elif action == ACTION_LEFT:
                if is_grid:
                    if self._focused_card_idx % 2 == 1:
                        self._focused_card_idx -= 1
                        self._apply_focus_visuals()
                    elif self._focused_card_idx > 0:
                        self._focused_card_idx -= 1
                        self._apply_focus_visuals()
                else:
                    if self._focused_card_idx > 0:
                        self._focused_card_idx -= 1
                        self._apply_focus_visuals()

            elif action == ACTION_RIGHT:
                if self._focused_card_idx < num_cards - 1:
                    self._focused_card_idx += 1
                    self._apply_focus_visuals()

            elif action == ACTION_SELECT:
                # Pressing A enters Action Mode on the selected card's action buttons
                if current_entry and num_buttons > 0:
                    self._focused_btn_idx = 0
                    self._apply_focus_visuals()

            elif action == ACTION_QUICK_ACTION:  # X Button directly invokes default action
                if current_entry and current_entry.get("default_button"):
                    current_entry["default_button"].invoke()

            elif action == ACTION_BACK:
                if self.search_var.get():
                    self.search_var.set("")
                    self._apply_focus_visuals()

    def _apply_focus_visuals(self, force_all: bool = False):
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

        if hasattr(self, 'btn_add_non_steam') and self.btn_add_non_steam.winfo_exists():
            is_add_focused = (self._focused_zone == "HEADER" and self._focused_header_idx == 0)
            self.btn_add_non_steam.configure(
                border_color="#6ee7b7" if is_add_focused else "#059669",
                border_width=2 if is_add_focused else 0,
                fg_color="#059669" if is_add_focused else "#10b981"
            )

        if hasattr(self, 'btn_refresh') and self.btn_refresh.winfo_exists():
            is_refresh_focused = (self._focused_zone == "HEADER" and self._focused_header_idx == 1)
            self.btn_refresh.configure(
                border_color="#60a5fa" if is_refresh_focused else "#1d4ed8",
                border_width=2 if is_refresh_focused else 0,
                fg_color="#1d4ed8" if is_refresh_focused else "#2563eb"
            )

        # 2. Update Card Focus Highlights (Differential O(1) Updates)
        is_library = (self._focused_zone == "LIBRARY")
        cur_card_idx = self._focused_card_idx if is_library else None
        prev_card_idx = getattr(self, "_prev_focused_card_idx", None)

        if force_all or prev_card_idx is None:
            for idx in range(len(self._card_entries)):
                self._apply_card_visual(idx, is_focused=(idx == cur_card_idx))
        else:
            # Unfocus previously focused card if it changed or button index changed
            if prev_card_idx != cur_card_idx or getattr(self, "_prev_focused_btn_idx", None) != self._focused_btn_idx:
                if prev_card_idx is not None:
                    self._apply_card_visual(prev_card_idx, is_focused=False)
            # Focus current card
            if cur_card_idx is not None:
                self._apply_card_visual(cur_card_idx, is_focused=True)

        self._prev_focused_card_idx = cur_card_idx
        self._prev_focused_btn_idx = self._focused_btn_idx

    def _apply_card_visual(self, idx: int, is_focused: bool):
        """Applies high-contrast focus highlight to a single card in O(1) time."""
        if not (0 <= idx < len(self._card_entries)):
            return
        entry = self._card_entries[idx]
        card = entry.get("card")
        if not card or not card.winfo_exists():
            return

        if is_focused:
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

        buttons = entry.get("buttons", [])
        for b_idx, btn in enumerate(buttons):
            if not btn.winfo_exists():
                continue
            if is_focused and b_idx == self._focused_btn_idx:
                btn.configure(border_color="#93c5fd", border_width=2)
            else:
                btn.configure(border_width=0 if btn.cget("fg_color") != "transparent" else 1)

    def _scroll_card_into_view(self, card_widget):
        """Auto-scrolls the scrollable frame viewport so the focused card is fully visible without jitter."""
        try:
            canvas = getattr(self.scrollable_games, "_parent_canvas", None)
            if not canvas or not canvas.winfo_exists() or not card_widget.winfo_exists():
                return

            canvas.update_idletasks()

            card_root_y = card_widget.winfo_rooty()
            canvas_root_y = canvas.winfo_rooty()
            card_h = card_widget.winfo_height() or 140
            canvas_h = canvas.winfo_height() or 500

            rel_top = card_root_y - canvas_root_y
            rel_bottom = rel_top + card_h

            bbox = canvas.bbox("all")
            if not bbox:
                return
            total_h = max(bbox[3] - bbox[1], canvas_h, 1)

            if total_h <= canvas_h:
                return

            curr_y_view = canvas.yview()
            curr_top_fraction = curr_y_view[0]
            curr_top_y = curr_top_fraction * total_h

            padding = 16

            # If card is above viewport margin
            if rel_top < padding:
                target_top_y = max(0.0, curr_top_y + rel_top - padding)
                canvas.yview_moveto(target_top_y / total_h)
            # If card is below viewport margin
            elif rel_bottom > canvas_h - padding:
                target_top_y = min(total_h - canvas_h, curr_top_y + (rel_bottom - canvas_h) + padding)
                canvas.yview_moveto(target_top_y / total_h)
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
            status_info = game_data.get("status_info") or self._compute_status_info(app_id, game_data)
            is_patched = status_info["is_patched"]
            has_clean_backup = status_info["has_clean_backup"]
            has_backup = status_info["has_backup"]
            has_local_patch = status_info["has_local_patch"]
            vn_info = status_info["vn_info"]
            has_vndb_18_patch = vn_info.get("has_18plus_en_patch", False)

            if is_patched:
                total_patched += 1
            if has_clean_backup or has_backup:
                total_backed_up += 1
            if has_local_patch:
                total_local_available += 1
            elif has_vndb_18_patch:
                total_missing_18 += 1

            # 1. Filter match
            if active_filter == "Patch Available" and not has_local_patch:
                continue
            elif active_filter == "Patched" and not is_patched:
                continue
            elif active_filter == "Missing 18+ (VNDB)" and (has_local_patch or not has_vndb_18_patch):
                continue
            elif active_filter == "Backed Up" and not (has_clean_backup or has_backup):
                continue

            # 2. Search match
            if search_query:
                game_name = game_data.get("name", "").lower()
                vn_title = vn_info.get("vn_title", "").lower()
                if search_query not in game_name and search_query not in vn_title and search_query not in str(app_id):
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
                key=lambda x: ((x[1].get("status_info") or self._compute_status_info(x[0], x[1])).get("status_priority", 3), x[1]["name"].lower())
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

        # Ensure human-readable name is resolved if placeholder
        cur_name = game_data.get("name", "")
        if not cur_name or cur_name.startswith("Steam App #"):
            if vn_info.get("vn_title"):
                game_data["name"] = vn_info["vn_title"]
            elif patch_info and patch_info.get("game_name"):
                game_data["name"] = patch_info["game_name"]

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
            "is_non_steam": game_data.get("is_non_steam", False),
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

        if status_info.get("is_non_steam"):
            ctk.CTkLabel(
                parent_frame,
                text="🎮 Non-Steam",
                text_color="#34d399",
                font=ctk.CTkFont(size=11, weight="bold")
            ).pack(side="left", padx=(0, 6))

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
                is_non_steam = game_data.get("is_non_steam", False)
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

                # 3. Actions Button Rows (Primary Row & Dedicated Tools Row)
                primary_actions_frame = ctk.CTkFrame(card, fg_color="transparent")
                primary_actions_frame.grid(row=2, column=0, padx=10, pady=(4, 2), sticky="sew")

                patch_data = self.repo.available_patches.get(app_id)
                card_buttons = []
                default_btn = None

                if has_local_patch:
                    btn_text = "Verify / Re-apply" if is_patched else "Apply Patch"
                    btn_apply = ctk.CTkButton(
                        primary_actions_frame,
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
                            primary_actions_frame,
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
                            primary_actions_frame,
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
                            primary_actions_frame,
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
                            primary_actions_frame,
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

                # Row 2: Tools & Utilities
                if game_data.get("is_installed", True):
                    tools_actions_frame = ctk.CTkFrame(card, fg_color="transparent")
                    tools_actions_frame.grid(row=3, column=0, padx=10, pady=(2, 10), sticky="sew")

                    btn_fix_video = ctk.CTkButton(
                        tools_actions_frame,
                        text="🔧 Fix Video",
                        font=ctk.CTkFont(size=11),
                        height=28,
                        fg_color="#1e293b",
                        hover_color="#334155",
                        border_width=1,
                        border_color="#334155",
                        command=lambda g=game_data, aid=app_id: self.run_fix_video(aid, g)
                    )
                    btn_fix_video.pack(side="left", fill="x", expand=True, padx=(0, 3))
                    card_buttons.append(btn_fix_video)

                    btn_custom_art = ctk.CTkButton(
                        tools_actions_frame,
                        text="🎨 Custom Art",
                        font=ctk.CTkFont(size=11),
                        height=28,
                        fg_color="#1e293b",
                        hover_color="#334155",
                        border_width=1,
                        border_color="#334155",
                        command=lambda g=game_data, aid=app_id: self.run_custom_artwork(aid, g)
                    )
                    btn_custom_art.pack(side="left", fill="x", expand=True, padx=(3, 3 if is_non_steam else 0))
                    card_buttons.append(btn_custom_art)

                    if is_non_steam:
                        btn_remove = ctk.CTkButton(
                            tools_actions_frame,
                            text="🗑️ Remove",
                            font=ctk.CTkFont(size=11),
                            height=28,
                            fg_color="#450a0a",
                            hover_color="#7f1d1d",
                            text_color="#fca5a5",
                            border_width=1,
                            border_color="#7f1d1d",
                            command=lambda g=game_data, aid=app_id: self.run_remove_non_steam(aid, g)
                        )
                        btn_remove.pack(side="left", fill="x", expand=True, padx=(3, 0))
                        card_buttons.append(btn_remove)

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
                is_non_steam = game_data.get("is_non_steam", False)
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

                # 3. Actions Frame (Primary Row & Tools Row)
                actions_frame = ctk.CTkFrame(card, fg_color="transparent")
                actions_frame.grid(row=0, column=2, padx=12, pady=6, sticky="e")

                primary_row = ctk.CTkFrame(actions_frame, fg_color="transparent")
                primary_row.pack(anchor="e", pady=(0, 2))

                patch_data = self.repo.available_patches.get(app_id)
                card_buttons = []
                default_btn = None

                if has_local_patch:
                    btn_text = "Verify / Re-apply" if is_patched else "Apply Patch"
                    btn_apply = ctk.CTkButton(
                        primary_row,
                        text=btn_text,
                        font=ctk.CTkFont(size=12),
                        height=28,
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
                            primary_row,
                            text="Restore (Backup)",
                            font=ctk.CTkFont(size=11),
                            height=28,
                            fg_color="#c0392b",
                            hover_color="#e74c3c",
                            command=lambda g=game_data: self.run_rollback(g)
                        )
                        btn_rollback.pack(side="left", padx=(0, 4))
                        card_buttons.append(btn_rollback)

                    if is_patched or has_backup:
                        btn_steam = ctk.CTkButton(
                            primary_row,
                            text="Restore via Steam",
                            font=ctk.CTkFont(size=11),
                            height=28,
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
                            primary_row,
                            text="Restore via Steam",
                            font=ctk.CTkFont(size=11),
                            height=28,
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
                            primary_row,
                            text="🔗 Open VNDB (Get Patch)",
                            font=ctk.CTkFont(size=12, weight="bold"),
                            height=28,
                            fg_color="#0284c7",
                            hover_color="#0369a1",
                            command=lambda u=vndb_url: webbrowser.open(u)
                        )
                        btn_vndb.pack(side="left")
                        card_buttons.append(btn_vndb)
                        if not default_btn:
                            default_btn = btn_vndb

                if game_data.get("is_installed", True):
                    tools_row = ctk.CTkFrame(actions_frame, fg_color="transparent")
                    tools_row.pack(anchor="e", pady=(2, 0), fill="x")

                    btn_fix_video = ctk.CTkButton(
                        tools_row,
                        text="🔧 Fix Video",
                        font=ctk.CTkFont(size=11),
                        height=26,
                        fg_color="#1e293b",
                        hover_color="#334155",
                        border_width=1,
                        border_color="#334155",
                        command=lambda g=game_data, aid=app_id: self.run_fix_video(aid, g)
                    )
                    btn_fix_video.pack(side="left", padx=(0, 4))
                    card_buttons.append(btn_fix_video)

                    btn_custom_art = ctk.CTkButton(
                        tools_row,
                        text="🎨 Custom Art",
                        font=ctk.CTkFont(size=11),
                        height=26,
                        fg_color="#1e293b",
                        hover_color="#334155",
                        border_width=1,
                        border_color="#334155",
                        command=lambda g=game_data, aid=app_id: self.run_custom_artwork(aid, g)
                    )
                    btn_custom_art.pack(side="left", padx=(0, 4 if is_non_steam else 0))
                    card_buttons.append(btn_custom_art)

                    if is_non_steam:
                        btn_remove = ctk.CTkButton(
                            tools_row,
                            text="🗑️ Remove",
                            font=ctk.CTkFont(size=11),
                            height=26,
                            fg_color="#450a0a",
                            hover_color="#7f1d1d",
                            text_color="#fca5a5",
                            border_width=1,
                            border_color="#7f1d1d",
                            command=lambda g=game_data, aid=app_id: self.run_remove_non_steam(aid, g)
                        )
                        btn_remove.pack(side="left")
                        card_buttons.append(btn_remove)

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

    def run_remove_non_steam(self, app_id: str, game_data: dict):
        """Confirms and removes a non-Steam visual novel shortcut from Steam and VNPM."""
        confirmed = messagebox.askyesno(
            "Remove Non-Steam Shortcut?",
            f"Are you sure you want to remove '{game_data['name']}' from Steam and VNPM?\n\n(This will remove the Steam shortcut and artwork, but will not delete your game files.)",
            parent=self
        )
        if not confirmed:
            return

        aid_32 = int(app_id) if app_id.isdigit() else None
        success, msg = self.non_steam_manager.remove_non_steam_game(
            app_name=game_data["name"],
            appid_32=aid_32
        )
        if success:
            self.lbl_status.configure(text=f"✅ {msg}", text_color="#34d399")
            self.refresh_data()
        else:
            self.lbl_status.configure(text=f"❌ {msg}", text_color="#ff4444")
            messagebox.showerror("Error Removing Shortcut", msg, parent=self)

    def run_custom_artwork(self, app_id: str, game_data: dict):
        """Opens the Decky-style visual artwork browser modal for this game."""
        self.open_artwork_browser_modal(app_id, game_data)

    def open_artwork_browser_modal(self, app_id: str, game_data: dict):
        """Opens an interactive artwork browser modal to choose Capsule, Wide Header, Hero, Logo, or Icon."""
        modal = ctk.CTkToplevel(self)
        modal.title(f"Visual Artwork Browser - {game_data['name']}")
        modal.geometry("820x620")
        modal.configure(fg_color="#09090b")
        modal.transient(self)
        modal.grab_set()

        # Modal Header Bar
        header_frame = ctk.CTkFrame(modal, fg_color="#121212", corner_radius=0, height=60)
        header_frame.pack(fill="x", padx=0, pady=(0, 10))
        header_frame.pack_propagate(False)

        ctk.CTkLabel(
            header_frame,
            text=f"🎨 Artwork Browser: {game_data['name']}",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#f1f5f9"
        ).pack(side="left", padx=16, pady=12)

        # Asset Type Selector & Search Bar Frame
        control_frame = ctk.CTkFrame(modal, fg_color="transparent")
        control_frame.pack(fill="x", padx=16, pady=(0, 8))

        var_asset_type = ctk.StringVar(value="capsule")
        var_search_query = ctk.StringVar(value=game_data["name"])

        # Category Tabs
        tab_buttons = [
            ("Capsule (600x900)", "capsule"),
            ("Wide Header", "wide"),
            ("Hero Banner", "hero"),
            ("Logo (PNG)", "logo"),
            ("Icon", "icon")
        ]

        seg_frame = ctk.CTkFrame(
            control_frame,
            fg_color="#18181b",
            border_color="#3b82f6",
            border_width=2,
            corner_radius=8
        )
        seg_frame.pack(side="left", padx=(0, 10))

        seg_type = ctk.CTkSegmentedButton(
            seg_frame,
            values=[name for name, _ in tab_buttons],
            command=lambda v: _on_category_changed(v),
            fg_color="#18181b",
            selected_color="#2563eb",
            selected_hover_color="#1d4ed8",
            unselected_hover_color="#27272a",
            text_color="#f1f5f9"
        )
        seg_type.set("Capsule (600x900)")
        seg_type.pack(padx=2, pady=2)

        # 18+ / NSFW Toggle in Modal
        switch_modal_nsfw = ctk.CTkSwitch(
            control_frame,
            text="🔞 18+ Art",
            font=ctk.CTkFont(size=12),
            text_color="#f1f5f9",
            progress_color="#ec4899",
            command=lambda: _fetch_and_render_assets()
        )
        if self.config_manager.config.get("steamgriddb_nsfw", True):
            switch_modal_nsfw.select()
        else:
            switch_modal_nsfw.deselect()
        switch_modal_nsfw.pack(side="left", padx=(0, 10))

        # Animated Art Toggle in Modal
        switch_modal_animated = ctk.CTkSwitch(
            control_frame,
            text="✨ Animated",
            font=ctk.CTkFont(size=12),
            text_color="#f1f5f9",
            progress_color="#a855f7",
            command=lambda: _fetch_and_render_assets()
        )
        if self.config_manager.config.get("steamgriddb_animated", True):
            switch_modal_animated.select()
        else:
            switch_modal_animated.deselect()
        switch_modal_animated.pack(side="left", padx=(0, 10))

        # Local File Upload Button
        btn_local_file = ctk.CTkButton(
            control_frame,
            text="📁 Local File...",
            width=110,
            fg_color="#27272a",
            hover_color="#3f3f46",
            command=lambda: _on_local_file_upload()
        )
        btn_local_file.pack(side="right")

        # Scrollable Thumbnail Grid
        scroll_grid = ctk.CTkScrollableFrame(modal, fg_color="#000000", corner_radius=8, border_width=1, border_color="#27272a")
        scroll_grid.pack(fill="both", expand=True, padx=16, pady=(0, 10))
        scroll_grid.grid_columnconfigure((0, 1, 2), weight=1)

        # Status & Action Footer
        modal_footer = ctk.CTkFrame(modal, fg_color="#121212", corner_radius=0, height=45)
        modal_footer.pack(fill="x", side="bottom")
        modal_footer.pack_propagate(False)

        lbl_modal_status = ctk.CTkLabel(
            modal_footer,
            text="Loading visual assets from SteamGridDB & VNDB...",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8"
        )
        lbl_modal_status.pack(side="left", padx=16)

        btn_close = ctk.CTkButton(
            modal_footer,
            text="Close",
            width=80,
            fg_color="#27272a",
            hover_color="#3f3f46",
            command=lambda: _close_modal()
        )
        btn_close.pack(side="right", padx=16, pady=6)

        # In-memory store for loaded PIL thumbnail CTkImages & animation timers
        loaded_thumb_images = []
        active_animation_timers = []
        modal_card_widgets = []  # List of dicts: {"card": CTkFrame, "btn": CTkButton, "apply_fn": Callable}

        # Modal Focus State
        modal_focus_state = {
            "zone": "TABS",       # "TABS", "GRID", "CONTROLS"
            "tab_idx": 0,         # 0..len(tab_buttons)-1
            "card_idx": 0,        # 0..len(modal_card_widgets)-1
            "control_idx": 0      # 0=NSFW, 1=Animated, 2=Local File
        }

        def _cancel_animations():
            for timer_id in active_animation_timers:
                try:
                    modal.after_cancel(timer_id)
                except Exception:
                    pass
            active_animation_timers.clear()

        def _apply_modal_focus_visuals():
            if not modal.winfo_exists():
                return
            zone = modal_focus_state["zone"]
            t_idx = modal_focus_state["tab_idx"]
            c_idx = modal_focus_state["card_idx"]
            ctrl_idx = modal_focus_state["control_idx"]

            # Highlight Tab Bar Container
            if seg_frame.winfo_exists():
                if zone == "TABS":
                    seg_frame.configure(border_color="#3b82f6", border_width=2)
                else:
                    seg_frame.configure(border_color="#27272a", border_width=1)

            # Highlight Controls
            if zone == "CONTROLS":
                switch_modal_nsfw.configure(
                    progress_color="#3b82f6" if ctrl_idx == 0 else "#ec4899",
                    text_color="#60a5fa" if ctrl_idx == 0 else "#f1f5f9"
                )
                switch_modal_animated.configure(
                    progress_color="#3b82f6" if ctrl_idx == 1 else "#a855f7",
                    text_color="#60a5fa" if ctrl_idx == 1 else "#f1f5f9"
                )
                btn_local_file.configure(
                    border_color="#3b82f6" if ctrl_idx == 2 else "#3f3f46",
                    border_width=2 if ctrl_idx == 2 else 0,
                    text_color="#60a5fa" if ctrl_idx == 2 else "#f1f5f9"
                )
            else:
                switch_modal_nsfw.configure(progress_color="#ec4899", text_color="#f1f5f9")
                switch_modal_animated.configure(progress_color="#a855f7", text_color="#f1f5f9")
                btn_local_file.configure(border_color="#3f3f46", border_width=0, text_color="#f1f5f9")

            # Highlight Grid Cards
            for idx, item_w in enumerate(modal_card_widgets):
                card = item_w["card"]
                btn = item_w["btn"]
                if card.winfo_exists():
                    if zone == "GRID" and idx == c_idx:
                        card.configure(border_color="#3b82f6", border_width=2, fg_color="#18181b")
                        btn.configure(fg_color="#2563eb", hover_color="#1d4ed8")
                        # Ensure card is visible by scrolling
                        try:
                            card_y = card.winfo_y()
                            frame_h = scroll_grid.winfo_height()
                            if card_y and frame_h and hasattr(scroll_grid, "_parent_canvas"):
                                scroll_grid._parent_canvas.yview_moveto(max(0.0, min(1.0, card_y / max(scroll_grid._parent_canvas.bbox("all")[3], 1))))
                        except Exception:
                            pass
                    else:
                        card.configure(border_color="#27272a", border_width=1, fg_color="#121212")
                        btn.configure(fg_color="#27272a", hover_color="#3f3f46")

        def _handle_modal_controller(action: str):
            num_cards = len(modal_card_widgets)
            curr_zone = modal_focus_state["zone"]

            # Global Modal Bumper Tab Switching (L1 / R1)
            if action == ACTION_PREV_TAB:
                t_names = [name for name, _ in tab_buttons]
                curr_t = seg_type.get()
                curr_i = t_names.index(curr_t) if curr_t in t_names else 0
                next_i = (curr_i - 1) % len(t_names)
                seg_type.set(t_names[next_i])
                modal_focus_state["tab_idx"] = next_i
                modal_focus_state["card_idx"] = 0
                _apply_modal_focus_visuals()
                _fetch_and_render_assets()
                return
            elif action == ACTION_NEXT_TAB:
                t_names = [name for name, _ in tab_buttons]
                curr_t = seg_type.get()
                curr_i = t_names.index(curr_t) if curr_t in t_names else 0
                next_i = (curr_i + 1) % len(t_names)
                seg_type.set(t_names[next_i])
                modal_focus_state["tab_idx"] = next_i
                modal_focus_state["card_idx"] = 0
                _apply_modal_focus_visuals()
                _fetch_and_render_assets()
                return

            # Fast scrolling inside modal (L2 / R2 / Right Stick)
            if action == ACTION_SCROLL_UP:
                try:
                    scroll_grid._parent_canvas.yview_scroll(-4, "units")
                except Exception:
                    pass
                return
            elif action == ACTION_SCROLL_DOWN:
                try:
                    scroll_grid._parent_canvas.yview_scroll(4, "units")
                except Exception:
                    pass
                return

            # Back button (B) closes modal
            if action == ACTION_BACK:
                _close_modal()
                return

            # Quick Action (X Button) toggles Animated Filter
            if action == ACTION_QUICK_ACTION:
                switch_modal_animated.toggle()
                _fetch_and_render_assets()
                return

            # Search Action (Y Button) opens Local File Picker
            if action == ACTION_SEARCH:
                _on_local_file_upload()
                return

            # Navigation in Zone TABS
            if curr_zone == "TABS":
                t_names = [name for name, _ in tab_buttons]
                curr_t = seg_type.get()
                curr_i = t_names.index(curr_t) if curr_t in t_names else 0

                if action == ACTION_LEFT:
                    next_i = (curr_i - 1) % len(t_names)
                    seg_type.set(t_names[next_i])
                    modal_focus_state["tab_idx"] = next_i
                    _apply_modal_focus_visuals()
                    _fetch_and_render_assets()
                elif action == ACTION_RIGHT:
                    if curr_i == len(t_names) - 1:
                        modal_focus_state["zone"] = "CONTROLS"
                        modal_focus_state["control_idx"] = 0
                        _apply_modal_focus_visuals()
                    else:
                        next_i = (curr_i + 1) % len(t_names)
                        seg_type.set(t_names[next_i])
                        modal_focus_state["tab_idx"] = next_i
                        _apply_modal_focus_visuals()
                        _fetch_and_render_assets()
                elif action == ACTION_DOWN:
                    if num_cards > 0:
                        modal_focus_state["zone"] = "GRID"
                        modal_focus_state["card_idx"] = 0
                    else:
                        modal_focus_state["zone"] = "CONTROLS"
                        modal_focus_state["control_idx"] = 0
                    _apply_modal_focus_visuals()
                elif action == ACTION_SELECT:
                    if num_cards > 0:
                        modal_focus_state["zone"] = "GRID"
                        modal_focus_state["card_idx"] = 0
                        _apply_modal_focus_visuals()
                return

            # Navigation in Zone CONTROLS (Toggles & Local File)
            if curr_zone == "CONTROLS":
                c_i = modal_focus_state["control_idx"]
                if action == ACTION_LEFT:
                    if c_i == 0:
                        modal_focus_state["zone"] = "TABS"
                        _apply_modal_focus_visuals()
                    else:
                        modal_focus_state["control_idx"] = c_i - 1
                        _apply_modal_focus_visuals()
                elif action == ACTION_RIGHT:
                    if c_i < 2:
                        modal_focus_state["control_idx"] = c_i + 1
                        _apply_modal_focus_visuals()
                elif action == ACTION_DOWN:
                    if num_cards > 0:
                        modal_focus_state["zone"] = "GRID"
                        modal_focus_state["card_idx"] = 0
                        _apply_modal_focus_visuals()
                elif action == ACTION_UP:
                    modal_focus_state["zone"] = "TABS"
                    _apply_modal_focus_visuals()
                elif action == ACTION_SELECT:
                    if c_i == 0:
                        switch_modal_nsfw.toggle()
                        _fetch_and_render_assets()
                    elif c_i == 1:
                        switch_modal_animated.toggle()
                        _fetch_and_render_assets()
                    elif c_i == 2:
                        _on_local_file_upload()
                return

            # Navigation in Zone GRID (Artwork Cards)
            if curr_zone == "GRID":
                cols = 3
                curr_card = modal_focus_state["card_idx"]

                if action == ACTION_UP:
                    if curr_card < cols:
                        modal_focus_state["zone"] = "TABS"
                        _apply_modal_focus_visuals()
                    else:
                        modal_focus_state["card_idx"] = max(0, curr_card - cols)
                        _apply_modal_focus_visuals()
                elif action == ACTION_DOWN:
                    if curr_card + cols < num_cards:
                        modal_focus_state["card_idx"] = curr_card + cols
                        _apply_modal_focus_visuals()
                    else:
                        modal_focus_state["card_idx"] = min(num_cards - 1, curr_card + cols)
                        _apply_modal_focus_visuals()
                elif action == ACTION_LEFT:
                    if curr_card > 0:
                        modal_focus_state["card_idx"] = curr_card - 1
                        _apply_modal_focus_visuals()
                elif action == ACTION_RIGHT:
                    if curr_card < num_cards - 1:
                        modal_focus_state["card_idx"] = curr_card + 1
                        _apply_modal_focus_visuals()
                elif action == ACTION_SELECT:
                    if 0 <= curr_card < num_cards:
                        modal_card_widgets[curr_card]["btn"].invoke()
                return

        # Register Modal Controller on Controller Stack
        self.push_modal_controller_handler(_handle_modal_controller)

        # Bind keyboard events directly to modal window as well
        modal.bind("<Up>", lambda e: _handle_modal_controller(ACTION_UP) or "break")
        modal.bind("<Down>", lambda e: _handle_modal_controller(ACTION_DOWN) or "break")
        modal.bind("<Left>", lambda e: _handle_modal_controller(ACTION_LEFT) or "break")
        modal.bind("<Right>", lambda e: _handle_modal_controller(ACTION_RIGHT) or "break")
        modal.bind("<Return>", lambda e: _handle_modal_controller(ACTION_SELECT) or "break")
        modal.bind("<Escape>", lambda e: _handle_modal_controller(ACTION_BACK) or "break")
        modal.bind("<F1>", lambda e: _handle_modal_controller(ACTION_PREV_TAB) or "break")
        modal.bind("<F2>", lambda e: _handle_modal_controller(ACTION_NEXT_TAB) or "break")
        modal.bind("<Prior>", lambda e: _handle_modal_controller(ACTION_SCROLL_UP) or "break")
        modal.bind("<Next>", lambda e: _handle_modal_controller(ACTION_SCROLL_DOWN) or "break")
        modal.focus_set()

        def _close_modal():
            self.pop_modal_controller_handler(_handle_modal_controller)
            _cancel_animations()
            modal.destroy()
            self._apply_focus_visuals()

        modal.protocol("WM_DELETE_WINDOW", _close_modal)

        def _get_type_key(tab_name: str) -> str:
            for name, key in tab_buttons:
                if name == tab_name:
                    return key
            return "capsule"

        def _apply_selected_asset(asset_url: str, asset_type: str):
            lbl_modal_status.configure(text=f"Downloading and applying {asset_type}...", text_color="#fbbf24")
            def _apply_thread():
                try:
                    import requests
                    headers = {"User-Agent": "VNPM/2.0 (Linux; SteamDeck; github.com/user/VNPM)"}
                    resp = requests.get(asset_url, headers=headers, timeout=12)
                    if resp.status_code == 200 and len(resp.content) > 0:
                        success = self.cover_manager.set_specific_grid_asset(
                            app_id=str(app_id),
                            asset_type=asset_type,
                            image_bytes=resp.content
                        )
                        if success:
                            def _refresh_app_ui():
                                for widget, name, size in self._banner_widgets.get(str(app_id), []):
                                    try:
                                        new_img = self.cover_manager.get_cover_image(str(app_id), title=name, size=size)
                                        widget.configure(image=new_img)
                                    except Exception as ex:
                                        logger.warning(f"Error updating widget image: {ex}")
                                lbl_modal_status.configure(text=f"✅ Successfully applied {asset_type} artwork!", text_color="#34d399")
                                self.lbl_status.configure(text=f"✅ Updated {asset_type} artwork for {game_data['name']}.", text_color="#34d399")
                            self.run_on_main_thread(_refresh_app_ui)
                        else:
                            self.run_on_main_thread(lambda: lbl_modal_status.configure(text=f"❌ Failed to decode or save {asset_type}.", text_color="#ff4444"))
                    else:
                        self.run_on_main_thread(lambda: lbl_modal_status.configure(text=f"❌ HTTP {resp.status_code} downloading image.", text_color="#ff4444"))
                except Exception as e:
                    logger.error(f"Error applying asset: {e}")
                    self.run_on_main_thread(lambda: lbl_modal_status.configure(text=f"Error: {e}", text_color="#ff4444"))

            threading.Thread(target=_apply_thread, daemon=True).start()

        def _on_local_file_upload():
            chosen = filedialog.askopenfilename(
                parent=modal,
                title=f"Select Local Image for {game_data['name']}",
                filetypes=[("Image Files", "*.png *.jpg *.jpeg *.webp *.bmp"), ("All Files", "*.*")]
            )
            if not chosen:
                return
            chosen_p = Path(chosen)
            try:
                raw_bytes = chosen_p.read_bytes()
                curr_type = _get_type_key(seg_type.get())
                success = self.cover_manager.set_specific_grid_asset(str(app_id), curr_type, raw_bytes)
                if success:
                    for widget, name, size in self._banner_widgets.get(str(app_id), []):
                        try:
                            new_img = self.cover_manager.get_cover_image(str(app_id), title=name, size=size)
                            widget.configure(image=new_img)
                        except Exception:
                            pass
                    lbl_modal_status.configure(text=f"✅ Applied local image as {curr_type}!", text_color="#34d399")
                    self.lbl_status.configure(text=f"✅ Updated artwork from local file.", text_color="#34d399")
            except Exception as e:
                lbl_modal_status.configure(text=f"❌ Error loading local file: {e}", text_color="#ff4444")

        def _fetch_and_render_assets():
            _cancel_animations()
            for widget in scroll_grid.winfo_children():
                widget.destroy()
            loaded_thumb_images.clear()
            modal_card_widgets.clear()
            modal_focus_state["card_idx"] = 0

            curr_type = _get_type_key(seg_type.get())
            is_nsfw = bool(switch_modal_nsfw.get())
            is_animated = bool(switch_modal_animated.get())
            lbl_modal_status.configure(text=f"Fetching {curr_type} artwork...", text_color="#94a3b8")

            def _worker():
                import io
                import requests
                from PIL import ImageSequence
                found_assets = []

                # 1. Check SteamGridDB if API key present
                if self.steamgriddb_client.has_api_key():
                    sgdb_game_id = None
                    if app_id.isdigit() and int(app_id) < 2147483647:
                        sgdb_game_id = self.steamgriddb_client.get_game_by_steam_appid(app_id)
                    if not sgdb_game_id:
                        search_res = self.steamgriddb_client.search_games(game_data["name"])
                        if search_res:
                            sgdb_game_id = search_res[0].get("id")

                    if sgdb_game_id:
                        found_assets = self.steamgriddb_client.get_assets(
                            sgdb_game_id,
                            curr_type,
                            nsfw=is_nsfw,
                            animated=is_animated
                        )

                # 2. Add fallback assets from VNDB and Steam CDN
                fallbacks = self.steamgriddb_client.get_fallback_assets(
                    app_id=app_id,
                    game_name=game_data["name"],
                    asset_type=curr_type,
                    vndb_meta=game_data.get("vndb")
                )
                found_assets.extend(fallbacks)

                # Download thumbnails & parse multi-frame animations
                rendered_cards = []
                for item in found_assets[:36]:  # Show top 36 assets
                    is_item_anim = bool(item.get("is_animated") or item.get("types") == "animated")
                    # If animated toggle is active and the item is animated, fetch raw URL to get all animation frames
                    if is_animated and is_item_anim and item.get("url"):
                        t_url = item["url"]
                    else:
                        t_url = item.get("thumb") or item.get("url")

                    try:
                        resp = requests.get(t_url, headers={"User-Agent": "VNPM/2.0"}, timeout=7)
                        if resp.status_code == 200:
                            pil_raw = Image.open(io.BytesIO(resp.content))
                            if curr_type == "capsule":
                                thumb_size = (180, 270)
                            elif curr_type == "hero":
                                thumb_size = (240, 78)
                            elif curr_type == "logo":
                                thumb_size = (200, 112)
                            elif curr_type == "icon":
                                thumb_size = (80, 80)
                            else:  # wide
                                thumb_size = (230, 108)

                            # Extract animated frames if multi-frame
                            n_frames = getattr(pil_raw, "n_frames", 1)
                            frame_ctk_images = []
                            frame_durations = []

                            if n_frames > 1 and is_animated:
                                for frame in ImageSequence.Iterator(pil_raw):
                                    if curr_type == "logo":
                                        f_res = frame.convert("RGBA").resize(thumb_size, Image.Resampling.BICUBIC)
                                    else:
                                        f_res = frame.convert("RGB").resize(thumb_size, Image.Resampling.BICUBIC)
                                    f_ctk = ctk.CTkImage(light_image=f_res, dark_image=f_res, size=thumb_size)
                                    frame_ctk_images.append(f_ctk)
                                    duration = frame.info.get("duration", 100)
                                    frame_durations.append(max(duration, 30))
                                item["is_animated"] = True
                            else:
                                if curr_type == "logo":
                                    pil_resized = pil_raw.convert("RGBA").resize(thumb_size, Image.Resampling.BICUBIC)
                                else:
                                    pil_resized = pil_raw.convert("RGB").resize(thumb_size, Image.Resampling.BICUBIC)
                                f_ctk = ctk.CTkImage(light_image=pil_resized, dark_image=pil_resized, size=thumb_size)
                                frame_ctk_images.append(f_ctk)
                                frame_durations.append(1000)
                                item["is_animated"] = False

                            rendered_cards.append((item, frame_ctk_images, frame_durations))
                    except Exception as ex:
                        logger.warning(f"Error loading thumb from {t_url}: {ex}")

                def _populate():
                    if not rendered_cards:
                        if not self.steamgriddb_client.has_api_key():
                            no_key_frame = ctk.CTkFrame(scroll_grid, fg_color="transparent")
                            no_key_frame.pack(pady=40)
                            ctk.CTkLabel(
                                no_key_frame,
                                text="No artwork found for this category.\nTip: Add a free SteamGridDB API key in Settings to unlock thousands of community assets!",
                                font=ctk.CTkFont(size=13),
                                text_color="#94a3b8",
                                justify="center"
                            ).pack(pady=(0, 10))
                            ctk.CTkButton(
                                no_key_frame,
                                text="🔑 Open Settings / Get API Key",
                                fg_color="#2563eb",
                                hover_color="#1d4ed8",
                                command=lambda: (_close_modal(), self.tabview.set("Settings"))
                            ).pack()
                        else:
                            ctk.CTkLabel(
                                scroll_grid,
                                text="No artwork found on SteamGridDB for this category.",
                                font=ctk.CTkFont(size=13),
                                text_color="#94a3b8"
                            ).pack(pady=40)
                        lbl_modal_status.configure(text="No items found.", text_color="#94a3b8")
                        _apply_modal_focus_visuals()
                        return

                    cols = 3 if curr_type in ("capsule", "wide", "hero", "logo") else 4
                    for idx, (asset_data, frames, durations) in enumerate(rendered_cards):
                        for f in frames:
                            loaded_thumb_images.append(f)
                        row = idx // cols
                        col = idx % cols

                        card = ctk.CTkFrame(scroll_grid, fg_color="#121212", border_width=1, border_color="#27272a", corner_radius=8)
                        card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")

                        lbl_img = ctk.CTkLabel(card, text="", image=frames[0])
                        lbl_img.pack(padx=8, pady=(8, 4))

                        # Setup animation cycling if multi-frame
                        if len(frames) > 1:
                            def _make_cycle(w=lbl_img, f_list=frames, d_list=durations):
                                def _step(frame_i=0):
                                    try:
                                        if w.winfo_exists():
                                            w.configure(image=f_list[frame_i])
                                            next_i = (frame_i + 1) % len(f_list)
                                            tid = modal.after(d_list[frame_i], lambda: _step(next_i))
                                            active_animation_timers.append(tid)
                                    except Exception:
                                        pass
                                _step(0)
                            _make_cycle()

                        # Author & Source text with optional animated badge
                        badge = " ✨ ANIMATED" if asset_data.get("is_animated") else ""
                        source_text = f"{asset_data.get('source', 'Community')} • {asset_data.get('author', 'Artist')}{badge}"
                        text_color = "#c084fc" if asset_data.get("is_animated") else "#71717a"
                        ctk.CTkLabel(card, text=source_text, font=ctk.CTkFont(size=10), text_color=text_color).pack(padx=6, pady=(0, 4))

                        btn_pick = ctk.CTkButton(
                            card,
                            text="Apply This Art",
                            font=ctk.CTkFont(size=11, weight="bold"),
                            height=26,
                            fg_color="#2563eb",
                            hover_color="#1d4ed8",
                            command=lambda u=asset_data["url"], t=curr_type: _apply_selected_asset(u, t)
                        )
                        btn_pick.pack(fill="x", padx=8, pady=(0, 8))

                        modal_card_widgets.append({
                            "card": card,
                            "btn": btn_pick,
                            "url": asset_data["url"]
                        })

                    lbl_modal_status.configure(text=f"Found {len(rendered_cards)} artwork choices. Click 'Apply This Art' or press (A) to select.", text_color="#34d399")
                    _apply_modal_focus_visuals()

                self.run_on_main_thread(_populate)

            threading.Thread(target=_worker, daemon=True).start()

        def _on_category_changed(val):
            _fetch_and_render_assets()

        _fetch_and_render_assets()

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
                    self.run_on_main_thread(lambda: self.lbl_status.configure(text=f"✅ {msg}", text_color="#34d399"))
                else:
                    self.run_on_main_thread(lambda: self.lbl_status.configure(text=f"⚠️ {msg}", text_color="#fbbf24"))
            except Exception as e:
                logger.error(f"Error applying video fixes: {e}")
                self.run_on_main_thread(self._stop_progress)
                self.run_on_main_thread(lambda: self.lbl_status.configure(text=f"Failed to apply video fixes: {e}", text_color="#ff4444"))

        threading.Thread(target=_fix_task, daemon=True).start()

    def open_add_non_steam_modal(self):
        """Opens a modal dialog to select and register a non-Steam visual novel into Steam."""
        modal = ctk.CTkToplevel(self)
        modal.title("Add Non-Steam Visual Novel")
        modal.geometry("620x520")
        modal.configure(fg_color="#121212")
        modal.transient(self)
        modal.grab_set()

        ctk.CTkLabel(
            modal,
            text="➕ Register Non-Steam Visual Novel",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#f1f5f9"
        ).pack(pady=(16, 6), padx=20, anchor="w")

        ctk.CTkLabel(
            modal,
            text="Select a game folder or executable from DLsite, JAST, MangaGamer, or your SD card.\nVNPM will match it with VNDB, create a Steam shortcut, and deploy 5-slot grid artwork.",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8",
            justify="left"
        ).pack(pady=(0, 10), padx=20, anchor="w")

        # 1. Path Entry & Browse
        path_label = ctk.CTkLabel(modal, text="Game Path (Folder or Executable):", font=ctk.CTkFont(size=12, weight="bold"), text_color="#f1f5f9")
        path_label.pack(anchor="w", padx=20, pady=(0, 2))

        path_frame = ctk.CTkFrame(modal, fg_color="#18181b", border_width=1, border_color="#27272a", corner_radius=8)
        path_frame.pack(fill="x", padx=20, pady=(0, 10))
        path_frame.grid_columnconfigure(0, weight=1)

        entry_path = ctk.CTkEntry(
            path_frame,
            placeholder_text="Select game directory or executable...",
            fg_color="transparent",
            border_width=0,
            text_color="#f1f5f9"
        )
        entry_path.grid(row=0, column=0, padx=8, pady=6, sticky="ew")

        # 2. Editable Title Entry
        title_label = ctk.CTkLabel(modal, text="Game Title (Editable / Live Match):", font=ctk.CTkFont(size=12, weight="bold"), text_color="#f1f5f9")
        title_label.pack(anchor="w", padx=20, pady=(0, 2))

        title_frame = ctk.CTkFrame(modal, fg_color="#18181b", border_width=1, border_color="#27272a", corner_radius=8)
        title_frame.pack(fill="x", padx=20, pady=(0, 10))
        title_frame.grid_columnconfigure(0, weight=1)

        entry_title = ctk.CTkEntry(
            title_frame,
            placeholder_text="Type or edit visual novel title...",
            fg_color="transparent",
            border_width=0,
            text_color="#f1f5f9"
        )
        entry_title.grid(row=0, column=0, padx=8, pady=6, sticky="ew")

        # 3. Match Info Card
        preview_card = ctk.CTkFrame(modal, fg_color="#18181b", border_width=1, border_color="#27272a", corner_radius=8)
        preview_card.pack(fill="both", expand=True, padx=20, pady=(0, 12))
        preview_card.grid_columnconfigure(0, weight=1)

        lbl_matched_meta = ctk.CTkLabel(
            preview_card,
            text="VNDB Database: Waiting for game selection...",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8",
            justify="left"
        )
        lbl_matched_meta.pack(anchor="w", padx=12, pady=12)

        matched_state = {"vndb_id": None}

        def _update_match_for_title(title_text):
            if not title_text.strip():
                lbl_matched_meta.configure(text="VNDB Database: (No title entered)", text_color="#94a3b8")
                matched_state["vndb_id"] = None
                return
            meta = self.non_steam_manager.match_vn_metadata(title_text)
            matched_state["vndb_id"] = meta["vndb_id"]
            if meta.get("vndb_id"):
                rating_str = f"★ {meta['rating']:.1f}" if meta.get("rating") else "No rating"
                lbl_matched_meta.configure(
                    text=f"✅ Matched: {meta['title']}\nVNDB ID: {meta['vndb_id']} ({rating_str})\nArtwork & metadata will be configured automatically.",
                    text_color="#34d399"
                )
            else:
                lbl_matched_meta.configure(
                    text=f"ℹ️ Custom Title: {meta['title']}\nVNDB: Not found in database (will use default artwork).",
                    text_color="#94a3b8"
                )

        def _on_title_typed(*args):
            _update_match_for_title(entry_title.get())

        entry_title.bind("<KeyRelease>", _on_title_typed)

        def _on_browse():
            chosen = filedialog.askdirectory(parent=modal, title="Select Non-Steam VN Game Folder")
            if not chosen:
                chosen = filedialog.askopenfilename(
                    parent=modal,
                    title="Or Select Game Executable",
                    filetypes=[("Executables", "*.exe *.sh *.bin *.x86_64"), ("All Files", "*.*")]
                )
            if chosen:
                p = Path(chosen)
                entry_path.delete(0, "end")
                entry_path.insert(0, str(p))
                folder_name = p.name if p.is_dir() else p.parent.name
                meta = self.non_steam_manager.match_vn_metadata(folder_name, p.name)
                entry_title.delete(0, "end")
                entry_title.insert(0, meta["title"])
                _update_match_for_title(meta["title"])

        btn_browse = ctk.CTkButton(
            path_frame,
            text="📂 Browse",
            width=80,
            fg_color="#27272a",
            hover_color="#3f3f46",
            command=_on_browse
        )
        btn_browse.grid(row=0, column=1, padx=6, pady=6)

        # Modal Controller Navigation for Add Non-Steam Dialog
        add_focus_state = {"index": 0}  # 0=Path Browse, 1=Title Entry, 2=Create, 3=Cancel

        def _apply_add_modal_focus():
            if not modal.winfo_exists():
                return
            idx = add_focus_state["index"]
            btn_browse.configure(border_color="#3b82f6" if idx == 0 else "#27272a", border_width=2 if idx == 0 else 0)
            title_frame.configure(border_color="#3b82f6" if idx == 1 else "#27272a", border_width=2 if idx == 1 else 1)
            btn_create.configure(border_color="#3b82f6" if idx == 2 else "#059669", border_width=2 if idx == 2 else 0)
            btn_cancel.configure(border_color="#3b82f6" if idx == 3 else "#27272a", border_width=2 if idx == 3 else 0)

            if idx == 1:
                entry_title.focus_set()
                SteamOSHelper.show_onscreen_keyboard()
            else:
                modal.focus_set()
                SteamOSHelper.hide_onscreen_keyboard()

        def _handle_add_modal_controller(action: str):
            curr_i = add_focus_state["index"]
            if action == ACTION_BACK:
                _close_add_modal()
                return

            if action == ACTION_UP:
                add_focus_state["index"] = max(0, curr_i - 1)
                _apply_add_modal_focus()
            elif action == ACTION_DOWN:
                add_focus_state["index"] = min(3, curr_i + 1)
                _apply_add_modal_focus()
            elif action == ACTION_LEFT:
                if curr_i == 3:
                    add_focus_state["index"] = 2
                    _apply_add_modal_focus()
            elif action == ACTION_RIGHT:
                if curr_i == 2:
                    add_focus_state["index"] = 3
                    _apply_add_modal_focus()
            elif action in (ACTION_SELECT, ACTION_QUICK_ACTION):
                if curr_i == 0:
                    _on_browse()
                elif curr_i == 1:
                    entry_title.focus_set()
                    SteamOSHelper.show_onscreen_keyboard()
                elif curr_i == 2:
                    _on_register()
                elif curr_i == 3:
                    _close_add_modal()

        self.push_modal_controller_handler(_handle_add_modal_controller)

        modal.bind("<Up>", lambda e: _handle_add_modal_controller(ACTION_UP) or "break")
        modal.bind("<Down>", lambda e: _handle_add_modal_controller(ACTION_DOWN) or "break")
        modal.bind("<Left>", lambda e: _handle_add_modal_controller(ACTION_LEFT) or "break")
        modal.bind("<Right>", lambda e: _handle_add_modal_controller(ACTION_RIGHT) or "break")
        modal.bind("<Return>", lambda e: _handle_add_modal_controller(ACTION_SELECT) or "break")
        modal.bind("<Escape>", lambda e: _handle_add_modal_controller(ACTION_BACK) or "break")

        def _close_add_modal():
            self.pop_modal_controller_handler(_handle_add_modal_controller)
            SteamOSHelper.hide_onscreen_keyboard()
            modal.destroy()
            self._apply_focus_visuals()

        modal.protocol("WM_DELETE_WINDOW", _close_add_modal)
        _apply_add_modal_focus()

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

