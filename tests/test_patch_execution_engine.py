import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
import vnpatchmanager
from vnpatchmanager import PatchExecutionEngine, ConfigManager, SteamScanner, BackupManager


def test_get_patch_status(tmp_path):
    game_dir = tmp_path / "Game"
    game_dir.mkdir()
    assert not PatchExecutionEngine.get_patch_status(game_dir)

    tracking_file = game_dir / ".patch_applied.json"
    tracking_file.write_text("{}")
    assert PatchExecutionEngine.get_patch_status(game_dir)


def test_find_proton_executable(mock_steam_structure, tmp_path):
    primary_lib = mock_steam_structure["steam_root"]
    secondary_lib = mock_steam_structure["secondary_library"]

    with patch.object(SteamScanner, "get_steam_root", return_value=primary_lib):
        # 1. Primary library direct search -> picks Proton 9.0 over Proton 8.0
        proton_bin = PatchExecutionEngine._find_proton_executable(primary_lib)
        assert proton_bin is not None
        assert "Proton 9.0" in str(proton_bin)

        # 2. Secondary library (SD Card on Steam Deck without Proton) finds Proton on Primary Library
        proton_sdcard = PatchExecutionEngine._find_proton_executable(secondary_lib)
        assert proton_sdcard is not None
        assert "Proton 9.0" in str(proton_sdcard)

    # 3. Custom Compatibility Tools (GE-Proton)
    compat_tools_dir = primary_lib / "compatibilitytools.d" / "GE-Proton10-25"
    compat_tools_dir.mkdir(parents=True, exist_ok=True)
    ge_bin = compat_tools_dir / "proton"
    ge_bin.write_text("#!/bin/sh\nexit 0\n")
    ge_bin.chmod(0o755)

    with patch.object(SteamScanner, "get_steam_root", return_value=primary_lib):
        proton_ge = PatchExecutionEngine._find_proton_executable()
        assert proton_ge is not None
        assert "GE-Proton10-25" in str(proton_ge)

    # 4. No Steam root and no Proton in empty library
    with patch.object(SteamScanner, "get_steam_root", return_value=None):
        empty_lib = tmp_path / "EmptyLib"
        empty_lib.mkdir()
        assert PatchExecutionEngine._find_proton_executable(empty_lib) is None


def test_apply_patch_copy_file_and_dir_local(temp_config_dir, mock_steam_structure, mock_patch_repo):
    cm = ConfigManager()
    cm.config["mode"] = "local"

    game_data = {
        "name": mock_steam_structure["game1"]["name"],
        "path": mock_steam_structure["game1"]["path"],
        "library_path": mock_steam_structure["game1"]["library_path"]
    }
    patch_data = mock_patch_repo["patch1_manifest"].copy()
    patch_data["patch_source_dir"] = str(mock_patch_repo["patch1_dir"])

    logs = []
    log_callback = lambda msg: logs.append(msg)

    success = PatchExecutionEngine.apply_patch(game_data, patch_data, cm, log_callback)
    assert success is True

    # Verify copied file and folder
    game_path = mock_steam_structure["game1"]["path"]
    assert (game_path / "update.xp3").exists()
    assert (game_path / "update.xp3").read_text() == "patch content xp3"
    assert (game_path / "data" / "extra.bin").exists()
    assert (game_path / "data" / "extra.bin").read_text() == "extra binary content"

    # Verify .patch_applied.json tracking file
    tracking_file = game_path / ".patch_applied.json"
    assert tracking_file.exists()
    with open(tracking_file, "r") as f:
        meta = json.load(f)
    assert meta["steam_app_id"] == 900001
    assert meta["status"] == "success"
    assert meta["actions_applied"] == 2

    # Verify backup was automatically created in .backup
    assert BackupManager.has_backup(game_path)
    latest_dir, manifest = BackupManager.get_latest_backup(game_path)
    assert manifest["steam_app_id"] == "900001"
    assert "game.exe" in manifest["files"]


