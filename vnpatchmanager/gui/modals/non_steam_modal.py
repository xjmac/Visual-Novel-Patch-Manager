"""
Modal dialog for registering non-Steam visual novels into Steam with VNDB artwork.
"""

import logging
import threading
from pathlib import Path
from tkinter import filedialog
import customtkinter as ctk

from ...controller_manager import (
    ACTION_UP,
    ACTION_DOWN,
    ACTION_LEFT,
    ACTION_RIGHT,
    ACTION_SELECT,
    ACTION_BACK,
    ACTION_QUICK_ACTION,
)
from ...steamos_helper import SteamOSHelper
from ..constants import (
    COLOR_SURFACE_DARK,
    COLOR_SURFACE_BORDER,
    COLOR_BORDER_FOCUSED,
    COLOR_ACCENT_GREEN,
    COLOR_TEXT_WHITE,
    COLOR_TEXT_MUTED,
)

logger = logging.getLogger(__name__)


def show_add_non_steam_modal(app):
    """Opens a modal dialog to select and register a non-Steam visual novel into Steam."""
    modal = ctk.CTkToplevel(app)
    modal.title("Add Non-Steam Visual Novel")
    modal.geometry("620x520")
    modal.configure(fg_color=COLOR_SURFACE_DARK)
    modal.transient(app)
    modal.grab_set()

    ctk.CTkLabel(
        modal,
        text="➕ Register Non-Steam Visual Novel",
        font=ctk.CTkFont(size=16, weight="bold"),
        text_color=COLOR_TEXT_WHITE,
    ).pack(pady=(16, 6), padx=20, anchor="w")

    ctk.CTkLabel(
        modal,
        text="Select a game folder or executable from DLsite, JAST, MangaGamer, or your SD card.\nVNPM will match it with VNDB, create a Steam shortcut, and deploy 5-slot grid artwork.",
        font=ctk.CTkFont(size=12),
        text_color=COLOR_TEXT_MUTED,
        justify="left",
    ).pack(pady=(0, 10), padx=20, anchor="w")

    # 1. Path Entry & Browse
    path_label = ctk.CTkLabel(
        modal, text="Game Path (Folder or Executable):", font=ctk.CTkFont(size=12, weight="bold"), text_color=COLOR_TEXT_WHITE
    )
    path_label.pack(anchor="w", padx=20, pady=(0, 2))

    path_frame = ctk.CTkFrame(
        modal, fg_color="#18181b", border_width=1, border_color=COLOR_SURFACE_BORDER, corner_radius=8
    )
    path_frame.pack(fill="x", padx=20, pady=(0, 10))
    path_frame.grid_columnconfigure(0, weight=1)

    entry_path = ctk.CTkEntry(
        path_frame,
        placeholder_text="Select game directory or executable...",
        fg_color="transparent",
        border_width=0,
        text_color=COLOR_TEXT_WHITE,
    )
    entry_path.grid(row=0, column=0, padx=8, pady=6, sticky="ew")

    # 2. Editable Title Entry
    title_label = ctk.CTkLabel(
        modal, text="Game Title (Editable / Live Match):", font=ctk.CTkFont(size=12, weight="bold"), text_color=COLOR_TEXT_WHITE
    )
    title_label.pack(anchor="w", padx=20, pady=(0, 2))

    title_frame = ctk.CTkFrame(
        modal, fg_color="#18181b", border_width=1, border_color=COLOR_SURFACE_BORDER, corner_radius=8
    )
    title_frame.pack(fill="x", padx=20, pady=(0, 10))
    title_frame.grid_columnconfigure(0, weight=1)

    entry_title = ctk.CTkEntry(
        title_frame,
        placeholder_text="Type or edit visual novel title...",
        fg_color="transparent",
        border_width=0,
        text_color=COLOR_TEXT_WHITE,
    )
    entry_title.grid(row=0, column=0, padx=8, pady=6, sticky="ew")

    # 3. Match Info Card
    preview_card = ctk.CTkFrame(
        modal, fg_color="#18181b", border_width=1, border_color=COLOR_SURFACE_BORDER, corner_radius=8
    )
    preview_card.pack(fill="both", expand=True, padx=20, pady=(0, 12))
    preview_card.grid_columnconfigure(0, weight=1)

    lbl_matched_meta = ctk.CTkLabel(
        preview_card,
        text="VNDB Database: Waiting for game selection...",
        font=ctk.CTkFont(size=12),
        text_color=COLOR_TEXT_MUTED,
        justify="left",
    )
    lbl_matched_meta.pack(anchor="w", padx=12, pady=12)

    matched_state = {"vndb_id": None}

    def _update_match_for_title(title_text):
        if not title_text.strip():
            lbl_matched_meta.configure(text="VNDB Database: (No title entered)", text_color=COLOR_TEXT_MUTED)
            matched_state["vndb_id"] = None
            return
        meta = app.non_steam_manager.match_vn_metadata(title_text)
        matched_state["vndb_id"] = meta["vndb_id"]
        if meta.get("vndb_id"):
            rating_str = f"★ {meta['rating']:.1f}" if meta.get("rating") else "No rating"
            lbl_matched_meta.configure(
                text=f"✅ Matched: {meta['title']}\nVNDB ID: {meta['vndb_id']} ({rating_str})\nArtwork & metadata will be configured automatically.",
                text_color="#34d399",
            )
        else:
            lbl_matched_meta.configure(
                text=f"ℹ️ Custom Title: {meta['title']}\nVNDB: Not found in database (will use default artwork).",
                text_color=COLOR_TEXT_MUTED,
            )

    def _on_title_typed(*args):
        _update_match_for_title(entry_title.get())

    entry_title.bind("<KeyRelease>", _on_title_typed)

    def _on_browse():
        chosen = filedialog.askdirectory(parent=modal, title="Select Non-Steam VN Game Folder")
        if not chosen:
            chosen = filedialog.askopenfilename(
                parent=modal,
                title="Or Select Game Executable",
                filetypes=[("Executables", "*.exe *.sh *.bin *.x86_64"), ("All Files", "*.*")],
            )
        if chosen:
            p = Path(chosen)
            entry_path.delete(0, "end")
            entry_path.insert(0, str(p))
            folder_name = p.name if p.is_dir() else p.parent.name
            meta = app.non_steam_manager.match_vn_metadata(folder_name, p.name)
            entry_title.delete(0, "end")
            entry_title.insert(0, meta["title"])
            _update_match_for_title(meta["title"])

    btn_browse = ctk.CTkButton(
        path_frame,
        text="📂 Browse",
        width=80,
        fg_color=COLOR_SURFACE_BORDER,
        hover_color="#3f3f46",
        command=_on_browse,
    )
    btn_browse.grid(row=0, column=1, padx=6, pady=6)

    def _on_register():
        path_str = entry_path.get().strip()
        title_str = entry_title.get().strip()
        if not path_str or not title_str:
            lbl_matched_meta.configure(text="❌ Error: Please provide both a game path and title.", text_color="#f87171")
            return

        game_path = Path(path_str)
        if not game_path.exists():
            lbl_matched_meta.configure(text=f"❌ Error: Path does not exist:\n{path_str}", text_color="#f87171")
            return

        lbl_matched_meta.configure(text="Registering shortcut and deploying artwork...", text_color="#60a5fa")
        modal.update_idletasks()

        def _worker():
            try:
                success, msg, _ = app.non_steam_manager.register_non_steam_game(
                    game_path=game_path, app_name=title_str
                )
                def _done():
                    if success:
                        _close_add_modal()
                        app.refresh_data()
                    else:
                        lbl_matched_meta.configure(text=f"❌ Registration Failed: {msg}", text_color="#f87171")
                app.run_on_main_thread(_done)
            except Exception as e:
                logger.error(f"Error registering non-steam game: {e}", exc_info=True)
                app.run_on_main_thread(
                    lambda err=e: lbl_matched_meta.configure(text=f"❌ Registration Failed: {err}", text_color="#f87171")
                )

        threading.Thread(target=_worker, daemon=True).start()

    # 4. Action Buttons Frame
    btn_actions_frame = ctk.CTkFrame(modal, fg_color="transparent")
    btn_actions_frame.pack(fill="x", padx=20, pady=(0, 16))

    btn_create = ctk.CTkButton(
        btn_actions_frame,
        text="✨ Add to Steam",
        font=ctk.CTkFont(weight="bold"),
        height=34,
        fg_color=COLOR_ACCENT_GREEN,
        hover_color="#059669",
        command=_on_register,
    )
    btn_create.pack(side="left", fill="x", expand=True, padx=(0, 6))

    btn_cancel = ctk.CTkButton(
        btn_actions_frame,
        text="Cancel",
        font=ctk.CTkFont(weight="bold"),
        height=34,
        fg_color=COLOR_SURFACE_BORDER,
        hover_color="#3f3f46",
        command=lambda: _close_add_modal(),
    )
    btn_cancel.pack(side="right", fill="x", expand=True, padx=(6, 0))

    # Modal Controller Navigation
    add_focus_state = {"index": 0}

    def _apply_add_modal_focus():
        if not modal.winfo_exists():
            return
        idx = add_focus_state["index"]
        btn_browse.configure(
            border_color=COLOR_BORDER_FOCUSED if idx == 0 else COLOR_SURFACE_BORDER,
            border_width=2 if idx == 0 else 0,
        )
        title_frame.configure(
            border_color=COLOR_BORDER_FOCUSED if idx == 1 else COLOR_SURFACE_BORDER,
            border_width=2 if idx == 1 else 1,
        )
        btn_create.configure(
            border_color=COLOR_BORDER_FOCUSED if idx == 2 else "#059669",
            border_width=2 if idx == 2 else 0,
        )
        btn_cancel.configure(
            border_color=COLOR_BORDER_FOCUSED if idx == 3 else COLOR_SURFACE_BORDER,
            border_width=2 if idx == 3 else 0,
        )

        if idx == 1:
            entry_title.focus_set()
            SteamOSHelper.show_onscreen_keyboard()
        else:
            modal.focus_set()
            SteamOSHelper.hide_onscreen_keyboard()

    def _handle_add_modal_controller(action: str):
        curr_i = add_focus_state["index"]
        if action == ACTION_BACK:
            _close_add_modal()
            return

        if action == ACTION_UP:
            add_focus_state["index"] = max(0, curr_i - 1)
            _apply_add_modal_focus()
        elif action == ACTION_DOWN:
            add_focus_state["index"] = min(3, curr_i + 1)
            _apply_add_modal_focus()
        elif action == ACTION_LEFT:
            if curr_i == 3:
                add_focus_state["index"] = 2
                _apply_add_modal_focus()
        elif action == ACTION_RIGHT:
            if curr_i == 2:
                add_focus_state["index"] = 3
                _apply_add_modal_focus()
        elif action in (ACTION_SELECT, ACTION_QUICK_ACTION):
            if curr_i == 0:
                _on_browse()
            elif curr_i == 1:
                entry_title.focus_set()
                SteamOSHelper.show_onscreen_keyboard()
            elif curr_i == 2:
                _on_register()
            elif curr_i == 3:
                _close_add_modal()

    app.push_modal_controller_handler(_handle_add_modal_controller)

    modal.bind("<Up>", lambda e: _handle_add_modal_controller(ACTION_UP) or "break")
    modal.bind("<Down>", lambda e: _handle_add_modal_controller(ACTION_DOWN) or "break")
    modal.bind("<Left>", lambda e: _handle_add_modal_controller(ACTION_LEFT) or "break")
    modal.bind("<Right>", lambda e: _handle_add_modal_controller(ACTION_RIGHT) or "break")
    modal.bind("<Return>", lambda e: _handle_add_modal_controller(ACTION_SELECT) or "break")
    modal.bind("<Escape>", lambda e: _handle_add_modal_controller(ACTION_BACK) or "break")

    def _close_add_modal():
        app.pop_modal_controller_handler(_handle_add_modal_controller)
        SteamOSHelper.hide_onscreen_keyboard()
        modal.destroy()
        app._apply_focus_visuals()

    modal.protocol("WM_DELETE_WINDOW", _close_add_modal)
    _apply_add_modal_focus()

    modal._entry_path = entry_path
    modal._entry_title = entry_title
    modal._lbl_matched_meta = lbl_matched_meta
    modal._btn_browse = btn_browse
    modal._btn_create = btn_create
    modal._btn_cancel = btn_cancel
    modal._on_browse = _on_browse
    modal._on_register = _on_register
    modal._close_add_modal = _close_add_modal
    modal._controller_handler = _handle_add_modal_controller

    return modal
