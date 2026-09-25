"""
Library toolbar, filtering, sorting, and poster/list rendering.
"""

import logging
import webbrowser
import customtkinter as ctk

from .constants import (
    FILTER_LABELS,
    FILTER_ORDER,
    SORT_ORDER,
)
from .status import status_word
from .theme import (
    COLOR_BORDER_2,
    COLOR_BORDER_FOCUSED,
    COLOR_CANVAS,
    COLOR_ELEVATION_2,
    COLOR_ELEVATION_3,
    COLOR_PRIMARY_BLUE,
    COLOR_PRIMARY_HOVER,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    MIN_TOUCH_TARGET,
    POSTER_CARD_SIZE,
    POSTER_COLUMNS_MIN,
    POSTER_COL_WIDTH,
)
from .views import create_poster_card

logger = logging.getLogger(__name__)

_LEGACY_FILTERS = {
    "All": "all",
    "Patch Available": "ready",
    "Patched": "patched",
    "Missing 18+ (VNDB)": "missing",
    "Backed Up": "backup",
}
_LEGACY_SORTS = {
    "Title (A-Z)": "A-Z",
    "Title (Z-A)": "Z-A",
    "VNDB Rating": "Rating",
}


class GamesTabMixin:
    """Library chips, search filtering, and poster or list rendering."""

    def _canonical_filter(self) -> str:
        raw = self.filter_var.get()
        mapped = _LEGACY_FILTERS.get(raw, raw)
        return mapped if mapped in FILTER_ORDER else "all"

    def _canonical_sort(self) -> str:
        raw = self.sort_var.get()
        mapped = _LEGACY_SORTS.get(raw, raw)
        return mapped if mapped in SORT_ORDER else "A-Z"

    def _setup_games_tab(self):
        """Builds the filter chips and the scrollable library."""
        self.chip_bar.grid_columnconfigure(1, weight=1)

        chip_row = ctk.CTkFrame(self.chip_bar, fg_color="transparent")
        chip_row.grid(row=0, column=0, sticky="w")
        self._chip_buttons = []
        for fid in FILTER_ORDER:
            button = ctk.CTkButton(
                chip_row,
                text=FILTER_LABELS[fid],
                height=MIN_TOUCH_TARGET,
                width=88,
                corner_radius=8,
                border_width=1,
                border_color=COLOR_BORDER_2,
                fg_color=COLOR_ELEVATION_2,
                hover_color=COLOR_ELEVATION_3,
                text_color=COLOR_TEXT_PRIMARY,
                font=ctk.CTkFont(size=15),
                command=lambda value=fid: self._select_filter(value),
            )
            button.pack(side="left", padx=(0, 8))
            self._chip_buttons.append(button)
        self._filter_frame = chip_row

        self.lbl_stats = ctk.CTkLabel(
            self.chip_bar,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        )
        self.lbl_stats.grid(row=0, column=1, sticky="w", padx=8)

        self._sort_frame = ctk.CTkFrame(self.chip_bar, fg_color="transparent")
        self._sort_frame.grid(row=0, column=2, padx=(0, 8))
        self.opt_sort = ctk.CTkOptionMenu(
            self._sort_frame,
            values=SORT_ORDER,
            variable=self.sort_var,
            command=lambda _value: self._apply_filters_and_render(),
            width=100,
            height=MIN_TOUCH_TARGET,
            fg_color=COLOR_ELEVATION_2,
            button_color=COLOR_ELEVATION_3,
            button_hover_color=COLOR_BORDER_2,
            text_color=COLOR_TEXT_PRIMARY,
        )
        self.opt_sort.pack()

        self._view_frame = ctk.CTkFrame(
            self.chip_bar,
            fg_color=COLOR_ELEVATION_2,
            border_width=1,
            border_color=COLOR_BORDER_2,
            corner_radius=8,
        )
        self._view_frame.grid(row=0, column=3)
        self._btn_view_posters = ctk.CTkButton(
            self._view_frame,
            text="Posters",
            width=80,
            height=MIN_TOUCH_TARGET,
            fg_color=COLOR_PRIMARY_BLUE,
            hover_color=COLOR_PRIMARY_HOVER,
            command=lambda: self._select_view("Posters"),
        )
        self._btn_view_posters.pack(side="left", padx=2, pady=2)
        self._btn_view_list = ctk.CTkButton(
            self._view_frame,
            text="List",
            width=64,
            height=MIN_TOUCH_TARGET,
            fg_color="transparent",
            hover_color=COLOR_ELEVATION_3,
            text_color=COLOR_TEXT_PRIMARY,
            command=lambda: self._select_view("List"),
        )
        self._btn_view_list.pack(side="left", padx=2, pady=2)

        self.library_host.grid_rowconfigure(0, weight=1)
        self.library_host.grid_columnconfigure(0, weight=1)
        self.scrollable_games = ctk.CTkScrollableFrame(
            self.library_host,
            fg_color=COLOR_CANVAS,
            corner_radius=0,
        )
        self.scrollable_games.grid(row=0, column=0, sticky="nsew")
        self.scrollable_games.grid_columnconfigure(0, weight=1)

        self._empty_frame = ctk.CTkFrame(self.library_host, fg_color=COLOR_CANVAS)
        self._empty_frame.grid(row=0, column=0, sticky="nsew")
        self._empty_frame.grid_remove()
        ctk.CTkLabel(
            self._empty_frame,
            text="The patch folder has not been chosen.",
            font=ctk.CTkFont(size=15),
            text_color=COLOR_TEXT_MUTED,
        ).pack(pady=(80, 12))
        ctk.CTkButton(
            self._empty_frame,
            text="Choose folder",
            height=48,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color=COLOR_PRIMARY_BLUE,
            hover_color=COLOR_PRIMARY_HOVER,
            command=self._choose_patch_folder,
        ).pack()

        canvas = getattr(self.scrollable_games, "_parent_canvas", None)
        if canvas:
            canvas.bind("<Configure>", self._on_games_area_resized, add="+")
        else:
            self.scrollable_games.bind("<Configure>", self._on_games_area_resized, add="+")
        self._bind_mouse_wheel_scrolling()
        self._paint_filter_chips()
        self._paint_view_toggle()

    def _select_filter(self, value: str):
        self.filter_var.set(value)
        self._paint_filter_chips()
        self._apply_filters_and_render()

    def _select_view(self, value: str):
        self.view_var.set("List" if value == "List" else "Posters")
        self._paint_view_toggle()
        self._apply_filters_and_render()

    def _paint_filter_chips(self):
        current = self._canonical_filter()
        focused = getattr(self, "_focused_zone", "") == "CHIPS"
        chip_idx = getattr(self, "_focused_chip_idx", -1)
        for idx, fid in enumerate(FILTER_ORDER):
            button = self._chip_buttons[idx]
            selected = fid == current
            is_focus = focused and chip_idx == idx
            button.configure(
                fg_color=COLOR_PRIMARY_BLUE if selected else COLOR_ELEVATION_2,
                border_width=2 if is_focus else 1,
                border_color=COLOR_BORDER_FOCUSED if is_focus else COLOR_BORDER_2,
            )

    def _paint_view_toggle(self):
        posters = "List" not in self.view_var.get()
        self._btn_view_posters.configure(
            fg_color=COLOR_PRIMARY_BLUE if posters else "transparent",
            text_color=COLOR_TEXT_PRIMARY,
        )
        self._btn_view_list.configure(
            fg_color=COLOR_PRIMARY_BLUE if not posters else "transparent",
            text_color=COLOR_TEXT_PRIMARY,
        )

    def _show_empty_folder(self):
        self._empty_folder = True
        self.scrollable_games.grid_remove()
        self._empty_frame.grid()
        if hasattr(self, "chip_bar"):
            self.chip_bar.grid_remove()
        self.lbl_status.configure(text="The patch folder has not been chosen.", text_color="gray")
        self.lbl_stats.configure(text="")

    def _hide_empty_folder(self):
        self._empty_folder = False
        self._empty_frame.grid_remove()
        self.scrollable_games.grid()
        if hasattr(self, "chip_bar") and not (getattr(self, "_game_page", None) and self._use_full_page()):
            self.chip_bar.grid()

    def _update_scroll_region(self):
        """Explicitly recalculates and updates the canvas scrollregion."""
        canvas = getattr(self.scrollable_games, "_parent_canvas", None)
        if canvas and canvas.winfo_exists():
            canvas.update_idletasks()
            bbox = canvas.bbox("all")
            if bbox:
                canvas.configure(scrollregion=bbox)

    def _bind_mouse_wheel_scrolling(self):
        """Binds mouse wheel handlers across Linux and Windows."""
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
            if getattr(event, "num", None) == 5:
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
        """Recursively binds mouse wheel events so cards scroll the library."""
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
            if getattr(event, "num", None) == 5:
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
        """Recomputes poster columns when the library width changes."""
        self._update_scroll_region()
        if "List" in self.view_var.get():
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
        """Opens the in-window game page for a library card."""
        status_info = self._get_game_status_info(app_id, game_data)
        return self._open_game_page(app_id, game_data, status_info)

    def _on_search_changed(self, *args):
        """Debounces search input."""
        if self._search_debounce_job:
            try:
                self.after_cancel(self._search_debounce_job)
            except Exception:
                pass
        self._search_debounce_job = self.after(60, self._apply_filters_and_render)

    def _populate_game_list(self, supported_games: dict):
        """Stores a scan result and renders it."""
        self._all_supported_games = supported_games
        self._hide_empty_folder()
        self._apply_filters_and_render()

    def _filter_matches(self, status_info: dict, active: str) -> bool:
        if active in ("all", "All", ""):
            return True
        if active == "Patch Available":
            return bool(status_info.get("has_local_patch"))
        if active == "Patched":
            return bool(status_info.get("is_patched"))
        if active == "Missing 18+ (VNDB)":
            return bool(status_info.get("has_vndb_18_patch")) and not status_info.get("has_local_patch")
        if active == "Backed Up":
            return bool(status_info.get("has_clean_backup") or status_info.get("has_backup"))
        word = status_info.get("status_word") or status_word(status_info)
        return word.lower() == active.lower()

    def _apply_filters_and_render(self):
        """Filters, sorts, and batch-renders the library."""
        if getattr(self, "_empty_folder", False):
            return
        if self._active_render_job:
            try:
                self.after_cancel(self._active_render_job)
            except Exception:
                pass
            self._active_render_job = None

        for widget in self.scrollable_games.winfo_children():
            widget.destroy()
        self._card_entries.clear()
        self._paint_filter_chips()
        self._paint_view_toggle()

        if not self._all_supported_games:
            ctk.CTkLabel(
                self.scrollable_games,
                text="No patchable visual novels found.",
                font=ctk.CTkFont(size=15),
                text_color=COLOR_TEXT_MUTED,
            ).pack(pady=40)
            self.lbl_status.configure(text="Scan complete. No patchable visual novels found.", text_color="gray")
            self.lbl_stats.configure(text="0 Patchable VNs Found")
            return

        search_query = self.search_var.get().strip().lower()
        active_filter = self.filter_var.get()
        view_mode = self.view_var.get()
        matched_games = {}
        total_patched = 0
        total_local_available = 0
        total_missing_18 = 0

        for app_id, game_data in self._all_supported_games.items():
            status_info = game_data.get("status_info") or self._compute_status_info(app_id, game_data)
            game_data["status_info"] = status_info
            if status_info["is_patched"]:
                total_patched += 1
            if status_info["has_local_patch"]:
                total_local_available += 1
            elif status_info["has_vndb_18_patch"]:
                total_missing_18 += 1
            if not self._filter_matches(status_info, active_filter):
                continue
            if search_query and search_query not in status_info.get("search_haystack", ""):
                name = game_data.get("name", "").lower()
                vn_title = (status_info.get("vn_info") or {}).get("vn_title", "").lower()
                if search_query not in name and search_query not in vn_title and search_query not in str(app_id):
                    continue
            matched_games[app_id] = game_data

        total_vns = len(self._all_supported_games)
        self.lbl_stats.configure(
            text=f"{total_vns} Patchable VNs · {total_local_available} ready · {total_missing_18} missing · {total_patched} patched"
        )
        if not matched_games:
            ctk.CTkLabel(
                self.scrollable_games,
                text="Nothing matches this filter.",
                font=ctk.CTkFont(size=15),
                text_color=COLOR_TEXT_MUTED,
            ).pack(pady=40)
            self.lbl_status.configure(text="Filter active: 0 matches.", text_color="gray")
            return

        sort_mode = self._canonical_sort()
        if sort_mode == "Z-A":
            sorted_games = dict(sorted(matched_games.items(), key=lambda item: item[1]["name"].lower(), reverse=True))
        elif sort_mode == "Rating":
            sorted_games = dict(
                sorted(
                    matched_games.items(),
                    key=lambda item: (
                        (item[1].get("status_info") or {}).get("rating") is not None,
                        (item[1].get("status_info") or {}).get("rating") or 0.0,
                        item[1]["name"].lower(),
                    ),
                    reverse=True,
                )
            )
        elif self.sort_var.get() == "Status Priority":
            sorted_games = dict(
                sorted(
                    matched_games.items(),
                    key=lambda item: (
                        (item[1].get("status_info") or {}).get("status_priority", 3),
                        item[1]["name"].lower(),
                    ),
                )
            )
        elif self.sort_var.get() == "Installed First":
            sorted_games = dict(
                sorted(
                    matched_games.items(),
                    key=lambda item: (not item[1].get("is_installed", False), item[1]["name"].lower()),
                )
            )
        else:
            sorted_games = dict(sorted(matched_games.items(), key=lambda item: item[1]["name"].lower()))

        self._banner_widgets.clear()
        if "List" in view_mode:
            self._render_list_view(sorted_games)
        else:
            self._render_poster_view(sorted_games)
        self.lbl_status.configure(text=f"Showing {len(matched_games)} of {total_vns} Visual Novel(s).", text_color="gray")

    def _render_poster_view(self, games_dict):
        """Batch-renders a responsive poster grid."""
        try:
            curr_w = self.scrollable_games.winfo_width()
            if curr_w <= 100:
                curr_w = self.winfo_width()
        except Exception:
            curr_w = 1060
        self._last_rendered_width = curr_w
        col_count = max(POSTER_COLUMNS_MIN, curr_w // POSTER_COL_WIDTH)
        self._poster_col_count = col_count
        for column in range(col_count):
            self.scrollable_games.grid_columnconfigure(column, weight=1)

        items = list(games_dict.items())

        def render_batch(start_idx, batch_size=12):
            if start_idx >= len(items):
                self._apply_focus_visuals()
                return
            end_idx = min(start_idx + batch_size, len(items))
            for idx in range(start_idx, end_idx):
                app_id, game_data = items[idx]
                status_info = self._get_game_status_info(app_id, game_data)
                entry = create_poster_card(
                    self.scrollable_games,
                    app_id,
                    game_data,
                    status_info,
                    self.cover_manager,
                    on_select=self.open_game_detail,
                    row_idx=idx // col_count,
                    col_idx=idx % col_count,
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

    def _render_list_view(self, games_dict):
        """Batch-renders a single-column list."""
        self.scrollable_games.grid_columnconfigure(0, weight=1)
        self._poster_col_count = 1
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

    def _run_card_primary(self, app_id: str, game_data: dict):
        """X on a card: apply, re-apply, or open VNDB. Clean cards do nothing noisy."""
        status_info = self._get_game_status_info(app_id, game_data)
        word = status_info.get("status_word") or status_word(status_info)
        if word in ("Ready", "Patched"):
            self.run_patch(game_data, self.repo.available_patches.get(app_id))
        elif word == "Missing":
            vn_info = status_info.get("vn_info") or {}
            url = vn_info.get("vndb_url") or (f"https://vndb.org/{vn_info['vn_id']}" if vn_info.get("vn_id") else None)
            if url:
                webbrowser.open(url)
