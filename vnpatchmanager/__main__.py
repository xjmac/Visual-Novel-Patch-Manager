"""Executable entrypoint for python -m vnpatchmanager"""
import sys
from .gui import VNPatchManagerApp
from .cli import main as cli_main

try:
    import customtkinter as ctk
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")
except ImportError:
    pass


def main():
    # If CLI flags were provided, delegate to argument parser
    cli_flags = {"-h", "--help", "-V", "--version", "-l", "--list", "--sync-vndb", "--export-licenses", "--output-file", "-o", "-d", "--debug"}
    if any(arg in cli_flags for arg in sys.argv[1:]):
        cli_main()
        return

    app = VNPatchManagerApp()
    app.mainloop()


if __name__ == "__main__":
    main()


