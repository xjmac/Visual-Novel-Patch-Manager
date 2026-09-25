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
    ACTION_SCAN,
)
from ..steamos_helper import SteamOSHelper
from .constants import (
    FILTER_ORDER,
    SORT_ORDER,
    COLOR_BORDER_FOCUSED,
    COLOR_BORDER_2,
    COLOR_ELEVATION_2,
    COLOR_ELEVATION_3,
)

logger = logging.getLogger(__name__)

_HEADER_COUNT = 4
_CHIP_COUNT = 7


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
        """Forces window focus for the SteamOS Game Mode compositor."""
        try:
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def _is_entry_widget(self, widget) -> bool:
        """Determines if a widget (or its master) is a text entry."""
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
        """Binds keyboard stand-ins for the gamepad."""
        self.bind_all("<Up>", lambda e: self._on_key_event(ACTION_UP, e))
        self.bind_all("<Down>", lambda e: self._on_key_event(ACTION_DOWN, e))
        self.bind_all("<Left>", lambda e: self._on_key_event(ACTION_LEFT, e))
        self.bind_all("<Right>", lambda e: self._on_key_event(ACTION_RIGHT, e))
        self.bind_all("<KP_Up>", lambda e: self._on_key_event(ACTION_UP, e))
        self.bind_all("<KP_Down>", lambda e: self._on_key_event(ACTION_DOWN, e))
        self.bind_all("<KP_Left>", lambda e: self._on_key_event(ACTION_LEFT, e))
        self.bind_all("<KP_Right>", lambda e: self._on_key_event(ACTION_RIGHT, e))
        self.bind_all("<w>", lambda e: self._on_key_event(ACTION_UP, e))
        self.bind_all("<W>", lambda e: self._on_key_event(ACTION_UP, e))
        self.bind_all("<s>", lambda e: self._on_key_event(ACTION_DOWN, e))
        self.bind_all("<S>", lambda e: self._on_key_event(ACTION_DOWN, e))
        self.bind_all("<a>", lambda e: self._on_key_event(ACTION_LEFT, e))
        self.bind_all("<A>", lambda e: self._on_key_event(ACTION_LEFT, e))
        self.bind_all("<d>", lambda e: self._on_key_event(ACTION_RIGHT, e))
        self.bind_all("<D>", lambda e: self._on_key_event(ACTION_RIGHT, e))
        self.bind_all("<Return>", lambda e: self._on_key_event(ACTION_SELECT, e))
        self.bind_all("<KP_Enter>", lambda e: self._on_key_event(ACTION_SELECT, e))
        self.bind_all("<space>", lambda e: self._on_key_event(ACTION_SELECT, e))
        self.bind_all("<Escape>", lambda e: self._on_key_event(ACTION_BACK, e))
        self.bind_all("<BackSpace>", lambda e: self._on_key_event(ACTION_BACK, e))
        self.bind_all("<F1>", lambda e: self._on_key_event(ACTION_PREV_TAB, e))
        self.bind_all("<F2>", lambda e: self._on_key_event(ACTION_NEXT_TAB, e))
        self.bind_all("<bracketleft>", lambda e: self._on_key_event(ACTION_PREV_TAB, e))
        self.bind_all("<bracketright>", lambda e: self._on_key_event(ACTION_NEXT_TAB, e))
        self.bind_all("<Prior>", lambda e: self._on_key_event(ACTION_SCROLL_UP, e))
        self.bind_all("<Next>", lambda e: self._on_key_event(ACTION_SCROLL_DOWN, e))
        self.bind_all("<F5>", lambda e: self._on_key_event(ACTION_SCAN, e))
        self.bind_all("<x>", lambda e: self._on_key_event(ACTION_QUICK_ACTION, e))
        self.bind_all("<X>", lambda e: self._on_key_event(ACTION_QUICK_ACTION, e))
        self.bind_all("<y>", lambda e: self._on_key_event(ACTION_SEARCH, e))
        self.bind_all("<Y>", lambda e: self._on_key_event(ACTION_SEARCH, e))

    def _on_key_event(self, action: str, event=None):
        """Lets an entry keep typed characters, and leaves it on Escape, Enter, or vertical arrows."""
        focused_widget = self.focus_get()
        if self._is_entry_widget(focused_widget):
            keysym = getattr(event, "keysym", "")
            if len(keysym) == 1 or keysym in ("space", "BackSpace"):
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
        """Search focus opens the on-screen keyboard."""
        self._focused_zone = "HEADER"
        self._focused_header_idx = 0
        SteamOSHelper.show_onscreen_keyboard()
        self._apply_focus_visuals()

    def _on_search_submit(self):
        """Leaves search and returns to the posters."""
        SteamOSHelper.hide_onscreen_keyboard()
        self.focus_set()
        self._focused_zone = "LIBRARY"
        self._focus_band = "cards"
        self._focused_card_idx = 0
        self._apply_focus_visuals()

    def _library_columns(self) -> int:
        if "List" in self.view_var.get():
            return 1
        return max(1, getattr(self, "_poster_col_count", 1) or 1)

    def _cycle_filter(self, step: int):
        current = self._canonical_filter()
        index = FILTER_ORDER.index(current)
        nxt = FILTER_ORDER[(index + step) % len(FILTER_ORDER)]
        self._focused_zone = "CHIPS"
        self._focused_chip_idx = FILTER_ORDER.index(nxt)
        self._select_filter(nxt)

    def _cycle_sort(self):
        current = self._canonical_sort()
        index = SORT_ORDER.index(current)
        self.sort_var.set(SORT_ORDER[(index + 1) % len(SORT_ORDER)])
        self._apply_filters_and_render()

    def _activate_header(self):
        index = self._focused_header_idx
        if index <= 0:
            self.entry_search.focus_set()
        elif index == 1:
            self.refresh_data()
        elif index == 2:
            self.open_add_non_steam_modal()
        else:
            self._open_settings()

    def _activate_chip(self):
        index = self._focused_chip_idx
        if index < len(FILTER_ORDER):
            self._select_filter(FILTER_ORDER[index])
        elif index == len(FILTER_ORDER):
            self._cycle_sort()
        else:
            self._select_view("List" if "List" not in self.view_var.get() else "Posters")

    def _activate_settings(self):
        targets = self._settings_targets()
        if not targets:
            return
        index = min(self._settings_index, len(targets) - 1)
        widget = targets[index]
        if widget is self._chip_local:
            self._set_connection("local")
        elif widget is self._chip_network:
            self._set_connection("smb")
        elif widget is self.btn_save:
            self.save_settings()
        elif widget is self._btn_browse:
            self._browse_local_path()
        elif widget is self._btn_get_key:
            command = getattr(widget, "_command", None)
            if command:
                command()
        elif widget in (self.switch_sgdb_nsfw, self.switch_sgdb_animated):
            if widget.get():
                widget.deselect()
            else:
                widget.select()
        else:
            widget.focus_set()

    def _handle_controller_action(self, action: str):
        """Processes gamepad and keyboard navigation."""
        if getattr(self, "_modal_controller_stack", None):
            try:
                self._modal_controller_stack[-1](action)
                return
            except Exception as ex:
                logger.warning(f"Error in modal controller handler: {ex}")

        page = getattr(self, "_game_page", None)
        if page is not None and page.confirming:
            page._handle_controller_input(action)
            return

        if action == ACTION_SCAN:
            self.refresh_data()
            return
        if action == ACTION_PREV_TAB:
            self._cycle_filter(-1)
            return
        if action == ACTION_NEXT_TAB:
            self._cycle_filter(1)
            return
        if action == ACTION_SEARCH:
            self._on_search_focused()
            return
        if action == ACTION_SCROLL_UP:
            self._scroll_library(-3)
            return
        if action == ACTION_SCROLL_DOWN:
            self._scroll_library(3)
            return

        zone = self._focused_zone
        if zone in ("DETAIL", "CONFIRM") and page is not None:
            page._handle_controller_input(action)
            return
        if zone == "SETTINGS" or self._settings_open and zone != "LIBRARY":
            self._handle_settings_action(action)
            return
        if zone == "HEADER":
            self._handle_header_action(action)
            return
        if zone == "CHIPS":
            self._handle_chip_action(action)
            return
        self._handle_library_action(action)

    def _scroll_library(self, steps: int):
        canvas = getattr(self.scrollable_games, "_parent_canvas", None)
        if canvas:
            canvas.yview_scroll(steps, "units")

    def _handle_header_action(self, action: str):
        if action == ACTION_LEFT:
            self._focused_header_idx = max(0, self._focused_header_idx - 1)
        elif action == ACTION_RIGHT:
            self._focused_header_idx = min(_HEADER_COUNT - 1, self._focused_header_idx + 1)
        elif action == ACTION_DOWN:
            self._focused_zone = "CHIPS"
        elif action == ACTION_UP:
            return
        elif action == ACTION_SELECT:
            self._activate_header()
            return
        elif action == ACTION_BACK:
            if self.search_var.get():
                self.search_var.set("")
            else:
                self._focused_zone = "LIBRARY"
        self._apply_focus_visuals()

    def _handle_chip_action(self, action: str):
        if action == ACTION_LEFT:
            self._focused_chip_idx = max(0, self._focused_chip_idx - 1)
        elif action == ACTION_RIGHT:
            self._focused_chip_idx = min(_CHIP_COUNT - 1, self._focused_chip_idx + 1)
        elif action == ACTION_UP:
            self._focused_zone = "HEADER"
            self._focused_header_idx = 1
        elif action == ACTION_DOWN:
            self._focused_zone = "LIBRARY"
            self._focused_card_idx = 0
        elif action == ACTION_SELECT:
            self._activate_chip()
            return
        elif action == ACTION_BACK:
            if self.search_var.get():
                self.search_var.set("")
            self._focused_zone = "LIBRARY"
        self._apply_focus_visuals()

    def _handle_library_action(self, action: str):
        cards = self._card_entries
        count = len(cards)
        if count == 0:
            if action == ACTION_UP:
                self._focused_zone = "CHIPS"
                self._apply_focus_visuals()
            return
        cols = self._library_columns()
        index = min(self._focused_card_idx, count - 1)
        self._focused_card_idx = index
        if action == ACTION_LEFT and index > 0:
            self._focused_card_idx = index - 1
        elif action == ACTION_RIGHT and index < count - 1:
            self._focused_card_idx = index + 1
        elif action == ACTION_DOWN:
            self._focused_card_idx = min(count - 1, index + cols)
        elif action == ACTION_UP:
            if index < cols:
                self._focused_zone = "CHIPS"
            else:
                self._focused_card_idx = index - cols
        elif action == ACTION_SELECT:
            opener = cards[self._focused_card_idx].get("open_detail")
            if opener:
                opener()
            return
        elif action == ACTION_QUICK_ACTION:
            entry = cards[self._focused_card_idx]
            self._run_card_primary(entry["app_id"], entry["game_data"])
            return
        elif action == ACTION_BACK and self.search_var.get():
            self.search_var.set("")
        self._apply_focus_visuals()

    def _handle_settings_action(self, action: str):
        targets = self._settings_targets()
        if not targets:
            if action == ACTION_BACK:
                self._close_settings()
            return
        index = min(self._settings_index, len(targets) - 1)
        self._settings_index = index
        if action == ACTION_UP:
            self._settings_index = max(0, index - 1)
        elif action == ACTION_DOWN:
            self._settings_index = min(len(targets) - 1, index + 1)
        elif action == ACTION_LEFT and index <= 1:
            self._set_connection("local")
            self._settings_index = 0
        elif action == ACTION_RIGHT and index <= 1:
            self._set_connection("smb")
            self._settings_index = 1
        elif action == ACTION_SELECT:
            self._activate_settings()
            return
        elif action == ACTION_BACK:
            self._close_settings()
            return
        self._apply_focus_visuals()

    def _apply_focus_visuals(self, force_all: bool = False):
        """Paints the focus ring for the active zone."""
        if hasattr(self, "update_controller_prompts"):
            self.update_controller_prompts(self._focused_zone)
        self._paint_header_focus()
        self._paint_chip_focus()
        self._paint_card_focus(force_all)
        self._paint_settings_focus()

    def _paint_header_focus(self):
        focused = self._focused_zone == "HEADER"
        pairs = (
            (getattr(self, "_search_frame", None), 0),
            (getattr(self, "btn_refresh", None), 1),
            (getattr(self, "btn_add_non_steam", None), 2),
            (getattr(self, "btn_settings", None), 3),
        )
        for widget, index in pairs:
            if widget is None or not widget.winfo_exists():
                continue
            on = focused and self._focused_header_idx == index
            widget.configure(
                border_width=2 if on else 1,
                border_color=COLOR_BORDER_FOCUSED if on else COLOR_BORDER_2,
            )

    def _paint_chip_focus(self):
        if hasattr(self, "_paint_filter_chips"):
            self._paint_filter_chips()
        focused = self._focused_zone == "CHIPS"
        chip_idx = self._focused_chip_idx
        sort_on = focused and chip_idx == len(FILTER_ORDER)
        view_on = focused and chip_idx == len(FILTER_ORDER) + 1
        for widget, on in ((getattr(self, "_sort_frame", None), sort_on), (getattr(self, "_view_frame", None), view_on)):
            if widget is None or not widget.winfo_exists():
                continue
            widget.configure(
                border_width=2 if on else 1,
                border_color=COLOR_BORDER_FOCUSED if on else COLOR_BORDER_2,
            )

    def _paint_card_focus(self, force_all: bool):
        cards_live = self._focused_zone == "LIBRARY"
        current = self._focused_card_idx if cards_live else None
        previous = getattr(self, "_prev_focused_card_idx", None)
        if force_all or previous is None or not cards_live:
            for idx in range(len(self._card_entries)):
                self._apply_card_visual(idx, is_focused=(idx == current))
        else:
            if previous != current and previous is not None:
                self._apply_card_visual(previous, is_focused=False)
            if current is not None:
                self._apply_card_visual(current, is_focused=True)
        self._prev_focused_card_idx = current

    def _apply_card_visual(self, idx: int, is_focused: bool):
        if not (0 <= idx < len(self._card_entries)):
            return
        card = self._card_entries[idx].get("card")
        if not card or not card.winfo_exists():
            return
        if is_focused:
            card.configure(border_color=COLOR_BORDER_FOCUSED, border_width=2, fg_color=COLOR_ELEVATION_3)
            self._scroll_card_into_view(card)
        else:
            card.configure(border_color=COLOR_BORDER_2, border_width=1, fg_color=COLOR_ELEVATION_2)

    def _paint_settings_focus(self):
        if not hasattr(self, "btn_save"):
            return
        targets = self._settings_targets() if self._settings_open else []
        index = self._settings_index
        for pos, widget in enumerate(targets):
            if not widget.winfo_exists():
                continue
            on = self._focused_zone == "SETTINGS" and pos == index
            try:
                widget.configure(
                    border_width=2 if on else 1,
                    border_color=COLOR_BORDER_FOCUSED if on else COLOR_BORDER_2,
                )
            except Exception:
                pass

    def _scroll_card_into_view(self, card_widget):
        """Scrolls the library so the focused card stays visible."""
        try:
            canvas = getattr(self.scrollable_games, "_parent_canvas", None)
            if not canvas or not canvas.winfo_exists() or not card_widget.winfo_exists():
                return
            canvas.update_idletasks()
            bbox = canvas.bbox("all")
            if not bbox:
                return
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
            if card_y < viewport_top + padding:
                canvas.yview_moveto(max(0.0, card_y - padding) / total_h)
            elif (card_y + card_h) > viewport_bottom - padding:
                target = min(total_h - canvas_h, (card_y + card_h + padding) - canvas_h)
                canvas.yview_moveto(target / total_h)
        except Exception:
            pass
