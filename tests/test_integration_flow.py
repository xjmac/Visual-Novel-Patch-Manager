"""
End-to-End Integration Test for Visual Novel Patch Manager (VNPM).

Tests the full lifecycle:
Vanilla Installation -> Backup Creation -> Patch Application -> Status Verification -> Rollback Restoration
"""

import hashlib
import json
import os
import zipfile
from pathlib import Path

import pytest

from vnpatchmanager import (
    BackupManager,
    PatchExecutionEngine,
    ConfigManager,
)
from vnpatchmanager.exceptions import PatchExtractionError


def _snapshot_tree(root: Path) -> dict:
    """Map relative paths to SHA256 digests for every file under root."""
    snapshot = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = str(path.relative_to(root))
            snapshot[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def test_full_patch_backup_rollback_lifecycle(tmp_path):
    # 1. Setup mock vanilla game installation
    game_dir = tmp_path / "SyntheticVisualNovel"
    game_dir.mkdir()
    (game_dir / "game").mkdir()
    (game_dir / "data").mkdir()

    exe_file = game_dir / "game.exe"
    exe_file.write_bytes(b"ORIGINAL_EXE_BINARY_V1")
    script_file = game_dir / "game" / "scripts.rpa"
    script_file.write_bytes(b"ORIGINAL_ALL_AGES_SCRIPTS")
    voice_file = game_dir / "data" / "voices.dat"
    voice_file.write_bytes(b"ORIGINAL_AUDIO_TRACKS")

    original_exe_hash = hashlib.sha256(b"ORIGINAL_EXE_BINARY_V1").hexdigest()
    original_script_hash = hashlib.sha256(b"ORIGINAL_ALL_AGES_SCRIPTS").hexdigest()
    original_voice_hash = hashlib.sha256(b"ORIGINAL_AUDIO_TRACKS").hexdigest()

    # Initial verification: Game is clean vanilla, no backups, unpatched
    assert not BackupManager.has_backup(game_dir)
    assert not BackupManager.has_clean_backup(game_dir)
    assert not PatchExecutionEngine.get_patch_status(game_dir)

    # 2. Setup patch repository source with zip archive and loose files
    patch_dir = tmp_path / "Patches" / "SyntheticVN_18Plus"
    patch_dir.mkdir(parents=True)

    patch_zip = patch_dir / "r18_update.zip"
    with zipfile.ZipFile(patch_zip, "w") as zf:
        zf.writestr("patch.rpa", b"UNCENSORED_18PLUS_RPA_CONTENT")
        zf.writestr("bonus_cg.dat", b"BONUS_ILLUSTRATIONS")

    patch_data = {
        "steam_app_id": "888123",
        "patch_source_dir": str(patch_dir),
        "actions": [
            {
                "type": "extract_archive",
                "source": "r18_update.zip",
                "destination": "{game_dir}/game/"
            }
        ]
    }

    game_data = {
        "name": "Synthetic Visual Novel",
        "path": str(game_dir),
        "library_path": str(tmp_path),
        "is_installed": True
    }

    # 3. Create pre-patch clean backup
    logs = []
    backup_path = BackupManager.create_backup(
        game_install_path=game_dir,
        app_id="888123",
        game_name="Synthetic Visual Novel",
        patch_source_dir=patch_dir,
        log_callback=lambda m: logs.append(m)
    )

    assert backup_path.exists()
    assert (backup_path / "manifest.json").exists()
    assert BackupManager.has_backup(game_dir)
    assert BackupManager.has_clean_backup(game_dir)

    with open(backup_path / "manifest.json", "r", encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["is_clean_original"] is True
    assert "game.exe" in manifest["files"]
    assert "game/scripts.rpa" in manifest["files"]
    assert "data/voices.dat" in manifest["files"]
    assert manifest["files"]["game.exe"]["sha256"] == original_exe_hash

    # 4. Apply patch via PatchExecutionEngine
    cm = ConfigManager()
    patch_logs = []
    success = PatchExecutionEngine.apply_patch(
        game_data=game_data,
        patch_data=patch_data,
        config_manager=cm,
        log_callback=lambda m: patch_logs.append(m)
    )
    assert success is True
    assert any("Patch successfully applied" in log for log in patch_logs)

    # 5. Verify patched state
    assert (game_dir / ".patch_applied.json").exists()
    assert (game_dir / "game" / "patch.rpa").exists()
    assert (game_dir / "game" / "patch.rpa").read_bytes() == b"UNCENSORED_18PLUS_RPA_CONTENT"
    assert (game_dir / "game" / "bonus_cg.dat").exists()
    assert PatchExecutionEngine.get_patch_status(game_dir, patch_data=patch_data) is True

    # 6. Execute Rollback to Restore Original Vanilla Game
    rollback_logs = []
    restored = BackupManager.restore_backup(
        game_install_path=game_dir,
        log_callback=lambda m: rollback_logs.append(m)
    )
    assert restored is True
    assert any("Rollback successful" in log for log in rollback_logs)

    # 7. Post-Rollback Integrity Verification
    # Tracking file and patch files must be purged
    assert not (game_dir / ".patch_applied.json").exists()
    assert not (game_dir / "game" / "patch.rpa").exists()
    assert not (game_dir / "game" / "bonus_cg.dat").exists()

    # Original files must exist with exact byte content and hashes
    assert exe_file.exists()
    assert exe_file.read_bytes() == b"ORIGINAL_EXE_BINARY_V1"
    assert hashlib.sha256(exe_file.read_bytes()).hexdigest() == original_exe_hash

    assert script_file.exists()
    assert script_file.read_bytes() == b"ORIGINAL_ALL_AGES_SCRIPTS"
    assert hashlib.sha256(script_file.read_bytes()).hexdigest() == original_script_hash

    assert voice_file.exists()
    assert voice_file.read_bytes() == b"ORIGINAL_AUDIO_TRACKS"
    assert hashlib.sha256(voice_file.read_bytes()).hexdigest() == original_voice_hash

    # Final patch status check must report clean vanilla
    assert not PatchExecutionEngine.get_patch_status(game_dir, patch_data=patch_data)


def test_apply_failure_leaves_pre_patch_tree_unchanged(tmp_path, temp_config_dir):
    """A later action failure must not leave the earlier action's writes behind."""
    game_dir = tmp_path / "SyntheticVisualNovelFail"
    (game_dir / "game" / "saves").mkdir(parents=True)
    (game_dir / "game.exe").write_bytes(b"ORIGINAL_EXE")
    (game_dir / "game" / "scripts.rpa").write_bytes(b"ORIGINAL_SCRIPTS")
    (game_dir / "game" / "saves" / "slot.save").write_bytes(b"SLOT_ONE")

    before = _snapshot_tree(game_dir)

    patch_dir = tmp_path / "fail_patch"
    patch_dir.mkdir()
    (patch_dir / "game.exe").write_bytes(b"PATCHED_EXE")
    (patch_dir / "patch.rpa").write_bytes(b"PATCH_PAYLOAD")

    patch_data = {
        "steam_app_id": "888124",
        "patch_source_dir": str(patch_dir),
        "actions": [
            {"type": "copy_file", "source": "game.exe", "destination": "{game_dir}/game.exe"},
            {"type": "copy_file", "source": "patch.rpa", "destination": "{game_dir}/game/patch.rpa"},
            {"type": "copy_file", "source": "missing.rpa", "destination": "{game_dir}/game/missing.rpa"},
        ],
    }
    game_data = {
        "name": "Synthetic Visual Novel",
        "path": str(game_dir),
        "library_path": str(tmp_path),
        "is_installed": True,
    }
    cm = ConfigManager()
    cm.config["mode"] = "local"

    with pytest.raises(PatchExtractionError, match="does not exist"):
        PatchExecutionEngine.apply_patch(game_data, patch_data, cm, lambda _msg: None)

    assert _snapshot_tree(game_dir) == before
    assert not (game_dir / "game" / "patch.rpa").exists()
    assert not (game_dir / ".patch_applied.json").exists()
    assert not (game_dir / ".backup").exists()
    parent = game_dir.parent
    assert not (parent / f".{game_dir.name}.vnpm-old").exists()
    assert not list(parent.glob(f".{game_dir.name}.vnpm-stage-*"))


def test_restore_preserves_saves_created_after_backup(tmp_path):
    """Rollback restores game files and keeps save data written after the backup."""
    game_dir = tmp_path / "SaveProtectedVN"
    (game_dir / "game" / "saves").mkdir(parents=True)
    (game_dir / "game.exe").write_bytes(b"ORIGINAL_EXE")
    (game_dir / "game" / "scripts.rpa").write_bytes(b"ORIGINAL_SCRIPTS")
    (game_dir / "game" / "saves" / "old.save").write_bytes(b"before")
    (game_dir / "game" / "saves" / "removed.save").write_bytes(b"gone-later")

    BackupManager.create_backup(game_dir, "888125", "Save Protected VN")

    (game_dir / "game" / "scripts.rpa").write_bytes(b"PATCHED_SCRIPTS")
    (game_dir / "game" / "patch.rpa").write_bytes(b"PATCH_PAYLOAD")
    (game_dir / ".patch_applied.json").write_text('{"status": "success"}')
    (game_dir / "game" / "saves" / "old.save").write_bytes(b"after")
    (game_dir / "game" / "saves" / "removed.save").unlink()
    (game_dir / "game" / "saves" / "new.save").write_bytes(b"NEW_SLOT")
    (game_dir / "game" / "saves" / "persistent").write_bytes(b"PERSISTENT")
    (game_dir / "savedata").mkdir()
    (game_dir / "savedata" / "data.bin").write_bytes(b"KIRIKIRI")
    (game_dir / "save").mkdir()
    (game_dir / "save" / "slot1.bin").write_bytes(b"SLOT_BIN")
    (game_dir / "quick.save").write_bytes(b"QUICK")
    (game_dir / "Game" / "Saves").mkdir(parents=True)
    (game_dir / "Game" / "Saves" / "slot.SAVE").write_bytes(b"CASE")

    assert BackupManager.restore_backup(game_dir) is True

    assert (game_dir / "game.exe").read_bytes() == b"ORIGINAL_EXE"
    assert (game_dir / "game" / "scripts.rpa").read_bytes() == b"ORIGINAL_SCRIPTS"
    assert not (game_dir / "game" / "patch.rpa").exists()
    assert not (game_dir / ".patch_applied.json").exists()
    assert BackupManager.has_backup(game_dir)

    assert (game_dir / "game" / "saves" / "old.save").read_bytes() == b"after"
    assert not (game_dir / "game" / "saves" / "removed.save").exists()
    assert (game_dir / "game" / "saves" / "new.save").read_bytes() == b"NEW_SLOT"
    assert (game_dir / "game" / "saves" / "persistent").read_bytes() == b"PERSISTENT"
    assert (game_dir / "savedata" / "data.bin").read_bytes() == b"KIRIKIRI"
    assert (game_dir / "save" / "slot1.bin").read_bytes() == b"SLOT_BIN"
    assert (game_dir / "quick.save").read_bytes() == b"QUICK"
    assert (game_dir / "Game" / "Saves" / "slot.SAVE").read_bytes() == b"CASE"
