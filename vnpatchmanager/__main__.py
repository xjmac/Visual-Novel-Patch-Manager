"""Executable entrypoint for python -m vnpatchmanager"""
import sys
from .cli import main as cli_main


def __getattr__(name: str):
    if name == "VNPatchManagerApp":
        from .gui import VNPatchManagerApp
        return VNPatchManagerApp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def main():
    # If arguments were provided, delegate directly to CLI router
    if len(sys.argv) > 1:
        cli_main()
        return

    app_cls = getattr(sys.modules[__name__], "VNPatchManagerApp")
    app = app_cls()
    app.mainloop()


if __name__ == "__main__":
    main()