def test_apply_patch_copy_file_missing_source(temp_config_dir, mock_steam_structure, tmp_path):
    cm = ConfigManager()
    cm.config["mode"] = "local"

    source_dir = tmp_path / "empty_patch"
    source_dir.mkdir()

    game_data = {
        "name": "Dummy Game",
        "path": tmp_path / "GameDir",
        "library_path": tmp_path / "Steam"
    }
    game_data["path"].mkdir(parents=True)

    patch_data = {
        "steam_app_id": 999,
        "patch_source_dir": str(source_dir),
        "actions": [
            {
                "type": "copy_file",
                "source": "nonexistent.dat",
                "destination": "{game_dir}/nonexistent.dat"
            }
        ]
    }

    logs = []
    with pytest.raises(Exception) as exc_info:
        PatchExecutionEngine.apply_patch(game_data, patch_data, cm, lambda m: logs.append(m))
    assert "Source file/folder does not exist" in str(exc_info.value)


def test_apply_patch_extract_inno_setup_success(temp_config_dir, mock_steam_structure, mock_patch_repo):
    cm = ConfigManager()
    cm.config["mode"] = "local"

    game_data = {
        "name": mock_steam_structure["game2"]["name"],
        "path": mock_steam_structure["game2"]["path"],
        "library_path": mock_steam_structure["game2"]["library_path"]
    }
    patch_data = mock_patch_repo["patch2_manifest"].copy()
    patch_data["patch_source_dir"] = str(mock_patch_repo["patch2_dir"])

    logs = []

    # Mock innoextract command to populate simulated app/ folder in extract_tmp
    def fake_subprocess_run(cmd, capture_output=True, text=True, **kwargs):
        # cmd format: ["innoextract", "-s", "-d", str(extract_tmp), str(exe_file)]
        extract_tmp = Path(cmd[3])
        app_dir = extract_tmp / "app"
        app_dir.mkdir(parents=True, exist_ok=True)
        (app_dir / "voice.pak").write_text("voice package data")
        res = MagicMock()
        res.returncode = 0
        return res

    with patch("shutil.which", return_value="/usr/bin/innoextract"), \
         patch("subprocess.run", side_effect=fake_subprocess_run) as mock_run:
        success = PatchExecutionEngine.apply_patch(game_data, patch_data, cm, lambda m: logs.append(m))
        assert success is True

    game_path = mock_steam_structure["game2"]["path"]
    assert (game_path / "voice.pak").exists()
    assert (game_path / "voice.pak").read_text() == "voice package data"
    assert (game_path / ".patch_applied.json").exists()


def test_apply_patch_extract_inno_setup_missing_binary(temp_config_dir, mock_steam_structure, mock_patch_repo):
    cm = ConfigManager()
    cm.config["mode"] = "local"

    game_data = {
        "name": mock_steam_structure["game2"]["name"],
        "path": mock_steam_structure["game2"]["path"],
        "library_path": mock_steam_structure["game2"]["library_path"]
    }
    patch_data = mock_patch_repo["patch2_manifest"].copy()
    patch_data["patch_source_dir"] = str(mock_patch_repo["patch2_dir"])

    with patch("shutil.which", return_value=None):
        with pytest.raises(Exception) as exc_info:
            PatchExecutionEngine.apply_patch(game_data, patch_data, cm, lambda m: None)
        assert "innoextract is not installed" in str(exc_info.value)


def test_apply_patch_extract_inno_setup_failure_exit_code(temp_config_dir, mock_steam_structure, mock_patch_repo):
    cm = ConfigManager()
    cm.config["mode"] = "local"

    game_data = {
        "name": mock_steam_structure["game2"]["name"],
        "path": mock_steam_structure["game2"]["path"],
        "library_path": mock_steam_structure["game2"]["library_path"]
    }
    patch_data = mock_patch_repo["patch2_manifest"].copy()
    patch_data["patch_source_dir"] = str(mock_patch_repo["patch2_dir"])

    mock_res = MagicMock(returncode=1, stderr="Corrupted Inno installer", stdout="")
    with patch("shutil.which", return_value="/usr/bin/innoextract"), \
         patch("subprocess.run", return_value=mock_res):
        with pytest.raises(Exception) as exc_info:
            PatchExecutionEngine.apply_patch(game_data, patch_data, cm, lambda m: None)
        assert "innoextract failed with code 1" in str(exc_info.value)


