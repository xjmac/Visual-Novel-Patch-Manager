import logging
import threading
import queue
import time
import webbrowser
from tkinter import messagebox
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

APP_NAME = "VN Patch Manager"

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

        # Initial Data Load
        self.refresh_data()

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

    def _setup_settings_tab(self):
        self.tab_settings.grid_columnconfigure(1, weight=1)

        # Connection Mode
        ctk.CTkLabel(self.tab_settings, text="Connection Mode:", font=ctk.CTkFont(weight="bold"), text_color="#f1f5f9").grid(row=0, column=0, padx=12, pady=12, sticky="w")
        self.var_mode = ctk.StringVar(value=self.config_manager.config.get("mode"))
        self.opt_mode = ctk.CTkSegmentedButton(
            self.tab_settings,
            values=["local", "smb"],
            variable=self.var_mode,
            command=self._toggle_settings_fields,
            fg_color="#121212",
            selected_color="#2563eb",
            selected_hover_color="#1d4ed8",
            unselected_hover_color="#1e1e1e",
            text_color="#f1f5f9"
        )
        self.opt_mode.grid(row=0, column=1, padx=12, pady=12, sticky="w")

        # Local Settings Frame
        self.frame_local = ctk.CTkFrame(self.tab_settings, fg_color="#121212", border_width=1, border_color="#27272a", corner_radius=10)
        self.frame_local.grid(row=1, column=0, columnspan=2, padx=12, pady=8, sticky="nsew")
        self.frame_local.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self.frame_local, text="Local Path:", text_color="#f1f5f9").grid(row=0, column=0, padx=12, pady=12, sticky="w")
        self.entry_local_path = ctk.CTkEntry(self.frame_local, fg_color="#18181b", border_color="#27272a", border_width=1, text_color="#f1f5f9")
        self.entry_local_path.insert(0, self.config_manager.config.get("local_path"))
        self.entry_local_path.grid(row=0, column=1, padx=12, pady=12, sticky="ew")

        # SMB Settings Frame
        self.frame_smb = ctk.CTkFrame(self.tab_settings, fg_color="#121212", border_width=1, border_color="#27272a", corner_radius=10)
        self.frame_smb.grid(row=2, column=0, columnspan=2, padx=12, pady=8, sticky="nsew")
        self.frame_smb.grid_columnconfigure(1, weight=1)

        # SMB Fields
        smb_fields = [
            ("SMB Server IP:", "smb_server"),
            ("SMB Share Name:", "smb_share"),
            ("Path inside Share:", "smb_path"),
            ("Username:", "smb_username"),
            ("Password:", "smb_password")
        ]

        self.smb_entries = {}
        for idx, (label_text, key) in enumerate(smb_fields):
            ctk.CTkLabel(self.frame_smb, text=label_text, text_color="#f1f5f9").grid(row=idx, column=0, padx=12, pady=6, sticky="w")
            entry = ctk.CTkEntry(self.frame_smb, show="*" if "password" in key else "", fg_color="#18181b", border_color="#27272a", border_width=1, text_color="#f1f5f9")
            entry.insert(0, self.config_manager.config.get(key, ""))
            entry.grid(row=idx, column=1, padx=12, pady=6, sticky="ew")
            self.smb_entries[key] = entry

        # Save Button
        self.btn_save = ctk.CTkButton(
            self.tab_settings,
            text="Save Settings & Refresh",
            font=ctk.CTkFont(weight="bold"),
            height=34,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self.save_settings
        )
        self.btn_save.grid(row=3, column=0, columnspan=2, pady=20)

        self._toggle_settings_fields(self.var_mode.get())

    def _toggle_settings_fields(self, mode):
        """Show/Hide frames based on selected mode."""
        if mode == "local":
            self.frame_local.grid()
            self.frame_smb.grid_remove()
        else:
            self.frame_local.grid_remove()
            self.frame_smb.grid()

    def save_settings(self):
        """Commits GUI inputs to the config manager."""
        self.config_manager.config["mode"] = self.var_mode.get()
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

        # Status Filter
        self.opt_filter = ctk.CTkSegmentedButton(
            toolbar_frame,
            values=["All", "Available", "Patched", "Missing 18+ (VNDB)", "Backed Up"],
            variable=self.filter_var,
            command=lambda v: self._apply_filters_and_render(),
            fg_color="#121212",
            selected_color="#2563eb",
            selected_hover_color="#1d4ed8",
            unselected_hover_color="#1e1e1e",
            text_color="#f1f5f9"
        )
        self.opt_filter.grid(row=0, column=1, padx=(0, 10))

        # Sort Dropdown
        self.opt_sort = ctk.CTkOptionMenu(
            toolbar_frame,
            values=["Title (A-Z)", "Title (Z-A)", "VNDB Rating", "Status Priority", "Installed First"],
            variable=self.sort_var,
            command=lambda v: self._apply_filters_and_render(),
            width=135,
            fg_color="#121212",
            button_color="#1e1e1e",
            button_hover_color="#27272a",
            text_color="#f1f5f9"
        )
        self.opt_sort.grid(row=0, column=2, padx=(0, 10))

        # View Mode Toggle
        self.opt_view = ctk.CTkSegmentedButton(
            toolbar_frame,
            values=["Grid", "List"],
            variable=self.view_var,
            command=lambda v: self._apply_filters_and_render(),
            fg_color="#121212",
            selected_color="#2563eb",
            selected_hover_color="#1d4ed8",
            unselected_hover_color="#1e1e1e",
            text_color="#f1f5f9"
        )
        self.opt_view.grid(row=0, column=3)

        # Scrollable Game Cards Container - OLED Pure Black Background
        self.scrollable_games = ctk.CTkScrollableFrame(
            self.tab_games,
            corner_radius=8,
            fg_color="#000000",
            scrollbar_button_color="#27272a",
            scrollbar_button_hover_color="#3f3f46"
        )
        self.scrollable_games.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 4))
        self.scrollable_games.grid_columnconfigure(0, weight=1)

    def _setup_bottom_footer(self):
        footer_frame = ctk.CTkFrame(self, fg_color="transparent")
        footer_frame.grid(row=2, column=0, padx=20, pady=(4, 10), sticky="ew")
        footer_frame.grid_columnconfigure(0, weight=1)

        self.lbl_status = ctk.CTkLabel(footer_frame, text="Ready", text_color="gray", font=ctk.CTkFont(size=12))
        self.lbl_status.grid(row=0, column=0, sticky="w")

        self.progress_bar = ctk.CTkProgressBar(footer_frame, width=200, height=10)
        self.progress_bar.grid(row=0, column=1, sticky="e")
        self.progress_bar.set(0)

    def refresh_data(self):
        """Scans Steam, NAS repository, and VNDB to update the UI with instant loading and background sync."""
        self.lbl_status.configure(text="Loading visual novels...", text_color="gray")
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()

        def _bg_task():
            try:
                # ----------------------------------------------------
                # PHASE 1: INSTANT LOCAL & BUNDLED DISCOVERY (< 0.05s)
                # ----------------------------------------------------
                # 1. Fetch available patches from NAS/Local
                self.repo.refresh_patches()

                # 2. Get all owned Steam games (installed and uninstalled)
                all_owned = self.steam_scanner.get_owned_games()

                # 3. Get all existing cached & bundled VNDB metadata (< 0.005s)
                cached_vndb = self.vndb_scanner.get_cached_vns()

                # 4. Build immediate initial game list
                current_games = {}
                for app_id, game_data in all_owned.items():
                    patch_info = self.repo.available_patches.get(app_id)
                    has_repo_patch = patch_info is not None
                    vn_info = cached_vndb.get(app_id, {})
                    has_vndb_18_patch = vn_info.get("has_18plus_en_patch", False)

                    if has_repo_patch or has_vndb_18_patch:
                        is_installed = bool(game_data.get("is_installed", True)) and bool(game_data.get("path"))
                        is_patched = is_installed and PatchExecutionEngine.get_patch_status(game_data["path"], patch_info, vn_info)
                        g_copy = game_data.copy()
                        if vn_info:
                            g_copy["vndb"] = vn_info
                            if vn_info.get("vn_title") and (not g_copy.get("name") or g_copy["name"].startswith("Steam App #")):
                                g_copy["name"] = vn_info["vn_title"]
                        current_games[app_id] = g_copy

                # Also add uninstalled games from cache that have 18+ patches
                for app_id, vn_info in cached_vndb.items():
                    if vn_info.get("has_18plus_en_patch") and app_id not in current_games and app_id in all_owned:
                        owned_data = all_owned.get(app_id, {})
                        current_games[app_id] = {
                            "name": vn_info.get("vn_title") or owned_data.get("name", f"Steam App #{app_id}"),
                            "path": owned_data.get("path", ""),
                            "library_path": owned_data.get("library_path", ""),
                            "is_installed": owned_data.get("is_installed", False),
                            "vndb": vn_info
                        }

                # Also add any games discovered from the patch repository that are in the user's library
                for app_id, patch_data in self.repo.available_patches.items():
                    if app_id in all_owned and app_id not in current_games:
                        vn_info = cached_vndb.get(app_id, {})
                        owned_data = all_owned.get(app_id, {})
                        game_name = patch_data.get("game_name") or vn_info.get("vn_title") or owned_data.get("name", f"Steam App #{app_id}")
                        current_games[app_id] = {
                            "name": game_name,
                            "path": owned_data.get("path", ""),
                            "library_path": owned_data.get("library_path", ""),
                            "is_installed": owned_data.get("is_installed", False),
                            "vndb": vn_info
                        }

                # Compute cached status and search haystack in background thread
                for app_id, game_data in current_games.items():
                    game_data["status_info"] = self._compute_status_info(app_id, game_data)

                # IMMEDIATELY populate UI (< 0.05s) so the user never waits
                self.run_on_main_thread(self._populate_game_list, current_games.copy())

                # Pre-download cover art for currently displayed games and refresh banners live
                for app_id in list(current_games.keys()):
                    if self.cover_manager.download_cover(app_id):
                        self.run_on_main_thread(self._refresh_banner, app_id)

                # ----------------------------------------------------
                # PHASE 2: FAST ASYNCHRONOUS SNAPSHOT SYNC (~2-3s)
                # ----------------------------------------------------
                self.run_on_main_thread(
                    lambda: self.lbl_status.configure(text="Checking VNDB for updates...", text_color="gray")
                )

                synced = self.vndb_scanner.sync_vndb_snapshot()
                if synced:
                    updated_vndb = self.vndb_scanner.get_cached_vns()
                    changed = False
                    for app_id, vn_info in updated_vndb.items():
                        if vn_info.get("has_18plus_en_patch") and app_id not in current_games and app_id in all_owned:
                            owned_data = all_owned.get(app_id, {})
                            current_games[app_id] = {
                                "name": vn_info.get("vn_title") or owned_data.get("name", f"Steam App #{app_id}"),
                                "path": owned_data.get("path", ""),
                                "library_path": owned_data.get("library_path", ""),
                                "is_installed": owned_data.get("is_installed", False),
                                "vndb": vn_info
                            }
                            changed = True
                            if self.cover_manager.download_cover(app_id):
                                self.run_on_main_thread(self._refresh_banner, app_id)

                    if changed:
                        for app_id, game_data in current_games.items():
                            if "status_info" not in game_data:
                                game_data["status_info"] = self._compute_status_info(app_id, game_data)
                        self.run_on_main_thread(self._populate_game_list, current_games.copy())

                self.run_on_main_thread(
                    lambda: self.lbl_status.configure(text="Library sync complete.", text_color="gray")
                )
            except Exception as e:
                logger.warning(f"Error during refresh_data: {e}")
                self.run_on_main_thread(
                    lambda: self.lbl_status.configure(text="Scan completed with warnings.", text_color="#f87171")
                )
            finally:
                self.run_on_main_thread(self._stop_progress)

        # Run in thread so GUI never freezes
        threading.Thread(target=_bg_task, daemon=True).start()

    def _stop_progress(self):
        self.progress_bar.stop()
        self.progress_bar.set(1.0)

    def _populate_game_list(self, filtered_games):
        self._stop_progress()
        self._all_supported_games = filtered_games or {}
        self._apply_filters_and_render()

    def _apply_filters_and_render(self):
        # Cancel any in-flight rendering batches immediately
        if self._active_render_job is not None:
            try:
                self.after_cancel(self._active_render_job)
            except Exception:
                pass
            self._active_render_job = None

        # Clear existing items
        for widget in self.scrollable_games.winfo_children():
            widget.destroy()

        if not self._all_supported_games:
            ctk.CTkLabel(self.scrollable_games, text="No Visual Novels requiring 18+ patches found in your Steam library.", font=ctk.CTkFont(size=14)).pack(pady=40)
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
            if active_filter == "Available" and (is_patched or not has_local_patch):
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
        else: # Default: Title (A-Z)
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
            if end_idx < len(items):
                self._active_render_job = self.after(16, lambda: render_batch(end_idx, batch_size))
            else:
                self._active_render_job = None
        
        render_batch(0)

    def _render_list_view(self, games_dict):
        self.scrollable_games.grid_columnconfigure(0, weight=1)
        self.scrollable_games.grid_columnconfigure(1, weight=0)

        items = list(games_dict.items())

        def render_batch(start_idx, batch_size=15):
            if start_idx >= len(items):
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

                else:
                    vndb_url = vn_info.get("vndb_url") or f"https://vndb.org/{vn_info.get('vn_id', '')}"
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

                    vndb_url = vn_info.get("vndb_url") or (f"https://vndb.org/{vn_info.get('vn_id')}" if vn_info.get("vn_id") else None)
                    if vndb_url:
                        btn_vndb = ctk.CTkButton(
                            actions_frame,
                            text="🔗 Open VNDB (Get Patch)",
                            font=ctk.CTkFont(size=11, weight="bold"),
                            height=30,
                            fg_color="#0284c7",
                            hover_color="#0369a1",
                            command=lambda u=vndb_url: webbrowser.open(u)
                        )
                        btn_vndb.pack(side="left")
            if end_idx < len(items):
                self._active_render_job = self.after(16, lambda: render_batch(end_idx, batch_size))
            else:
                self._active_render_job = None
        
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

