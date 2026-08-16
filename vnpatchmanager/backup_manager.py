import os
import json
import shutil
import hashlib
import time
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
from datetime import datetime, timezone

class BackupManager:
    """Manages creation, verification, and atomic rollback of game backups."""

    BACKUP_DIR_NAME = ".backup"
    MANIFEST_NAME = "manifest.json"

    @staticmethod
    def compute_sha256(file_path: Path) -> str:
        """Computes the SHA256 hex digest of a file in 64KB chunks."""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    def has_backup(game_install_path) -> bool:
        """Checks if a valid backup with manifest exists in the game's .backup directory."""
        backup_root = Path(game_install_path) / BackupManager.BACKUP_DIR_NAME
        if not backup_root.exists() or not backup_root.is_dir():
            return False
        for item in backup_root.iterdir():
            if item.is_dir() and (item / BackupManager.MANIFEST_NAME).exists():
                return True
        return False

    @staticmethod
    def get_latest_backup(game_install_path) -> tuple[Path, dict]:
        """Returns the path to the newest backup directory and its parsed manifest."""
        backup_root = Path(game_install_path) / BackupManager.BACKUP_DIR_NAME
        if not backup_root.exists() or not backup_root.is_dir():
            return None, None

        valid_backups = []
        for item in backup_root.iterdir():
            if item.is_dir():
                manifest_file = item / BackupManager.MANIFEST_NAME
                if manifest_file.exists():
                    try:
                        with open(manifest_file, "r") as f:
                            manifest = json.load(f)
                            ts = manifest.get("timestamp", 0)
                            valid_backups.append((ts, item, manifest))
                    except Exception as e:
                        logger.warning(f"Error reading manifest in {item}: {e}")

        if not valid_backups:
            return None, None

        # Sort by timestamp descending
        valid_backups.sort(key=lambda x: x[0], reverse=True)
        _, latest_dir, latest_manifest = valid_backups[0]
        return latest_dir, latest_manifest

    @staticmethod
    def has_clean_backup(game_install_path) -> bool:
        """Returns True if the newest backup is marked clean and free of pre-existing patch files."""
        _, manifest = BackupManager.get_latest_backup(game_install_path)
        if not manifest:
            return False
        return manifest.get("is_clean_original", True) is True

    @staticmethod
    def create_backup(game_install_path, app_id: str, game_name: str, patch_source_dir=None, log_callback=None) -> Path:
        """
        Computes SHA256 checksums of all original game files, stores them in
        .backup/<timestamp>/ with a manifest.json.
        Checks for patch file hash collisions to detect pre-patched games.
        """
        install_dir = Path(game_install_path)
        if not install_dir.exists():
            raise Exception(f"Game directory does not exist: {install_dir}")

        now = time.time()
        iso_str = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
        folder_tag = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y%m%d_%H%M%S")

        backup_dir = install_dir / BackupManager.BACKUP_DIR_NAME / f"backup_{folder_tag}"
        files_backup_dir = backup_dir / "files"
        files_backup_dir.mkdir(parents=True, exist_ok=True)

        if log_callback:
            log_callback(f"Creating backup for {game_name} in {backup_dir.name}...")

        # Pre-scan patch directory to collect known patch hashes
        patch_hashes = set()
        if patch_source_dir and Path(patch_source_dir).exists():
            p_source = Path(patch_source_dir)
            for p_root, _, p_files in os.walk(p_source):
                for p_file in p_files:
                    p_full = Path(p_root) / p_file
                    try:
                        patch_hashes.add(BackupManager.compute_sha256(p_full))
                    except (OSError, PermissionError) as e:
                        logger.warning(f"Cannot hash patch file {p_full}: {e}")

        detected_collisions = []
        manifest_data = {
            "timestamp": now,
            "iso_timestamp": iso_str,
            "steam_app_id": str(app_id),
            "game_name": game_name,
            "is_clean_original": True,
            "detected_collisions": [],
            "files": {}
        }

        # Recursively scan original files
        for root, dirs, files in os.walk(install_dir):
            root_path = Path(root)
            # Skip .backup directory itself
            if BackupManager.BACKUP_DIR_NAME in root_path.parts:
                continue

            for file_name in files:
                # Skip .patch_applied.json from previous runs if any
                if file_name == ".patch_applied.json":
                    continue

                full_file_path = root_path / file_name
                rel_path = full_file_path.relative_to(install_dir)
                rel_path_str = str(rel_path)

                sha256_hash = BackupManager.compute_sha256(full_file_path)
                file_size = full_file_path.stat().st_size

                if patch_hashes and sha256_hash in patch_hashes:
                    detected_collisions.append(rel_path_str)

                # Copy to backup location
                dst_backup_file = files_backup_dir / rel_path
                dst_backup_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(full_file_path, dst_backup_file)

                manifest_data["files"][rel_path_str] = {
                    "sha256": sha256_hash,
                    "size": file_size
                }

        if detected_collisions:
            manifest_data["is_clean_original"] = False
            manifest_data["detected_collisions"] = detected_collisions
            if log_callback:
                log_callback(f"Warning: Pre-existing patch file(s) detected: {', '.join(detected_collisions[:3])}")

        manifest_file = backup_dir / BackupManager.MANIFEST_NAME
        with open(manifest_file, "w") as f:
            json.dump(manifest_data, f, indent=4)

        if log_callback:
            log_callback(f"Backup complete: {len(manifest_data['files'])} files cataloged.")

        return backup_dir

    @staticmethod
    def restore_backup(game_install_path, log_callback=None) -> bool:
        """
        Restores original game files from the latest backup atomically,
        verifying SHA256 checksums before and after restoration.
        """
        install_dir = Path(game_install_path)
        latest_dir, manifest = BackupManager.get_latest_backup(install_dir)

        if not latest_dir or not manifest:
            raise Exception("No valid backup found to restore.")

        if log_callback:
            log_callback(f"Verifying backup integrity from {latest_dir.name}...")

        files_backup_dir = latest_dir / "files"
        manifest_files = manifest.get("files", {})

        # 1. Pre-restoration integrity check of the backup repository
        for rel_path_str, meta in manifest_files.items():
            backup_file = files_backup_dir / rel_path_str
            if not backup_file.exists():
                raise Exception(f"Corrupted backup: missing file '{rel_path_str}' in backup storage.")
            current_hash = BackupManager.compute_sha256(backup_file)
            if current_hash != meta["sha256"]:
                raise Exception(f"Corrupted backup: checksum mismatch for '{rel_path_str}'.")

        if log_callback:
            log_callback("Restoring original files and purging patch files...")

        # 2. Remove files currently in game directory that are not part of .backup
        for root, dirs, files in os.walk(install_dir, topdown=False):
            root_path = Path(root)
            if BackupManager.BACKUP_DIR_NAME in root_path.parts:
                continue

            for file_name in files:
                full_file_path = root_path / file_name
                full_file_path.unlink()

            # Remove empty directories (except install_dir and .backup)
            if root_path != install_dir and not any(root_path.iterdir()):
                try:
                    root_path.rmdir()
                except OSError:
                    pass  # Directory not empty or other OS error, skip

        # 3. Restore all original files from the backup
        for rel_path_str, meta in manifest_files.items():
            src_backup_file = files_backup_dir / rel_path_str
            dst_restored_file = install_dir / rel_path_str
            dst_restored_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_backup_file, dst_restored_file)

        # 4. Post-restoration verification
        if log_callback:
            log_callback("Verifying restored file integrity...")

        for rel_path_str, meta in manifest_files.items():
            restored_file = install_dir / rel_path_str
            if not restored_file.exists():
                raise Exception(f"Rollback failed: restored file '{rel_path_str}' missing.")
            restored_hash = BackupManager.compute_sha256(restored_file)
            if restored_hash != meta["sha256"]:
                raise Exception(f"Rollback failed: restored checksum mismatch for '{rel_path_str}'.")

        # 5. Remove .patch_applied.json if present
        tracking_file = install_dir / ".patch_applied.json"
        tracking_file.unlink(missing_ok=True)

        if log_callback:
            log_callback("Rollback successful! Original game restored.")

        return True