def test_apply_patch_run_proton_executable_success(temp_config_dir, mock_steam_structure, mock_patch_repo):
    cm = ConfigManager()
    cm.config["mode"] = "local"

    game_data = {
        "name": mock_steam_structure["game1"]["name"],
        "path": mock_steam_structure["game1"]["path"],
        "library_path": mock_steam_structure["game1"]["library_path"]
    }
    patch_data = mock_patch_repo["patch3_manifest"].copy()
    patch_data["steam_app_id"] = 900001 # Set to installed game
    patch_data["patch_source_dir"] = str(mock_patch_repo["patch3_dir"])

    executed_cmd = None
    executed_env = None
    executed_cwd = None

    def fake_subprocess_run(cmd, env=None, cwd=None, capture_output=True, text=True, **kwargs):
        nonlocal executed_cmd, executed_env, executed_cwd
        executed_cmd = cmd
        executed_env = env
        executed_cwd = cwd
        res = MagicMock()
        res.returncode = 0
        return res

    with patch("subprocess.run", side_effect=fake_subprocess_run), \
         patch.object(SteamScanner, "get_steam_root", return_value=mock_steam_structure["steam_root"]):
        success = PatchExecutionEngine.apply_patch(game_data, patch_data, cm, lambda m: None)
        assert success is True

    # Assert correct proton binary used (Proton 9.0)
    assert "Proton 9.0/proton" in executed_cmd[0]
    assert executed_cmd[1] == "run"
    assert "patch_installer.exe" in executed_cmd[2]
    assert executed_cmd[3] == "/SILENT"

    # Assert Windows Z: path formatting
    win_dir_expected = f'"Z:{str(mock_steam_structure["game1"]["path"]).replace("/", "\\")}"'
    assert executed_cmd[4] == f"/DIR={win_dir_expected}"

    # Assert Environment Variables
    assert executed_env["STEAM_COMPAT_APP_ID"] == "900001"
    assert executed_env["STEAM_COMPAT_DATA_PATH"] == str(mock_steam_structure["steam_root"] / "steamapps" / "compatdata" / "900001")
    assert executed_env["WINEPREFIX"] == str(mock_steam_structure["steam_root"] / "steamapps" / "compatdata" / "900001" / "pfx")

    # Assert CWD is the directory containing the exe in the staged temp dir
    assert "vnpatch_900001" in str(executed_cwd)


def test_apply_patch_run_proton_executable_failure_exit_code(temp_config_dir, mock_steam_structure, mock_patch_repo):
    cm = ConfigManager()
    cm.config["mode"] = "local"

    game_data = {
        "name": mock_steam_structure["game1"]["name"],
        "path": mock_steam_structure["game1"]["path"],
        "library_path": mock_steam_structure["game1"]["library_path"]
    }
    patch_data = mock_patch_repo["patch3_manifest"].copy()
    patch_data["steam_app_id"] = 900001
    patch_data["patch_source_dir"] = str(mock_patch_repo["patch3_dir"])

    mock_res = MagicMock(returncode=255, stderr="Wine crash")
    with patch("subprocess.run", return_value=mock_res), \
         patch.object(SteamScanner, "get_steam_root", return_value=mock_steam_structure["steam_root"]):
        with pytest.raises(Exception) as exc_info:
            PatchExecutionEngine.apply_patch(game_data, patch_data, cm, lambda m: None)
        assert "Proton executable failed with code 255" in str(exc_info.value)


