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

## 🚀 Quick Start

### 1. One-Click Launch (Recommended)

Clone the repository and run the included `start.sh` launcher. It will automatically create an isolated Python virtual environment (`.venv`) and install all required dependencies on first run:

```bash
git clone https://github.com/xjmac/Visual-Novel-Patch-Manager.git
cd Visual-Novel-Patch-Manager
chmod +x start.sh
./start.sh
```

### 2. Manual Installation

If you prefer to manage your own Python environment:

```bash
# Clone the repository
git clone https://github.com/xjmac/Visual-Novel-Patch-Manager.git
cd Visual-Novel-Patch-Manager

# Create & activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Launch VNPM
python3 vnpatchmanager.py
```

---

## 🎮 Steam Deck Usage

1. Switch to **Desktop Mode** on your Steam Deck.
2. Open **Konsole** and clone/download VNPM to a folder of your choice (e.g., `~/Games/VNPM` or `~/Documents/prog/VNPM`).
3. Make `start.sh` executable:
   ```bash
   chmod +x start.sh
   ```
4. Double-click `start.sh` (select **Execute** when prompted) or add `start.sh` as a **Non-Steam Game** in desktop Steam to launch it directly from Game Mode.

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
