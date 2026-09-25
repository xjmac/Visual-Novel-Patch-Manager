"""
Portrait poster card for the library.
The cover is the card. One title line and one status word sit underneath.
"""

import logging
from typing import Any, Callable, Dict
import customtkinter as ctk

from ..theme import (
    COLOR_BORDER_2,
    COLOR_ELEVATION_2,
    COLOR_STATUS_BACKUP,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    POSTER_CARD_SIZE,
    CARD_RADIUS,
)
from ..status import show_backup_mark, status_color, status_word

logger = logging.getLogger(__name__)


def create_poster_card(
    parent: Any,
    app_id: str,
    game_data: Dict[str, Any],
    status_info: Dict[str, Any],
    cover_manager: Any,
    on_select: Callable[[str, Dict[str, Any]], None],
    row_idx: int = 0,
    col_idx: int = 0,
) -> Dict[str, Any]:
    """Portrait card. The whole card opens the game page."""
    card = ctk.CTkFrame(
        parent,
        corner_radius=CARD_RADIUS,
        fg_color=COLOR_ELEVATION_2,
        border_width=1,
        border_color=COLOR_BORDER_2,
    )
    card.grid(row=row_idx, column=col_idx, padx=8, pady=8, sticky="nsew")
    card.grid_columnconfigure(0, weight=1)

    cover_img = cover_manager.get_cover_image(
        app_id, title=game_data.get("name", ""), size=POSTER_CARD_SIZE
    )
    lbl_banner = ctk.CTkLabel(card, text="", image=cover_img, corner_radius=8)
    lbl_banner.grid(row=0, column=0, padx=8, pady=(8, 4), sticky="nsew")

    installed = status_info.get("is_installed", True)
    title = ctk.CTkLabel(
        card,
        text=game_data.get("name", ""),
        font=ctk.CTkFont(size=15, weight="bold"),
        text_color=COLOR_TEXT_PRIMARY if installed else COLOR_TEXT_MUTED,
        wraplength=POSTER_CARD_SIZE[0],
        justify="left",
        anchor="w",
    )
    title.grid(row=1, column=0, padx=10, pady=(2, 0), sticky="ew")

    meta = ctk.CTkFrame(card, fg_color="transparent")
    meta.grid(row=2, column=0, padx=10, pady=(2, 8), sticky="ew")
    word = status_info.get("status_word") or status_word(status_info)
    ctk.CTkLabel(
        meta,
        text=word,
        font=ctk.CTkFont(size=12, weight="bold"),
        text_color=status_color(status_info),
    ).pack(side="left")
    if status_info.get("show_backup_mark") or show_backup_mark(status_info):
        ctk.CTkLabel(
            meta,
            text="●",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_STATUS_BACKUP,
        ).pack(side="left", padx=(6, 0))
    rating = status_info.get("rating")
    if rating:
        ctk.CTkLabel(
            meta,
            text=f"{float(rating):.1f}",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_MUTED,
        ).pack(side="right")

    def _handle_click(event=None):
        on_select(app_id, game_data)

    def _bind_click_recursive(widget):
        widget.bind("<Button-1>", _handle_click)
        for child in widget.winfo_children():
            _bind_click_recursive(child)

    _bind_click_recursive(card)

    canvas = getattr(parent, "_parent_canvas", None)
    if canvas:
        def _forward_mouse_wheel(event):
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

        def _bind_mouse_wheel_recursive(widget):
            for seq in ("<Button-4>", "<Button-5>", "<MouseWheel>"):
                try:
                    widget.bind(seq, _forward_mouse_wheel, add="+")
                except Exception:
                    pass
            for child in widget.winfo_children():
                _bind_mouse_wheel_recursive(child)

        _bind_mouse_wheel_recursive(card)

    return {
        "card": card,
        "app_id": app_id,
        "game_data": game_data,
        "open_detail": _handle_click,
        "buttons": [],
        "default_button": None,
        "banner_label": lbl_banner,
    }