def test_apply_patch_run_proton_missing_proton(temp_config_dir, mock_steam_structure, mock_patch_repo):
    cm = ConfigManager()
    cm.config["mode"] = "local"

    game_data = {
        "name": mock_steam_structure["game1"]["name"],
        "path": mock_steam_structure["game1"]["path"],
        "library_path": mock_steam_structure["game1"]["library_path"]
    }
    patch_data = mock_patch_repo["patch3_manifest"].copy()
    patch_data["steam_app_id"] = 900001
    patch_data["patch_source_dir"] = str(mock_patch_repo["patch3_dir"])

    with patch.object(PatchExecutionEngine, "_find_proton_executable", return_value=None):
        with pytest.raises(Exception) as exc_info:
            PatchExecutionEngine.apply_patch(game_data, patch_data, cm, lambda m: None)
        assert "Could not find a Proton installation" in str(exc_info.value)


def test_apply_patch_smb_staging(temp_config_dir, mock_steam_structure):
    cm = ConfigManager()
    cm.config["mode"] = "smb"

    game_data = {
        "name": mock_steam_structure["game1"]["name"],
        "path": mock_steam_structure["game1"]["path"],
        "library_path": mock_steam_structure["game1"]["library_path"]
    }

    patch_data = {
        "steam_app_id": 1001,
        "patch_source_dir": r"\\192.168.1.100\Share\VN\Patch1",
        "actions": [
            {
                "type": "copy_file",
                "source": "smb_patch.dat",
                "destination": "{game_dir}/smb_patch.dat"
            }
        ]
    }

    def fake_smb_copyfile(src, dst):
        Path(dst).write_text("staged smb data")

    stat_mock = MagicMock()
    stat_mock.st_mode = 0o100644

    with patch("smbclient.listdir", return_value=["smb_patch.dat"]), \
         patch("smbclient.stat", return_value=stat_mock), \
         patch("smbclient.shutil.copyfile", side_effect=fake_smb_copyfile):
        success = PatchExecutionEngine.apply_patch(game_data, patch_data, cm, lambda m: None)
        assert success is True

    assert (mock_steam_structure["game1"]["path"] / "smb_patch.dat").read_text() == "staged smb data"


def test_apply_patch_unknown_action(temp_config_dir, mock_steam_structure, tmp_path):
    cm = ConfigManager()
    cm.config["mode"] = "local"

    source_dir = tmp_path / "patch_unknown"
    source_dir.mkdir()

    game_data = {
        "name": "Game",
        "path": tmp_path / "GameDir",
        "library_path": tmp_path / "Steam"
    }
    game_data["path"].mkdir(parents=True)

    patch_data = {
        "steam_app_id": 1001,
        "patch_source_dir": str(source_dir),
        "actions": [
            {
                "type": "unsupported_action_type"
            }
        ]
    }

    logs = []
    with pytest.raises(Exception, match="Unknown patch action type"):
        PatchExecutionEngine.apply_patch(game_data, patch_data, cm, lambda m: logs.append(m))


def test_apply_patch_cleans_up_temp_on_failure(temp_config_dir, mock_steam_structure, tmp_path):
    cm = ConfigManager()
    cm.config["mode"] = "local"

    source_dir = tmp_path / "patch_fail"
    source_dir.mkdir()

    game_data = {
        "name": "Game",
        "path": tmp_path / "GameDir",
        "library_path": tmp_path / "Steam"
    }
    game_data["path"].mkdir(parents=True)

    patch_data = {
        "steam_app_id": 1001,
        "patch_source_dir": str(source_dir),
        "actions": [
            {
                "type": "copy_file",
                "source": "missing.txt",
                "destination": "{game_dir}/missing.txt"
            }
        ]
    }

    created_temp_dirs = []
    orig_mkdtemp = tempfile.mkdtemp

    def tracked_mkdtemp(*args, **kwargs):
        td = orig_mkdtemp(*args, **kwargs)
        created_temp_dirs.append(td)
        return td

    with patch("tempfile.mkdtemp", side_effect=tracked_mkdtemp):
        with pytest.raises(Exception):
            PatchExecutionEngine.apply_patch(game_data, patch_data, cm, lambda m: None)

    assert len(created_temp_dirs) == 1
    # Check that temp directory was cleaned up
    assert not Path(created_temp_dirs[0]).exists()


