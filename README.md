# 🌸 Visual Novel Patch Manager (VNPM)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20Steam%20Deck-informational.svg)]()

A lightweight, automated Visual Novel patch manager designed to streamline patch installation, backups, and VNDB metadata syncing on **Linux** and **Steam Deck**.

---

## ✨ Features

- **🎮 Automatic Steam Library Detection**
  - Scans Steam libraries across default paths, secondary storage, and microSD cards.
  - Full support for both native Linux Steam and Flatpak Steam installations.
  - Automatically identifies installed Visual Novels using `appmanifest` files and internal database matching.

- **📖 VNDB Integration & Cover Art**
  - Matches Steam App IDs against VNDB (Visual Novel Database) metadata.
  - Automatically downloads and caches high-quality cover art and game information locally.

- **📁 Flexible Patch Sources (Local & SMB / Network Shares)**
  - Scan local directories or SMB network storage for patches.
  - Recursive search automatically pairs patch files/archives with your installed games.
  - Supports standard archive formats (`.zip`, `.rar`, `.7z`, `.tar`, `.tar.gz`, etc.).

- **⚙️ Multi-Mode Patch Installer**
  - Direct file extraction & replacement for data/archive patches.
  - Wine/Proton execution support for Windows `.exe` patch installers.

- **🛡️ Built-in Backup & Rollback System**
  - Applies a patch to a full clone of the install, writes the backup only after every action succeeds, then swaps that checked tree into place.
  - Restore builds a checked tree beside the install and swaps it in only after the staged hashes match.
  - Keeps live saves: any path under `save`, `saves`, or `savedata`, and any `*.save` file, is copied from the running install and is left in place across rollback.
  - Can ask Steam to validate the game's files when a local restore is not enough.

- **🎯 Non-Steam Shortcuts**
  - The installer adds VN Patch Manager itself as a non-Steam game, with portrait, wide capsule, hero, and icon art.
  - The app can also register a visual novel in Steam's `shortcuts.vdf`. The update is written to a temporary file and moved into place with `os.replace`. Steam rewrites `shortcuts.vdf` when it exits.

- **📱 Steam Deck & Touch-Friendly UI**
  - Modern, responsive dark UI built with CustomTkinter, including gamepad navigation in the desktop window.
  - Seamless operation in Steam Deck Desktop Mode, or launched via Game Mode as a non-Steam shortcut.

- **🔌 Game Mode Daemon**
  - `vnpm --daemon` (also `--service`) serves JSON-RPC on `~/.cache/vnpatchmanager/vnpm.sock` for the Decky Loader plugin. Long calls return a job id, and the plugin polls for the result.
  - Plugin setup is documented in [decky-plugin/README.md](decky-plugin/README.md).

- **🎬 Codec Fixes**
  - Applies Proton video codec fixes for a Steam app from the desktop window or from the daemon.

---

## 🚀 Quick Start & Installation

### 1. One-Line Installer for Steam Deck & Linux Desktop (Recommended)

In Desktop Mode on your Steam Deck or Linux PC, open a terminal (Konsole) and run:

```bash
curl -sSL https://raw.githubusercontent.com/xjmac/Visual-Novel-Patch-Manager/main/install.sh | bash
```

**What this does automatically:**
- ✅ Sets up an isolated environment in `~/.local/share/vnpm/` (**100% persistent across SteamOS system updates**).
- ✅ Adds **VN Patch Manager** as a **Non-Steam Game in Steam Game Mode** with custom portrait capsule, wide capsule, hero banner, and app icon.
- ✅ Creates desktop and application menu launchers.
- ✅ Requires **zero sudo / root permissions**.

---

### 2. Manual / Development Installation

If you prefer to clone and develop locally:

```bash
# Clone repository
git clone https://github.com/xjmac/Visual-Novel-Patch-Manager.git
cd Visual-Novel-Patch-Manager

# Run local installer or start script
./install.sh
# or
./start.sh
```

`./start.sh` creates a repository-local `.venv`, installs `requirements.txt`, and forwards any extra arguments to the app (for example `./start.sh --list`).

---

## 🗑️ Uninstallation

To cleanly remove VN Patch Manager and its shortcuts:

```bash
curl -sSL https://raw.githubusercontent.com/xjmac/Visual-Novel-Patch-Manager/main/uninstall.sh | bash
```

---

## ⌨️ Command Line

With the package installed, `vnpm` opens the CustomTkinter window. `python vnpatchmanager.py` does the same. `pyproject.toml` registers the `vnpm` console script as `vnpatchmanager:main`.

| Flag | Behavior |
|---|---|
| `--version`, `-V` | Print the version and exit |
| `--debug`, `-d` | Enable verbose debug logging |
| `--list`, `-l` | List detected visual novels and patch statuses without opening the window |
| `--daemon`, `--service` | Run the headless JSON-RPC daemon for the Decky Loader plugin |
| `--sync-vndb` | Force-refresh the local VNDB database snapshot |
| `--export-licenses [FILE]` | Read Steam AppIDs from `FILE` (default `raw_licenses.txt`) and export names |
| `--output-file`, `-o FILE` | Output path for `--export-licenses` (default `my_steam_games.txt`) |

---

## 🛠️ Project Structure

```text
Visual-Novel-Patch-Manager/
├── vnpatchmanager/           # Core application package
│   ├── gui/                  # CustomTkinter window, gamepad navigation, modals
│   ├── cli.py                # vnpm entry: GUI, --list, --daemon, VNDB, licenses
│   ├── ipc_service.py        # JSON-RPC daemon and job queue
│   ├── patch_execution.py    # Staging apply, confinement, Proton, Steam verify
│   ├── backup_manager.py     # Save-safe restore and interrupted-swap recovery
│   ├── non_steam_manager.py  # shortcuts.vdf registration
│   ├── codec_fixer.py        # Proton video codec fixes
│   ├── steam_scanner.py      # Steam library and game manifest detection
│   ├── vndb_scanner.py       # VNDB database matching and metadata lookup
│   ├── patch_repository.py   # Local and SMB patch discovery
│   └── cover_art_manager.py  # Local caching and fetching of game cover art
├── decky-plugin/             # SteamOS Game Mode Quick Access plugin
├── scripts/                  # add_to_steam.py and VNDB/license helpers
├── tests/                    # Automated unit and integration tests
├── install.sh                # User install into ~/.local/share/vnpm/venv
├── uninstall.sh              # Remove the app, venv, and Steam shortcuts
├── start.sh                  # Dev launcher; creates .venv from requirements.txt
├── pyproject.toml            # Package metadata, vnpm script, dev extra
├── requirements.txt          # Runtime dependencies only
├── vnpatchmanager.py         # Main entry point script
├── LICENSE                   # MIT License
└── README.md                 # Project documentation
```

---

## 🧪 Running Tests

`./start.sh` creates `.venv` and installs runtime packages from `requirements.txt`. That environment does not include pytest. `./install.sh` uses `~/.local/share/vnpm/venv` and also does not include pytest.

Install the `dev` extra (pytest, pytest-cov, and ruff), then run the suite with the same interpreter. Python 3.10 through 3.14 are supported. CustomTkinter tests need a display; on a headless machine, `xvfb-run` provides one:

```bash
python -m pip install -e ".[dev]"
xvfb-run -a python -m pytest --cov=vnpatchmanager --cov-fail-under=80 tests/
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE) — see the LICENSE file for details.
