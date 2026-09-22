"""
End-to-End Integration Test for Visual Novel Patch Manager (VNPM).

Tests the full lifecycle:
Vanilla Installation -> Backup Creation -> Patch Application -> Status Verification -> Rollback Restoration
"""

import hashlib
import json
import zipfile

from vnpatchmanager import (
    BackupManager,
    PatchExecutionEngine,
    ConfigManager,
)


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
