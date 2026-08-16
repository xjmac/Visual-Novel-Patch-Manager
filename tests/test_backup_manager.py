import hashlib
import json
import time
from pathlib import Path
import pytest
from vnpatchmanager import BackupManager


def test_compute_sha256(tmp_path):
    test_file = tmp_path / "test.txt"
    content = b"VN Patch Manager Automated Backup System"
    test_file.write_bytes(content)

    expected_hash = hashlib.sha256(content).hexdigest()
    assert BackupManager.compute_sha256(test_file) == expected_hash


def test_create_backup_success(tmp_path):
    game_dir = tmp_path / "MockVN1"
    game_dir.mkdir()
    (game_dir / "game.exe").write_text("original game executable")
    (game_dir / "data").mkdir()
    (game_dir / "data" / "script.dat").write_text("original script data")

    logs = []
    backup_dir = BackupManager.create_backup(
        game_dir,
        app_id="900001",
        game_name="Mock Visual Novel 1",
        log_callback=lambda m: logs.append(m)
    )

    assert backup_dir.exists()
    assert (backup_dir / "manifest.json").exists()
    assert (backup_dir / "files").exists()

    with open(backup_dir / "manifest.json", "r") as f:
        manifest = json.load(f)

    assert manifest["steam_app_id"] == "900001"
    assert manifest["game_name"] == "Mock Visual Novel 1"
    assert "game.exe" in manifest["files"]
    assert "data/script.dat" in manifest["files"]

    game_exe_hash = hashlib.sha256(b"original game executable").hexdigest()
    assert manifest["files"]["game.exe"]["sha256"] == game_exe_hash

    # Check that backed-up files exist in files/ folder
    assert (backup_dir / "files" / "game.exe").read_text() == "original game executable"
    assert (backup_dir / "files" / "data" / "script.dat").read_text() == "original script data"
    assert any("Backup complete" in log for log in logs)


def test_create_backup_ignores_existing_backup_and_tracking_file(tmp_path):
    game_dir = tmp_path / "Game"
    game_dir.mkdir()
    (game_dir / "main.exe").write_text("main binary")
    (game_dir / ".patch_applied.json").write_text('{"status": "old"}')

    backup_dir = BackupManager.create_backup(game_dir, "2000", "Game")
    with open(backup_dir / "manifest.json", "r") as f:
        manifest = json.load(f)

    assert "main.exe" in manifest["files"]
    assert ".patch_applied.json" not in manifest["files"]
    assert not any(".backup" in k for k in manifest["files"])


def test_create_backup_nonexistent_dir(tmp_path):
    with pytest.raises(Exception) as exc_info:
        BackupManager.create_backup(tmp_path / "NonExistent", "123", "Game")
    assert "does not exist" in str(exc_info.value)


def test_has_backup(tmp_path):
    game_dir = tmp_path / "Game"
    game_dir.mkdir()
    assert not BackupManager.has_backup(game_dir)

    (game_dir / "file.txt").write_text("abc")
    BackupManager.create_backup(game_dir, "100", "Game")
    assert BackupManager.has_backup(game_dir)


def test_get_latest_backup_ordering(tmp_path):
    game_dir = tmp_path / "Game"
    game_dir.mkdir()
    (game_dir / "file.txt").write_text("v1")

    backup_dir_1 = BackupManager.create_backup(game_dir, "100", "Game")

    # Fast-forward time for second backup
    time.sleep(0.01)
    (game_dir / "file.txt").write_text("v2")
    backup_dir_2 = BackupManager.create_backup(game_dir, "100", "Game")

    latest_dir, latest_manifest = BackupManager.get_latest_backup(game_dir)
    assert latest_dir == backup_dir_2
    assert latest_manifest["timestamp"] >= 0


