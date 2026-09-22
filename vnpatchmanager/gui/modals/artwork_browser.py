"""
Interactive artwork browser modal dialog for selecting SteamGridDB and VNDB visual assets.
"""

import io
import logging
import threading
from pathlib import Path
from tkinter import filedialog
from PIL import Image, ImageSequence
import customtkinter as ctk

from ...controller_manager import (
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
from ..constants import (
    COLOR_MODAL_CANVAS,
    COLOR_SURFACE_DARK,
    COLOR_SURFACE_BORDER,
    COLOR_BORDER_FOCUSED,
    COLOR_PRIMARY_BLUE,
    COLOR_PRIMARY_HOVER,
    COLOR_STATUS_GREEN,
    COLOR_TEXT_WHITE,
    COLOR_TEXT_MUTED,
)

logger = logging.getLogger(__name__)


def show_artwork_browser_modal(app, app_id: str, game_data: dict):
    """Opens an interactive artwork browser modal to choose Capsule, Wide Header, Hero, Logo, or Icon."""
    modal = ctk.CTkToplevel(app)
    modal.title(f"Visual Artwork Browser - {game_data['name']}")
    modal.geometry("820x620")
    modal.configure(fg_color=COLOR_MODAL_CANVAS)
    modal.transient(app)
    modal.grab_set()

    # Modal Header Bar
    header_frame = ctk.CTkFrame(modal, fg_color=COLOR_SURFACE_DARK, corner_radius=0, height=60)
    header_frame.pack(fill="x", padx=0, pady=(0, 10))
    header_frame.pack_propagate(False)

    ctk.CTkLabel(
        header_frame,
        text=f"🎨 Artwork Browser: {game_data['name']}",
        font=ctk.CTkFont(size=16, weight="bold"),
        text_color=COLOR_TEXT_WHITE,
    ).pack(side="left", padx=16, pady=12)

    # Asset Type Selector & Search Bar Frame
    control_frame = ctk.CTkFrame(modal, fg_color="transparent")
    control_frame.pack(fill="x", padx=16, pady=(0, 8))

    tab_buttons = [
        ("Capsule (600x900)", "capsule"),
        ("Wide Header", "wide"),
        ("Hero Banner", "hero"),
        ("Logo (PNG)", "logo"),
        ("Icon", "icon"),
    ]

    seg_frame = ctk.CTkFrame(
        control_frame,
        fg_color="#18181b",
        border_color=COLOR_BORDER_FOCUSED,
        border_width=2,
        corner_radius=8,
    )
    seg_frame.pack(side="left", padx=(0, 10))

    seg_type = ctk.CTkSegmentedButton(
        seg_frame,
        values=[name for name, _ in tab_buttons],
        command=lambda v: _on_category_changed(v),
        fg_color="#18181b",
        selected_color=COLOR_PRIMARY_BLUE,
        selected_hover_color=COLOR_PRIMARY_HOVER,
        unselected_hover_color=COLOR_SURFACE_BORDER,
        text_color=COLOR_TEXT_WHITE,
    )
    seg_type.set("Capsule (600x900)")
    seg_type.pack(padx=2, pady=2)

    # 18+ / NSFW Toggle in Modal
    switch_modal_nsfw = ctk.CTkSwitch(
        control_frame,
        text="🔞 18+ Art",
        font=ctk.CTkFont(size=12),
        text_color=COLOR_TEXT_WHITE,
        progress_color="#ec4899",
        command=lambda: _fetch_and_render_assets(),
    )
    if app.config_manager.config.get("steamgriddb_nsfw", True):
        switch_modal_nsfw.select()
    else:
        switch_modal_nsfw.deselect()
    switch_modal_nsfw.pack(side="left", padx=(0, 10))

    # Animated Art Toggle in Modal
    switch_modal_animated = ctk.CTkSwitch(
        control_frame,
        text="✨ Animated",
        font=ctk.CTkFont(size=12),
        text_color=COLOR_TEXT_WHITE,
        progress_color="#a855f7",
        command=lambda: _fetch_and_render_assets(),
    )
    if app.config_manager.config.get("steamgriddb_animated", True):
        switch_modal_animated.select()
    else:
        switch_modal_animated.deselect()
    switch_modal_animated.pack(side="left", padx=(0, 10))

    # Local File Upload Button
    btn_local_file = ctk.CTkButton(
        control_frame,
        text="📁 Local File...",
        width=110,
        fg_color=COLOR_SURFACE_BORDER,
        hover_color="#3f3f46",
        command=lambda: _on_local_file_upload(),
    )
    btn_local_file.pack(side="right")

    # Scrollable Thumbnail Grid
    scroll_grid = ctk.CTkScrollableFrame(
        modal, fg_color="#000000", corner_radius=8, border_width=1, border_color=COLOR_SURFACE_BORDER
    )
    scroll_grid.pack(fill="both", expand=True, padx=16, pady=(0, 10))
    scroll_grid.grid_columnconfigure((0, 1, 2), weight=1)

    # Status & Action Footer
    modal_footer = ctk.CTkFrame(modal, fg_color=COLOR_SURFACE_DARK, corner_radius=0, height=45)
    modal_footer.pack(fill="x", side="bottom")
    modal_footer.pack_propagate(False)

    lbl_modal_status = ctk.CTkLabel(
        modal_footer,
        text="Loading visual assets from SteamGridDB & VNDB...",
        font=ctk.CTkFont(size=12),
        text_color=COLOR_TEXT_MUTED,
    )
    lbl_modal_status.pack(side="left", padx=16, pady=10)

    # Controller Spatial Navigation for Artwork Browser Modal
    modal_card_widgets = []
    loaded_thumb_images = []
    active_animation_timers = []

    modal_focus_state = {
        "zone": "GRID",
        "tab_idx": 0,
        "card_idx": 0,
        "control_idx": 0,
    }

    def _cancel_animations():
        for timer_id in active_animation_timers:
            try:
                modal.after_cancel(timer_id)
            except Exception:
                pass
        active_animation_timers.clear()

    def _apply_modal_focus_visuals():
        if not modal.winfo_exists():
            return
        zone = modal_focus_state["zone"]
        c_idx = modal_focus_state["card_idx"]
        ctrl_idx = modal_focus_state["control_idx"]

        if seg_frame.winfo_exists():
            if zone == "TABS":
                seg_frame.configure(border_color=COLOR_BORDER_FOCUSED, border_width=2)
            else:
                seg_frame.configure(border_color=COLOR_SURFACE_BORDER, border_width=1)

        if zone == "CONTROLS":
            switch_modal_nsfw.configure(
                progress_color=COLOR_BORDER_FOCUSED if ctrl_idx == 0 else "#ec4899",
                text_color="#60a5fa" if ctrl_idx == 0 else COLOR_TEXT_WHITE,
            )
            switch_modal_animated.configure(
                progress_color=COLOR_BORDER_FOCUSED if ctrl_idx == 1 else "#a855f7",
                text_color="#60a5fa" if ctrl_idx == 1 else COLOR_TEXT_WHITE,
            )
            btn_local_file.configure(
                border_color=COLOR_BORDER_FOCUSED if ctrl_idx == 2 else "#3f3f46",
                border_width=2 if ctrl_idx == 2 else 0,
                text_color="#60a5fa" if ctrl_idx == 2 else COLOR_TEXT_WHITE,
            )
        else:
            switch_modal_nsfw.configure(progress_color="#ec4899", text_color=COLOR_TEXT_WHITE)
            switch_modal_animated.configure(progress_color="#a855f7", text_color=COLOR_TEXT_WHITE)
            btn_local_file.configure(border_color="#3f3f46", border_width=0, text_color=COLOR_TEXT_WHITE)

        for idx, item_w in enumerate(modal_card_widgets):
            card = item_w["card"]
            btn = item_w["btn"]
            if card.winfo_exists():
                if zone == "GRID" and idx == c_idx:
                    card.configure(border_color=COLOR_BORDER_FOCUSED, border_width=2, fg_color="#18181b")
                    btn.configure(fg_color=COLOR_PRIMARY_BLUE, hover_color=COLOR_PRIMARY_HOVER)
                    try:
                        card_y = card.winfo_y()
                        frame_h = scroll_grid.winfo_height()
                        if card_y and frame_h and hasattr(scroll_grid, "_parent_canvas"):
                            scroll_grid._parent_canvas.yview_moveto(
                                max(0.0, min(1.0, card_y / max(scroll_grid._parent_canvas.bbox("all")[3], 1)))
                            )
                    except Exception:
                        pass
                else:
                    card.configure(border_color=COLOR_SURFACE_BORDER, border_width=1, fg_color="#121212")
                    btn.configure(fg_color=COLOR_SURFACE_BORDER, hover_color="#3f3f46")

    def _handle_modal_controller(action: str):
        num_cards = len(modal_card_widgets)
        curr_zone = modal_focus_state["zone"]

        if action == ACTION_PREV_TAB:
            t_names = [name for name, _ in tab_buttons]
            curr_t = seg_type.get()
            curr_i = t_names.index(curr_t) if curr_t in t_names else 0
            next_i = (curr_i - 1) % len(t_names)
            seg_type.set(t_names[next_i])
            modal_focus_state["tab_idx"] = next_i
            modal_focus_state["card_idx"] = 0
            _apply_modal_focus_visuals()
            _fetch_and_render_assets()
            return
        elif action == ACTION_NEXT_TAB:
            t_names = [name for name, _ in tab_buttons]
            curr_t = seg_type.get()
            curr_i = t_names.index(curr_t) if curr_t in t_names else 0
            next_i = (curr_i + 1) % len(t_names)
            seg_type.set(t_names[next_i])
            modal_focus_state["tab_idx"] = next_i
            modal_focus_state["card_idx"] = 0
            _apply_modal_focus_visuals()
            _fetch_and_render_assets()
            return

        if action == ACTION_SCROLL_UP:
            try:
                scroll_grid._parent_canvas.yview_scroll(-4, "units")
            except Exception:
                pass
            return
        elif action == ACTION_SCROLL_DOWN:
            try:
                scroll_grid._parent_canvas.yview_scroll(4, "units")
            except Exception:
                pass
            return

        if action == ACTION_BACK:
            _close_modal()
            return

        if action == ACTION_QUICK_ACTION:
            switch_modal_animated.toggle()
            _fetch_and_render_assets()
            return

        if action == ACTION_SEARCH:
            _on_local_file_upload()
            return

        if curr_zone == "TABS":
            t_names = [name for name, _ in tab_buttons]
            curr_t = seg_type.get()
            curr_i = t_names.index(curr_t) if curr_t in t_names else 0

            if action == ACTION_LEFT:
                next_i = (curr_i - 1) % len(t_names)
                seg_type.set(t_names[next_i])
                modal_focus_state["tab_idx"] = next_i
                _apply_modal_focus_visuals()
                _fetch_and_render_assets()
            elif action == ACTION_RIGHT:
                if curr_i == len(t_names) - 1:
                    modal_focus_state["zone"] = "CONTROLS"
                    modal_focus_state["control_idx"] = 0
                    _apply_modal_focus_visuals()
                else:
                    next_i = (curr_i + 1) % len(t_names)
                    seg_type.set(t_names[next_i])
                    modal_focus_state["tab_idx"] = next_i
                    _apply_modal_focus_visuals()
                    _fetch_and_render_assets()
            elif action == ACTION_DOWN:
                if num_cards > 0:
                    modal_focus_state["zone"] = "GRID"
                    modal_focus_state["card_idx"] = 0
                else:
                    modal_focus_state["zone"] = "CONTROLS"
                    modal_focus_state["control_idx"] = 0
                _apply_modal_focus_visuals()
            elif action == ACTION_SELECT:
                if num_cards > 0:
                    modal_focus_state["zone"] = "GRID"
                    modal_focus_state["card_idx"] = 0
                    _apply_modal_focus_visuals()
            return

        if curr_zone == "CONTROLS":
            c_i = modal_focus_state["control_idx"]
            if action == ACTION_LEFT:
                if c_i == 0:
                    modal_focus_state["zone"] = "TABS"
                    _apply_modal_focus_visuals()
                else:
                    modal_focus_state["control_idx"] = c_i - 1
                    _apply_modal_focus_visuals()
            elif action == ACTION_RIGHT:
                if c_i < 2:
                    modal_focus_state["control_idx"] = c_i + 1
                    _apply_modal_focus_visuals()
            elif action == ACTION_DOWN:
                if num_cards > 0:
                    modal_focus_state["zone"] = "GRID"
                    modal_focus_state["card_idx"] = 0
                    _apply_modal_focus_visuals()
            elif action == ACTION_UP:
                modal_focus_state["zone"] = "TABS"
                _apply_modal_focus_visuals()
            elif action == ACTION_SELECT:
                if c_i == 0:
                    switch_modal_nsfw.toggle()
                    _fetch_and_render_assets()
                elif c_i == 1:
                    switch_modal_animated.toggle()
                    _fetch_and_render_assets()
                elif c_i == 2:
                    _on_local_file_upload()
            return

        if curr_zone == "GRID":
            cols = 3
            curr_card = modal_focus_state["card_idx"]

            if action == ACTION_UP:
                if curr_card < cols:
                    modal_focus_state["zone"] = "TABS"
                    _apply_modal_focus_visuals()
                else:
                    modal_focus_state["card_idx"] = max(0, curr_card - cols)
                    _apply_modal_focus_visuals()
            elif action == ACTION_DOWN:
                if curr_card + cols < num_cards:
                    modal_focus_state["card_idx"] = curr_card + cols
                    _apply_modal_focus_visuals()
                else:
                    modal_focus_state["card_idx"] = min(num_cards - 1, curr_card + cols)
                    _apply_modal_focus_visuals()
            elif action == ACTION_LEFT:
                if curr_card > 0:
                    modal_focus_state["card_idx"] = curr_card - 1
                    _apply_modal_focus_visuals()
            elif action == ACTION_RIGHT:
                if curr_card < num_cards - 1:
                    modal_focus_state["card_idx"] = curr_card + 1
                    _apply_modal_focus_visuals()
            elif action == ACTION_SELECT:
                if 0 <= curr_card < num_cards:
                    modal_card_widgets[curr_card]["btn"].invoke()
            return

    app.push_modal_controller_handler(_handle_modal_controller)

    modal.bind("<Up>", lambda e: _handle_modal_controller(ACTION_UP) or "break")
    modal.bind("<Down>", lambda e: _handle_modal_controller(ACTION_DOWN) or "break")
    modal.bind("<Left>", lambda e: _handle_modal_controller(ACTION_LEFT) or "break")
    modal.bind("<Right>", lambda e: _handle_modal_controller(ACTION_RIGHT) or "break")
    modal.bind("<Return>", lambda e: _handle_modal_controller(ACTION_SELECT) or "break")
    modal.bind("<Escape>", lambda e: _handle_modal_controller(ACTION_BACK) or "break")
    modal.bind("<F1>", lambda e: _handle_modal_controller(ACTION_PREV_TAB) or "break")
    modal.bind("<F2>", lambda e: _handle_modal_controller(ACTION_NEXT_TAB) or "break")
    modal.bind("<Prior>", lambda e: _handle_modal_controller(ACTION_SCROLL_UP) or "break")
    modal.bind("<Next>", lambda e: _handle_modal_controller(ACTION_SCROLL_DOWN) or "break")
    modal.focus_set()

    def _close_modal():
        app.pop_modal_controller_handler(_handle_modal_controller)
        _cancel_animations()
        modal.destroy()
        app._apply_focus_visuals()

    modal.protocol("WM_DELETE_WINDOW", _close_modal)

    def _get_type_key(tab_name: str) -> str:
        for display_name, key in tab_buttons:
            if display_name == tab_name:
                return key
        return "capsule"

    def _apply_selected_asset(asset_url: str, asset_type: str):
        lbl_modal_status.configure(text=f"Downloading and applying {asset_type}...", text_color="#fbbf24")

        def _apply_thread():
            try:
                success = app.cover_manager.download_and_set_specific_asset(
                    app_id=str(app_id),
                    asset_type=asset_type,
                    url=asset_url,
                    steamgriddb_client=app.steamgriddb_client,
                )
                if success:
                    def _refresh_app_ui():
                        for widget, name, size in app._banner_widgets.get(str(app_id), []):
                            try:
                                new_img = app.cover_manager.get_cover_image(str(app_id), title=name, size=size)
                                widget.configure(image=new_img)
                            except Exception as ex:
                                logger.warning(f"Error updating widget image: {ex}")
                        lbl_modal_status.configure(
                            text=f"✅ Successfully applied {asset_type} artwork!", text_color=COLOR_STATUS_GREEN
                        )
                        app.lbl_status.configure(
                            text=f"✅ Updated {asset_type} artwork for {game_data['name']}.", text_color=COLOR_STATUS_GREEN
                        )
                    app.run_on_main_thread(_refresh_app_ui)
                else:
                    app.run_on_main_thread(
                        lambda: lbl_modal_status.configure(
                            text=f"❌ Failed to decode or save {asset_type}.", text_color="#ff4444"
                        )
                    )
            except Exception as e:
                err_msg = str(e)
                logger.error(f"Error applying asset: {err_msg}", exc_info=True)
                app.run_on_main_thread(
                    lambda err=err_msg: lbl_modal_status.configure(text=f"Error: {err}", text_color="#ff4444")
                )

        threading.Thread(target=_apply_thread, daemon=True).start()

    def _on_local_file_upload():
        chosen = filedialog.askopenfilename(
            parent=modal,
            title=f"Select Local Image for {game_data['name']}",
            filetypes=[("Image Files", "*.png *.jpg *.jpeg *.webp *.bmp"), ("All Files", "*.*")],
        )
        if not chosen:
            return
        chosen_p = Path(chosen)
        try:
            raw_bytes = chosen_p.read_bytes()
            curr_type = _get_type_key(seg_type.get())
            success = app.cover_manager.set_specific_grid_asset(str(app_id), curr_type, raw_bytes)
            if success:
                for widget, name, size in app._banner_widgets.get(str(app_id), []):
                    try:
                        new_img = app.cover_manager.get_cover_image(str(app_id), title=name, size=size)
                        widget.configure(image=new_img)
                    except Exception:
                        pass
                lbl_modal_status.configure(text=f"✅ Applied local image as {curr_type}!", text_color=COLOR_STATUS_GREEN)
                app.lbl_status.configure(text="✅ Updated artwork from local file.", text_color=COLOR_STATUS_GREEN)
        except Exception as e:
            lbl_modal_status.configure(text=f"❌ Error loading local file: {e}", text_color="#ff4444")

    def _fetch_and_render_assets():
        _cancel_animations()
        for widget in scroll_grid.winfo_children():
            widget.destroy()
        loaded_thumb_images.clear()
        modal_card_widgets.clear()
        modal_focus_state["card_idx"] = 0

        curr_type = _get_type_key(seg_type.get())
        is_nsfw = bool(switch_modal_nsfw.get())
        is_animated = bool(switch_modal_animated.get())
        lbl_modal_status.configure(text=f"Fetching {curr_type} artwork...", text_color=COLOR_TEXT_MUTED)

        def _worker():
            found_assets = []

            # 1. Check SteamGridDB if API key present
            if app.steamgriddb_client.has_api_key():
                sgdb_game_id = None
                if app_id.isdigit() and int(app_id) < 2147483647:
                    sgdb_game_id = app.steamgriddb_client.get_game_by_steam_appid(app_id)
                if not sgdb_game_id:
                    search_res = app.steamgriddb_client.search_games(game_data["name"])
                    if search_res:
                        sgdb_game_id = search_res[0].get("id")

                if sgdb_game_id:
                    found_assets = app.steamgriddb_client.get_assets(
                        sgdb_game_id, curr_type, nsfw=is_nsfw, animated=is_animated
                    )

            # 2. Add fallback assets from VNDB and Steam CDN
            fallbacks = app.steamgriddb_client.get_fallback_assets(
                app_id=app_id,
                game_name=game_data["name"],
                asset_type=curr_type,
                vndb_meta=game_data.get("vndb"),
            )
            found_assets.extend(fallbacks)

            rendered_cards = []
            for item in found_assets[:36]:
                is_item_anim = bool(item.get("is_animated") or item.get("types") == "animated")
                if is_animated and is_item_anim and item.get("url"):
                    t_url = item["url"]
                else:
                    t_url = item.get("thumb") or item.get("url")

                try:
                    raw_bytes = app.steamgriddb_client.download_image_bytes(t_url, timeout=7)
                    if not raw_bytes:
                        raw_bytes = app.cover_manager.download_image_bytes(t_url, timeout=7)

                    if raw_bytes:
                        pil_raw = Image.open(io.BytesIO(raw_bytes))
                        if curr_type == "capsule":
                            thumb_size = (180, 270)
                        elif curr_type == "hero":
                            thumb_size = (240, 78)
                        elif curr_type == "logo":
                            thumb_size = (200, 112)
                        elif curr_type == "icon":
                            thumb_size = (80, 80)
                        else:
                            thumb_size = (230, 108)

                        n_frames = getattr(pil_raw, "n_frames", 1)
                        frame_ctk_images = []
                        frame_durations = []

                        if n_frames > 1 and is_animated:
                            for frame in ImageSequence.Iterator(pil_raw):
                                if curr_type == "logo":
                                    f_res = frame.convert("RGBA").resize(thumb_size, Image.Resampling.BICUBIC)
                                else:
                                    f_res = frame.convert("RGB").resize(thumb_size, Image.Resampling.BICUBIC)
                                f_ctk = ctk.CTkImage(light_image=f_res, dark_image=f_res, size=thumb_size)
                                frame_ctk_images.append(f_ctk)
                                duration = frame.info.get("duration", 100)
                                frame_durations.append(max(duration, 30))
                            item["is_animated"] = True
                        else:
                            if curr_type == "logo":
                                pil_resized = pil_raw.convert("RGBA").resize(thumb_size, Image.Resampling.BICUBIC)
                            else:
                                pil_resized = pil_raw.convert("RGB").resize(thumb_size, Image.Resampling.BICUBIC)
                            f_ctk = ctk.CTkImage(light_image=pil_resized, dark_image=pil_resized, size=thumb_size)
                            frame_ctk_images.append(f_ctk)
                            frame_durations.append(1000)
                            item["is_animated"] = False

                        rendered_cards.append((item, frame_ctk_images, frame_durations))
                except Exception as ex:
                    logger.warning(f"Error loading thumb from {t_url}: {ex}")

            def _populate():
                if not rendered_cards:
                    if not app.steamgriddb_client.has_api_key():
                        no_key_frame = ctk.CTkFrame(scroll_grid, fg_color="transparent")
                        no_key_frame.pack(pady=40)
                        ctk.CTkLabel(
                            no_key_frame,
                            text="No artwork found for this category.\nTip: Add a free SteamGridDB API key in Settings to unlock thousands of community assets!",
                            font=ctk.CTkFont(size=13),
                            text_color=COLOR_TEXT_MUTED,
                            justify="center",
                        ).pack(pady=(0, 10))
                        ctk.CTkButton(
                            no_key_frame,
                            text="🔑 Open Settings / Get API Key",
                            fg_color=COLOR_PRIMARY_BLUE,
                            hover_color=COLOR_PRIMARY_HOVER,
                            command=lambda: (_close_modal(), app.tabview.set("Settings")),
                        ).pack()
                    else:
                        ctk.CTkLabel(
                            scroll_grid,
                            text="No artwork found on SteamGridDB for this category.",
                            font=ctk.CTkFont(size=13),
                            text_color=COLOR_TEXT_MUTED,
                        ).pack(pady=40)
                    lbl_modal_status.configure(text="No items found.", text_color=COLOR_TEXT_MUTED)
                    _apply_modal_focus_visuals()
                    return

                cols = 3 if curr_type in ("capsule", "wide", "hero", "logo") else 4
                for idx, (asset_data, frames, durations) in enumerate(rendered_cards):
                    for f in frames:
                        loaded_thumb_images.append(f)
                    row = idx // cols
                    col = idx % cols

                    card = ctk.CTkFrame(
                        scroll_grid,
                        fg_color="#121212",
                        border_width=1,
                        border_color=COLOR_SURFACE_BORDER,
                        corner_radius=8,
                    )
                    card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")

                    lbl_img = ctk.CTkLabel(card, text="", image=frames[0])
                    lbl_img.pack(padx=8, pady=(8, 4))

                    if len(frames) > 1:
                        def _make_cycle(w=lbl_img, f_list=frames, d_list=durations):
                            def _step(frame_i=0):
                                try:
                                    if w.winfo_exists():
                                        w.configure(image=f_list[frame_i])
                                        next_i = (frame_i + 1) % len(f_list)
                                        tid = modal.after(d_list[frame_i], lambda: _step(next_i))
                                        active_animation_timers.append(tid)
                                except Exception:
                                    pass
                            _step(0)
                        _make_cycle()

                    badge = " ✨ ANIMATED" if asset_data.get("is_animated") else ""
                    source_text = f"{asset_data.get('source', 'Community')} • {asset_data.get('author', 'Artist')}{badge}"
                    text_color = "#c084fc" if asset_data.get("is_animated") else "#71717a"
                    ctk.CTkLabel(card, text=source_text, font=ctk.CTkFont(size=10), text_color=text_color).pack(
                        padx=6, pady=(0, 4)
                    )

                    btn_pick = ctk.CTkButton(
                        card,
                        text="Apply This Art",
                        font=ctk.CTkFont(size=11, weight="bold"),
                        height=26,
                        fg_color=COLOR_PRIMARY_BLUE,
                        hover_color=COLOR_PRIMARY_HOVER,
                        command=lambda u=asset_data["url"], t=curr_type: _apply_selected_asset(u, t),
                    )
                    btn_pick.pack(fill="x", padx=8, pady=(0, 8))

                    modal_card_widgets.append({"card": card, "btn": btn_pick, "url": asset_data["url"]})

                lbl_modal_status.configure(
                    text=f"Found {len(rendered_cards)} artwork choices. Click 'Apply This Art' or press (A) to select.",
                    text_color=COLOR_STATUS_GREEN,
                )
                _apply_modal_focus_visuals()

            app.run_on_main_thread(_populate)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_category_changed(val):
        _fetch_and_render_assets()

    _fetch_and_render_assets()