def test_rollback_patch_success(temp_config_dir, mock_steam_structure, mock_patch_repo):
    cm = ConfigManager()
    cm.config["mode"] = "local"

    game_data = {
        "name": mock_steam_structure["game1"]["name"],
        "path": mock_steam_structure["game1"]["path"],
        "library_path": mock_steam_structure["game1"]["library_path"]
    }
    patch_data = mock_patch_repo["patch1_manifest"].copy()
    patch_data["patch_source_dir"] = str(mock_patch_repo["patch1_dir"])

    # 1. Apply patch (which also creates backup)
    PatchExecutionEngine.apply_patch(game_data, patch_data, cm, lambda m: None)
    game_path = mock_steam_structure["game1"]["path"]
    assert (game_path / "update.xp3").exists()
    assert (game_path / ".patch_applied.json").exists()

    # 2. Rollback patch
    logs = []
    success = PatchExecutionEngine.rollback_patch(game_data, lambda m: logs.append(m))
    assert success is True

    # 3. Assert original state restored
    assert not (game_path / "update.xp3").exists()
    assert not (game_path / ".patch_applied.json").exists()
    assert (game_path / "game.exe").read_text() == "dummy game executable"
    assert any("Rollback successful" in log for log in logs)


def test_restore_via_steam_success(tmp_path):
    game_dir = tmp_path / "SyntheticGameRestore"
    game_dir.mkdir()
    (game_dir / "update.xp3").write_text("patch xp3 file")
    (game_dir / ".patch_applied.json").write_text('{"steam_app_id": "900050"}')

    game_data = {
        "name": "Synthetic Restore Game",
        "path": game_dir,
        "steam_app_id": "900050"
    }
    patch_data = {
        "steam_app_id": "900050",
        "actions": [
            {
                "type": "copy_file",
                "source": "update.xp3",
                "destination": "{game_dir}/update.xp3"
            }
        ]
    }

    logs = []
    with patch("subprocess.Popen") as mock_popen:
        success = PatchExecutionEngine.restore_via_steam(game_data, patch_data, lambda m: logs.append(m))
        assert success is True
        mock_popen.assert_called_once_with(["steam", "steam://validate/900050"])

    # Check that patch file and tracking file were purged
    assert not (game_dir / "update.xp3").exists()
    assert not (game_dir / ".patch_applied.json").exists()
    assert any("Steam verification initiated" in log for log in logs)


def test_restore_via_steam_xdg_fallback(tmp_path):
    game_dir = tmp_path / "Game"
    game_dir.mkdir()
    (game_dir / ".patch_applied.json").write_text('{"steam_app_id": "2000"}')

    game_data = {
        "name": "Game",
        "path": game_dir,
        "steam_app_id": "2000"
    }

    def popen_side_effect(cmd, *args, **kwargs):
        if cmd[0] == "steam":
            raise FileNotFoundError("No steam command")
        return MagicMock()

    with patch("subprocess.Popen", side_effect=popen_side_effect) as mock_popen:
        success = PatchExecutionEngine.restore_via_steam(game_data, None)
        assert success is True
        assert mock_popen.call_count == 2
        assert mock_popen.call_args[0][0] == ["xdg-open", "steam://validate/2000"]


def test_apply_patch_extract_archive_zip(tmp_path, temp_config_dir):
    import zipfile

    # Create dummy game dir
    game_dir = tmp_path / "Game"
    game_dir.mkdir()
    (game_dir / "game.exe").write_text("dummy exe")

    # Create dummy zip patch
    patch_dir = tmp_path / "Patch"
    patch_dir.mkdir()
    zip_path = patch_dir / "patch.zip"

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("patch_content.dat", "18+ unlocked content")

    game_data = {
        "name": "Game",
        "path": game_dir,
        "library_path": tmp_path
    }
    patch_data = {
        "steam_app_id": "9999",
        "patch_source_dir": str(patch_dir),
        "actions": [
            {
                "type": "extract_archive",
                "source": "patch.zip",
                "destination": "{game_dir}/"
            }
        ]
    }

    cm = ConfigManager()
    cm.config["mode"] = "local"

    logs = []
    success = PatchExecutionEngine.apply_patch(game_data, patch_data, cm, lambda m: logs.append(m))
    assert success is True
    assert (game_dir / "patch_content.dat").exists()
    assert (game_dir / "patch_content.dat").read_text() == "18+ unlocked content"


