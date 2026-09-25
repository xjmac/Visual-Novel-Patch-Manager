"""
In-window game page. Wide windows keep the library beside it.
Game Mode and narrow windows replace the library and pin the primary action.
"""

import logging
import webbrowser
from typing import Any, Dict, List, Optional
import customtkinter as ctk

from ...controller_manager import (
    ACTION_BACK,
    ACTION_DOWN,
    ACTION_LEFT,
    ACTION_RIGHT,
    ACTION_SELECT,
    ACTION_UP,
)
from ..status import show_backup_mark, status_color, status_word
from ..theme import (
    COLOR_BORDER_1,
    COLOR_BORDER_2,
    COLOR_BORDER_FOCUSED,
    COLOR_DANGER_HOVER,
    COLOR_DANGER_RED,
    COLOR_ELEVATION_1,
    COLOR_ELEVATION_2,
    COLOR_ELEVATION_3,
    COLOR_PRIMARY_BLUE,
    COLOR_PRIMARY_HOVER,
    COLOR_STATUS_BACKUP,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    HERO_BANNER_SIZE,
    MIN_TOUCH_TARGET,
)

logger = logging.getLogger(__name__)


def _vndb_url(status_info: dict) -> Optional[str]:
    vn_info = status_info.get("vn_info") or {}
    url = vn_info.get("vndb_url")
    if url:
        return url
    vn_id = vn_info.get("vn_id")
    if vn_id:
        return f"https://vndb.org/{vn_id}"
    return None