def test_restore_backup_atomic_success(tmp_path):
    game_dir = tmp_path / "Clannad"
    game_dir.mkdir()

    # Original files
    (game_dir / "clannad.exe").write_text("original clannad binary")
    (game_dir / "data").mkdir()
    (game_dir / "data" / "voice.bin").write_text("original voice data")

    # Create original backup
    BackupManager.create_backup(game_dir, "1002", "Clannad")

    # Simulate patch modification and patch files addition
    (game_dir / "clannad.exe").write_text("PATCHED clannad binary")
    (game_dir / "data" / "voice.bin").write_text("PATCHED voice data")
    (game_dir / "patch_hd.xp3").write_text("new patch file")
    (game_dir / "data" / "extra_patch.dat").write_text("extra patch dat")
    (game_dir / ".patch_applied.json").write_text('{"status": "success"}')

    logs = []
    success = BackupManager.restore_backup(game_dir, lambda m: logs.append(m))
    assert success is True

    # Check that original files are restored
    assert (game_dir / "clannad.exe").read_text() == "original clannad binary"
    assert (game_dir / "data" / "voice.bin").read_text() == "original voice data"

    # Check that checksums match
    orig_exe_hash = hashlib.sha256(b"original clannad binary").hexdigest()
    assert BackupManager.compute_sha256(game_dir / "clannad.exe") == orig_exe_hash

    # Check that added patch files and tracking file are deleted
    assert not (game_dir / "patch_hd.xp3").exists()
    assert not (game_dir / "data" / "extra_patch.dat").exists()
    assert not (game_dir / ".patch_applied.json").exists()

    # Check that backup archive itself is preserved
    assert BackupManager.has_backup(game_dir)


def test_restore_backup_tampered_backup_fails(tmp_path):
    game_dir = tmp_path / "Game"
    game_dir.mkdir()
    (game_dir / "file.txt").write_text("original")

    backup_dir = BackupManager.create_backup(game_dir, "100", "Game")

    # Tamper with the backup file directly
    tampered_file = backup_dir / "files" / "file.txt"
    tampered_file.write_text("tampered content")

    with pytest.raises(Exception) as exc_info:
        BackupManager.restore_backup(game_dir)
    assert "checksum mismatch" in str(exc_info.value)


def test_restore_backup_missing_file_in_storage(tmp_path):
    game_dir = tmp_path / "Game"
    game_dir.mkdir()
    (game_dir / "file.txt").write_text("original")

    backup_dir = BackupManager.create_backup(game_dir, "100", "Game")

    # Remove the backup file from storage
    (backup_dir / "files" / "file.txt").unlink()

    with pytest.raises(Exception) as exc_info:
        BackupManager.restore_backup(game_dir)
    assert "missing file" in str(exc_info.value)


def test_restore_backup_no_backup_found(tmp_path):
    game_dir = tmp_path / "GameNoBackup"
    game_dir.mkdir()

    with pytest.raises(Exception) as exc_info:
        BackupManager.restore_backup(game_dir)
    assert "No valid backup found" in str(exc_info.value)


def test_create_backup_detects_pre_existing_patch_collision(tmp_path):
    game_dir = tmp_path / "MockGameCollision"
    game_dir.mkdir()
    (game_dir / "game").mkdir()
    # Game file is already patched
    (game_dir / "game" / "assets.rpa").write_text("patched assets rpa content")

    patch_source = tmp_path / "patch_source"
    patch_source.mkdir()
    (patch_source / "assets.rpa").write_text("patched assets rpa content")

    logs = []
    backup_dir = BackupManager.create_backup(
        game_dir,
        "900101",
        "Mock Bunny Adventure",
        patch_source_dir=patch_source,
        log_callback=lambda m: logs.append(m)
    )

    with open(backup_dir / "manifest.json", "r") as f:
        manifest = json.load(f)

    assert manifest["is_clean_original"] is False
    assert "game/assets.rpa" in manifest["detected_collisions"]
    assert any("Pre-existing patch file(s) detected" in log for log in logs)
    assert not BackupManager.has_clean_backup(game_dir)


def test_has_clean_backup(tmp_path):
    game_dir = tmp_path / "CleanGame"
    game_dir.mkdir()
    (game_dir / "main.exe").write_text("clean executable")

    assert not BackupManager.has_clean_backup(game_dir)

    BackupManager.create_backup(game_dir, "1001", "CleanGame")
    assert BackupManager.has_clean_backup(game_dir)