def test_get_patch_status_manual_rpa(tmp_path):
    game_dir = tmp_path / "SakuraGame"
    game_dir.mkdir()
    game_sub = game_dir / "game"
    game_sub.mkdir()
    assert not PatchExecutionEngine.get_patch_status(game_dir)

    # Adding assets.rpa into game/
    (game_sub / "assets.rpa").write_bytes(b"rpa data")
    assert PatchExecutionEngine.get_patch_status(game_dir) is True


def test_get_patch_status_manual_pfs_and_xp3(tmp_path):
    game_dir = tmp_path / "YuzusoftGame"
    game_dir.mkdir()
    assert not PatchExecutionEngine.get_patch_status(game_dir)

    # XP3 signature
    (game_dir / "adult.xp3").write_bytes(b"xp3 data")
    assert PatchExecutionEngine.get_patch_status(game_dir) is True

    # PFS patch increment
    pfs_game_dir = tmp_path / "AmanatsuGame"
    pfs_game_dir.mkdir()
    (pfs_game_dir / "amanatu.pfs.040").write_bytes(b"pfs data")
    assert PatchExecutionEngine.get_patch_status(pfs_game_dir) is True


def test_get_patch_status_manual_archive(tmp_path):
    import zipfile

    game_dir = tmp_path / "MarshmallowGame"
    game_dir.mkdir()

    patch_dir = tmp_path / "SyntheticArchivePatch"
    patch_dir.mkdir()
    zip_path = patch_dir / "patch.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("patch1.noa", "noa data")

    patch_data = {
        "steam_app_id": "900060",
        "patch_source_dir": str(patch_dir),
        "actions": [{"type": "extract_archive", "source": "patch.zip", "destination": "{game_dir}/"}]
    }

    # Unpatched
    assert not PatchExecutionEngine.get_patch_status(game_dir, patch_data)

    # Manually extracted patch1.noa
    (game_dir / "patch1.noa").write_text("noa data")
    assert PatchExecutionEngine.get_patch_status(game_dir, patch_data) is True


def test_apply_patch_zip_slip_prevention(temp_config_dir, mock_steam_structure, tmp_path):
    """Verifies that archives containing path traversal entries ('../') are rejected safely."""
    import zipfile

    cm = ConfigManager()
    cm.config["mode"] = "local"

    source_dir = tmp_path / "patch_zipslip"
    source_dir.mkdir()

    # Create a malicious zip file with path traversal entry
    malicious_zip = source_dir / "malicious.zip"
    with zipfile.ZipFile(malicious_zip, "w") as zf:
        zf.writestr("../../escaped_file.txt", "pwned")

    game_dir = tmp_path / "ZipSlipGame"
    game_dir.mkdir()

    game_data = {
        "name": "ZipSlipGame",
        "path": game_dir,
        "library_path": tmp_path / "Steam"
    }

    patch_data = {
        "steam_app_id": 900001,
        "patch_source_dir": str(source_dir),
        "actions": [
            {
                "type": "extract_archive",
                "source": "malicious.zip",
                "destination": "{game_dir}/"
            }
        ]
    }

    from vnpatchmanager.exceptions import PatchSecurityError
    with pytest.raises(PatchSecurityError, match=r"(?i)zip slip"):
        PatchExecutionEngine.apply_patch(game_data, patch_data, cm, lambda m: None)

    # Ensure the escaped file was never written outside the target directory
    assert not (tmp_path / "escaped_file.txt").exists()


