import os
import json
import shutil
import tempfile
import time
import subprocess
from pathlib import Path
import logging
from typing import Any, Callable, Dict, Optional, Union

from .steam_scanner import SteamScanner
from .backup_manager import BackupManager
from .exceptions import BackupError, PatchSecurityError, PatchExtractionError, ProtonExecutionError

logger = logging.getLogger(__name__)

# Patch sources are copied here so Proton does not mmap a NAS mount and so
# extraction does not fill the small /tmp tmpfs used on SteamOS. The game
# clone stays a sibling of the install; this directory is not that clone.
PATCH_SOURCE_ROOT = Path.home() / ".cache" / "vnpatchmanager" / "patch-sources"

_SUPPORTED_ARCHIVE_SUFFIXES = ".zip, .tar, .tar.gz, .tgz, .tar.bz2, .tbz2, .tar.xz, .txz, .7z, .rar"


class PatchExecutionEngine:
    """Handles the actual copying of files and execution of Proton patches."""

    @staticmethod
    def _safe_extract_zip(zf: Any, extract_tmp: Path) -> None:
        extract_tmp_resolved = str(extract_tmp.resolve())
        for member in zf.namelist():
            member_path = str((extract_tmp / member).resolve())
            if os.path.commonpath([extract_tmp_resolved, member_path]) != extract_tmp_resolved:
                raise PatchSecurityError(f"Zip slip detected: {member} attempts to escape target directory")
        zf.extractall(extract_tmp)

    @staticmethod
    def _safe_extract_tar(tar: Any, extract_tmp: Path) -> None:
        extract_tmp_resolved = str(extract_tmp.resolve())
        for member in tar.getmembers():
            member_path = str((extract_tmp / member.name).resolve())
            if os.path.commonpath([extract_tmp_resolved, member_path]) != extract_tmp_resolved:
                raise PatchSecurityError(f"Tar slip detected: {member.name} attempts to escape target directory")
        tar.extractall(extract_tmp)

    @staticmethod
    def _validate_extracted_tree(extract_dir: Path) -> None:
        """Validates that all extracted files and symlinks stay strictly within extract_dir."""
        base_resolved = extract_dir.resolve()
        base_str = str(base_resolved)
        for root, dirs, files in os.walk(extract_dir, followlinks=False):
            root_path = Path(root)
            if os.path.commonpath([base_str, str(root_path.resolve())]) != base_str:
                raise PatchSecurityError(f"Directory traversal detected: {root_path} escapes {extract_dir}")
            for item in dirs + files:
                item_path = root_path / item
                if item_path.is_symlink():
                    target_resolved = item_path.resolve()
                    if os.path.commonpath([base_str, str(target_resolved)]) != base_str:
                        raise PatchSecurityError(
                            f"Symlink traversal detected: {item_path.name} -> {target_resolved} escapes {extract_dir}"
                        )
                else:
                    item_resolved = item_path.resolve()
                    if os.path.commonpath([base_str, str(item_resolved)]) != base_str:
                        raise PatchSecurityError(
                            f"Path traversal detected: {item_path.name} escapes {extract_dir}"
                        )

    @staticmethod
    def _resolve_action_destination(destination: Optional[str], root: Path) -> Path:
        """Resolve a patch destination and require it to stay inside ``root``.

        ``{game_dir}`` is replaced with ``root``. A relative path is anchored at
        ``root``. ``resolve()`` collapses ``..`` and follows existing symlinks.
        Nothing is created.
        """
        root_resolved = Path(root).resolve()
        raw = destination if destination else "{game_dir}"
        replaced = raw.replace("{game_dir}", str(root_resolved))
        candidate = Path(replaced)
        if not candidate.is_absolute():
            candidate = root_resolved / candidate
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root_resolved):
            raise PatchSecurityError(
                f"Destination escapes the install directory: {destination}"
            )
        return resolved

    @staticmethod
    def _reject_archive_member(name: str, extract_dir: Path) -> None:
        """Reject a member name that would leave ``extract_dir``. Does not extract."""
        normalized = (name or "").replace("\\", "/").strip()
        if not normalized:
            raise PatchSecurityError("Archive member path is empty")
        drive_prefix = len(normalized) >= 2 and normalized[0].isalpha() and normalized[1] == ":"
        if normalized.startswith("/") or drive_prefix:
            raise PatchSecurityError(f"Archive member escapes the extract directory: {name}")
        if any(part == ".." for part in normalized.split("/")):
            raise PatchSecurityError(f"Archive member escapes the extract directory: {name}")
        extract_resolved = Path(extract_dir).resolve()
        candidate = (extract_resolved / normalized).resolve()
        if not candidate.is_relative_to(extract_resolved):
            raise PatchSecurityError(f"Archive member escapes the extract directory: {name}")

    @staticmethod
    def _run_archive_listing(cmd: list, archive_name: str) -> str:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            raise PatchExtractionError(f"Failed to list archive {archive_name}: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise PatchExtractionError(
                f"Failed to list archive {archive_name} (code {result.returncode}). {detail}"
            )
        return result.stdout or ""

    @staticmethod
    def _list_7z_members(archive: Path) -> list:
        stdout = PatchExecutionEngine._run_archive_listing(
            ["7z", "l", "-ba", "-slt", str(archive)],
            archive.name,
        )
        ignored = {archive.name, str(archive), str(archive.resolve())}
        names = []
        for line in stdout.splitlines():
            stripped = line.strip()
            if not stripped.startswith("Path = "):
                continue
            value = stripped.split(" = ", 1)[1]
            if value in ignored:
                continue
            names.append(value)
        if not names:
            raise PatchExtractionError(f"7z listing produced no members: {archive.name}")
        return names

    @staticmethod
    def _list_unrar_members(archive: Path) -> list:
        stdout = PatchExecutionEngine._run_archive_listing(
            ["unrar", "lb", "-p-", str(archive)],
            archive.name,
        )
        names = [line.strip() for line in stdout.splitlines() if line.strip()]
        if not names:
            raise PatchExtractionError(f"unrar listing produced no members: {archive.name}")
        return names

    @staticmethod
    def _reject_listed_members(names: list, extract_dir: Path) -> None:
        for name in names:
            PatchExecutionEngine._reject_archive_member(name, extract_dir)

    @staticmethod
    def get_patch_status(
        game_install_path: Optional[Union[str, Path]],
        patch_data: Optional[Dict[str, Any]] = None,
        vn_info: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Checks if a patch is applied to the game directory.
        1. Checks for VNPM .patch_applied.json tracking manifest.
        2. If patch_data is supplied, checks if the patch's target files/payloads exist in game directory.
        3. Checks for well-known engine 18+ patch signature files.
        """
        if not game_install_path:
            return False

        game_path = Path(game_install_path)
        if not game_path.exists():
            return False

        # 1. VNPM Tracking File
        tracking_file = game_path / ".patch_applied.json"
        if tracking_file.exists():
            return True

        # 2. Check via patch_data actions if available
        if patch_data and isinstance(patch_data, dict):
            patch_src_dir = Path(patch_data.get("patch_source_dir", ""))
            actions = patch_data.get("actions", [])
            for action in actions:
                atype = action.get("type")
                source = action.get("source", "")
                destination = action.get("destination", "{game_dir}/")
                try:
                    PatchExecutionEngine._resolve_action_destination(destination, game_path)
                except PatchSecurityError as exc:
                    logger.warning("Skipping patch status check outside the install: %s", exc)
                    continue

                dest_clean = destination.replace("{game_dir}", "").strip("/\\")
                target_dir = (game_path / dest_clean) if dest_clean else game_path

                # Specific patch payload files or directory copies
                if atype in ("copy_file", "copy_directory"):
                    src_check = (patch_src_dir / source) if patch_src_dir.exists() else None
                    if source in [".", "patch_data"] or (src_check and src_check.is_dir()):
                        src_dir = (patch_src_dir / source) if source != "." else patch_src_dir
                        if src_dir.exists() and src_dir.is_dir():
                            src_files = [f for f in src_dir.glob("*") if f.is_file() and not f.name.endswith(".txt")]
                            for sf in src_files:
                                installed_file = target_dir / sf.name
                                if not installed_file.exists():
                                    installed_file = game_path / sf.name
                                if installed_file.exists():
                                    try:
                                        if installed_file.stat().st_size == sf.stat().st_size:
                                            return True
                                    except OSError:
                                        pass
                    else:
                        src_file = patch_src_dir / source if patch_src_dir.exists() else None
                        installed_file = target_dir / source if (source.endswith(".rpa") or dest_clean) else (game_path / source)
                        if not installed_file.exists():
                            installed_file = (game_path / "game" / source) if source.endswith(".rpa") else (game_path / source)

                        if installed_file.exists() and installed_file.is_file():
                            if src_file and src_file.exists() and src_file.is_file():
                                try:
                                    if installed_file.stat().st_size == src_file.stat().st_size:
                                        return True
                                except OSError:
                                    pass
                            else:
                                if source.lower() not in ["assets.rpa", "archive.rpa", "data.xp3"]:
                                    return True

                # Archive extraction
                if atype == "extract_archive":
                    arc_path = patch_src_dir / source if patch_src_dir.exists() else None
                    if arc_path and arc_path.exists():
                        if source.lower().endswith(".zip"):
                            try:
                                import zipfile
                                with zipfile.ZipFile(arc_path, "r") as zf:
                                    for info in zf.infolist():
                                        if info.is_dir() or info.filename.endswith(".txt"):
                                            continue
                                        fname = Path(info.filename).name
                                        installed_f = target_dir / fname
                                        if not installed_f.exists():
                                            installed_f = game_path / fname
                                        if installed_f.exists() and installed_f.stat().st_size == info.file_size:
                                            return True
                            except Exception as e:
                                logger.warning(f"Error checking zip members: {e}")

        # 3. Known Engine Patch Signature files
        game_sub = game_path / "game"
        if game_sub.exists():
            # Distinct 18+ Ren'Py patch additions
            for rpa_name in ["patch0x.rpa", "r18.rpa", "patch.rpa", "adult.rpa"]:
                if (game_sub / rpa_name).exists():
                    return True

        # Kirikiri / XP3
        for xp3_name in ["adult.xp3", "adultsonly.xp3", "adult2.xp3", "adult_patch.xp3"]:
            if (game_path / xp3_name).exists():
                return True

        # Artemis / PFS DLC & patch increments (.040, .041, .050, root.pfs.010)
        pfs_patches = list(game_path.glob("*.pfs.04*")) + list(game_path.glob("*.pfs.05*")) + list(game_path.glob("root.pfs.01*"))
        if pfs_patches:
            return True

        # CatSystem2 / NOA patches
        if (game_path / "patch1.noa").exists() or (game_path / "patch.noa").exists():
            return True

        # BGI patch files
        if (game_path / "ReadMe-Install Instruction.txt").exists():
            return True

        return False

    @staticmethod
    def _find_proton_executable(library_path: Optional[Union[str, Path]] = None) -> Optional[Path]:
        """
        Attempts to find a Proton installation across:
        1. The target game library path (if provided).
        2. The primary Steam root library (~/.local/share/Steam/steamapps/common).
        3. All library paths registered in libraryfolders.vdf (e.g. MicroSD cards on Steam Deck).
        4. Custom compatibility tools directories (compatibilitytools.d for GE-Proton).
        """
        candidates = []
        checked_common_dirs = set()
        checked_compat_dirs = set()

        # 1. Target game library
        if library_path:
            p = Path(library_path) / "steamapps" / "common"
            if p.exists():
                checked_common_dirs.add(p.resolve())

        # 2. Primary Steam root & registered libraries
        steam_root = SteamScanner.get_steam_root()
        if steam_root:
            p = steam_root / "steamapps" / "common"
            if p.exists():
                checked_common_dirs.add(p.resolve())

            # 3. Parse libraryfolders.vdf
            vdf_file = steam_root / "steamapps" / "libraryfolders.vdf"
            if vdf_file.exists():
                try:
                    import vdf
                    with open(vdf_file, "r") as f:
                        data = vdf.load(f)
                    for lib in data.get("libraryfolders", {}).values():
                        lpath = lib.get("path")
                        if lpath:
                            c_dir = Path(lpath) / "steamapps" / "common"
                            if c_dir.exists():
                                checked_common_dirs.add(c_dir.resolve())
                except Exception as e:
                    logger.warning(f"Failed to parse vdf: {e}")

            # 4. Compatibility tools (GE-Proton, custom Proton)
            for ct in [steam_root / "compatibilitytools.d", steam_root.parent / "compatibilitytools.d"]:
                if ct.exists():
                    checked_compat_dirs.add(ct.resolve())

        # Search common dirs
        for c_dir in checked_common_dirs:
            try:
                for item in c_dir.iterdir():
                    if ("Proton" in item.name or "GE-Proton" in item.name) and item.is_dir():
                        for bin_name in ["proton", "proton.sh", "files/bin/proton"]:
                            p_bin = item / bin_name
                            if p_bin.exists() and os.access(p_bin, os.X_OK):
                                candidates.append((item.name, p_bin))
                                break
            except OSError as e:
                logger.warning(f"Error accessing common dir: {e}")

        # Search compatibility tools dirs
        for ct_dir in checked_compat_dirs:
            try:
                for item in ct_dir.iterdir():
                    if item.is_dir():
                        for bin_name in ["proton", "proton.sh", "files/bin/proton"]:
                            p_bin = item / bin_name
                            if p_bin.exists() and os.access(p_bin, os.X_OK):
                                candidates.append((item.name, p_bin))
                                break
            except OSError as e:
                logger.warning(f"Error accessing compat dir: {e}")

        if not candidates:
            return None

        # Sort so highest official/experimental/GE version is selected first
        def _proton_sort_key(item):
            name = item[0]
            if "Experimental" in name:
                return (100, 0, name)
            import re
            m = re.search(r'(\d+)(?:\.(\d+))?', name)
            if m:
                major = int(m.group(1))
                minor = int(m.group(2)) if m.group(2) else 0
                return (major, minor, name)
            return (0, 0, name)

        candidates.sort(key=_proton_sort_key, reverse=True)
        return candidates[0][1]

    @staticmethod
    def rollback_patch(game_data, log_callback=None):
        """Rolls back applied patches and restores original game files."""
        install_dir = Path(game_data['path'])
        return BackupManager.restore_backup(install_dir, log_callback)

    @staticmethod
    def restore_via_steam(
        game_data: Dict[str, Any],
        patch_data: Optional[Dict[str, Any]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """
        Purges patch tracking and known patch files, then triggers Steam to verify
        and re-download original unpatched files directly from Steam CDN.
        """
        install_dir = Path(game_data['path'])
        app_id = str(game_data.get('steam_app_id') or '')
        if not app_id and patch_data:
            app_id = str(patch_data.get('steam_app_id', ''))

        if log_callback:
            log_callback(f"Purging patch artifacts for {game_data['name']}...")

        # 1. Remove .patch_applied.json
        tracking_file = install_dir / ".patch_applied.json"
        if tracking_file.exists():
            try:
                tracking_file.unlink()
            except OSError as e:
                logger.warning(f"Failed to unlink tracking file: {e}")

        # 2. Purge extraneous files using clean backup manifest if available
        # When a clean original backup manifest is recorded, any file currently in install_dir
        # that was not in the original manifest is an untracked patch addition.
        if BackupManager.has_clean_backup(install_dir):
            _, manifest = BackupManager.get_latest_backup(install_dir)
            if manifest and "files" in manifest:
                orig_files = set(manifest["files"].keys())
                for root, dirs, files in os.walk(install_dir, topdown=False):
                    dirs[:] = [d for d in dirs if d != BackupManager.BACKUP_DIR_NAME]
                    root_path = Path(root)
                    if BackupManager.BACKUP_DIR_NAME in root_path.parts:
                        continue
                    for file_name in files:
                        full_p = root_path / file_name
                        rel_p = str(full_p.relative_to(install_dir))
                        if rel_p not in orig_files and file_name != ".patch_applied.json":
                            if BackupManager.is_protected_save_path(rel_p):
                                continue
                            try:
                                full_p.unlink()
                                logger.info(f"Purged extraneous patch file: {rel_p}")
                            except OSError as e:
                                logger.warning(f"Failed to unlink {full_p}: {e}")
                    # Remove empty directories (except install_dir and .backup)
                    if root_path != install_dir and not any(root_path.iterdir()):
                        try:
                            root_path.rmdir()
                        except OSError:
                            pass

        # 3. If actions in patch_data copied specific non-vanilla files, remove them
        if patch_data:
            actions = patch_data.get('actions', [])
            patch_src_dir = Path(patch_data.get("patch_source_dir", ""))
            for action in actions:
                atype = action.get('type')
                if atype not in ('copy_file', 'copy_directory', 'extract_archive'):
                    continue
                raw_dest = action.get('destination', '')
                try:
                    dest_path = PatchExecutionEngine._resolve_action_destination(raw_dest, install_dir)
                except PatchSecurityError as exc:
                    logger.warning("Skipping patch cleanup outside the install: %s", exc)
                    continue
                if atype == 'copy_file':
                    if dest_path.exists() and not dest_path.is_dir():
                        try:
                            dest_path.unlink()
                        except OSError as e:
                            logger.warning(f"Failed to unlink {dest_path}: {e}")
                elif atype == 'copy_directory':
                    if dest_path.exists() and dest_path != install_dir.resolve():
                        try:
                            shutil.rmtree(dest_path, ignore_errors=True)
                        except OSError as e:
                            logger.warning(f"Failed to remove directory {dest_path}: {e}")
                elif atype == 'extract_archive':
                    source_arc = action.get('source', '')
                    arc_path = patch_src_dir / source_arc if patch_src_dir.exists() else None
                    if arc_path and arc_path.exists():
                        try:
                            if source_arc.lower().endswith((".zip", ".tar.gz", ".tgz")):
                                import zipfile
                                import tarfile
                                member_names = []
                                if zipfile.is_zipfile(arc_path):
                                    with zipfile.ZipFile(arc_path, "r") as zf:
                                        member_names = [Path(m).name for m in zf.namelist() if not m.endswith("/")]
                                elif tarfile.is_tarfile(arc_path):
                                    with tarfile.open(arc_path, "r:*") as tf:
                                        member_names = [Path(m.name).name for m in tf.getmembers() if m.isfile()]
                                for mname in member_names:
                                    target_m = dest_path / mname
                                    if target_m.exists() and target_m.is_file():
                                        try:
                                            target_m.unlink()
                                        except OSError as e:
                                            logger.warning(f"Failed to unlink {target_m}: {e}")
                        except Exception as e:
                            logger.warning(f"Error inspecting archive for cleanup: {e}")

        # 4. Universal purge of known engine patch signature files & patcher executables
        # Steam depot validation will NEVER remove non-depot files dropped into the game folder.
        sig_files = [
            # Ren'Py
            install_dir / "game" / "patch0x.rpa",
            install_dir / "game" / "r18.rpa",
            install_dir / "game" / "patch.rpa",
            install_dir / "game" / "adult.rpa",
            # Kirikiri
            install_dir / "adult.xp3",
            install_dir / "adultsonly.xp3",
            install_dir / "adult2.xp3",
            install_dir / "adult_patch.xp3",
            install_dir / "patch.xp3",
            # CatSystem2
            install_dir / "patch1.noa",
            install_dir / "patch.noa",
            # BGI
            install_dir / "ReadMe-Install Instruction.txt",
            # Common patch tools
            install_dir / "HPatch.exe",
            install_dir / "patch.exe",
            install_dir / "r18_patch.exe",
            install_dir / "hpatchz.exe",
        ]
        # Artemis PFS increments (*.pfs.04*, *.pfs.05*, root.pfs.01*)
        for pfs_pattern in ["*.pfs.04*", "*.pfs.05*", "root.pfs.01*"]:
            for pfs_file in install_dir.glob(pfs_pattern):
                if pfs_file.is_file():
                    sig_files.append(pfs_file)

        for sfile in sig_files:
            if sfile.exists() and sfile.is_file():
                try:
                    sfile.unlink()
                    logger.info(f"Purged patch signature file: {sfile.name}")
                except OSError as e:
                    logger.warning(f"Failed to unlink signature file {sfile}: {e}")

        # 5. Clean up dirty backups if any exists that are not clean
        backup_root = install_dir / BackupManager.BACKUP_DIR_NAME
        if backup_root.exists() and not BackupManager.has_clean_backup(install_dir):
            try:
                shutil.rmtree(backup_root, ignore_errors=True)
            except OSError as e:
                logger.warning(f"Failed to remove backup root: {e}")

        # 4. Launch Steam verification
        if not app_id:
            logger.warning(f"Cannot initiate Steam restore: Steam AppID could not be determined for {game_data.get('name')}.")
            if log_callback:
                log_callback(f"Failed to initiate Steam verification: AppID not found for {game_data.get('name')}.")
            return False

        if log_callback:
            log_callback(f"Launching Steam verification (AppID {app_id})...")

        steam_launched = False
        try:
            subprocess.Popen(["steam", f"steam://validate/{app_id}"])
            steam_launched = True
        except OSError as e:
            logger.warning(f"Failed to launch steam command: {e}")
            try:
                subprocess.Popen(["xdg-open", f"steam://validate/{app_id}"])
                steam_launched = True
            except OSError as ex:
                logger.error(f"Error launching Steam URL: {ex}")

        if steam_launched:
            if log_callback:
                log_callback("Steam verification initiated! Steam will validate & restore original files.")
            return True
        else:
            if log_callback:
                log_callback(f"Please verify {game_data['name']} files in the Steam client properties.")
            return False

    @staticmethod
    def _fingerprint_install(install_dir: Path) -> Dict[str, tuple]:
        """Stat fingerprint of the live install, excluding the backup store."""
        fingerprint: Dict[str, tuple] = {}
        install_dir = Path(install_dir)
        if not install_dir.exists():
            return fingerprint
        for root, dirs, files in os.walk(install_dir, followlinks=False):
            dirs[:] = [d for d in dirs if d != BackupManager.BACKUP_DIR_NAME]
            root_path = Path(root)
            if BackupManager.BACKUP_DIR_NAME in root_path.parts:
                continue
            for name in files:
                path = root_path / name
                try:
                    st = path.lstat() if path.is_symlink() else path.stat()
                except OSError:
                    continue
                rel = str(path.relative_to(install_dir))
                fingerprint[rel] = (st.st_dev, st.st_ino, st.st_size, getattr(st, "st_mtime_ns", st.st_mtime))
        return fingerprint

    @staticmethod
    def _require_live_unchanged(install_dir: Path, baseline: Dict[str, tuple]) -> None:
        current = PatchExecutionEngine._fingerprint_install(install_dir)
        if current != baseline:
            raise PatchExtractionError("Live install was modified during staging; aborting commit.")

    @staticmethod
    def _merge_tree(src_dir: Path, dest_dir: Path) -> None:
        """Copy ``src_dir`` into ``dest_dir`` without writing through hardlinked files."""
        src_dir = Path(src_dir)
        dest_dir = Path(dest_dir)
        if dest_dir.is_symlink() or (dest_dir.exists() and not dest_dir.is_dir()):
            dest_dir.unlink()
        dest_dir.mkdir(parents=True, exist_ok=True)
        for root, dirs, files in os.walk(src_dir, followlinks=False):
            root_path = Path(root)
            target_root = dest_dir / root_path.relative_to(src_dir)
            target_root.mkdir(parents=True, exist_ok=True)
            kept_dirs = []
            for directory in dirs:
                dir_path = root_path / directory
                if dir_path.is_symlink():
                    link_dest = target_root / directory
                    if link_dest.is_dir() and not link_dest.is_symlink():
                        shutil.rmtree(link_dest)
                    elif link_dest.exists() or link_dest.is_symlink():
                        link_dest.unlink()
                    link_dest.symlink_to(os.readlink(dir_path))
                    continue
                kept_dirs.append(directory)
            dirs[:] = kept_dirs
            for name in files:
                src_file = root_path / name
                dest_file = target_root / name
                if src_file.is_symlink():
                    if dest_file.is_dir() and not dest_file.is_symlink():
                        shutil.rmtree(dest_file)
                    elif dest_file.exists() or dest_file.is_symlink():
                        dest_file.unlink()
                    dest_file.symlink_to(os.readlink(src_file))
                    continue
                BackupManager._place_file(src_file, dest_file)

    @staticmethod
    def apply_patch(
        game_data: Dict[str, Any],
        patch_data: Dict[str, Any],
        config_manager: Any,
        log_callback: Callable[[str], None],
    ) -> bool:
        """Applies the patch logic based on the 'actions' from patch.json"""
        app_id = patch_data.get('steam_app_id')
        install_dir = Path(game_data['path'])
        library_path = Path(game_data['library_path'])
        source_dir = patch_data.get('patch_source_dir')
        mode = config_manager.config.get('mode')
        actions = patch_data.get('actions', [])

        temp_dir = None
        game_staging = None
        swapped = False
        working_source = Path(source_dir)

        try:
            log_callback(f"Starting patch for {game_data['name']}...")
            BackupManager.recover_interrupted_swap(install_dir)
            if not install_dir.exists():
                raise BackupError(f"Game directory does not exist: {install_dir}")

            # Fingerprint the live tree before any staging so a leaked write aborts the commit.
            live_baseline = PatchExecutionEngine._fingerprint_install(install_dir)
            game_staging = BackupManager.make_staging_dir(install_dir)
            BackupManager._clone_tree(
                install_dir,
                game_staging,
                skip_dir_names={BackupManager.BACKUP_DIR_NAME},
            )
            stage_root = game_staging
            PatchExecutionEngine._require_live_unchanged(install_dir, live_baseline)

            # Stage patch sources on the home cache disk. Proton must not mmap a NAS
            # mount, and the default temp directory is a small tmpfs on SteamOS.
            # The game shadow above stays a sibling of the install so the final
            # rename stays on one filesystem.
            log_callback("Staging patch files to a local temporary folder...")
            PATCH_SOURCE_ROOT.mkdir(parents=True, exist_ok=True)
            os.chmod(PATCH_SOURCE_ROOT, 0o700)
            temp_dir = tempfile.mkdtemp(prefix=f"vnpatch_{app_id}_", dir=PATCH_SOURCE_ROOT)
            working_source = Path(temp_dir)

            if mode == 'smb':
                import smbclient.shutil
                # Copy contents from the SMB share to our local temp directory
                for item in smbclient.listdir(source_dir):
                    src_item = rf"{source_dir}\{item}"
                    dst_item = working_source / item
                    if smbclient.stat(src_item).st_mode & 0o040000: # is directory
                        smbclient.shutil.copytree(src_item, str(dst_item))
                    else:
                        smbclient.shutil.copyfile(src_item, str(dst_item))
            else:
                # Local mode (which is often an fstab NAS mount).
                # We copy to local disk to avoid Wine mmap/locking crashes.
                shutil.copytree(source_dir, working_source, dirs_exist_ok=True)

            # 2. Execute Actions
            for i, action in enumerate(actions):
                action_type = action.get('type')
                log_callback(f"Executing step {i+1}/{len(actions)}: {action_type}...")

                if action_type == 'copy_file':
                    src_file = working_source / action.get('source', '')
                    raw_dest = action.get('destination', '')
                    dest_path = PatchExecutionEngine._resolve_action_destination(raw_dest, stage_root)

                    logger.debug(f"Attempting to copy from '{src_file}' to '{dest_path}'")

                    if not src_file.exists():
                        raise PatchExtractionError(f"Source file/folder does not exist: {src_file}")

                    if src_file.is_dir():
                        PatchExecutionEngine._merge_tree(src_file, dest_path)
                    else:
                        # If destination ends in a slash, treat it as a directory to copy into
                        if raw_dest.endswith('/') or dest_path.is_dir():
                            dest_path.mkdir(parents=True, exist_ok=True)
                            BackupManager._place_file(src_file, dest_path / src_file.name)
                        else:
                            BackupManager._place_file(src_file, dest_path)

                elif action_type == 'extract_inno_setup':
                    exe_file = working_source / action.get('source', '')
                    raw_dest = action.get('destination', '{game_dir}')
                    dest_path = PatchExecutionEngine._resolve_action_destination(raw_dest, stage_root)

                    if not shutil.which("innoextract"):
                        raise PatchExtractionError("innoextract is not installed. Please install it (sudo pacman -S innoextract).")

                    logger.debug(f"Checking for executable at: {exe_file}")

                    # 1. Check if the file actually exists
                    if not exe_file.exists():
                        files_present = [f.name for f in working_source.iterdir()]
                        raise PatchExtractionError(f"File not found: '{exe_file.name}'\nCheck patch.json for typos (Linux is case-sensitive!)\nFiles actually in folder: {files_present}")

                    # 2. Check if we have read permissions (NAS copies can sometimes be strict)
                    if not os.access(exe_file, os.R_OK):
                        logger.debug(f"Missing read permissions on {exe_file}. Attempting to fix...")
                        exe_file.chmod(0o644)

                    log_callback("Extracting natively using innoextract...")

                    # Extract to a temporary sub-folder first because Inno Setup packages
                    # usually hide the actual game files inside an internal 'app/' folder.
                    extract_tmp = working_source / "inno_extracted"
                    extract_tmp.mkdir(exist_ok=True)

                    cmd = ["innoextract", "-s", "-d", str(extract_tmp), str(exe_file)]
                    logger.debug(f"Running innoextract command: {cmd}")

                    try:
                        process = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                    except subprocess.TimeoutExpired:
                        raise PatchExtractionError("innoextract timed out after 5 minutes.")
                    if process.returncode != 0:
                        logger.error(f"innoextract Error Output:\n{process.stderr}\n{process.stdout}")
                        raise PatchExtractionError(f"innoextract failed with code {process.returncode}")

                    # Check if the "app" folder exists. If so, that's what we want to copy.
                    app_dir = extract_tmp / "app"
                    source_copy_dir = app_dir if app_dir.exists() else extract_tmp

                    PatchExecutionEngine._validate_extracted_tree(extract_tmp)

                    log_callback("Copying extracted files to game directory...")
                    PatchExecutionEngine._merge_tree(source_copy_dir, dest_path)

                elif action_type == 'extract_archive':
                    arc_file = working_source / action.get('source', '')
                    raw_dest = action.get('destination', '{game_dir}')
                    dest_path = PatchExecutionEngine._resolve_action_destination(raw_dest, stage_root)

                    if not arc_file.exists():
                        raise PatchExtractionError(f"Archive file not found: {arc_file}")

                    log_callback(f"Extracting {arc_file.name} to game directory...")
                    extract_tmp = working_source / f"extracted_{arc_file.stem}"
                    arc_name = arc_file.name.lower()

                    if arc_name.endswith('.zip'):
                        import zipfile
                        dest_path.mkdir(parents=True, exist_ok=True)
                        extract_tmp.mkdir(exist_ok=True)
                        with zipfile.ZipFile(arc_file, 'r') as zf:
                            PatchExecutionEngine._safe_extract_zip(zf, extract_tmp)
                    elif arc_name.endswith(('.tar.gz', '.tar.bz2', '.tar.xz', '.tar', '.tgz', '.tbz2', '.txz')):
                        import tarfile
                        dest_path.mkdir(parents=True, exist_ok=True)
                        extract_tmp.mkdir(exist_ok=True)
                        with tarfile.open(arc_file, 'r') as tar:
                            PatchExecutionEngine._safe_extract_tar(tar, extract_tmp)
                    elif arc_file.suffix.lower() == '.7z':
                        if not shutil.which("7z"):
                            raise PatchExtractionError("7z tool not found. Please install p7zip (sudo pacman -S p7zip).")
                        PatchExecutionEngine._reject_listed_members(
                            PatchExecutionEngine._list_7z_members(arc_file),
                            extract_tmp,
                        )
                        dest_path.mkdir(parents=True, exist_ok=True)
                        extract_tmp.mkdir(exist_ok=True)
                        subprocess.run(["7z", "x", "-y", f"-o{extract_tmp}", str(arc_file)], check=True)
                    elif arc_file.suffix.lower() == '.rar':
                        if shutil.which("unrar"):
                            PatchExecutionEngine._reject_listed_members(
                                PatchExecutionEngine._list_unrar_members(arc_file),
                                extract_tmp,
                            )
                            dest_path.mkdir(parents=True, exist_ok=True)
                            extract_tmp.mkdir(exist_ok=True)
                            subprocess.run(["unrar", "x", "-o+", str(arc_file), str(extract_tmp)], check=True)
                        elif shutil.which("7z"):
                            PatchExecutionEngine._reject_listed_members(
                                PatchExecutionEngine._list_7z_members(arc_file),
                                extract_tmp,
                            )
                            dest_path.mkdir(parents=True, exist_ok=True)
                            extract_tmp.mkdir(exist_ok=True)
                            subprocess.run(["7z", "x", "-y", f"-o{extract_tmp}", str(arc_file)], check=True)
                        else:
                            raise PatchExtractionError("unrar or 7z tool not found. Please install unrar or 7z.")
                    else:
                        raise PatchExtractionError(
                            f"Unsupported archive type '{arc_file.name}'. "
                            f"Supported suffixes: {_SUPPORTED_ARCHIVE_SUFFIXES}."
                        )

                    PatchExecutionEngine._validate_extracted_tree(extract_tmp)

                    PatchExecutionEngine._merge_tree(extract_tmp, dest_path)

                elif action_type == 'run_proton_executable':
                    exe_file = working_source / action.get('source', '')

                    # 1. Safety Check: Verify the file actually exists before letting Wine crash
                    if not exe_file.exists():
                        files_present = [f.name for f in exe_file.parent.iterdir()] if exe_file.parent.exists() else []
                        raise ProtonExecutionError(f"Proton Error: File not found at '{exe_file}'.\nFiles in that folder: {files_present}")

                    # Proton/Wine maps the Linux root (/) to the Windows Z: drive.
                    # We must convert the path for Windows installers to understand it.
                    raw_win_dir = "Z:" + str(stage_root).replace('/', '\\')
                    # Wrap in literal quotes to protect spaces in Windows command line parsing
                    win_install_dir = f'"{raw_win_dir}"'

                    args = []
                    for arg in action.get('args', []):
                        arg_str = arg.replace("{game_dir}", str(stage_root))
                        arg_str = arg_str.replace("{game_dir_win}", win_install_dir)
                        args.append(arg_str)

                    proton_bin = PatchExecutionEngine._find_proton_executable(library_path)
                    if not proton_bin:
                        raise ProtonExecutionError("Could not find a Proton installation in your Steam library.")

                    compatdata_path = library_path / "steamapps" / "compatdata" / str(app_id)

                    log_callback(f"Running installer via {proton_bin.parent.name}...")

                    # Set up environment variables required by Proton
                    env = os.environ.copy()
                    env["STEAM_COMPAT_DATA_PATH"] = str(compatdata_path)
                    env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] = str(SteamScanner.get_steam_root())
                    env["STEAM_COMPAT_APP_ID"] = str(app_id)
                    # Explicitly set WINEPREFIX for better stability
                    env["WINEPREFIX"] = str(compatdata_path / "pfx")

                    cmd = [str(proton_bin), "run", str(exe_file)] + args
                    logger.debug(f"Running command: {cmd}")

                    exe_cwd = exe_file.parent
                    try:
                        process = subprocess.run(cmd, env=env, cwd=exe_cwd, capture_output=True, text=True, timeout=900)
                    except subprocess.TimeoutExpired:
                        raise ProtonExecutionError("Proton executable timed out after 15 minutes.")
                    if process.returncode != 0:
                        logger.error(f"Proton Error Output:\n{process.stderr}")
                        raise ProtonExecutionError(f"Proton executable failed with code {process.returncode}")
                else:
                    raise PatchExtractionError(f"Unknown patch action type: '{action_type}'. Check patch.json for errors.")

            PatchExecutionEngine._require_live_unchanged(install_dir, live_baseline)

            # Backup the still-pristine live tree into the staging directory, then swap.
            if BackupManager.has_backup(install_dir):
                BackupManager._clone_tree(
                    install_dir / BackupManager.BACKUP_DIR_NAME,
                    stage_root / BackupManager.BACKUP_DIR_NAME,
                )
            else:
                log_callback("Creating backup of original game files and computing SHA256 checksums...")
                BackupManager.create_backup(
                    install_dir,
                    app_id,
                    game_data['name'],
                    patch_source_dir=source_dir,
                    log_callback=log_callback,
                    backup_parent=stage_root,
                )
            PatchExecutionEngine._require_live_unchanged(install_dir, live_baseline)

            tracking_file = stage_root / ".patch_applied.json"
            metadata = {
                "steam_app_id": app_id,
                "game_name": game_data['name'],
                "applied_timestamp": time.time(),
                "status": "success",
                "actions_applied": len(actions)
            }
            with open(tracking_file, 'w') as f:
                json.dump(metadata, f)

            BackupManager.commit_directory_swap(stage_root, install_dir)
            swapped = True
            log_callback(f"Patch successfully applied to {game_data['name']}!")
            return True

        except Exception as e:
            logger.error(f"CRITICAL ERROR: {str(e)}")
            log_callback(f"Error applying patch: {str(e)}")
            raise e
        finally:
            if temp_dir and Path(temp_dir).exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            if game_staging is not None and Path(game_staging).exists() and not swapped:
                shutil.rmtree(game_staging, ignore_errors=True)
            if install_dir.exists():
                BackupManager.recover_interrupted_swap(install_dir)
