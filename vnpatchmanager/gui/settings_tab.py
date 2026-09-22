"""
Settings tab UI, connection mode selection, SMB credentials, and SteamGridDB configuration.
"""

import logging
import webbrowser
from pathlib import Path
from tkinter import filedialog
import customtkinter as ctk

from ..version import APP_NAME, APP_VERSION
from .constants import (
    MODE_LOCAL_DISPLAY,
    MODE_SMB_DISPLAY,
    COLOR_PRIMARY_BLUE,
    COLOR_PRIMARY_HOVER,
    COLOR_TEXT_WHITE,
)

logger = logging.getLogger(__name__)


class SettingsTabMixin:
    """Provides the settings tab UI, storage configuration, and persistence."""

    def _browse_local_path(self):
        """Opens a folder picker to choose local patch repository directory."""
        curr_path = self.entry_local_path.get().strip() or str(Path.home())
        selected = filedialog.askdirectory(
            parent=self,
            title="Select Local Patch Folder",
            initialdir=curr_path,
        )
        if selected:
            self.entry_local_path.delete(0, "end")
            self.entry_local_path.insert(0, selected)

    def _setup_settings_tab(self):
        """Constructs settings tab layout and widgets."""
        self.tab_settings.grid_columnconfigure(0, weight=1)

        # Connection Mode Header Frame (Row 0)
        mode_header = ctk.CTkFrame(self.tab_settings, fg_color="transparent")
        mode_header.grid(row=0, column=0, padx=12, pady=(12, 6), sticky="w")

        ctk.CTkLabel(
            mode_header,
            text="Connection Mode:",
            font=ctk.CTkFont(weight="bold"),
            text_color=COLOR_TEXT_WHITE,
        ).pack(side="left", padx=(0, 12))

        curr_mode = self.config_manager.config.get("mode", "local")
        initial_mode_display = MODE_SMB_DISPLAY if curr_mode == "smb" else MODE_LOCAL_DISPLAY
        self.var_mode = ctk.StringVar(value=initial_mode_display)
        self.opt_mode = ctk.CTkSegmentedButton(
            mode_header,
            values=[MODE_LOCAL_DISPLAY, MODE_SMB_DISPLAY],
            variable=self.var_mode,
            command=self._toggle_settings_fields,
            fg_color="#121212",
            selected_color=COLOR_PRIMARY_BLUE,
            selected_hover_color=COLOR_PRIMARY_HOVER,
            unselected_hover_color="#1e1e1e",
            text_color=COLOR_TEXT_WHITE,
        )
        self.opt_mode.pack(side="left")

        # Dynamic Content Container (Row 1) - unified slot
        self.frame_mode_container = ctk.CTkFrame(self.tab_settings, fg_color="transparent")
        self.frame_mode_container.grid(row=1, column=0, padx=12, pady=4, sticky="nsew")
        self.frame_mode_container.grid_columnconfigure(0, weight=1)

        # Local Settings Frame
        self.frame_local = ctk.CTkFrame(
            self.frame_mode_container,
            fg_color="#121212",
            border_width=1,
            border_color="#27272a",
            corner_radius=10,
        )
        self.frame_local.grid(row=0, column=0, sticky="nsew")
        self.frame_local.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self.frame_local,
            text="Patch Folder Path:",
            font=ctk.CTkFont(weight="bold"),
            text_color=COLOR_TEXT_WHITE,
        ).grid(row=0, column=0, padx=12, pady=12, sticky="w")

        self.entry_local_path = ctk.CTkEntry(
            self.frame_local,
            placeholder_text="/home/deck/Games/Patches or MicroSD path",
            fg_color="#18181b",
            border_color="#27272a",
            border_width=1,
            text_color=COLOR_TEXT_WHITE,
        )
        self.entry_local_path.insert(0, self.config_manager.config.get("local_path", ""))
        self.entry_local_path.grid(row=0, column=1, padx=(0, 8), pady=12, sticky="ew")

        btn_browse = ctk.CTkButton(
            self.frame_local,
            text="📂 Browse...",
            width=90,
            fg_color="#27272a",
            hover_color="#3f3f46",
            command=self._browse_local_path,
        )
        btn_browse.grid(row=0, column=2, padx=(0, 12), pady=12)

        # SMB Settings Frame
        self.frame_smb = ctk.CTkFrame(
            self.frame_mode_container,
            fg_color="#121212",
            border_width=1,
            border_color="#27272a",
            corner_radius=10,
        )
        self.frame_smb.grid(row=0, column=0, sticky="nsew")
        self.frame_smb.grid_columnconfigure(1, weight=1)

        smb_fields = [
            ("Server Address / IP:", "smb_server", "e.g. 192.168.1.100 or truenas.local"),
            ("Share Name:", "smb_share", "e.g. Patches or Games"),
            ("Subfolder Path (Optional):", "smb_path", "e.g. Visual Novel Patches/ (leave blank for root)"),
            ("Username (Optional):", "smb_username", "Account or guest username"),
            ("Password (Optional):", "smb_password", "Account password"),
        ]

        self.smb_entries = {}
        for idx, (label_text, key, placeholder) in enumerate(smb_fields):
            ctk.CTkLabel(self.frame_smb, text=label_text, text_color=COLOR_TEXT_WHITE).grid(
                row=idx, column=0, padx=12, pady=6, sticky="w"
            )
            entry = ctk.CTkEntry(
                self.frame_smb,
                placeholder_text=placeholder,
                show="*" if "password" in key else "",
                fg_color="#18181b",
                border_color="#27272a",
                border_width=1,
                text_color=COLOR_TEXT_WHITE,
            )
            entry.insert(0, self.config_manager.config.get(key, ""))
            entry.grid(row=idx, column=1, padx=12, pady=6, sticky="ew")
            self.smb_entries[key] = entry

        # SteamGridDB Integration Card
        frame_sgdb = ctk.CTkFrame(
            self.tab_settings,
            fg_color="#121212",
            border_width=1,
            border_color="#27272a",
            corner_radius=10,
        )
        frame_sgdb.grid(row=2, column=0, padx=20, pady=(12, 0), sticky="ew")
        frame_sgdb.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            frame_sgdb,
            text="🎨 SteamGridDB Community Integration (Optional):",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLOR_TEXT_WHITE,
        ).grid(row=0, column=0, columnspan=3, padx=12, pady=(10, 4), sticky="w")

        ctk.CTkLabel(frame_sgdb, text="API Key:", text_color=COLOR_TEXT_WHITE).grid(
            row=1, column=0, padx=12, pady=(0, 10), sticky="w"
        )

        self.entry_sgdb_key = ctk.CTkEntry(
            frame_sgdb,
            placeholder_text="Paste your free SteamGridDB API key...",
            fg_color="#18181b",
            border_color="#27272a",
            border_width=1,
            text_color=COLOR_TEXT_WHITE,
        )
        self.entry_sgdb_key.insert(0, self.config_manager.config.get("steamgriddb_api_key", ""))
        self.entry_sgdb_key.grid(row=1, column=1, padx=(0, 8), pady=(0, 10), sticky="ew")

        btn_get_key = ctk.CTkButton(
            frame_sgdb,
            text="🔑 Get Key",
            width=90,
            fg_color="#27272a",
            hover_color="#3f3f46",
            command=lambda: webbrowser.open("https://www.steamgriddb.com/profile/preferences/api"),
        )
        btn_get_key.grid(row=1, column=2, padx=(0, 12), pady=(0, 10))

        self.switch_sgdb_nsfw = ctk.CTkSwitch(
            frame_sgdb,
            text="🔞 Allow 18+ / NSFW Community Artwork from SteamGridDB",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_WHITE,
            progress_color="#ec4899",
        )
        if self.config_manager.config.get("steamgriddb_nsfw", True):
            self.switch_sgdb_nsfw.select()
        else:
            self.switch_sgdb_nsfw.deselect()
        self.switch_sgdb_nsfw.grid(row=2, column=0, columnspan=3, padx=12, pady=(0, 6), sticky="w")

        self.switch_sgdb_animated = ctk.CTkSwitch(
            frame_sgdb,
            text="✨ Allow Animated Community Artwork from SteamGridDB",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_WHITE,
            progress_color="#a855f7",
        )
        if self.config_manager.config.get("steamgriddb_animated", True):
            self.switch_sgdb_animated.select()
        else:
            self.switch_sgdb_animated.deselect()
        self.switch_sgdb_animated.grid(row=3, column=0, columnspan=3, padx=12, pady=(0, 12), sticky="w")

        # Stable Footer Container (Row 3)
        frame_actions = ctk.CTkFrame(self.tab_settings, fg_color="transparent")
        frame_actions.grid(row=3, column=0, pady=(20, 10))

        # Save Button
        self.btn_save = ctk.CTkButton(
            frame_actions,
            text="Save Settings & Refresh",
            font=ctk.CTkFont(weight="bold"),
            height=34,
            fg_color=COLOR_PRIMARY_BLUE,
            hover_color=COLOR_PRIMARY_HOVER,
            command=self.save_settings,
        )
        self.btn_save.pack(pady=(0, 10))

        # Version Info Label
        self.lbl_version = ctk.CTkLabel(
            frame_actions,
            text=f"{APP_NAME} v{APP_VERSION}",
            font=ctk.CTkFont(size=12),
            text_color="#71717a",
        )
        self.lbl_version.pack()

        self._toggle_settings_fields(self.var_mode.get())

    def _toggle_settings_fields(self, mode):
        """Show/Hide frames based on selected mode."""
        if mode in ("local", MODE_LOCAL_DISPLAY):
            self.frame_local.grid()
            self.frame_smb.grid_remove()
        else:
            self.frame_local.grid_remove()
            self.frame_smb.grid()

    def save_settings(self):
        """Commits GUI inputs to the config manager."""
        mode_val = self.var_mode.get()
        self.config_manager.config["mode"] = "smb" if mode_val in ("smb", MODE_SMB_DISPLAY) else "local"
        self.config_manager.config["local_path"] = self.entry_local_path.get()
        self.config_manager.config["steamgriddb_api_key"] = self.entry_sgdb_key.get().strip()
        self.config_manager.config["steamgriddb_nsfw"] = bool(self.switch_sgdb_nsfw.get())
        self.config_manager.config["steamgriddb_animated"] = bool(self.switch_sgdb_animated.get())
        self.steamgriddb_client.set_api_key(self.entry_sgdb_key.get().strip())
        for key, entry in self.smb_entries.items():
            self.config_manager.config[key] = entry.get()

        self.config_manager.save_config()
        self.refresh_data()
