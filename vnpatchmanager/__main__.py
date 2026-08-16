"""Executable entrypoint for python -m vnpatchmanager"""
import sys

from .gui import VNPatchManagerApp

try:
    import customtkinter as ctk
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")
except ImportError:
    pass


def main():
    app = VNPatchManagerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