def test_apply_patch_extract_archive_tar_gz(temp_config_dir, mock_steam_structure, tmp_path):
    """Verifies that .tar.gz archives are extracted cleanly."""
    import tarfile
    import io

    cm = ConfigManager()
    cm.config["mode"] = "local"

    source_dir = tmp_path / "patch_targz"
    source_dir.mkdir()

    # Create a valid tar.gz file
    tar_path = source_dir / "patch.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tf:
        data = b"tar gz patch content"
        tarinfo = tarfile.TarInfo(name="patch_data.rpa")
        tarinfo.size = len(data)
        tf.addfile(tarinfo, io.BytesIO(data))

    game_dir = tmp_path / "TarGzGame"
    game_dir.mkdir()

    game_data = {
        "name": "TarGzGame",
        "path": game_dir,
        "library_path": tmp_path / "Steam"
    }

    patch_data = {
        "steam_app_id": 900001,
        "patch_source_dir": str(source_dir),
        "actions": [
            {
                "type": "extract_archive",
                "source": "patch.tar.gz",
                "destination": "{game_dir}/"
            }
        ]
    }

    success = PatchExecutionEngine.apply_patch(game_data, patch_data, cm, lambda m: None)
    assert success is True
    assert (game_dir / "patch_data.rpa").exists()
    assert (game_dir / "patch_data.rpa").read_bytes() == b"tar gz patch content"


def test_apply_patch_tar_slip_prevention(temp_config_dir, tmp_path):
    """Verifies that malicious tar archives with traversal paths (../) are blocked with PatchSecurityError."""
    import tarfile
    import io
    from vnpatchmanager.exceptions import PatchSecurityError

    cm = ConfigManager()
    cm.config["mode"] = "local"

    source_dir = tmp_path / "patch_tarslip"
    source_dir.mkdir()

    tar_path = source_dir / "malicious.tar"
    with tarfile.open(tar_path, "w") as tf:
        data = b"malicious content"
        tarinfo = tarfile.TarInfo(name="../../escaped_tar.txt")
        tarinfo.size = len(data)
        tf.addfile(tarinfo, io.BytesIO(data))

    game_dir = tmp_path / "TarSlipGame"
    game_dir.mkdir()

    game_data = {
        "name": "TarSlipGame",
        "path": game_dir,
        "library_path": tmp_path / "Steam"
    }

    patch_data = {
        "steam_app_id": 900001,
        "patch_source_dir": str(source_dir),
        "actions": [
            {
                "type": "extract_archive",
                "source": "malicious.tar",
                "destination": "{game_dir}/"
            }
        ]
    }

    with pytest.raises(PatchSecurityError, match=r"(?i)tar slip"):
        PatchExecutionEngine.apply_patch(game_data, patch_data, cm, lambda m: None)

    assert not (tmp_path / "escaped_tar.txt").exists()


def test_apply_patch_subprocess_timeouts(temp_config_dir, mock_steam_structure, mock_patch_repo):
    """Verifies that subprocess timeouts raise appropriate custom exceptions."""
    import subprocess
    from vnpatchmanager.exceptions import ProtonExecutionError, PatchExtractionError

    cm = ConfigManager()
    cm.config["mode"] = "local"

    game_data = {
        "name": mock_steam_structure["game1"]["name"],
        "path": mock_steam_structure["game1"]["path"],
        "library_path": mock_steam_structure["game1"]["library_path"]
    }
    patch_data = mock_patch_repo["patch3_manifest"].copy()
    patch_data["steam_app_id"] = 900001
    patch_data["patch_source_dir"] = str(mock_patch_repo["patch3_dir"])

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="proton", timeout=900)), \
         patch.object(SteamScanner, "get_steam_root", return_value=mock_steam_structure["steam_root"]):
        with pytest.raises(ProtonExecutionError, match="timed out"):
            PatchExecutionEngine.apply_patch(game_data, patch_data, cm, lambda m: None)





