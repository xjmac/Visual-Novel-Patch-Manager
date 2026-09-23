"""
Controller spatial navigation, keyboard binding, and focus management for VNPM.
"""

import logging
import customtkinter as ctk

from ..controller_manager import (
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
from ..steamos_helper import SteamOSHelper
from .constants import (
    MODE_LOCAL_DISPLAY,
    MODE_SMB_DISPLAY,
    COLOR_BORDER_FOCUSED,
    COLOR_SURFACE_BORDER,
    COLOR_PRIMARY_BLUE,
    COLOR_ACCENT_GREEN,
)

logger = logging.getLogger(__name__)


class NavigationMixin:
    """Provides gamepad and keyboard navigation, focus visuals, and modal stacks."""

    def push_modal_controller_handler(self, handler):
        """Pushes a modal controller callback onto the stack to intercept gamepad input."""
        self._modal_controller_stack.append(handler)

    def pop_modal_controller_handler(self, handler=None):
        """Pops a modal controller callback from the stack."""
        if handler and handler in self._modal_controller_stack:
            self._modal_controller_stack.remove(handler)
        elif self._modal_controller_stack:
            self._modal_controller_stack.pop()

    def _ensure_game_mode_focus(self):
        """Forces window focus and active window state for SteamOS Game Mode Gamescope compositor."""
        try:
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def _is_entry_widget(self, widget) -> bool:
        """Determines if a widget (or its master) is a text entry or text editing widget."""
        if widget is None:
            return False
        if isinstance(widget, (ctk.CTkEntry, ctk.CTkTextbox)):
            return True
        widget_class = widget.__class__.__name__
        if widget_class in ("Entry", "CTkEntry", "Text", "CTkTextbox"):
            return True
        parent = getattr(widget, "master", None)
        if parent is not None:
            if isinstance(parent, (ctk.CTkEntry, ctk.CTkTextbox)):
                return True
            if parent.__class__.__name__ in ("Entry", "CTkEntry", "Text", "CTkTextbox"):
                return True
        return False

    def _bind_controller_and_keyboard_events(self):
        """Binds universal keyboard and Steam Input shortcut keys."""
        # Standard Arrows & Keypad Arrows
        self.bind_all("<Up>", lambda e: self._on_key_event(ACTION_UP, e))
        self.bind_all("<Down>", lambda e: self._on_key_event(ACTION_DOWN, e))
        self.bind_all("<Left>", lambda e: self._on_key_event(ACTION_LEFT, e))
        self.bind_all("<Right>", lambda e: self._on_key_event(ACTION_RIGHT, e))
        self.bind_all("<KP_Up>", lambda e: self._on_key_event(ACTION_UP, e))
        self.bind_all("<KP_Down>", lambda e: self._on_key_event(ACTION_DOWN, e))
        self.bind_all("<KP_Left>", lambda e: self._on_key_event(ACTION_LEFT, e))
        self.bind_all("<KP_Right>", lambda e: self._on_key_event(ACTION_RIGHT, e))

        # WASD Navigation (Keyboard / Desktop Template)
        self.bind_all("<w>", lambda e: self._on_key_event(ACTION_UP, e))
        self.bind_all("<W>", lambda e: self._on_key_event(ACTION_UP, e))
        self.bind_all("<s>", lambda e: self._on_key_event(ACTION_DOWN, e))
        self.bind_all("<S>", lambda e: self._on_key_event(ACTION_DOWN, e))
        self.bind_all("<a>", lambda e: self._on_key_event(ACTION_LEFT, e))
        self.bind_all("<A>", lambda e: self._on_key_event(ACTION_LEFT, e))
        self.bind_all("<d>", lambda e: self._on_key_event(ACTION_RIGHT, e))
        self.bind_all("<D>", lambda e: self._on_key_event(ACTION_RIGHT, e))

        # Selection / A button
        self.bind_all("<Return>", lambda e: self._on_key_event(ACTION_SELECT, e))
        self.bind_all("<KP_Enter>", lambda e: self._on_key_event(ACTION_SELECT, e))
        self.bind_all("<space>", lambda e: self._on_key_event(ACTION_SELECT, e))

        # Back / B button
        self.bind_all("<Escape>", lambda e: self._on_key_event(ACTION_BACK, e))
        self.bind_all("<BackSpace>", lambda e: self._on_key_event(ACTION_BACK, e))

        # Tab navigation / Bumpers L1, R1
        self.bind_all("<F1>", lambda e: self._on_key_event(ACTION_PREV_TAB, e))
        self.bind_all("<F2>", lambda e: self._on_key_event(ACTION_NEXT_TAB, e))
        self.bind_all("<bracketleft>", lambda e: self._on_key_event(ACTION_PREV_TAB, e))
        self.bind_all("<bracketright>", lambda e: self._on_key_event(ACTION_NEXT_TAB, e))

        # Page scrolling / Triggers / Right Stick
        self.bind_all("<Prior>", lambda e: self._on_key_event(ACTION_SCROLL_UP, e))
        self.bind_all("<Next>", lambda e: self._on_key_event(ACTION_SCROLL_DOWN, e))

    def _on_key_event(self, action: str, event=None):
        """Filters keyboard events if user is currently typing in an Entry widget."""
        focused_widget = self.focus_get()
        if self._is_entry_widget(focused_widget):
            keysym = getattr(event, "keysym", "")
            # Let standard typing (letters, spaces, backspaces) pass through unmodified
            if keysym in ("space", "BackSpace", "w", "W", "a", "A", "s", "S", "d", "D"):
                return None
            if keysym == "Escape":
                self.focus_set()
                self._handle_controller_action(ACTION_BACK)
                return "break"
            if keysym in ("Return", "KP_Enter"):
                if hasattr(self, "entry_search") and (
                    focused_widget == self.entry_search
                    or getattr(focused_widget, "master", None) == self.entry_search
                ):
                    self._on_search_submit()
                    return "break"
                self._handle_controller_action(ACTION_SELECT)
                return "break"
            if action in (ACTION_UP, ACTION_DOWN):
                self.focus_set()
                self._handle_controller_action(action)
                return "break"
            return None

        self._handle_controller_action(action)
        return "break"

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
        if getattr(self, "_modal_controller_stack", None):
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
            view_options = ["Posters", "Grid", "List"]

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
                    if hasattr(self, "opt_view") and self.opt_view:
                        self.opt_view.set(view_options[next_idx])
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
            elif action in (ACTION_SELECT, ACTION_QUICK_ACTION):
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

            if "Posters" in self.view_var.get():
                col_count = getattr(self, "_poster_col_count", 3)
            elif "Grid" in self.view_var.get():
                col_count = 2
            else:
                col_count = 1

            current_entry = self._card_entries[self._focused_card_idx] if 0 <= self._focused_card_idx < num_cards else None
            num_buttons = len(current_entry["buttons"]) if current_entry else 0

            # Case A: In Action Mode (A button was pressed to enter buttons)
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
                    self._focused_btn_idx = -1
                    self._apply_focus_visuals()
                return

            # Case B: In Card Browsing Mode (_focused_btn_idx == -1)
            if action == ACTION_UP:
                if self._focused_card_idx < col_count:
                    self._focused_zone = "TOOLBAR"
                    self._focused_toolbar_idx = 0
                    self._apply_focus_visuals()
                else:
                    self._focused_card_idx = max(0, self._focused_card_idx - col_count)
                    self._apply_focus_visuals()

            elif action == ACTION_DOWN:
                self._focused_card_idx = min(num_cards - 1, self._focused_card_idx + col_count)
                self._apply_focus_visuals()

            elif action == ACTION_LEFT:
                if self._focused_card_idx > 0:
                    self._focused_card_idx -= 1
                    self._apply_focus_visuals()

            elif action == ACTION_RIGHT:
                if self._focused_card_idx < num_cards - 1:
                    self._focused_card_idx += 1
                    self._apply_focus_visuals()

            elif action == ACTION_SELECT:
                # Direct selection: open Game Detail View or enter action buttons
                if current_entry and current_entry.get("open_detail"):
                    current_entry["open_detail"]()
                elif current_entry and num_buttons > 0:
                    self._focused_btn_idx = 0
                    self._apply_focus_visuals()

            elif action == ACTION_QUICK_ACTION:  # X Button directly invokes quick action
                if current_entry and current_entry.get("default_button"):
                    current_entry["default_button"].invoke()
                elif current_entry and current_entry.get("app_id"):
                    aid = current_entry["app_id"]
                    gdata = current_entry["game_data"]
                    pdata = getattr(self, "repo", None).available_patches.get(aid) if hasattr(self, "repo") else None
                    if pdata:
                        self.run_patch(gdata, pdata)
                    elif current_entry.get("open_detail"):
                        current_entry["open_detail"]()

            elif action == ACTION_BACK:
                if self.search_var.get():
                    self.search_var.set("")
                    self._apply_focus_visuals()

    def _apply_focus_visuals(self, force_all: bool = False):
        """Updates high-contrast OLED visual focus borders across all UI components."""
        if hasattr(self, "update_controller_prompts"):
            self.update_controller_prompts(self._focused_zone)

        # 1. Update Tabview and Toolbar Focus Highlights
        is_tabs_focused = (self._focused_zone == "TABS")
        if hasattr(self, 'tabview') and self.tabview.winfo_exists():
            self.tabview.configure(
                border_color=COLOR_BORDER_FOCUSED if is_tabs_focused else COLOR_SURFACE_BORDER,
                border_width=2 if is_tabs_focused else 1
            )

        if hasattr(self, 'btn_save') and self.btn_save.winfo_exists():
            is_settings_focused = (self._focused_zone == "SETTINGS")
            self.btn_save.configure(
                border_color="#60a5fa" if is_settings_focused else "#1d4ed8",
                border_width=2 if is_settings_focused else 0
            )

        if hasattr(self, '_search_frame') and self._search_frame and self._search_frame.winfo_exists():
            is_search_focused = (self._focused_zone == "TOOLBAR" and self._focused_toolbar_idx == 0)
            self._search_frame.configure(
                border_color=COLOR_BORDER_FOCUSED if is_search_focused else "#3f3f46",
                border_width=2 if is_search_focused else 1
            )

        if hasattr(self, '_filter_frame') and self._filter_frame and self._filter_frame.winfo_exists():
            is_filter_focused = (self._focused_zone == "TOOLBAR" and self._focused_toolbar_idx == 1)
            self._filter_frame.configure(
                border_color=COLOR_BORDER_FOCUSED if is_filter_focused else "#3f3f46",
                border_width=2 if is_filter_focused else 1
            )

        if hasattr(self, '_sort_frame') and self._sort_frame and self._sort_frame.winfo_exists():
            is_sort_focused = (self._focused_zone == "TOOLBAR" and self._focused_toolbar_idx == 2)
            self._sort_frame.configure(
                border_color=COLOR_BORDER_FOCUSED if is_sort_focused else "#3f3f46",
                border_width=2 if is_sort_focused else 1
            )

        if hasattr(self, '_view_frame') and self._view_frame and self._view_frame.winfo_exists():
            is_view_focused = (self._focused_zone == "TOOLBAR" and self._focused_toolbar_idx == 3)
            self._view_frame.configure(
                border_color=COLOR_BORDER_FOCUSED if is_view_focused else "#3f3f46",
                border_width=2 if is_view_focused else 1
            )

        if hasattr(self, 'btn_add_non_steam') and self.btn_add_non_steam.winfo_exists():
            is_add_focused = (self._focused_zone == "HEADER" and self._focused_header_idx == 0)
            self.btn_add_non_steam.configure(
                border_color="#6ee7b7" if is_add_focused else "#059669",
                border_width=2 if is_add_focused else 0,
                fg_color="#059669" if is_add_focused else COLOR_ACCENT_GREEN
            )

        if hasattr(self, 'btn_refresh') and self.btn_refresh.winfo_exists():
            is_refresh_focused = (self._focused_zone == "HEADER" and self._focused_header_idx == 1)
            self.btn_refresh.configure(
                border_color="#60a5fa" if is_refresh_focused else "#1d4ed8",
                border_width=2 if is_refresh_focused else 0,
                fg_color="#1d4ed8" if is_refresh_focused else COLOR_PRIMARY_BLUE
            )

        # 2. Update Card Focus Highlights (Differential O(1) Updates)
        is_library = (self._focused_zone == "LIBRARY")
        cur_card_idx = self._focused_card_idx if is_library else None
        prev_card_idx = getattr(self, "_prev_focused_card_idx", None)

        if force_all or prev_card_idx is None:
            for idx in range(len(self._card_entries)):
                self._apply_card_visual(idx, is_focused=(idx == cur_card_idx))
        else:
            if prev_card_idx != cur_card_idx or getattr(self, "_prev_focused_btn_idx", None) != self._focused_btn_idx:
                if prev_card_idx is not None:
                    self._apply_card_visual(prev_card_idx, is_focused=False)
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
                border_color=COLOR_BORDER_FOCUSED,
                border_width=3,
                fg_color="#1e293b"
            )
            self._scroll_card_into_view(card)
        else:
            card.configure(
                border_color=COLOR_SURFACE_BORDER,
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

            bbox = canvas.bbox("all")
            if not bbox:
                return

            # Ensure canvas scrollregion is configured if missing or outdated
            if not canvas.cget("scrollregion"):
                canvas.configure(scrollregion=bbox)

            canvas_h = canvas.winfo_height() or 500
            total_h = max(bbox[3] - bbox[1], canvas_h, 1)

            if total_h <= canvas_h:
                return

            card_y = card_widget.winfo_y()
            card_h = card_widget.winfo_height() or 270

            viewport_top = canvas.canvasy(0)
            viewport_bottom = canvas.canvasy(canvas_h)

            padding = 20

            # If card is above viewport margin
            if card_y < viewport_top + padding:
                target_top_y = max(0.0, card_y - padding)
                canvas.yview_moveto(target_top_y / total_h)
            # If card is below viewport margin
            elif (card_y + card_h) > viewport_bottom - padding:
                target_top_y = min(total_h - canvas_h, (card_y + card_h + padding) - canvas_h)
                canvas.yview_moveto(target_top_y / total_h)
        except Exception:
            pass