class GamePage(ctk.CTkFrame):
    """Game page embedded in the library window."""

    def __init__(
        self,
        parent: Any,
        app_id: str,
        game_data: Dict[str, Any],
        status_info: Dict[str, Any],
        on_back: Optional[Any] = None,
        pinned: bool = False,
        host: Optional[Any] = None,
    ):
        super().__init__(parent, fg_color=COLOR_ELEVATION_1, corner_radius=0)
        self.parent = host if host is not None else parent
        self.app_id = str(app_id)
        self.game_data = game_data
        self.status_info = status_info
        self.on_back = on_back
        self.pinned = pinned
        self._action_buttons: List[Any] = []
        self._focused_btn_idx = 0
        self.confirming = False
        self._confirm_yes = None
        self._confirm_buttons: List[Any] = []
        self._confirm_idx = 0
        self._details_open = False
        self._details_body = None
        self._build()

    def _build(self):
        for child in self.winfo_children():
            child.destroy()
        self._action_buttons = []
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        bar = ctk.CTkFrame(self, fg_color=COLOR_ELEVATION_1, height=56, corner_radius=0)
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(
            bar,
            text="Back",
            width=72,
            height=MIN_TOUCH_TARGET,
            fg_color="transparent",
            hover_color=COLOR_ELEVATION_2,
            text_color=COLOR_TEXT_PRIMARY,
            command=self._go_back,
        ).grid(row=0, column=0, padx=8, pady=6)
        ctk.CTkLabel(
            bar,
            text=self.game_data.get("name", "Visual novel"),
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        ).grid(row=0, column=1, sticky="ew", padx=4)

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.grid(row=1, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)
        self._scroll = scroll

        self._build_hero(scroll)
        self._build_status(scroll)
        self._build_synopsis(scroll)
        self._build_actions(scroll)

        word = status_word(self.status_info)
        primary = self._primary_spec(word)
        if self.pinned and primary:
            foot = ctk.CTkFrame(self, fg_color=COLOR_ELEVATION_1, corner_radius=0)
            foot.grid(row=2, column=0, sticky="ew")
            button = self._make_primary(foot, primary)
            button.pack(fill="x", padx=16, pady=12)
            self._action_buttons.insert(0, self._action_buttons.pop())
        self._paint_button_focus()

    def _build_hero(self, parent):
        cover_mgr = getattr(self.parent, "cover_manager", None)
        image = None
        title = self.game_data.get("name", "")
        if cover_mgr is not None and hasattr(cover_mgr, "get_hero_image"):
            candidate = cover_mgr.get_hero_image(
                self.app_id,
                title=title,
                size=HERO_BANNER_SIZE,
                game_data=self.game_data,
            )
            if isinstance(candidate, ctk.CTkImage):
                image = candidate
        if image is None and cover_mgr is not None and hasattr(cover_mgr, "get_cover_image"):
            candidate = cover_mgr.get_cover_image(self.app_id, title=title, size=HERO_BANNER_SIZE)
            if isinstance(candidate, ctk.CTkImage):
                image = candidate
        if image is not None:
            label = ctk.CTkLabel(parent, text="", image=image)
            label._keep_image = image
            label.grid(row=0, column=0, sticky="ew", pady=(0, 8))

    def _build_status(self, parent):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", padx=16, pady=(8, 0))
        word = status_word(self.status_info)
        ctk.CTkLabel(
            row,
            text=word,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=status_color(self.status_info),
        ).pack(side="left")
        if show_backup_mark(self.status_info):
            ctk.CTkLabel(
                row,
                text="Backup",
                font=ctk.CTkFont(size=12),
                text_color=COLOR_STATUS_BACKUP,
            ).pack(side="left", padx=(8, 0))
        rating = (self.status_info.get("vn_info") or {}).get("rating") or self.status_info.get("rating")
        if rating:
            ctk.CTkLabel(
                row,
                text=f"{float(rating):.1f}",
                font=ctk.CTkFont(size=13),
                text_color=COLOR_TEXT_MUTED,
            ).pack(side="right")

    def _build_synopsis(self, parent):
        text = ((self.status_info.get("vn_info") or {}).get("description") or "").strip()
        if not text:
            return
        ctk.CTkLabel(
            parent,
            text=text,
            font=ctk.CTkFont(size=13),
            text_color=COLOR_TEXT_SECONDARY,
            wraplength=380,
            justify="left",
            anchor="w",
        ).grid(row=2, column=0, sticky="ew", padx=16, pady=(8, 8))

    def _primary_spec(self, word: str):
        if word == "Ready":
            return ("Apply patch", self._apply)
        if word == "Patched":
            return ("Re-apply", self._apply)
        if word == "Missing":
            return ("Get the patch", self._open_vndb)
        return None

    def _make_primary(self, parent, spec):
        text, command = spec
        button = ctk.CTkButton(
            parent,
            text=text,
            height=48,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color=COLOR_PRIMARY_BLUE,
            hover_color=COLOR_PRIMARY_HOVER,
            command=command,
        )
        self._action_buttons.append(button)
        return button

    def _row_button(self, parent, text, command):
        button = ctk.CTkButton(
            parent,
            text=text,
            height=MIN_TOUCH_TARGET,
            anchor="w",
            font=ctk.CTkFont(size=15),
            fg_color=COLOR_ELEVATION_2,
            hover_color=COLOR_ELEVATION_3,
            border_width=1,
            border_color=COLOR_BORDER_2,
            text_color=COLOR_TEXT_PRIMARY,
            command=command,
        )
        button.pack(fill="x", pady=4)
        self._action_buttons.append(button)
        return button

    def _build_actions(self, parent):
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=3, column=0, sticky="ew", padx=16, pady=(4, 12))
        word = status_word(self.status_info)
        primary = self._primary_spec(word)
        if primary and not self.pinned:
            self._make_primary(box, primary).pack(fill="x", pady=(0, 8))
        if self.status_info.get("has_clean_backup"):
            self._row_button(box, "Restore backup", self._ask_restore)
        self._row_button(box, "Fix video", self._fix_video)
        self._row_button(box, "Artwork", self._artwork)
        self._row_button(box, "Open on VNDB", self._open_vndb)
        installed = self.status_info.get("is_installed", True)
        if installed and not self.game_data.get("is_non_steam"):
            self._row_button(box, "Restore via Steam", self._steam_restore)
        if self.game_data.get("is_non_steam"):
            self._row_button(box, "Remove from Steam", self._ask_remove)
        self._row_button(box, "Details", self._toggle_details)
        self._details_body = ctk.CTkFrame(box, fg_color="transparent")

    def _toggle_details(self):
        self._details_open = not self._details_open
        if not self._details_body:
            return
        if not self._details_open:
            self._details_body.pack_forget()
            for child in self._details_body.winfo_children():
                child.destroy()
            return
        vn_info = self.status_info.get("vn_info") or {}
        app_line = "Non-Steam" if self.game_data.get("is_non_steam") else self.app_id
        path = self.game_data.get("path") or "Not installed"
        rows = [
            ("Developer", vn_info.get("developer") or "Unknown"),
            ("Release", vn_info.get("released") or "Unknown"),
            ("Length", vn_info.get("length_str") or "Standard VN"),
            ("App ID", app_line),
            ("Install path", str(path)),
        ]
        for label, value in rows:
            line = ctk.CTkFrame(self._details_body, fg_color="transparent")
            line.pack(fill="x", pady=2)
            ctk.CTkLabel(line, text=label, width=110, anchor="w", text_color=COLOR_TEXT_MUTED, font=ctk.CTkFont(size=12)).pack(side="left")
            ctk.CTkLabel(line, text=value, anchor="w", text_color=COLOR_TEXT_PRIMARY, font=ctk.CTkFont(size=13), wraplength=260, justify="left").pack(side="left", fill="x", expand=True)
        self._details_body.pack(fill="x", pady=(4, 0))

    def _patch_data(self):
        repo = getattr(self.parent, "repo", None)
        if repo is None:
            return None
        return repo.available_patches.get(self.app_id)

    def _apply(self):
        runner = getattr(self.parent, "run_patch", None)
        if runner:
            runner(self.game_data, self._patch_data())

    def _fix_video(self):
        runner = getattr(self.parent, "run_fix_video", None)
        if runner:
            runner(self.app_id, self.game_data)

    def _artwork(self):
        runner = getattr(self.parent, "run_custom_artwork", None)
        if runner:
            runner(self.app_id, self.game_data)

    def _steam_restore(self):
        runner = getattr(self.parent, "run_steam_restore", None)
        if runner:
            runner(self.game_data, patch_data=self._patch_data(), app_id=self.app_id)

    def _open_vndb(self):
        url = _vndb_url(self.status_info)
        if url:
            webbrowser.open(url)
            return
        logger.info("No VNDB page for %s", self.app_id)

    def _ask_restore(self):
        name = self.game_data.get("name", "this game")
        self._open_confirm(
            "Restore backup",
            f"This puts the clean backup back in place of the patched files for {name}.",
            self._do_restore,
        )

    def _do_restore(self):
        runner = getattr(self.parent, "run_rollback", None)
        if runner:
            runner(self.game_data)

    def _ask_remove(self):
        name = self.game_data.get("name", "this game")
        self._open_confirm(
            "Remove from library",
            f"This removes the non-Steam shortcut for {name}. The installed files stay on disk.",
            self._do_remove,
        )

    def _do_remove(self):
        runner = getattr(self.parent, "run_remove_non_steam", None)
        if runner:
            runner(self.app_id, self.game_data)

    def _open_confirm(self, title: str, body: str, on_yes):
        self.confirming = True
        self._confirm_yes = on_yes
        self._confirm_idx = 0
        overlay = ctk.CTkFrame(self, fg_color=COLOR_ELEVATION_1, border_color=COLOR_BORDER_1, border_width=1, corner_radius=12)
        overlay.place(relx=0.5, rely=0.5, anchor="center")
        self._confirm_overlay = overlay
        ctk.CTkLabel(overlay, text=title, font=ctk.CTkFont(size=20, weight="bold"), text_color=COLOR_TEXT_PRIMARY).pack(padx=20, pady=(16, 4))
        ctk.CTkLabel(overlay, text=body, wraplength=320, justify="left", text_color=COLOR_TEXT_SECONDARY, font=ctk.CTkFont(size=13)).pack(padx=20, pady=(0, 12))
        actions = ctk.CTkFrame(overlay, fg_color="transparent")
        actions.pack(padx=16, pady=(0, 16))
        cancel = ctk.CTkButton(actions, text="Cancel", height=MIN_TOUCH_TARGET, fg_color=COLOR_ELEVATION_2, hover_color=COLOR_ELEVATION_3, command=self._close_confirm)
        cancel.pack(side="left", padx=4)
        yes = ctk.CTkButton(actions, text=title.split()[0], height=MIN_TOUCH_TARGET, fg_color=COLOR_DANGER_RED, hover_color=COLOR_DANGER_HOVER, command=self._accept_confirm)
        yes.pack(side="left", padx=4)
        self._confirm_buttons = [cancel, yes]
        self._paint_confirm_focus()
        host = self.parent
        if hasattr(host, "_focused_zone"):
            host._focused_zone = "CONFIRM"

    def _close_confirm(self):
        self.confirming = False
        self._confirm_yes = None
        self._confirm_buttons = []
        overlay = getattr(self, "_confirm_overlay", None)
        if overlay is not None:
            overlay.destroy()
            self._confirm_overlay = None
        host = self.parent
        if hasattr(host, "_focused_zone") and host._focused_zone == "CONFIRM":
            host._focused_zone = "DETAIL"

    def _accept_confirm(self):
        action = self._confirm_yes
        self._close_confirm()
        if action:
            action()

    def _handle_confirm(self, action: str):
        if action in (ACTION_RIGHT, ACTION_DOWN):
            self._confirm_idx = min(1, self._confirm_idx + 1)
        elif action in (ACTION_LEFT, ACTION_UP):
            self._confirm_idx = max(0, self._confirm_idx - 1)
        elif action == ACTION_SELECT:
            if self._confirm_idx == 0:
                self._close_confirm()
            else:
                self._accept_confirm()
            return
        elif action == ACTION_BACK:
            self._close_confirm()
            return
        self._paint_confirm_focus()

    def _paint_confirm_focus(self):
        for idx, button in enumerate(self._confirm_buttons):
            button.configure(border_width=2 if idx == self._confirm_idx else 0, border_color=COLOR_BORDER_FOCUSED)

    def _go_back(self):
        callback = self.on_back
        if callback:
            callback()
        else:
            self.destroy()

    def _invoke(self, index: int):
        if not (0 <= index < len(self._action_buttons)):
            return
        button = self._action_buttons[index]
        command = getattr(button, "_command", None)
        if command:
            command()

    def _handle_controller_input(self, action: str):
        if self.confirming:
            self._handle_confirm(action)
            return
        count = len(self._action_buttons)
        if count == 0:
            if action == ACTION_BACK:
                self._go_back()
            return
        if action in (ACTION_RIGHT, ACTION_DOWN):
            self._focused_btn_idx = min(count - 1, self._focused_btn_idx + 1)
        elif action in (ACTION_LEFT, ACTION_UP):
            self._focused_btn_idx = max(0, self._focused_btn_idx - 1)
        elif action == ACTION_SELECT:
            self._invoke(self._focused_btn_idx)
        elif action == ACTION_BACK:
            self._go_back()
        self._paint_button_focus()

    def _paint_button_focus(self):
        for idx, button in enumerate(self._action_buttons):
            try:
                if not button.winfo_exists():
                    continue
                button.configure(
                    border_width=2 if idx == self._focused_btn_idx else 1,
                    border_color=COLOR_BORDER_FOCUSED if idx == self._focused_btn_idx else COLOR_BORDER_2,
                )
            except Exception:
                pass


def show_game_detail_modal(
    parent: Any,
    app_id: str,
    game_data: Dict[str, Any],
    status_info: Dict[str, Any],
    on_close: Optional[Any] = None,
) -> GamePage:
    """Mount the game page inside parent. Used by the window and by GUI tests."""
    page = GamePage(parent, app_id, game_data, status_info, on_back=on_close, pinned=True, host=parent)
    page.pack(fill="both", expand=True)
    return page


GameDetailModal = GamePage
