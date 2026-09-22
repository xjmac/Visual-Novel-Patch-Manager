"""
Game card layout, status badge rendering, and card widget creation for VNPM.
"""

import logging
import webbrowser
import customtkinter as ctk

from ..backup_manager import BackupManager
from ..patch_execution import PatchExecutionEngine
from .constants import (
    COLOR_SURFACE_CARD,
    COLOR_SURFACE_BORDER,
    COLOR_PRIMARY_BLUE,
    COLOR_PRIMARY_HOVER,
    COLOR_STATUS_GREEN,
    COLOR_STATUS_YELLOW,
    COLOR_STATUS_AMBER,
    COLOR_STATUS_ROSE,
    COLOR_TEXT_WHITE,
    COLOR_TEXT_MUTED,
    COLOR_BADGE_PINK,
    COLOR_BADGE_SKY,
    GRID_CARD_BANNER_SIZE,
    LIST_ROW_BANNER_SIZE,
)

logger = logging.getLogger(__name__)


class GameCardMixin:
    """Provides status calculation, badge rendering, and card widget building."""

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
            status_color = COLOR_STATUS_AMBER
            status_priority = 0 if is_installed else 3
        elif has_vndb_18_patch:
            status_text = "● Missing 18+ Patch (VNDB)"
            status_color = COLOR_STATUS_ROSE
            status_priority = 1
        else:
            status_text = ""
            status_color = COLOR_TEXT_MUTED
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
            "search_haystack": search_haystack,
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
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        lbl_status_badge.pack(side="left", padx=(0, 6))

        if status_info.get("is_non_steam"):
            ctk.CTkLabel(
                parent_frame,
                text="🎮 Non-Steam",
                text_color=COLOR_STATUS_GREEN,
                font=ctk.CTkFont(size=11, weight="bold"),
            ).pack(side="left", padx=(0, 6))

        if status_info["rating"] is not None:
            ctk.CTkLabel(
                parent_frame,
                text=f"★ {status_info['rating']:.1f}",
                text_color=COLOR_STATUS_YELLOW,
                font=ctk.CTkFont(size=11, weight="bold"),
            ).pack(side="left", padx=(0, 6))

        if not status_info["is_installed"]:
            ctk.CTkLabel(
                parent_frame,
                text="💾 Not Installed",
                text_color=COLOR_TEXT_MUTED,
                font=ctk.CTkFont(size=11),
            ).pack(side="left", padx=(0, 4))
        elif status_info["has_clean_backup"]:
            ctk.CTkLabel(
                parent_frame,
                text="💾 Clean Backup",
                text_color=COLOR_BADGE_SKY,
                font=ctk.CTkFont(size=11),
            ).pack(side="left", padx=(0, 4))
        elif status_info["has_backup"]:
            ctk.CTkLabel(
                parent_frame,
                text="⚠️ Pre-Patched Backup",
                text_color=COLOR_STATUS_YELLOW,
                font=ctk.CTkFont(size=11),
            ).pack(side="left", padx=(0, 4))

        if (
            status_info["has_vndb_18_patch"]
            and not status_info["is_patched"]
            and status_info["has_local_patch"]
        ):
            ctk.CTkLabel(
                parent_frame,
                text="🔞 18+ on VNDB",
                text_color=COLOR_BADGE_PINK,
                font=ctk.CTkFont(size=11),
            ).pack(side="left")

    def _create_grid_card(self, parent, app_id: str, game_data: dict, row_idx: int, col_idx: int) -> dict:
        """Constructs a responsive grid card for a visual novel."""
        is_non_steam = game_data.get("is_non_steam", False)

        card = ctk.CTkFrame(
            parent,
            corner_radius=12,
            fg_color=COLOR_SURFACE_CARD,
            border_width=1,
            border_color=COLOR_SURFACE_BORDER,
        )
        card.grid(row=row_idx, column=col_idx, padx=8, pady=8, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(1, weight=1)

        # 1. Top Cover Banner
        cover_img = self.cover_manager.get_cover_image(
            app_id, title=game_data["name"], size=GRID_CARD_BANNER_SIZE
        )
        lbl_banner = ctk.CTkLabel(card, text="", image=cover_img, corner_radius=8)
        lbl_banner.grid(row=0, column=0, padx=10, pady=(10, 6), sticky="ew")
        self._banner_widgets.setdefault(str(app_id), []).append(
            (lbl_banner, game_data["name"], GRID_CARD_BANNER_SIZE)
        )

        # 2. Content Info Frame
        info_frame = ctk.CTkFrame(card, fg_color="transparent")
        info_frame.grid(row=1, column=0, padx=12, pady=4, sticky="ew")
        info_frame.grid_columnconfigure(0, weight=1)

        # Game Title
        ctk.CTkLabel(
            info_frame,
            text=game_data["name"],
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLOR_TEXT_WHITE,
            wraplength=270,
            justify="left",
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
                fg_color=COLOR_PRIMARY_BLUE,
                hover_color=COLOR_PRIMARY_HOVER,
                command=lambda g=game_data, p=patch_data: self.run_patch(g, p),
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
                    command=lambda g=game_data: self.run_rollback(g),
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
                    command=lambda g=game_data, p=patch_data: self.run_steam_restore(g, p),
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
                    command=lambda g=game_data, p=patch_data: self.run_steam_restore(g, p),
                )
                btn_steam.pack(side="left", fill="x", expand=True, padx=(0, 4))
                card_buttons.append(btn_steam)
                default_btn = btn_steam

            vndb_url = vn_info.get("vndb_url") or (
                f"https://vndb.org/{vn_info.get('vn_id')}" if vn_info.get("vn_id") else None
            )
            if vndb_url:
                btn_vndb = ctk.CTkButton(
                    primary_actions_frame,
                    text="🔗 Open VNDB (Get Patch)",
                    font=ctk.CTkFont(size=12, weight="bold"),
                    height=32,
                    fg_color="#0284c7",
                    hover_color="#0369a1",
                    command=lambda u=vndb_url: webbrowser.open(u),
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
                command=lambda g=game_data, aid=app_id: self.run_fix_video(aid, g),
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
                command=lambda g=game_data, aid=app_id: self.run_custom_artwork(aid, g),
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
                    command=lambda g=game_data, aid=app_id: self.run_remove_non_steam(aid, g),
                )
                btn_remove.pack(side="left", fill="x", expand=True, padx=(3, 0))
                card_buttons.append(btn_remove)

        return {
            "card": card,
            "app_id": app_id,
            "game_data": game_data,
            "buttons": card_buttons,
            "default_button": default_btn,
        }

    def _create_list_row(self, parent, app_id: str, game_data: dict, row_idx: int) -> dict:
        """Constructs a compact list row for a visual novel."""
        is_non_steam = game_data.get("is_non_steam", False)

        card = ctk.CTkFrame(
            parent,
            corner_radius=8,
            fg_color=COLOR_SURFACE_CARD,
            border_width=1,
            border_color=COLOR_SURFACE_BORDER,
        )
        card.grid(row=row_idx, column=0, padx=6, pady=4, sticky="ew")
        card.grid_columnconfigure(1, weight=1)

        # 1. Mini Thumbnail
        cover_img = self.cover_manager.get_cover_image(
            app_id, title=game_data["name"], size=(80, 44)
        )
        lbl_thumb = ctk.CTkLabel(card, text="", image=cover_img)
        lbl_thumb.grid(row=0, column=0, padx=(10, 12), pady=8)
        self._banner_widgets.setdefault(str(app_id), []).append(
            (lbl_thumb, game_data["name"], (80, 44))
        )

        # 2. Title & Badges
        info_frame = ctk.CTkFrame(card, fg_color="transparent")
        info_frame.grid(row=0, column=1, sticky="w", pady=6)

        ctk.CTkLabel(
            info_frame,
            text=game_data["name"],
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLOR_TEXT_WHITE,
        ).pack(anchor="w")

        status_info = self._get_game_status_info(app_id, game_data)
        is_patched = status_info["is_patched"]
        has_clean_backup = status_info["has_clean_backup"]
        has_backup = status_info["has_backup"]
        has_local_patch = status_info["has_local_patch"]
        vn_info = status_info["vn_info"]

        badges_row = ctk.CTkFrame(info_frame, fg_color="transparent")
        badges_row.pack(anchor="w", pady=(2, 0))
        self._render_badges(badges_row, status_info)

        # 3. Actions Frame
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
                fg_color=COLOR_PRIMARY_BLUE,
                hover_color=COLOR_PRIMARY_HOVER,
                command=lambda g=game_data, p=patch_data: self.run_patch(g, p),
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
                    command=lambda g=game_data: self.run_rollback(g),
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
                    command=lambda g=game_data, p=patch_data: self.run_steam_restore(g, p),
                )
                btn_steam.pack(side="left")
                card_buttons.append(btn_steam)

        else:
            if is_patched:
                btn_steam = ctk.CTkButton(
                    primary_row,
                    text="Restore via Steam",
                    font=ctk.CTkFont(size=11),
                    height=28,
                    fg_color="#4f46e5",
                    hover_color="#6366f1",
                    command=lambda g=game_data, p=patch_data: self.run_steam_restore(g, p),
                )
                btn_steam.pack(side="left", padx=(0, 4))
                card_buttons.append(btn_steam)
                default_btn = btn_steam

            vndb_url = vn_info.get("vndb_url") or (
                f"https://vndb.org/{vn_info.get('vn_id')}" if vn_info.get("vn_id") else None
            )
            if vndb_url:
                btn_vndb = ctk.CTkButton(
                    primary_row,
                    text="🔗 Open VNDB (Get Patch)",
                    font=ctk.CTkFont(size=12, weight="bold"),
                    height=28,
                    fg_color="#0284c7",
                    hover_color="#0369a1",
                    command=lambda u=vndb_url: webbrowser.open(u),
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
                command=lambda g=game_data, aid=app_id: self.run_fix_video(aid, g),
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
                command=lambda g=game_data, aid=app_id: self.run_custom_artwork(aid, g),
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
                    command=lambda g=game_data, aid=app_id: self.run_remove_non_steam(aid, g),
                )
                btn_remove.pack(side="left")
                card_buttons.append(btn_remove)

        return {
            "card": card,
            "app_id": app_id,
            "game_data": game_data,
            "buttons": card_buttons,
            "default_button": default_btn,
        }
