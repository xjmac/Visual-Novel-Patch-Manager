"""
Game card layout, status calculation, and list rows for VNPM.
"""

import logging
import customtkinter as ctk

from ..backup_manager import BackupManager
from ..patch_execution import PatchExecutionEngine
from .constants import (
    COLOR_SURFACE_BORDER,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_WHITE,
)
from .status import show_backup_mark, status_color, status_word
from .theme import COLOR_ELEVATION_2, COLOR_STATUS_BACKUP

logger = logging.getLogger(__name__)


class GameCardMixin:
    """Provides status calculation and compact list rows."""

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

        cur_name = game_data.get("name", "")
        if not cur_name or cur_name.startswith("Steam App #"):
            if vn_info.get("steam_title"):
                game_data["name"] = vn_info["steam_title"]
            elif vn_info.get("vn_title"):
                game_data["name"] = vn_info["vn_title"]
            elif patch_info and patch_info.get("game_name"):
                game_data["name"] = patch_info["game_name"]

        name_str = game_data.get("name", "").lower()
        vn_title_str = vn_info.get("vn_title", "").lower()
        vn_id_str = vn_info.get("vn_id", "").lower()
        search_haystack = f"{name_str} {vn_title_str} {str(app_id)} {vn_id_str}".strip()

        info = {
            "is_installed": is_installed,
            "is_patched": is_patched,
            "has_backup": has_backup,
            "has_clean_backup": has_clean_backup,
            "has_local_patch": has_local_patch,
            "has_vndb_18_patch": has_vndb_18_patch,
            "is_non_steam": game_data.get("is_non_steam", False),
            "rating": vn_info.get("rating"),
            "vn_info": vn_info,
            "patch_info": patch_info,
            "search_haystack": search_haystack,
        }
        word = status_word(info)
        info["status_word"] = word
        info["status_text"] = word
        info["status_color"] = status_color(info)
        info["show_backup_mark"] = show_backup_mark(info)
        if word == "Ready":
            info["status_priority"] = 0 if is_installed else 3
        elif word == "Missing":
            info["status_priority"] = 1
        elif word == "Patched":
            info["status_priority"] = 2
        else:
            info["status_priority"] = 3
        return info

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

    def _create_list_row(self, parent, app_id: str, game_data: dict, row_idx: int) -> dict:
        """One library row: cover, title, rating, and the shared status word."""
        status_info = self._get_game_status_info(app_id, game_data)
        card = ctk.CTkFrame(
            parent,
            corner_radius=8,
            fg_color=COLOR_ELEVATION_2,
            border_width=1,
            border_color=COLOR_SURFACE_BORDER,
            height=72,
        )
        card.grid(row=row_idx, column=0, padx=8, pady=4, sticky="ew")
        card.grid_columnconfigure(1, weight=1)

        cover_img = self.cover_manager.get_cover_image(app_id, title=game_data.get("name", ""), size=(48, 72))
        lbl_thumb = ctk.CTkLabel(card, text="", image=cover_img)
        lbl_thumb.grid(row=0, column=0, padx=(8, 12), pady=8)
        self._banner_widgets.setdefault(str(app_id), []).append((lbl_thumb, game_data.get("name", ""), (48, 72)))

        title_color = COLOR_TEXT_MUTED if not status_info.get("is_installed", True) else COLOR_TEXT_WHITE
        ctk.CTkLabel(
            card,
            text=game_data.get("name", ""),
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=title_color,
            anchor="w",
        ).grid(row=0, column=1, sticky="w")

        rating = status_info.get("rating")
        rating_text = f"{float(rating):.1f}" if rating else ""
        ctk.CTkLabel(
            card,
            text=rating_text,
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_MUTED,
        ).grid(row=0, column=2, padx=(8, 4))

        word = status_info.get("status_word") or status_word(status_info)
        ctk.CTkLabel(
            card,
            text=word,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=status_info.get("status_color") or status_color(status_info),
        ).grid(row=0, column=3, padx=(4, 4))
        if status_info.get("show_backup_mark"):
            ctk.CTkLabel(
                card,
                text="●",
                font=ctk.CTkFont(size=12),
                text_color=COLOR_STATUS_BACKUP,
            ).grid(row=0, column=4, padx=(0, 12))
        else:
            ctk.CTkLabel(card, text="", width=8).grid(row=0, column=4, padx=(0, 8))

        def _open(event=None, aid=app_id, data=game_data):
            self.open_game_detail(aid, data)

        def _bind(widget):
            widget.bind("<Button-1>", _open)
            for child in widget.winfo_children():
                _bind(child)

        _bind(card)
        return {
            "card": card,
            "app_id": app_id,
            "game_data": game_data,
            "open_detail": _open,
            "buttons": [],
            "default_button": None,
            "banner_label": lbl_thumb,
        }
