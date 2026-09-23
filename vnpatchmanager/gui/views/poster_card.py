"""
Portrait Poster Card component for Visual Novel Patch Manager.
Renders 2:3 aspect ratio visual novel capsule posters with clean metadata,
single status pills, and zero nested button traps for console-grade navigation.
"""

import logging
from typing import Callable, Dict, Any
import customtkinter as ctk

from ..theme import (
    COLOR_ELEVATION_2,
    COLOR_BORDER_2,
    COLOR_TEXT_PRIMARY,
    COLOR_STATUS_PATCHED,
    COLOR_STATUS_READY,
    COLOR_STATUS_MISSING,
    COLOR_STATUS_BACKUP,
    COLOR_STATUS_MUTED,
    POSTER_CARD_SIZE,
    CARD_RADIUS,
)

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
    """Constructs an uncluttered portrait poster card with direct click/gamepad selection."""
    card = ctk.CTkFrame(
        parent,
        corner_radius=CARD_RADIUS,
        fg_color=COLOR_ELEVATION_2,
        border_width=1,
        border_color=COLOR_BORDER_2,
        width=POSTER_CARD_SIZE[0] + 16,
    )
    card.grid(row=row_idx, column=col_idx, padx=8, pady=8, sticky="nsew")
    card.grid_columnconfigure(0, weight=1)

    # 1. High-Resolution Portrait Cover (2:3 aspect ratio)
    cover_img = cover_manager.get_cover_image(
        app_id, title=game_data.get("name", ""), size=POSTER_CARD_SIZE
    )
    lbl_banner = ctk.CTkLabel(card, text="", image=cover_img, corner_radius=8)
    lbl_banner.grid(row=0, column=0, padx=8, pady=(8, 4), sticky="nsew")

    # 2. Status Pill & Rating Row
    meta_row = ctk.CTkFrame(card, fg_color="transparent")
    meta_row.grid(row=1, column=0, padx=10, pady=(2, 2), sticky="ew")
    meta_row.grid_columnconfigure(0, weight=1)

    # Resolve primary status pill
    is_patched = status_info.get("is_patched", False)
    has_local_patch = status_info.get("has_local_patch", False)
    has_vndb_18_patch = status_info.get("has_vndb_18_patch", False)
    has_clean_backup = status_info.get("has_clean_backup", False)

    if is_patched:
        pill_text = "● Patched"
        pill_color = COLOR_STATUS_PATCHED
        pill_bg = "#064e3b"
    elif has_local_patch:
        pill_text = "● Ready"
        pill_color = COLOR_STATUS_READY
        pill_bg = "#451a03"
    elif has_vndb_18_patch:
        pill_text = "● Missing 18+"
        pill_color = COLOR_STATUS_MISSING
        pill_bg = "#500724"
    elif has_clean_backup:
        pill_text = "● Backup"
        pill_color = COLOR_STATUS_BACKUP
        pill_bg = "#082f49"
    else:
        pill_text = "● Clean"
        pill_color = COLOR_STATUS_MUTED
        pill_bg = "#1e293b"

    lbl_pill = ctk.CTkLabel(
        meta_row,
        text=f" {pill_text} ",
        font=ctk.CTkFont(size=10, weight="bold"),
        text_color=pill_color,
        fg_color=pill_bg,
        corner_radius=6,
        height=18,
    )
    lbl_pill.pack(side="left", padx=(0, 4))

    rating = status_info.get("rating")
    if rating:
        lbl_rating = ctk.CTkLabel(
            meta_row,
            text=f"★ {float(rating):.1f}",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#fbbf24",
        )
        lbl_rating.pack(side="right")

    # 3. Game Title (Clean 2-line clamp)
    lbl_title = ctk.CTkLabel(
        card,
        text=game_data.get("name", ""),
        font=ctk.CTkFont(size=12, weight="bold"),
        text_color=COLOR_TEXT_PRIMARY,
        wraplength=POSTER_CARD_SIZE[0],
        justify="left",
        anchor="w",
    )
    lbl_title.grid(row=2, column=0, padx=10, pady=(2, 8), sticky="ew")

    # 4. Interactive Click Handlers (Opening Game Detail Drawer)
    def _handle_click(event=None):
        on_select(app_id, game_data)

    def _bind_click_recursive(widget):
        widget.bind("<Button-1>", _handle_click)
        for child in widget.winfo_children():
            _bind_click_recursive(child)

    _bind_click_recursive(card)

    # 5. Forward Mouse Wheel Events to Parent Canvas
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
            elif getattr(event, "num", None) == 5:
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
                    if hasattr(widget, "_canvas") and widget._canvas:
                        widget._canvas.bind(seq, _forward_mouse_wheel, add="+")
                    if hasattr(widget, "_label") and widget._label:
                        widget._label.bind(seq, _forward_mouse_wheel, add="+")
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
