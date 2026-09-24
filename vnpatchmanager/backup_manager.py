import os
import json
import shutil
import hashlib
import tempfile
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Tuple, Union
from .exceptions import BackupError

logger = logging.getLogger(__name__)

class BackupManager:
    """Manages creation, verification, and atomic rollback of game backups."""

    BACKUP_DIR_NAME = ".backup"
    MANIFEST_NAME = "manifest.json"
    _SAVE_DIR_NAMES = frozenset({"save", "saves", "savedata"})
    _OLD_SUFFIX = ".vnpm-old"
    _STAGE_PREFIX = ".vnpm-stage-"

    @staticmethod
    def is_protected_save_path(relative_path: Union[str, Path]) -> bool:
        """Return True for user save files that rollback must not delete or overwrite.

        A path is protected when any component is ``save``, ``saves``, or ``savedata``,
        or when the filename ends with ``.save``. Matching is case-insensitive.
        """
        text = str(relative_path).replace("\\", "/")
        rel = Path(text)
        if rel.name.lower().endswith(".save"):
            return True
        return any(part.lower() in BackupManager._SAVE_DIR_NAMES for part in rel.parts)

    @staticmethod
    def _old_tree_path(install_dir: Path) -> Path:
        return install_dir.parent / f".{install_dir.name}{BackupManager._OLD_SUFFIX}"

    @staticmethod
    def recover_interrupted_swap(install_dir: Union[str, Path]) -> None:
        """Finish or undo a directory swap that stopped between the two renames.

        If the install path is missing and ``.vnpm-old`` exists, the previous tree
        is renamed back. If both exist, the swap already finished and the sibling
        is leftover, so it is removed. The leftover is never renamed over a live install.
        """
        install_dir = Path(install_dir)
        old = BackupManager._old_tree_path(install_dir)
        if old.exists() and not install_dir.exists():
            logger.warning("Recovering interrupted install swap for %s", install_dir)
            os.replace(old, install_dir)
        elif old.exists() and install_dir.exists():
            shutil.rmtree(old, ignore_errors=True)

    @staticmethod
    def make_staging_dir(install_dir: Union[str, Path]) -> Path:
        """Create a sibling staging directory on the same filesystem as the install."""
        install_dir = Path(install_dir)
        return Path(tempfile.mkdtemp(
            prefix=f".{install_dir.name}{BackupManager._STAGE_PREFIX}",
            dir=str(install_dir.parent),
        ))

    @staticmethod
    def commit_directory_swap(staging: Union[str, Path], install_dir: Union[str, Path]) -> None:
        """Replace ``install_dir`` with ``staging`` via two same-filesystem renames.

        On failure of the second rename, the previous tree is moved back when that
        rename itself succeeds. A crash that skips that rollback leaves the complete
        previous tree at ``.vnpm-old``.
        """
        install_dir = Path(install_dir)
        staging = Path(staging)
        BackupManager.recover_interrupted_swap(install_dir)
        if not install_dir.exists():
            raise BackupError(f"Game directory does not exist: {install_dir}")
        if not staging.exists():
            raise BackupError(f"Staging directory does not exist: {staging}")
        if staging.stat().st_dev != install_dir.stat().st_dev:
            raise BackupError("Staging directory is not on the same filesystem as the game install.")

        old = BackupManager._old_tree_path(install_dir)
        if old.exists():
            shutil.rmtree(old)
        os.replace(install_dir, old)
        try:
            os.replace(staging, install_dir)
        except Exception:
            try:
                if not install_dir.exists() and old.exists():
                    os.replace(old, install_dir)
            except Exception as rollback_exc:
                logger.error("Failed to roll back directory swap for %s: %s", install_dir, rollback_exc)
            raise
        shutil.rmtree(old, ignore_errors=True)

    @staticmethod
    def _place_file(src: Path, dest: Path) -> None:
        """Copy ``src`` onto ``dest`` through a same-directory temp name and ``os.replace``.

        ``os.replace`` swaps the directory entry, so a hardlinked ``dest`` is not
        written through. A crash during the copy leaves the previous ``dest`` in place.
        If the copy produces no file, ``dest`` is left unchanged and the caller checks.
        """
        src = Path(src)
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_symlink():
            dest.unlink()
        elif dest.is_dir():
            shutil.rmtree(dest)
        partial = dest.with_name(dest.name + ".vnpm-partial")
        if partial.is_symlink() or (partial.exists() and not partial.is_dir()):
            partial.unlink()
        elif partial.is_dir():
            shutil.rmtree(partial)
        try:
            shutil.copy2(src, partial)
            if not partial.exists():
                return
            os.replace(partial, dest)
        finally:
            if partial.exists():
                try:
                    partial.unlink()
                except OSError:
                    pass

    @staticmethod
    def _clone_tree(
        src: Path,
        dest: Path,
        skip_dir_names: Optional[Iterable[str]] = None,
    ) -> None:
        """Reproduce ``src`` at ``dest``, hardlinking files when the filesystem allows.

        Directory symlinks are not followed. File symlinks are recreated. ``OSError``
        from ``os.link`` (exFAT, FAT, cross-device) falls back to ``_place_file``.
        """
        src = Path(src)
        dest = Path(dest)
        if not src.exists() and not src.is_symlink():
            return
        if src.is_symlink():
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists() and not dest.is_symlink():
                dest.symlink_to(os.readlink(src))
            return
        if not src.is_dir():
            BackupManager._place_file(src, dest)
            return

        skip = set(skip_dir_names or ())
        dest.mkdir(parents=True, exist_ok=True)
        for root, dirs, files in os.walk(src, followlinks=False):
            root_path = Path(root)
            target_root = dest / root_path.relative_to(src)
            target_root.mkdir(parents=True, exist_ok=True)
            kept_dirs = []
            for directory in dirs:
                dir_path = root_path / directory
                if directory in skip:
                    continue
                if dir_path.is_symlink():
                    link_dest = target_root / directory
                    if not link_dest.exists() and not link_dest.is_symlink():
                        link_dest.symlink_to(os.readlink(dir_path))
                    continue
                kept_dirs.append(directory)
            dirs[:] = kept_dirs
            for name in files:
                src_file = root_path / name
                dest_file = target_root / name
                if dest_file.exists() or dest_file.is_symlink():
                    continue
                if src_file.is_symlink():
                    dest_file.symlink_to(os.readlink(src_file))
                    continue
                try:
                    os.link(src_file, dest_file, follow_symlinks=False)
                except OSError:
                    BackupManager._place_file(src_file, dest_file)

    @staticmethod
    def compute_sha256(file_path: Path) -> str:
        """Computes the SHA256 hex digest of a file in 64KB chunks."""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    def has_backup(game_install_path: Union[str, Path]) -> bool:
        """Checks if a valid backup with manifest exists in the game's .backup directory."""
        backup_root = Path(game_install_path) / BackupManager.BACKUP_DIR_NAME
        if not backup_root.exists() or not backup_root.is_dir():
            return False
        for item in backup_root.iterdir():
            if item.is_dir() and (item / BackupManager.MANIFEST_NAME).exists():
                return True
        return False

    @staticmethod
    def get_latest_backup(game_install_path: Union[str, Path]) -> Tuple[Optional[Path], Optional[Dict[str, Any]]]:
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
    def has_clean_backup(game_install_path: Union[str, Path]) -> bool:
        """Returns True if the newest backup is marked clean and free of pre-existing patch files."""
        _, manifest = BackupManager.get_latest_backup(game_install_path)
        if not manifest:
            return False
        return manifest.get("is_clean_original", True) is True

    @staticmethod
    def create_backup(
        game_install_path: Union[str, Path],
        app_id: Union[str, int],
        game_name: str,
        patch_source_dir: Optional[Union[str, Path]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        backup_parent: Optional[Union[str, Path]] = None,
    ) -> Path:
        """
        Computes SHA256 checksums of all original game files, stores them in
        .backup/<timestamp>/ with a manifest.json. Pass ``backup_parent`` to write
        that directory under a staging tree instead of the live install.
        Checks for patch file hash collisions to detect pre-patched games.
        """
        install_dir = Path(game_install_path)
        if not install_dir.exists():
            raise BackupError(f"Game directory does not exist: {install_dir}")

        now = time.time()
        iso_str = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
        folder_tag = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y%m%d_%H%M%S")

        parent = Path(backup_parent) if backup_parent is not None else install_dir
        backup_dir = parent / BackupManager.BACKUP_DIR_NAME / f"backup_{folder_tag}"
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
            # Prune .backup directory so os.walk does not descend into it
            dirs[:] = [d for d in dirs if d != BackupManager.BACKUP_DIR_NAME]
            root_path = Path(root)
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
    def _overlay_live_saves(install_dir: Path, staging: Path) -> None:
        """Copy protected save files from the live install onto the staged tree."""
        if not install_dir.exists():
            return
        for root, dirs, files in os.walk(install_dir, followlinks=False):
            dirs[:] = [d for d in dirs if d != BackupManager.BACKUP_DIR_NAME]
            root_path = Path(root)
            if BackupManager.BACKUP_DIR_NAME in root_path.parts:
                continue
            for file_name in files:
                full_path = root_path / file_name
                rel = full_path.relative_to(install_dir)
                if not BackupManager.is_protected_save_path(rel):
                    continue
                BackupManager._place_file(full_path, staging / rel)

    @staticmethod
    def restore_backup(
        game_install_path: Union[str, Path],
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """
        Restores original game files from the latest backup.

        The next tree is built in a sibling directory, checked, then swapped in
        with two renames. Save files are copied from the live tree and are not
        replaced by backup bytes or resurrected if the user deleted them.
        """
        install_dir = Path(game_install_path)
        BackupManager.recover_interrupted_swap(install_dir)
        latest_dir, manifest = BackupManager.get_latest_backup(install_dir)

        if not latest_dir or not manifest:
            raise BackupError("No valid backup found to restore.")

        if log_callback:
            log_callback(f"Verifying backup integrity from {latest_dir.name}...")

        files_backup_dir = latest_dir / "files"
        manifest_files = manifest.get("files", {})

        # Read-only integrity check. Nothing in the live install is renamed yet.
        for rel_path_str, meta in manifest_files.items():
            backup_file = files_backup_dir / rel_path_str
            if not backup_file.exists():
                raise BackupError(f"Corrupted backup: missing file '{rel_path_str}' in backup storage.")
            current_hash = BackupManager.compute_sha256(backup_file)
            if current_hash != meta["sha256"]:
                raise BackupError(f"Corrupted backup: checksum mismatch for '{rel_path_str}'.")

        if log_callback:
            log_callback("Restoring original files and purging patch files...")

        staging = None
        swapped = False
        try:
            staging = BackupManager.make_staging_dir(install_dir)
            if log_callback:
                log_callback("Verifying restored file integrity...")

            for rel_path_str, meta in manifest_files.items():
                if BackupManager.is_protected_save_path(rel_path_str):
                    continue
                staged_file = staging / rel_path_str
                BackupManager._place_file(files_backup_dir / rel_path_str, staged_file)
                if not staged_file.exists():
                    raise BackupError(f"Rollback failed: restored file '{rel_path_str}' missing.")
                restored_hash = BackupManager.compute_sha256(staged_file)
                if restored_hash != meta["sha256"]:
                    raise BackupError(f"Rollback failed: restored checksum mismatch for '{rel_path_str}'.")

            BackupManager._overlay_live_saves(install_dir, staging)
            backup_root = install_dir / BackupManager.BACKUP_DIR_NAME
            if backup_root.exists():
                BackupManager._clone_tree(backup_root, staging / BackupManager.BACKUP_DIR_NAME)

            BackupManager.commit_directory_swap(staging, install_dir)
            swapped = True
        finally:
            if staging is not None and staging.exists() and not swapped:
                shutil.rmtree(staging, ignore_errors=True)
            # A finished swap, or a second rename that was rolled back, leaves the
            # install in place. A crash between the renames leaves .vnpm-old for
            # the next recover_interrupted_swap call and must not be deleted here.
            if install_dir.exists():
                BackupManager.recover_interrupted_swap(install_dir)

        if log_callback:
            log_callback("Rollback successful! Original game restored.")

        return True
