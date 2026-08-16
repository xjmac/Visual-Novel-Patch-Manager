import os
import json
import pytest
from pathlib import Path
import vdf
import vnpatchmanager


@pytest.fixture
def temp_config_dir(tmp_path, monkeypatch):
    """Overrides CONFIG_DIR and CONFIG_FILE in vnpatchmanager with a temporary folder."""
    cfg_dir = tmp_path / ".config" / "vnpatchmanager"
    cfg_file = cfg_dir / "config.json"
    monkeypatch.setattr(vnpatchmanager, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(vnpatchmanager, "CONFIG_FILE", cfg_file)
    return cfg_dir, cfg_file


@pytest.fixture
def mock_steam_structure(tmp_path):
    """
    Creates a realistic Steam directory structure with multiple libraries,
    installed games, Proton installations, and compatdata Wineprefixes.
    """
    steam_root = tmp_path / "Steam"
    steam_root_steamapps = steam_root / "steamapps"
    steam_root_steamapps.mkdir(parents=True, exist_ok=True)

    secondary_library = tmp_path / "SecondaryLibrary"
    secondary_steamapps = secondary_library / "steamapps"
    secondary_steamapps.mkdir(parents=True, exist_ok=True)

    # 1. Setup libraryfolders.vdf
    library_folders_data = {
        "libraryfolders": {
            "0": {
                "path": str(steam_root),
                "label": "",
                "contentid": "0",
                "totalsize": "0",
                "apps": {
                    "900001": "1000000"
                }
            },
            "1": {
                "path": str(secondary_library),
                "label": "SDCard",
                "contentid": "1",
                "totalsize": "0",
                "apps": {
                    "900002": "2000000"
                }
            }
        }
    }

    vdf_file = steam_root_steamapps / "libraryfolders.vdf"
    with open(vdf_file, "w") as f:
        vdf.dump(library_folders_data, f)

    # 2. Setup game in Primary Library (AppID 900001: Synthetic VN Alpha)
    game1_common = steam_root_steamapps / "common" / "SyntheticVNAlpha"
    game1_common.mkdir(parents=True, exist_ok=True)
    with open(game1_common / "game.exe", "w") as f:
        f.write("dummy game executable")

    acf1_data = {
        "AppState": {
            "appid": "900001",
            "Universe": "1",
            "name": "Synthetic VN Alpha",
            "installdir": "SyntheticVNAlpha",
            "StateFlags": "4"
        }
    }
    with open(steam_root_steamapps / "appmanifest_900001.acf", "w") as f:
        vdf.dump(acf1_data, f)

    # Setup Proton installations in primary library
    proton8_dir = steam_root_steamapps / "common" / "Proton 8.0"
    proton8_dir.mkdir(parents=True, exist_ok=True)
    proton8_bin = proton8_dir / "proton"
    proton8_bin.write_text("#!/bin/sh\nexit 0\n")
    proton8_bin.chmod(0o755)

    proton9_dir = steam_root_steamapps / "common" / "Proton 9.0"
    proton9_dir.mkdir(parents=True, exist_ok=True)
    proton9_bin = proton9_dir / "proton"
    proton9_bin.write_text("#!/bin/sh\nexit 0\n")
    proton9_bin.chmod(0o755)

    # Setup compatdata for game 1
    compatdata1 = steam_root_steamapps / "compatdata" / "900001" / "pfx"
    compatdata1.mkdir(parents=True, exist_ok=True)

    # 3. Setup game in Secondary Library (AppID 900002: Synthetic VN Beta)
    game2_common = secondary_steamapps / "common" / "SyntheticVNBeta"
    game2_common.mkdir(parents=True, exist_ok=True)
    with open(game2_common / "game.exe", "w") as f:
        f.write("dummy beta executable")

    acf2_data = {
        "AppState": {
            "appid": "900002",
            "Universe": "1",
            "name": "Synthetic VN Beta",
            "installdir": "SyntheticVNBeta",
            "StateFlags": "4"
        }
    }
    with open(secondary_steamapps / "appmanifest_900002.acf", "w") as f:
        vdf.dump(acf2_data, f)

    # Setup compatdata for game 2
    compatdata2 = secondary_steamapps / "compatdata" / "900002" / "pfx"
    compatdata2.mkdir(parents=True, exist_ok=True)

    return {
        "steam_root": steam_root,
        "secondary_library": secondary_library,
        "game1": {
            "appid": "900001",
            "name": "Synthetic VN Alpha",
            "path": game1_common,
            "library_path": steam_root,
            "compatdata": compatdata1.parent
        },
        "game2": {
            "appid": "900002",
            "name": "Synthetic VN Beta",
            "path": game2_common,
            "library_path": secondary_library,
            "compatdata": compatdata2.parent
        },
        "proton8_bin": proton8_bin,
        "proton9_bin": proton9_bin
    }


@pytest.fixture
def mock_patch_repo(tmp_path):
    """
    Creates a patch repository with mock patch folders and patch.json definitions.
    """
    repo_dir = tmp_path / "patches"
    repo_dir.mkdir(parents=True, exist_ok=True)

    # Patch 1: Copy file patch for AppID 900001
    patch1_dir = repo_dir / "synthetic_alpha_patch"
    patch1_dir.mkdir(parents=True, exist_ok=True)

    patch1_file = patch1_dir / "update.xp3"
    patch1_file.write_text("patch content xp3")

    patch1_subdir = patch1_dir / "data"
    patch1_subdir.mkdir(parents=True, exist_ok=True)
    (patch1_subdir / "extra.bin").write_text("extra binary content")

    patch1_manifest = {
        "steam_app_id": 900001,
        "title": "Synthetic VN Alpha English Patch",
        "actions": [
            {
                "type": "copy_file",
                "source": "update.xp3",
                "destination": "{game_dir}/update.xp3"
            },
            {
                "type": "copy_file",
                "source": "data",
                "destination": "{game_dir}/data"
            }
        ]
    }
    with open(patch1_dir / "patch.json", "w") as f:
        json.dump(patch1_manifest, f)

    # Patch 2: Inno setup patch for AppID 900002
    patch2_dir = repo_dir / "synthetic_beta_patch"
    patch2_dir.mkdir(parents=True, exist_ok=True)
    patch2_exe = patch2_dir / "setup_patch.exe"
    patch2_exe.write_text("inno setup payload")

    patch2_manifest = {
        "steam_app_id": 900002,
        "title": "Synthetic VN Beta Voice & HD Patch",
        "actions": [
            {
                "type": "extract_inno_setup",
                "source": "setup_patch.exe",
                "destination": "{game_dir}"
            }
        ]
    }
    with open(patch2_dir / "patch.json", "w") as f:
        json.dump(patch2_manifest, f)

    # Patch 3: Proton Executable patch for AppID 900003 (not installed)
    patch3_dir = repo_dir / "synthetic_gamma_patch"
    patch3_dir.mkdir(parents=True, exist_ok=True)
    patch3_exe = patch3_dir / "patch_installer.exe"
    patch3_exe.write_text("windows installer payload")

    patch3_manifest = {
        "steam_app_id": 900003,
        "title": "Synthetic VN Gamma Patch",
        "actions": [
            {
                "type": "run_proton_executable",
                "source": "patch_installer.exe",
                "args": ["/SILENT", "/DIR={game_dir_win}"]
            }
        ]
    }
    with open(patch3_dir / "patch.json", "w") as f:
        json.dump(patch3_manifest, f)

    return {
        "repo_dir": repo_dir,
        "patch1_dir": patch1_dir,
        "patch2_dir": patch2_dir,
        "patch3_dir": patch3_dir,
        "patch1_manifest": patch1_manifest,
        "patch2_manifest": patch2_manifest,
        "patch3_manifest": patch3_manifest
    }
