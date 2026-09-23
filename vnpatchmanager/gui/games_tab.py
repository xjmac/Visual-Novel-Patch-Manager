"""
Games Library tab UI, toolbar controls, filtering, sorting, and batch rendering.
"""

import logging
import customtkinter as ctk

from .constants import (
    COLOR_BG_BLACK,
    COLOR_PRIMARY_BLUE,
    COLOR_PRIMARY_HOVER,
    COLOR_TEXT_WHITE,
    COLOR_TEXT_MUTED,
    POSTER_CARD_SIZE,
    POSTER_COLUMNS_MIN,
    POSTER_COL_WIDTH,
)
from .views import create_poster_card, show_game_detail_modal

logger = logging.getLogger(__name__)


class GamesTabMixin:
    """Provides games tab layout, search, filter/sort controls, and batch rendering orchestration."""

    def _setup_games_tab(self):
        """Constructs the games library tab toolbar and scrollable container."""
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
            height=34,
        )
        search_frame.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        search_frame.grid_columnconfigure(1, weight=1)
        self._search_frame = search_frame

        lbl_search_icon = ctk.CTkLabel(
            search_frame,
            text="🔍",
            font=ctk.CTkFont(size=13),
            text_color=COLOR_TEXT_MUTED,
        )
        lbl_search_icon.grid(row=0, column=0, padx=(8, 4), pady=2)

        self.entry_search = ctk.CTkEntry(
            search_frame,
            placeholder_text="Search visual novels by title...",
            placeholder_text_color="#71717a",
            textvariable=self.search_var,
            fg_color="transparent",
            border_width=0,
            text_color=COLOR_TEXT_WHITE,
            font=ctk.CTkFont(size=12),
            height=30,
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
            command=lambda: self.search_var.set(""),
        )
        self.btn_clear_search.grid(row=0, column=2, padx=(2, 6), pady=2)

        # Status Filter Container
        filter_frame = ctk.CTkFrame(
            toolbar_frame,
            fg_color="#18181b",
            border_color="#3f3f46",
            border_width=1,
            corner_radius=8,
        )
        filter_frame.grid(row=0, column=1, padx=(0, 10))
        self._filter_frame = filter_frame

        self.opt_filter = ctk.CTkSegmentedButton(
            filter_frame,
            values=["All", "Patch Available", "Patched", "Missing 18+ (VNDB)", "Backed Up"],
            variable=self.filter_var,
            command=lambda v: self._apply_filters_and_render(),
            fg_color="#121212",
            selected_color=COLOR_PRIMARY_BLUE,
            selected_hover_color=COLOR_PRIMARY_HOVER,
            unselected_hover_color="#1e1e1e",
            text_color=COLOR_TEXT_WHITE,
        )
        self.opt_filter.pack(padx=2, pady=2)

        # Sort Dropdown Container
        sort_frame = ctk.CTkFrame(
            toolbar_frame,
            fg_color="#18181b",
            border_color="#3f3f46",
            border_width=1,
            corner_radius=8,
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
            text_color=COLOR_TEXT_WHITE,
        )
        self.opt_sort.pack(padx=2, pady=2)

        # View Mode Toggle Container
        view_frame = ctk.CTkFrame(
            toolbar_frame,
            fg_color="#18181b",
            border_color="#3f3f46",
            border_width=1,
            corner_radius=8,
        )
        view_frame.grid(row=0, column=3)
        self._view_frame = view_frame

        self.opt_view = ctk.CTkSegmentedButton(
            view_frame,
            values=["Posters", "Grid", "List"],
            variable=self.view_var,
            command=lambda v: self._apply_filters_and_render(),
            fg_color="#121212",
            selected_color=COLOR_PRIMARY_BLUE,
            selected_hover_color=COLOR_PRIMARY_HOVER,
            unselected_hover_color="#1e1e1e",
            text_color=COLOR_TEXT_WHITE,
        )
        self.opt_view.pack(padx=2, pady=2)

        # Scrollable Game Area - SteamOS Slate Canvas
        self.scrollable_games = ctk.CTkScrollableFrame(
            self.tab_games,
            fg_color=COLOR_BG_BLACK,
            corner_radius=10,
            border_width=1,
            border_color="#18181b",
        )
        self.scrollable_games.grid(row=1, column=0, sticky="nsew")
        self.scrollable_games.grid_columnconfigure(0, weight=1)

        # Attach viewport canvas configure listener WITH add="+" so CTkScrollableFrame's
        # internal scrollregion configure binding is never overwritten
        canvas = getattr(self.scrollable_games, "_parent_canvas", None)
        if canvas:
            canvas.bind("<Configure>", self._on_games_area_resized, add="+")
        else:
            self.scrollable_games.bind("<Configure>", self._on_games_area_resized, add="+")

        # Bind universal mouse wheel scrolling handlers
        self._bind_mouse_wheel_scrolling()

    def _update_scroll_region(self):
        """Explicitly recalculates and updates the canvas scrollregion."""
        canvas = getattr(self.scrollable_games, "_parent_canvas", None)
        if canvas and canvas.winfo_exists():
            canvas.update_idletasks()
            bbox = canvas.bbox("all")
            if bbox:
                canvas.configure(scrollregion=bbox)

    def _bind_mouse_wheel_scrolling(self):
        """Binds universal mouse wheel handlers across Linux (X11 & Wayland) and Windows."""
        canvas = getattr(self.scrollable_games, "_parent_canvas", None)
        if not canvas:
            return

        def _on_mouse_wheel(event):
            bbox = canvas.bbox("all")
            if not bbox:
                return
            canvas_h = canvas.winfo_height()
            if (bbox[3] - bbox[1]) <= canvas_h:
                return

            if getattr(event, "num", None) == 4:
                canvas.yview_scroll(-3, "units")
                return "break"
            elif getattr(event, "num", None) == 5:
                canvas.yview_scroll(3, "units")
                return "break"

            delta = getattr(event, "delta", 0)
            if delta != 0:
                step = -1 if delta > 0 else 1
                canvas.yview_scroll(step * 3, "units")
                return "break"

        for widget in (canvas, self.scrollable_games):
            widget.bind("<Button-4>", _on_mouse_wheel, add="+")
            widget.bind("<Button-5>", _on_mouse_wheel, add="+")
            widget.bind("<MouseWheel>", _on_mouse_wheel, add="+")

    def _attach_mouse_wheel(self, widget):
        """Recursively binds mouse wheel events on a widget and its children to scroll the library canvas."""
        canvas = getattr(self.scrollable_games, "_parent_canvas", None)
        if not canvas:
            return

        def _on_mouse_wheel(event):
            bbox = canvas.bbox("all")
            if not bbox:
                return
            canvas_h = canvas.winfo_height()
            if (bbox[3] - bbox[1]) <= canvas_h:
                return

            if getattr(event, "num", None) == 4:
                canvas.yview_scroll(-3, "units")
                return "break"
            elif getattr(event, "num", None) == 5:
                canvas.yview_scroll(3, "units")
                return "break"

            delta = getattr(event, "delta", 0)
            if delta != 0:
                step = -1 if delta > 0 else 1
                canvas.yview_scroll(step * 3, "units")
                return "break"

        for w in (widget, getattr(widget, "_canvas", None), getattr(widget, "_label", None)):
            if w and hasattr(w, "bind"):
                try:
                    w.bind("<Button-4>", _on_mouse_wheel, add="+")
                    w.bind("<Button-5>", _on_mouse_wheel, add="+")
                    w.bind("<MouseWheel>", _on_mouse_wheel, add="+")
                except Exception:
                    pass
        for child in widget.winfo_children():
            self._attach_mouse_wheel(child)

    def _on_games_area_resized(self, event):
        """Dynamically recomputes column layout when window is resized."""
        self._update_scroll_region()
        if "Posters" not in self.view_var.get():
            return
        new_w = event.width
        last_w = getattr(self, "_last_rendered_width", 0)
        if abs(new_w - last_w) > 60:
            if getattr(self, "_resize_job", None):
                try:
                    self.after_cancel(self._resize_job)
                except Exception:
                    pass
            self._resize_job = self.after(150, self._apply_filters_and_render)

    def open_game_detail(self, app_id: str, game_data: dict):
        """Displays the full console-grade Game Detail Drawer/Modal for the selected visual novel."""
        status_info = self._get_game_status_info(app_id, game_data)
        return show_game_detail_modal(self, app_id, game_data, status_info)

    def _on_search_changed(self, *args):
        """Debounces search input to prevent UI lag during typing."""
        if hasattr(self, 'btn_clear_search'):
            query = self.search_var.get().strip()
            if query:
                self.btn_clear_search.configure(text_color=COLOR_TEXT_WHITE, state="normal")
            else:
                self.btn_clear_search.configure(text_color="#52525b", state="disabled")

        if self._search_debounce_job:
            try:
                self.after_cancel(self._search_debounce_job)
            except Exception:
                pass
        self._search_debounce_job = self.after(60, self._apply_filters_and_render)

    def _populate_game_list(self, supported_games: dict):
        """Populates the game list with scanned or filtered visual novels."""
        self._all_supported_games = supported_games
        self._apply_filters_and_render()

    def _apply_filters_and_render(self):
        """Filters, sorts, and triggers batch rendering of games."""
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
            ctk.CTkLabel(
                self.scrollable_games,
                text="No patchable visual novels found.",
                font=ctk.CTkFont(size=14),
            ).pack(pady=40)
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
            ctk.CTkLabel(
                self.scrollable_games,
                text="No Visual Novels match the current search/filter.",
                font=ctk.CTkFont(size=13),
            ).pack(pady=40)
            self.lbl_status.configure(text="Filter active: 0 matches.", text_color="gray")
            return

        # Apply Library Sorting
        sort_mode = self.sort_var.get()

        if sort_mode == "Title (Z-A)":
            sorted_games = dict(sorted(matched_games.items(), key=lambda x: x[1]["name"].lower(), reverse=True))
        elif sort_mode == "VNDB Rating":
            sorted_games = dict(
                sorted(
                    matched_games.items(),
                    key=lambda x: (
                        x[1].get("vndb", {}).get("rating") is not None,
                        x[1].get("vndb", {}).get("rating") or 0.0,
                        x[1].get("vndb", {}).get("votecount") or 0,
                        x[1]["name"].lower(),
                    ),
                    reverse=True,
                )
            )
        elif sort_mode == "Status Priority":
            sorted_games = dict(
                sorted(
                    matched_games.items(),
                    key=lambda x: (
                        (x[1].get("status_info") or self._compute_status_info(x[0], x[1])).get("status_priority", 3),
                        x[1]["name"].lower(),
                    ),
                )
            )
        elif sort_mode == "Installed First":
            sorted_games = dict(
                sorted(
                    matched_games.items(),
                    key=lambda x: (not x[1].get("is_installed", False), x[1]["name"].lower()),
                )
            )
        else:  # Default: Title (A-Z)
            sorted_games = dict(sorted(matched_games.items(), key=lambda x: x[1]["name"].lower()))

        self._banner_widgets.clear()
        if "Posters" in view_mode:
            self._render_poster_view(sorted_games)
        elif "Grid" in view_mode:
            self._render_grid_view(sorted_games)
        else:
            self._render_list_view(sorted_games)

        self.lbl_status.configure(text=f"Showing {len(matched_games)} of {total_vns} Visual Novel(s).", text_color="gray")

    def _render_poster_view(self, games_dict):
        """Batch-renders games in a responsive multi-column poster gallery (2:3 portrait capsules)."""
        try:
            curr_w = self.scrollable_games.winfo_width()
            if curr_w <= 100:
                curr_w = self.winfo_width()
        except Exception:
            curr_w = 1060
        self._last_rendered_width = curr_w

        col_count = max(POSTER_COLUMNS_MIN, curr_w // POSTER_COL_WIDTH)
        self._poster_col_count = col_count

        for c in range(col_count):
            self.scrollable_games.grid_columnconfigure(c, weight=1)

        items = list(games_dict.items())

        def render_batch(start_idx, batch_size=12):
            if start_idx >= len(items):
                self._apply_focus_visuals()
                return
            end_idx = min(start_idx + batch_size, len(items))
            for idx in range(start_idx, end_idx):
                app_id, game_data = items[idx]
                status_info = self._get_game_status_info(app_id, game_data)
                row_idx = idx // col_count
                col_idx = idx % col_count
                entry = create_poster_card(
                    self.scrollable_games,
                    app_id,
                    game_data,
                    status_info,
                    self.cover_manager,
                    on_select=self.open_game_detail,
                    row_idx=row_idx,
                    col_idx=col_idx,
                )
                self._card_entries.append(entry)
                self._attach_mouse_wheel(entry["card"])
                if entry.get("banner_label"):
                    self._banner_widgets.setdefault(str(app_id), []).append(
                        (entry["banner_label"], game_data.get("name", ""), POSTER_CARD_SIZE)
                    )

            if end_idx < len(items):
                self._active_render_job = self.after(16, lambda: render_batch(end_idx, batch_size))
            else:
                self._active_render_job = None
                self._update_scroll_region()
                self._apply_focus_visuals()

        render_batch(0)

    def _render_grid_view(self, games_dict):
        """Batch-renders games in a 2-column grid."""
        self.scrollable_games.grid_columnconfigure(0, weight=1)
        self.scrollable_games.grid_columnconfigure(1, weight=1)

        items = list(games_dict.items())

        def render_batch(start_idx, batch_size=10):
            if start_idx >= len(items):
                self._update_scroll_region()
                self._apply_focus_visuals()
                return
            end_idx = min(start_idx + batch_size, len(items))
            for idx in range(start_idx, end_idx):
                app_id, game_data = items[idx]
                row_idx = idx // 2
                col_idx = idx % 2
                entry = self._create_grid_card(self.scrollable_games, app_id, game_data, row_idx, col_idx)
                self._card_entries.append(entry)
                self._attach_mouse_wheel(entry["card"])

            if end_idx < len(items):
                self._active_render_job = self.after(16, lambda: render_batch(end_idx, batch_size))
            else:
                self._active_render_job = None
                self._update_scroll_region()
                self._apply_focus_visuals()

        render_batch(0)

    def _render_list_view(self, games_dict):
        """Batch-renders games in a compact single-column list."""
        self.scrollable_games.grid_columnconfigure(0, weight=1)
        self.scrollable_games.grid_columnconfigure(1, weight=0)

        items = list(games_dict.items())

        def render_batch(start_idx, batch_size=15):
            if start_idx >= len(items):
                self._update_scroll_region()
                self._apply_focus_visuals()
                return
            end_idx = min(start_idx + batch_size, len(items))
            for row_idx in range(start_idx, end_idx):
                app_id, game_data = items[row_idx]
                entry = self._create_list_row(self.scrollable_games, app_id, game_data, row_idx)
                self._card_entries.append(entry)
                self._attach_mouse_wheel(entry["card"])

            if end_idx < len(items):
                self._active_render_job = self.after(16, lambda: render_batch(end_idx, batch_size))
            else:
                self._active_render_job = None
                self._update_scroll_region()
                self._apply_focus_visuals()

        render_batch(0)
