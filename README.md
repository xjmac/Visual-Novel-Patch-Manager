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
  - Automatically snapshots replaced/modified files before applying any patch.
  - Single-click restore to easily revert a game to its clean, unpatched state.
  - Steam file validation trigger to verify integrity through Steam client if needed.

- **📱 Steam Deck & Touch-Friendly UI**
  - Modern, responsive dark UI built with CustomTkinter.
  - Seamless operation in Steam Deck Desktop Mode (or launched via Game Mode as a non-Steam shortcut).

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

---

## 🗑️ Uninstallation

To cleanly remove VN Patch Manager and its shortcuts:

```bash
curl -sSL https://raw.githubusercontent.com/xjmac/Visual-Novel-Patch-Manager/main/uninstall.sh | bash
```

---

## 🛠️ Project Structure

```text
Visual-Novel-Patch-Manager/
├── vnpatchmanager/           # Core application package
│   ├── backup_manager.py     # Backup creation, tracking, and rollback logic
│   ├── config_manager.py     # User settings and persistent configurations
│   ├── cover_art_manager.py  # Local caching & fetching of game cover art
│   ├── gui.py                # CustomTkinter graphical user interface
│   ├── patch_execution.py    # Patch installation (archive extract & exe execution)
│   ├── patch_repository.py   # Local & SMB repository patch discovery
│   ├── steam_scanner.py      # Steam library & game manifest detection
│   └── vndb_scanner.py       # VNDB database matching & metadata lookup
├── scripts/                  # Helper utilities & database sync tools
├── tests/                    # Automated unit & integration tests
├── start.sh                  # One-click automated setup & launcher script
├── vnpatchmanager.py         # Main entry point script
├── requirements.txt          # Python dependencies
├── LICENSE                   # MIT License
└── README.md                 # Project documentation
```

---

## 🧪 Running Tests

To run the test suite:

```bash
source .venv/bin/activate
pytest --cov=vnpatchmanager tests/
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE) — see the LICENSE file for details.
