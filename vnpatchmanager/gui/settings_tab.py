"""
Settings sheet: patch folder, network share, and artwork.
"""

import logging
import webbrowser
from pathlib import Path
from tkinter import filedialog
import customtkinter as ctk

from ..version import APP_NAME, APP_VERSION
from .constants import MODE_LOCAL_DISPLAY, MODE_SMB_DISPLAY
from .theme import (
    COLOR_BORDER_2,
    COLOR_ELEVATION_1,
    COLOR_ELEVATION_2,
    COLOR_PRIMARY_BLUE,
    COLOR_PRIMARY_HOVER,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    MIN_TOUCH_TARGET,
)

logger = logging.getLogger(__name__)


class SettingsTabMixin:
    """Settings form, storage configuration, and persistence."""

    def _browse_local_path(self):
        """Opens a folder picker for the local patch directory."""
        curr_path = self.entry_local_path.get().strip() or str(Path.home())
        selected = filedialog.askdirectory(
            parent=self,
            title="Select Local Patch Folder",
            initialdir=curr_path,
        )
        if selected:
            self.entry_local_path.delete(0, "end")
            self.entry_local_path.insert(0, selected)

    def _choose_patch_folder(self):
        """Empty-library action: pick a folder, save it, and scan."""
        self._browse_local_path()
        if self.entry_local_path.get().strip():
            self.save_settings()

    def _setup_settings_tab(self):
        """Builds the settings form inside settings_host."""
        host = self.settings_host
        host.configure(fg_color=COLOR_ELEVATION_1)
        host.grid_columnconfigure(0, weight=1)
        host.grid_rowconfigure(1, weight=1)

        bar = ctk.CTkFrame(host, fg_color=COLOR_ELEVATION_1, height=56, corner_radius=0)
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
            command=self._close_settings,
        ).grid(row=0, column=0, padx=8, pady=6)
        ctk.CTkLabel(
            bar,
            text="Settings",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        ).grid(row=0, column=1, sticky="w")

        body = ctk.CTkScrollableFrame(host, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(body, text="Connection", text_color=COLOR_TEXT_SECONDARY, font=ctk.CTkFont(size=13), anchor="w").grid(
            row=0, column=0, sticky="w", padx=16, pady=(12, 4)
        )
        chips = ctk.CTkFrame(body, fg_color="transparent")
        chips.grid(row=1, column=0, sticky="w", padx=16)
        curr_mode = self.config_manager.config.get("mode", "local")
        self.var_mode = ctk.StringVar(value="smb" if curr_mode == "smb" else "local")
        self._chip_local = ctk.CTkButton(
            chips,
            text=MODE_LOCAL_DISPLAY,
            height=MIN_TOUCH_TARGET,
            width=100,
            command=lambda: self._set_connection("local"),
        )
        self._chip_local.pack(side="left", padx=(0, 8))
        self._chip_network = ctk.CTkButton(
            chips,
            text=MODE_SMB_DISPLAY,
            height=MIN_TOUCH_TARGET,
            width=120,
            command=lambda: self._set_connection("smb"),
        )
        self._chip_network.pack(side="left")

        self.frame_local = ctk.CTkFrame(body, fg_color="transparent")
        self.frame_local.grid(row=2, column=0, sticky="ew", padx=16, pady=(16, 0))
        self.frame_local.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.frame_local, text="Patch folder", font=ctk.CTkFont(size=15, weight="bold"), text_color=COLOR_TEXT_PRIMARY, anchor="w").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            self.frame_local,
            text="Games are matched against the patches in this folder.",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(2, 8))
        ctk.CTkLabel(self.frame_local, text="Folder", font=ctk.CTkFont(size=13), text_color=COLOR_TEXT_SECONDARY, anchor="w").grid(row=2, column=0, sticky="w")
        path_row = ctk.CTkFrame(self.frame_local, fg_color="transparent")
        path_row.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        path_row.grid_columnconfigure(0, weight=1)
        self.entry_local_path = ctk.CTkEntry(
            path_row,
            height=MIN_TOUCH_TARGET,
            placeholder_text="/home/deck/Games/Patches",
            fg_color=COLOR_ELEVATION_2,
            border_color=COLOR_BORDER_2,
            text_color=COLOR_TEXT_PRIMARY,
        )
        self.entry_local_path.insert(0, self.config_manager.config.get("local_path", ""))
        self.entry_local_path.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._btn_browse = ctk.CTkButton(
            path_row,
            text="Browse",
            height=MIN_TOUCH_TARGET,
            width=100,
            fg_color=COLOR_ELEVATION_2,
            hover_color=COLOR_ELEVATION_1,
            border_width=1,
            border_color=COLOR_BORDER_2,
            command=self._browse_local_path,
        )
        self._btn_browse.grid(row=0, column=1)

        self.frame_smb = ctk.CTkFrame(body, fg_color="transparent")
        self.frame_smb.grid(row=2, column=0, sticky="ew", padx=16, pady=(16, 0))
        self.frame_smb.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.frame_smb, text="Network share", font=ctk.CTkFont(size=15, weight="bold"), text_color=COLOR_TEXT_PRIMARY, anchor="w").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            self.frame_smb,
            text="Read patches from a share on the local network.",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(2, 8))
        smb_fields = [
            ("Server", "smb_server", "192.168.1.20"),
            ("Share", "smb_share", "Patches"),
            ("Subfolder", "smb_path", "Optional"),
            ("Username", "smb_username", "Optional"),
            ("Password", "smb_password", ""),
        ]
        self.smb_entries = {}
        for idx, (label, key, placeholder) in enumerate(smb_fields):
            ctk.CTkLabel(self.frame_smb, text=label, font=ctk.CTkFont(size=13), text_color=COLOR_TEXT_SECONDARY, anchor="w").grid(
                row=2 + idx * 2, column=0, sticky="w", pady=(6, 0)
            )
            entry = ctk.CTkEntry(
                self.frame_smb,
                height=MIN_TOUCH_TARGET,
                placeholder_text=placeholder,
                show="*" if key == "smb_password" else "",
                fg_color=COLOR_ELEVATION_2,
                border_color=COLOR_BORDER_2,
                text_color=COLOR_TEXT_PRIMARY,
            )
            entry.insert(0, self.config_manager.config.get(key, ""))
            entry.grid(row=3 + idx * 2, column=0, sticky="ew", pady=(4, 0))
            self.smb_entries[key] = entry

        art = ctk.CTkFrame(body, fg_color="transparent")
        art.grid(row=3, column=0, sticky="ew", padx=16, pady=(16, 8))
        art.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(art, text="Artwork", font=ctk.CTkFont(size=15, weight="bold"), text_color=COLOR_TEXT_PRIMARY, anchor="w").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            art,
            text="Optional covers from SteamGridDB. The library works without a key.",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
            wraplength=420,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(2, 8))
        ctk.CTkLabel(art, text="API key", font=ctk.CTkFont(size=13), text_color=COLOR_TEXT_SECONDARY, anchor="w").grid(row=2, column=0, sticky="w")
        key_row = ctk.CTkFrame(art, fg_color="transparent")
        key_row.grid(row=3, column=0, sticky="ew", pady=(4, 8))
        key_row.grid_columnconfigure(0, weight=1)
        self.entry_sgdb_key = ctk.CTkEntry(
            key_row,
            height=MIN_TOUCH_TARGET,
            placeholder_text="Paste a key",
            fg_color=COLOR_ELEVATION_2,
            border_color=COLOR_BORDER_2,
            text_color=COLOR_TEXT_PRIMARY,
        )
        self.entry_sgdb_key.insert(0, self.config_manager.config.get("steamgriddb_api_key", ""))
        self.entry_sgdb_key.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._btn_get_key = ctk.CTkButton(
            key_row,
            text="Get key",
            height=MIN_TOUCH_TARGET,
            width=90,
            fg_color="transparent",
            text_color=COLOR_PRIMARY_BLUE,
            hover_color=COLOR_ELEVATION_2,
            command=lambda: webbrowser.open("https://www.steamgriddb.com/profile/preferences/api"),
        )
        self._btn_get_key.grid(row=0, column=1)

        self.switch_sgdb_nsfw = ctk.CTkSwitch(
            art,
            text="Include adult artwork",
            font=ctk.CTkFont(size=15),
            text_color=COLOR_TEXT_PRIMARY,
            progress_color=COLOR_PRIMARY_BLUE,
        )
        if self.config_manager.config.get("steamgriddb_nsfw", True):
            self.switch_sgdb_nsfw.select()
        else:
            self.switch_sgdb_nsfw.deselect()
        self.switch_sgdb_nsfw.grid(row=4, column=0, sticky="w", pady=(4, 0))
        ctk.CTkLabel(art, text="Community artwork marked as adult.", font=ctk.CTkFont(size=12), text_color=COLOR_TEXT_MUTED, anchor="w").grid(
            row=5, column=0, sticky="w"
        )
        self.switch_sgdb_animated = ctk.CTkSwitch(
            art,
            text="Include animated artwork",
            font=ctk.CTkFont(size=15),
            text_color=COLOR_TEXT_PRIMARY,
            progress_color=COLOR_PRIMARY_BLUE,
        )
        if self.config_manager.config.get("steamgriddb_animated", True):
            self.switch_sgdb_animated.select()
        else:
            self.switch_sgdb_animated.deselect()
        self.switch_sgdb_animated.grid(row=6, column=0, sticky="w", pady=(8, 0))
        ctk.CTkLabel(art, text="Animated banners and icons.", font=ctk.CTkFont(size=12), text_color=COLOR_TEXT_MUTED, anchor="w").grid(
            row=7, column=0, sticky="w", pady=(0, 8)
        )

        foot = ctk.CTkFrame(host, fg_color=COLOR_ELEVATION_1, corner_radius=0)
        foot.grid(row=2, column=0, sticky="ew")
        foot.grid_columnconfigure(0, weight=1)
        self.lbl_version = ctk.CTkLabel(
            foot,
            text=f"{APP_NAME} v{APP_VERSION}",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        )
        self.lbl_version.grid(row=0, column=0, sticky="w", padx=16, pady=(8, 4))
        self.btn_save = ctk.CTkButton(
            foot,
            text="Save",
            height=48,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color=COLOR_PRIMARY_BLUE,
            hover_color=COLOR_PRIMARY_HOVER,
            command=self.save_settings,
        )
        self.btn_save.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))
        self._toggle_settings_fields(self.var_mode.get())
        self._paint_connection_chips()

    def _set_connection(self, mode: str):
        self.var_mode.set("smb" if mode == "smb" else "local")
        self._toggle_settings_fields(self.var_mode.get())
        self._paint_connection_chips()

    def _paint_connection_chips(self):
        smb = self.var_mode.get() in ("smb", MODE_SMB_DISPLAY, "Network")
        self._chip_local.configure(
            fg_color=COLOR_ELEVATION_2 if smb else COLOR_PRIMARY_BLUE,
            text_color=COLOR_TEXT_PRIMARY,
        )
        self._chip_network.configure(
            fg_color=COLOR_PRIMARY_BLUE if smb else COLOR_ELEVATION_2,
            text_color=COLOR_TEXT_PRIMARY,
        )

    def _toggle_settings_fields(self, mode):
        """Show the folder fields or the share fields."""
        if mode in ("local", MODE_LOCAL_DISPLAY, "Local"):
            self.frame_local.grid()
            self.frame_smb.grid_remove()
        else:
            self.frame_local.grid_remove()
            self.frame_smb.grid()
        if hasattr(self, "_chip_local"):
            self._paint_connection_chips()

    def _settings_targets(self):
        items = [self._chip_local, self._chip_network]
        if self.var_mode.get() in ("local", MODE_LOCAL_DISPLAY, "Local"):
            items.extend([self.entry_local_path, self._btn_browse])
        else:
            items.extend(self.smb_entries[key] for key in ("smb_server", "smb_share", "smb_path", "smb_username", "smb_password"))
        items.extend([
            self.entry_sgdb_key,
            self._btn_get_key,
            self.switch_sgdb_nsfw,
            self.switch_sgdb_animated,
            self.btn_save,
        ])
        return items

    def save_settings(self):
        """Commits GUI inputs to the config manager and refreshes the library."""
        mode_val = self.var_mode.get()
        self.config_manager.config["mode"] = "smb" if mode_val in ("smb", MODE_SMB_DISPLAY, "Network") else "local"
        self.config_manager.config["local_path"] = self.entry_local_path.get()
        self.config_manager.config["steamgriddb_api_key"] = self.entry_sgdb_key.get().strip()
        self.config_manager.config["steamgriddb_nsfw"] = bool(self.switch_sgdb_nsfw.get())
        self.config_manager.config["steamgriddb_animated"] = bool(self.switch_sgdb_animated.get())
        self.steamgriddb_client.set_api_key(self.entry_sgdb_key.get().strip())
        for key, entry in self.smb_entries.items():
            self.config_manager.config[key] = entry.get()
        self.config_manager.save_config()
        self.refresh_data()
