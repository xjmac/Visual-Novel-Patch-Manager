import os
import json
import shutil
import tempfile
import time
import subprocess
from pathlib import Path
import logging

from .steam_scanner import SteamScanner
from .backup_manager import BackupManager
from .exceptions import PatchSecurityError, PatchExtractionError, ProtonExecutionError

logger = logging.getLogger(__name__)

class PatchExecutionEngine:
    """Handles the actual copying of files and execution of Proton patches."""

    @staticmethod
    def _safe_extract_zip(zf, extract_tmp):
        extract_tmp_resolved = str(extract_tmp.resolve())
        for member in zf.namelist():
            member_path = str((extract_tmp / member).resolve())
            if os.path.commonpath([extract_tmp_resolved, member_path]) != extract_tmp_resolved:
                raise PatchSecurityError(f"Zip slip detected: {member} attempts to escape target directory")
        zf.extractall(extract_tmp)

    @staticmethod
    def _safe_extract_tar(tar, extract_tmp):
        extract_tmp_resolved = str(extract_tmp.resolve())
        for member in tar.getmembers():
            member_path = str((extract_tmp / member.name).resolve())
            if os.path.commonpath([extract_tmp_resolved, member_path]) != extract_tmp_resolved:
                raise PatchSecurityError(f"Tar slip detected: {member.name} attempts to escape target directory")
        tar.extractall(extract_tmp)

    @staticmethod
    def get_patch_status(game_install_path, patch_data=None, vn_info=None):
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

                # RPA files
                if source.endswith(".rpa"):
                    target_dir = game_path / "game" if "game" in destination else game_path
                    if (target_dir / source).exists():
                        return True

                # Specific patch payload files
                if atype == "copy_file":
                    if source in [".", "patch_data"]:
                        if patch_src_dir.exists():
                            src_files = [f for f in patch_src_dir.glob("*") if f.is_file() and not f.name.endswith(".txt")]
                            if src_files and any((game_path / f.name).exists() for f in src_files):
                                return True
                    else:
                        target_file = game_path / source
                        if target_file.exists() and target_file.is_file():
                            return True

                # Archive extraction
                if atype == "extract_archive":
                    arc_path = patch_src_dir / source if patch_src_dir.exists() else None
                    if arc_path and arc_path.exists():
                        if source.lower().endswith(".zip"):
                            try:
                                import zipfile
                                with zipfile.ZipFile(arc_path, "r") as zf:
                                    members = [Path(m).name for m in zf.namelist() if Path(m).name and not Path(m).name.endswith(".txt")]
                                    if members and any((game_path / m).exists() for m in members):
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
            # For assets.rpa, only treat as patch if game needs an 18+ patch
            if (game_sub / "assets.rpa").exists():
                if vn_info is None or vn_info.get("has_18plus_en_patch", True):
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
    def _find_proton_executable(library_path: Path = None) -> Path:
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
    def restore_via_steam(game_data, patch_data=None, log_callback=None) -> bool:
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

        # 2. If actions in patch_data copied specific non-vanilla files, remove them
        if patch_data:
            actions = patch_data.get('actions', [])
            for action in actions:
                if action.get('type') == 'copy_file':
                    dest_str = action.get('destination', '').replace("{game_dir}", str(install_dir))
                    dest_path = Path(dest_str)
                    if dest_path.exists() and not dest_path.is_dir():
                        try:
                            dest_path.unlink()
                        except OSError as e:
                            logger.warning(f"Failed to unlink {dest_path}: {e}")

        # 3. Clean up dirty backups if any exists that are not clean
        backup_root = install_dir / BackupManager.BACKUP_DIR_NAME
        if backup_root.exists() and not BackupManager.has_clean_backup(install_dir):
            try:
                shutil.rmtree(backup_root, ignore_errors=True)
            except OSError as e:
                logger.warning(f"Failed to remove backup root: {e}")

        # 4. Launch Steam verification
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
    def apply_patch(game_data, patch_data, config_manager, log_callback):
        """Applies the patch logic based on the 'actions' from patch.json"""
        app_id = patch_data.get('steam_app_id')
        install_dir = Path(game_data['path'])
        library_path = Path(game_data['library_path'])
        source_dir = patch_data.get('patch_source_dir')
        mode = config_manager.config.get('mode')
        actions = patch_data.get('actions', [])

        temp_dir = None
        working_source = Path(source_dir)

        try:
            log_callback(f"Starting patch for {game_data['name']}...")

            # 0. Backup original files before applying patch if no backup exists
            if not BackupManager.has_backup(install_dir):
                log_callback("Creating backup of original game files and computing SHA256 checksums...")
                BackupManager.create_backup(
                    install_dir,
                    app_id,
                    game_data['name'],
                    patch_source_dir=source_dir,
                    log_callback=log_callback
                )

            # 1. Stage files locally (Crucial for Proton executing off NAS mounts)
            log_callback("Staging patch files to a local temporary folder...")
            temp_dir = tempfile.mkdtemp(prefix=f"vnpatch_{app_id}_")
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
                    # Resolve {game_dir} template
                    dest_str = action.get('destination', '').replace("{game_dir}", str(install_dir))
                    dest_path = Path(dest_str)

                    logger.debug(f"Attempting to copy from '{src_file}' to '{dest_path}'")

                    if not src_file.exists():
                        raise PatchExtractionError(f"Source file/folder does not exist: {src_file}")

                    if src_file.is_dir():
                        shutil.copytree(src_file, dest_path, dirs_exist_ok=True)
                    else:
                        # If destination ends in a slash, treat it as a directory to copy into
                        if dest_str.endswith('/') or dest_path.is_dir():
                            dest_path.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(src_file, dest_path)
                        else:
                            dest_path.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(src_file, dest_path)

                elif action_type == 'extract_inno_setup':
                    exe_file = working_source / action.get('source', '')
                    dest_str = action.get('destination', '{game_dir}').replace("{game_dir}", str(install_dir))
                    dest_path = Path(dest_str)

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

                    log_callback(f"Extracting natively using innoextract...")

                    # Extract to a temporary sub-folder first because Inno Setup packages
                    # usually hide the actual game files inside an internal 'app/' folder.
                    extract_tmp = working_source / "inno_extracted"
                    extract_tmp.mkdir(exist_ok=True)

                    cmd = ["innoextract", "-s", "-d", str(extract_tmp), str(exe_file)]
                    print(f"DEBUG: Running innoextract command: {cmd}")

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

                    log_callback("Copying extracted files to game directory...")
                    shutil.copytree(source_copy_dir, dest_path, dirs_exist_ok=True)

                elif action_type == 'extract_archive':
                    arc_file = working_source / action.get('source', '')
                    dest_str = action.get('destination', '{game_dir}').replace("{game_dir}", str(install_dir))
                    dest_path = Path(dest_str)
                    dest_path.mkdir(parents=True, exist_ok=True)

                    if not arc_file.exists():
                        raise PatchExtractionError(f"Archive file not found: {arc_file}")

                    log_callback(f"Extracting {arc_file.name} to game directory...")
                    extract_tmp = working_source / f"extracted_{arc_file.stem}"
                    extract_tmp.mkdir(exist_ok=True)

                    if arc_file.name.lower().endswith('.zip'):
                        import zipfile
                        with zipfile.ZipFile(arc_file, 'r') as zf:
                            PatchExecutionEngine._safe_extract_zip(zf, extract_tmp)
                    elif arc_file.name.lower().endswith(('.tar.gz', '.tar.bz2', '.tar.xz', '.tar', '.tgz', '.tbz2', '.txz')):
                        import tarfile
                        with tarfile.open(arc_file, 'r') as tar:
                            PatchExecutionEngine._safe_extract_tar(tar, extract_tmp)
                    elif arc_file.suffix.lower() == '.7z':
                        if shutil.which("7z"):
                            subprocess.run(["7z", "x", "-y", f"-o{extract_tmp}", str(arc_file)], check=True)
                        else:
                            raise PatchExtractionError("7z tool not found. Please install p7zip (sudo pacman -S p7zip).")
                    elif arc_file.suffix.lower() == '.rar':
                        if shutil.which("unrar"):
                            subprocess.run(["unrar", "x", "-o+", str(arc_file), str(extract_tmp)], check=True)
                        elif shutil.which("7z"):
                            subprocess.run(["7z", "x", "-y", f"-o{extract_tmp}", str(arc_file)], check=True)
                        else:
                            raise PatchExtractionError("unrar or 7z tool not found. Please install unrar or 7z.")
                    else:
                        shutil.unpack_archive(str(arc_file), str(extract_tmp))

                    shutil.copytree(extract_tmp, dest_path, dirs_exist_ok=True)

                elif action_type == 'run_proton_executable':
                    exe_file = working_source / action.get('source', '')

                    # 1. Safety Check: Verify the file actually exists before letting Wine crash
                    if not exe_file.exists():
                        files_present = [f.name for f in exe_file.parent.iterdir()] if exe_file.parent.exists() else []
                        raise ProtonExecutionError(f"Proton Error: File not found at '{exe_file}'.\nFiles in that folder: {files_present}")

                    # Proton/Wine maps the Linux root (/) to the Windows Z: drive.
                    # We must convert the path for Windows installers to understand it.
                    raw_win_dir = "Z:" + str(install_dir).replace('/', '\\')
                    # Wrap in literal quotes to protect spaces in Windows command line parsing
                    win_install_dir = f'"{raw_win_dir}"'

                    args = []
                    for arg in action.get('args', []):
                        arg_str = arg.replace("{game_dir}", str(install_dir))
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

            # 3. Create the hidden tracking file
            tracking_file = install_dir / ".patch_applied.json"
            metadata = {
                "steam_app_id": app_id,
                "game_name": game_data['name'],
                "applied_timestamp": time.time(),
                "status": "success",
                "actions_applied": len(actions)
            }
            with open(tracking_file, 'w') as f:
                json.dump(metadata, f)

            log_callback(f"Patch successfully applied to {game_data['name']}!")
            return True

        except Exception as e:
            logger.error(f"CRITICAL ERROR: {str(e)}")
            log_callback(f"Error applying patch: {str(e)}")
            raise e
        finally:
            # 4. Cleanup temporary files if SMB was used
            if temp_dir and Path(temp_dir).exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
