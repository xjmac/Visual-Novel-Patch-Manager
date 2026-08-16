#!/usr/bin/env python3
"""
Visual Novel Patch Manager (VNPM)
Automated visual novel patch manager for Linux and Steam Deck.
"""

import argparse
import logging
import os
import re
import sys
from pathlib import Path

VERSION = "2.0.0"


def setup_logging(debug: bool = False):
    """Configures root logger with appropriate formatting and log level."""
    level = logging.DEBUG if debug else logging.INFO
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(level=level, format=log_format, datefmt="%H:%M:%S")


def cmd_list_games(args):
    """Scans and prints detected visual novels in the terminal."""
    from vnpatchmanager.steam_scanner import SteamScanner
    from vnpatchmanager.vndb_scanner import VNDBScanner
    from vnpatchmanager.config_manager import ConfigManager
    from vnpatchmanager.patch_repository import PatchRepository
    from vnpatchmanager.patch_execution import PatchExecutionEngine

    cm = ConfigManager()
    repo = PatchRepository(cm)
    repo.refresh_patches()

    scanner = SteamScanner()
    owned_games = scanner.get_owned_games()

    vndb = VNDBScanner()
    cached_vndb = vndb.get_cached_vns()

    print(f"\n--- Visual Novel Library Scan ({len(owned_games)} Steam games examined) ---")
    matched = 0
    for app_id, gdata in sorted(owned_games.items(), key=lambda x: x[1].get("name", "").lower()):
        vn_info = cached_vndb.get(app_id, {})
        has_repo_patch = app_id in repo.available_patches
        has_vndb_18 = vn_info.get("has_18plus_en_patch", False)

        if has_repo_patch or has_vndb_18 or vn_info.get("is_vn"):
            matched += 1
            is_installed = bool(gdata.get("is_installed", False)) and bool(gdata.get("path"))
            is_patched = is_installed and PatchExecutionEngine.get_patch_status(gdata["path"], repo.available_patches.get(app_id), vn_info)

            status_tags = []
            if is_patched:
                status_tags.append("[Patched]")
            elif has_repo_patch:
                status_tags.append("[Patch Ready]")
            elif has_vndb_18:
                status_tags.append("[18+ on VNDB]")

            if not is_installed:
                status_tags.append("[Uninstalled]")

            rating_str = f" ★{vn_info['rating']:.1f}" if vn_info.get("rating") else ""
            status_display = " ".join(status_tags) if status_tags else "[Vanilla]"
            name = vn_info.get("vn_title") or gdata.get("name", f"App #{app_id}")
            print(f"  {app_id:>8} | {status_display:<24} | {name}{rating_str}")

    print(f"\nTotal visual novels found: {matched}\n")


def cmd_export_licenses(args):
    """Extracts AppIDs from a console dump and exports translated game names."""
    from vnpatchmanager.steam_scanner import SteamScanner

    input_path = Path(args.input_file or "raw_licenses.txt")
    output_path = Path(args.output_file or "my_steam_games.txt")

    if not input_path.exists():
        print(f"Error: '{input_path}' not found!")
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8", errors="ignore") as f:
        raw_content = f.read()

    found_ids = set(re.findall(r"\b\d{3,7}\b", raw_content))
    if not found_ids:
        print(f"Error: Could not extract any AppIDs from '{input_path}'.")
        sys.exit(1)

    print(f"Extracted {len(found_ids)} AppIDs from '{input_path}'. Resolving via local Steam cache...")
    owned_games = SteamScanner.get_owned_games()

    resolved = []
    for app_id in found_ids:
        if app_id in owned_games:
            resolved.append(owned_games[app_id]["name"])

    if resolved:
        resolved = sorted(list(set(resolved)))
        with open(output_path, "w", encoding="utf-8") as out_f:
            for game in resolved:
                out_f.write(f"{game}\n")
        print(f"Success! Exported {len(resolved)} games to '{output_path}'.")
    else:
        print("Could not resolve game names from local cache. Run Steam at least once to populate cache.")


def cmd_sync_vndb(args):
    """Force-refreshes the local VNDB database snapshot from query.vndb.org."""
    from vnpatchmanager.vndb_scanner import VNDBScanner

    print("Syncing latest VNDB visual novel index (this may take 2-4 seconds)...")
    vndb = VNDBScanner()
    success = vndb.sync_vndb_snapshot(force=True)
    if success:
        print("VNDB snapshot sync completed successfully!")
    else:
        print("VNDB sync failed or was unavailable. Bundled database remains active.")


def main():
    parser = argparse.ArgumentParser(
        prog="vnpm",
        description=f"Visual Novel Patch Manager (VNPM) v{VERSION} - Linux & Steam Deck"
    )
    parser.add_argument("--version", "-V", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("--debug", "-d", action="store_true", help="Enable verbose debug logging")
    parser.add_argument("--list", "-l", action="store_true", help="List detected visual novels and patch statuses (headless)")
    parser.add_argument("--sync-vndb", action="store_true", help="Force-sync the VNDB online database snapshot")
    parser.add_argument("--export-licenses", nargs="?", const="raw_licenses.txt", metavar="FILE", help="Extract AppIDs from raw_licenses.txt and export names")
    parser.add_argument("--output-file", "-o", metavar="FILE", help="Output file for --export-licenses (default: my_steam_games.txt)")

    args = parser.parse_args()
    setup_logging(args.debug)

    if args.list:
        cmd_list_games(args)
    elif args.sync_vndb:
        cmd_sync_vndb(args)
    elif args.export_licenses:
        args.input_file = args.export_licenses
        cmd_export_licenses(args)
    else:
        # Default mode: launch GUI
        try:
            import customtkinter as ctk
            ctk.set_appearance_mode("Dark")
            ctk.set_default_color_theme("blue")
        except ImportError as e:
            print(f"Error: Could not launch GUI ({e}).")
            if "_tkinter" in str(e) or "tkinter" in str(e):
                print("Notice: System Tkinter support is missing. Make sure python-tk / tk is installed.")
            else:
                print("Make sure dependencies are installed: pip install -r requirements.txt")
            sys.exit(1)

        from vnpatchmanager.gui import VNPatchManagerApp
        app = VNPatchManagerApp()
        app.mainloop()


if __name__ == "__main__":
    main()
