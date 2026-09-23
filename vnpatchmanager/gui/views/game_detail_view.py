"""
Game Detail View (Drawer / Modal) for Visual Novel Patch Manager.
Provides an immersive console-grade detail view with rich hero artwork,
VNDB synopsis, system metadata, touch-friendly 44px action buttons,
and 1:1 gamepad navigation.
"""

import logging
import webbrowser
from typing import Dict, Any, Optional
import customtkinter as ctk

from ..theme import (
    COLOR_CANVAS,
    COLOR_ELEVATION_1,
    COLOR_BORDER_1,
    COLOR_ELEVATION_2,
    COLOR_BORDER_2,
    COLOR_ELEVATION_3,
    COLOR_BORDER_FOCUSED,
    COLOR_PRIMARY_BLUE,
    COLOR_PRIMARY_HOVER,
    COLOR_DANGER_RED,
    COLOR_DANGER_HOVER,
    COLOR_STATUS_PATCHED,
    COLOR_STATUS_READY,
    COLOR_STATUS_MISSING,
    COLOR_STATUS_BACKUP,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_TEXT_MUTED,
    HERO_BANNER_SIZE,
    MIN_TOUCH_TARGET,
    CARD_RADIUS,
)

logger = logging.getLogger(__name__)


class GameDetailModal(ctk.CTkToplevel):
    """Console-grade Game Detail Drawer/Modal for Visual Novels."""

    def __init__(self, parent: Any, app_id: str, game_data: Dict[str, Any], status_info: Dict[str, Any], on_close: Optional[Any] = None):
        super().__init__(parent)
        self.parent = parent
        self.app_id = str(app_id)
        self.game_data = game_data
        self.status_info = status_info
        self.on_close_callback = on_close

        self.title(f"{game_data.get('name', 'Game Details')}")
        self.configure(fg_color=COLOR_CANVAS)
        self.resizable(True, True)

        # Responsive Geometry (Fits Steam Deck 1280x800 and desktop)
        w, h = 820, 620
        try:
            pw = self.parent.winfo_width()
            ph = self.parent.winfo_height()
            px = self.parent.winfo_rootx()
            py = self.parent.winfo_rooty()
            if pw > 100 and ph > 100:
                w = min(w, pw - 30)
                h = min(h, ph - 30)
                x = px + (pw - w) // 2
                y = py + (ph - h) // 2
                self.geometry(f"{w}x{h}+{x}+{y}")
            else:
                self.geometry(f"{w}x{h}")
        except Exception:
            self.geometry(f"{w}x{h}")

        self.minsize(580, 480)

        # Focus & Grab
        try:
            self.transient(self.parent)
            self.grab_set()
        except Exception:
            pass

        self._action_buttons = []
        self._focused_btn_idx = 0

        self._build_ui()

        # Controller handling registration
        if hasattr(self.parent, "push_modal_controller_handler"):
            self.parent.push_modal_controller_handler(self._handle_controller_input)

        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Escape>", lambda e: self._close())
        self.after(50, self._apply_button_focus)

    def _close(self):
        """Pops controller handler and cleans up modal."""
        if hasattr(self.parent, "pop_modal_controller_handler"):
            self.parent.pop_modal_controller_handler(self._handle_controller_input)
        try:
            self.grab_release()
        except Exception:
            pass
        if self.on_close_callback:
            try:
                self.on_close_callback()
            except Exception:
                pass
        self.destroy()

    def _build_ui(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Top Hero Header Bar
        top_bar = ctk.CTkFrame(self, fg_color=COLOR_ELEVATION_1, corner_radius=0, height=52)
        top_bar.grid(row=0, column=0, sticky="ew", padx=0, pady=0)
        top_bar.grid_columnconfigure(0, weight=1)

        lbl_top_title = ctk.CTkLabel(
            top_bar,
            text=self.game_data.get("name", "Visual Novel Details"),
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        )
        lbl_top_title.grid(row=0, column=0, padx=16, pady=10, sticky="w")

        btn_close = ctk.CTkButton(
            top_bar,
            text="✕",
            width=36,
            height=36,
            corner_radius=18,
            fg_color="transparent",
            hover_color=COLOR_ELEVATION_2,
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLOR_TEXT_SECONDARY,
            command=self._close,
        )
        btn_close.grid(row=0, column=1, padx=12, pady=8, sticky="e")

        # Main Scrollable Detail Container
        scroll_content = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll_content.grid(row=1, column=0, sticky="nsew", padx=16, pady=(10, 6))
        scroll_content.grid_columnconfigure(0, weight=1)

        # 1. Hero Artwork Banner
        cover_mgr = getattr(self.parent, "cover_manager", None)
        if cover_mgr:
            hero_img = cover_mgr.get_cover_image(
                self.app_id,
                title=self.game_data.get("name", ""),
                size=(min(760, HERO_BANNER_SIZE[0]), HERO_BANNER_SIZE[1]),
            )
            lbl_hero = ctk.CTkLabel(scroll_content, text="", image=hero_img, corner_radius=CARD_RADIUS)
            lbl_hero.grid(row=0, column=0, sticky="ew", pady=(0, 12))

        # 2. Metadata Cards Container
        meta_container = ctk.CTkFrame(
            scroll_content,
            fg_color=COLOR_ELEVATION_2,
            border_color=COLOR_BORDER_2,
            border_width=1,
            corner_radius=CARD_RADIUS,
        )
        meta_container.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        meta_container.grid_columnconfigure(1, weight=1)

        # Status & Badges
        is_patched = self.status_info.get("is_patched", False)
        has_local_patch = self.status_info.get("has_local_patch", False)
        has_vndb_18_patch = self.status_info.get("has_vndb_18_patch", False)
        has_clean_backup = self.status_info.get("has_clean_backup", False)
        vn_info = self.status_info.get("vn_info", {})

        badges_frame = ctk.CTkFrame(meta_container, fg_color="transparent")
        badges_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(14, 8))

        if is_patched:
            pill_text, pill_color = "● Patched & Verified", COLOR_STATUS_PATCHED
        elif has_local_patch:
            pill_text, pill_color = "● 18+ Patch Ready", COLOR_STATUS_READY
        elif has_vndb_18_patch:
            pill_text, pill_color = "● Missing 18+ Patch (VNDB)", COLOR_STATUS_MISSING
        else:
            pill_text, pill_color = "● Clean Unpatched", COLOR_TEXT_MUTED

        lbl_status = ctk.CTkLabel(
            badges_frame,
            text=f" {pill_text} ",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=pill_color,
            fg_color=COLOR_ELEVATION_1,
            corner_radius=6,
            height=24,
        )
        lbl_status.pack(side="left", padx=(0, 8))

        if has_clean_backup:
            lbl_backup = ctk.CTkLabel(
                badges_frame,
                text=" ● Clean Backup Stored ",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=COLOR_STATUS_BACKUP,
                fg_color=COLOR_ELEVATION_1,
                corner_radius=6,
                height=24,
            )
            lbl_backup.pack(side="left", padx=(0, 8))

        rating = vn_info.get("rating")
        votecount = vn_info.get("votecount")
        if rating:
            votes_str = f" ({votecount:,} votes)" if votecount else ""
            lbl_rating = ctk.CTkLabel(
                badges_frame,
                text=f"★ {float(rating):.2f}{votes_str}",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#fbbf24",
            )
            lbl_rating.pack(side="right", padx=(8, 0))

        # Metadata Specs Table
        dev = vn_info.get("developer") or "Unknown"
        released = vn_info.get("released") or "Unknown"
        length_str = vn_info.get("length_str") or ""
        install_path = self.game_data.get("path", "Not installed")

        specs = [
            ("Developer:", dev),
            ("Release Date:", released),
            ("Length:", length_str or "Standard VN"),
            ("App ID:", f"Steam #{self.app_id}" if not self.game_data.get("is_non_steam") else f"Non-Steam ({self.app_id})"),
            ("Install Path:", str(install_path)),
        ]

        for s_idx, (k, v) in enumerate(specs):
            lbl_k = ctk.CTkLabel(
                meta_container,
                text=k,
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=COLOR_TEXT_SECONDARY,
                anchor="w",
            )
            lbl_k.grid(row=s_idx + 1, column=0, sticky="w", padx=(16, 8), pady=2)

            lbl_v = ctk.CTkLabel(
                meta_container,
                text=v,
                font=ctk.CTkFont(size=12),
                text_color=COLOR_TEXT_PRIMARY,
                anchor="w",
                wraplength=480,
                justify="left",
            )
            lbl_v.grid(row=s_idx + 1, column=1, sticky="w", padx=(0, 16), pady=2)

        # Add spacing at bottom of meta
        meta_container.grid_rowconfigure(len(specs) + 1, minsize=8)

        # 3. Synopsis / Description Box
        desc_text = vn_info.get("description", "").strip()
        if desc_text:
            synopsis_frame = ctk.CTkFrame(
                scroll_content,
                fg_color=COLOR_ELEVATION_2,
                border_color=COLOR_BORDER_2,
                border_width=1,
                corner_radius=CARD_RADIUS,
            )
            synopsis_frame.grid(row=2, column=0, sticky="ew", pady=(0, 12))
            synopsis_frame.grid_columnconfigure(0, weight=1)

            lbl_syn_header = ctk.CTkLabel(
                synopsis_frame,
                text="Synopsis",
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=COLOR_TEXT_PRIMARY,
                anchor="w",
            )
            lbl_syn_header.grid(row=0, column=0, sticky="w", padx=16, pady=(10, 4))

            lbl_syn_body = ctk.CTkLabel(
                synopsis_frame,
                text=desc_text,
                font=ctk.CTkFont(size=12),
                text_color=COLOR_TEXT_SECONDARY,
                wraplength=700,
                justify="left",
                anchor="w",
            )
            lbl_syn_body.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 12))

        # Bottom Sticky Primary Action Bar (Touch-friendly 44px+ buttons)
        action_bar = ctk.CTkFrame(
            self,
            fg_color=COLOR_ELEVATION_1,
            border_color=COLOR_BORDER_1,
            border_width=1,
            corner_radius=0,
            height=64,
        )
        action_bar.grid(row=2, column=0, sticky="ew", padx=0, pady=0)
        action_bar.grid_columnconfigure(0, weight=1)

        btn_row = ctk.CTkFrame(action_bar, fg_color="transparent")
        btn_row.pack(side="left", fill="x", expand=True, padx=16, pady=10)

        patch_data = getattr(self.parent, "repo", None).available_patches.get(self.app_id) if hasattr(self.parent, "repo") else None
        is_non_steam = self.game_data.get("is_non_steam", False)

        # Primary Action Button
        if has_local_patch:
            primary_text = "[A] Verify / Re-apply Patch" if is_patched else "[A] Apply 18+ Patch"
            btn_primary = ctk.CTkButton(
                btn_row,
                text=primary_text,
                font=ctk.CTkFont(size=13, weight="bold"),
                height=MIN_TOUCH_TARGET,
                fg_color=COLOR_PRIMARY_BLUE,
                hover_color=COLOR_PRIMARY_HOVER,
                border_width=1,
                border_color="#0284c7",
                command=lambda: self._invoke_and_close(lambda: self.parent.run_patch(self.game_data, patch_data)),
            )
            btn_primary.pack(side="left", padx=(0, 8))
            self._action_buttons.append(btn_primary)

        # Secondary Actions
        if has_clean_backup:
            btn_rollback = ctk.CTkButton(
                btn_row,
                text="Restore Backup",
                font=ctk.CTkFont(size=12, weight="bold"),
                height=MIN_TOUCH_TARGET,
                fg_color=COLOR_DANGER_RED,
                hover_color=COLOR_DANGER_HOVER,
                command=lambda: self._invoke_and_close(lambda: self.parent.run_rollback(self.game_data)),
            )
            btn_rollback.pack(side="left", padx=(0, 8))
            self._action_buttons.append(btn_rollback)

        if not is_non_steam and (is_patched or self.status_info.get("has_backup")):
            btn_steam = ctk.CTkButton(
                btn_row,
                text="Restore via Steam",
                font=ctk.CTkFont(size=12),
                height=MIN_TOUCH_TARGET,
                fg_color=COLOR_BORDER_2,
                hover_color=COLOR_ELEVATION_3,
                command=lambda: self._invoke_and_close(
                    lambda: self.parent.run_steam_restore(self.game_data, patch_data=patch_data, app_id=self.app_id)
                ),
            )
            btn_steam.pack(side="left", padx=(0, 8))
            self._action_buttons.append(btn_steam)

        btn_codec = ctk.CTkButton(
            btn_row,
            text="🔧 Video Codec Fix",
            font=ctk.CTkFont(size=12),
            height=MIN_TOUCH_TARGET,
            fg_color=COLOR_BORDER_2,
            hover_color=COLOR_ELEVATION_3,
            command=lambda: self._invoke_and_close(
                lambda: self.parent.run_fix_video(self.app_id, self.game_data)
            ),
        )
        btn_codec.pack(side="left", padx=(0, 8))
        self._action_buttons.append(btn_codec)

        btn_art = ctk.CTkButton(
            btn_row,
            text="🎨 Custom Art",
            font=ctk.CTkFont(size=12),
            height=MIN_TOUCH_TARGET,
            fg_color=COLOR_BORDER_2,
            hover_color=COLOR_ELEVATION_3,
            command=lambda: self._invoke_and_close(lambda: self.parent.run_custom_artwork(self.app_id, self.game_data)),
        )
        btn_art.pack(side="left", padx=(0, 8))
        self._action_buttons.append(btn_art)

        vn_id = vn_info.get("vn_id")
        if vn_id:
            btn_vndb = ctk.CTkButton(
                btn_row,
                text="🔗 VNDB",
                font=ctk.CTkFont(size=12),
                height=MIN_TOUCH_TARGET,
                fg_color=COLOR_BORDER_2,
                hover_color=COLOR_ELEVATION_3,
                command=lambda: webbrowser.open(f"https://vndb.org/{vn_id}"),
            )
            btn_vndb.pack(side="left", padx=(0, 8))
            self._action_buttons.append(btn_vndb)

        if is_non_steam:
            btn_remove = ctk.CTkButton(
                btn_row,
                text="🗑️ Remove",
                font=ctk.CTkFont(size=12),
                height=MIN_TOUCH_TARGET,
                fg_color="#450a0a",
                hover_color="#7f1d1d",
                text_color="#fca5a5",
                border_width=1,
                border_color="#7f1d1d",
                command=lambda: self._invoke_and_close(lambda: self.parent.run_remove_non_steam(self.app_id, self.game_data)),
            )
            btn_remove.pack(side="left", padx=(0, 8))
            self._action_buttons.append(btn_remove)

    def _invoke_and_close(self, action_func):
        """Runs an action and gracefully dismisses detail modal."""
        self._close()
        try:
            action_func()
        except Exception as e:
            logger.error(f"Error executing detail action: {e}")

    def _handle_controller_input(self, action: str):
        """Handles gamepad controller navigation within the detail view."""
        from ...controller_manager import (
            ACTION_LEFT,
            ACTION_RIGHT,
            ACTION_SELECT,
            ACTION_BACK,
            ACTION_QUICK_ACTION,
        )

        num_btns = len(self._action_buttons)
        if action == ACTION_LEFT:
            if num_btns > 0:
                self._focused_btn_idx = max(0, self._focused_btn_idx - 1)
                self._apply_button_focus()
        elif action == ACTION_RIGHT:
            if num_btns > 0:
                self._focused_btn_idx = min(num_btns - 1, self._focused_btn_idx + 1)
                self._apply_button_focus()
        elif action == ACTION_SELECT:
            if 0 <= self._focused_btn_idx < num_btns:
                self._action_buttons[self._focused_btn_idx].invoke()
        elif action == ACTION_BACK:
            self._close()
        elif action == ACTION_QUICK_ACTION:
            # X shortcut triggers Custom Art or First Secondary action
            if len(self._action_buttons) >= 2:
                self._action_buttons[1].invoke()

    def _apply_button_focus(self):
        """Applies visual highlight border to focused action button."""
        for idx, btn in enumerate(self._action_buttons):
            if idx == self._focused_btn_idx:
                btn.configure(border_color=COLOR_BORDER_FOCUSED, border_width=2)
            else:
                btn.configure(border_color=COLOR_BORDER_2, border_width=1)


def show_game_detail_modal(parent: Any, app_id: str, game_data: Dict[str, Any], status_info: Dict[str, Any], on_close: Optional[Any] = None) -> GameDetailModal:
    """Factory function to instantiate and display the Game Detail Modal."""
    modal = GameDetailModal(parent, app_id, game_data, status_info, on_close)
    try:
        modal.lift()
        modal.focus_force()
    except Exception:
        pass
    return modal
