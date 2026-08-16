import io
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import smbclient
from vnpatchmanager import PatchRepository, ConfigManager


def test_refresh_patches_dispatches(temp_config_dir):
    cm = ConfigManager()
    repo = PatchRepository(cm)

    with patch.object(repo, "_scan_local") as mock_local, \
         patch.object(repo, "_scan_smb") as mock_smb:
        cm.config["mode"] = "local"
        repo.refresh_patches()
        mock_local.assert_called_once()
        mock_smb.assert_not_called()

        mock_local.reset_mock()
        cm.config["mode"] = "smb"
        repo.refresh_patches()
        mock_smb.assert_called_once()
        mock_local.assert_not_called()


def test_scan_local_success(temp_config_dir, mock_patch_repo):
    cm = ConfigManager()
    cm.config["mode"] = "local"
    cm.config["local_path"] = str(mock_patch_repo["repo_dir"])

    repo = PatchRepository(cm)
    repo.refresh_patches()

    assert "900001" in repo.available_patches
    assert "900002" in repo.available_patches
    assert "900003" in repo.available_patches

    patch1 = repo.available_patches["900001"]
    assert patch1["title"] == "Synthetic VN Alpha English Patch"
    assert patch1["patch_source_dir"] == str(mock_patch_repo["patch1_dir"])


def test_scan_local_nonexistent_directory(temp_config_dir, tmp_path, caplog):
    cm = ConfigManager()
    cm.config["mode"] = "local"
    cm.config["local_path"] = str(tmp_path / "nonexistent_patches_folder")

    repo = PatchRepository(cm)
    repo.refresh_patches()

    assert repo.available_patches == {}
    assert "Local patch directory not found" in caplog.text


def test_scan_local_corrupt_and_missing_appid_json(temp_config_dir, tmp_path, caplog):
    repo_dir = tmp_path / "patch_tests"
    repo_dir.mkdir()

    # Corrupt JSON
    bad_dir = repo_dir / "corrupted_patch"
    bad_dir.mkdir()
    (bad_dir / "patch.json").write_text("{ corrupt json")

    # Missing steam_app_id
    no_appid_dir = repo_dir / "no_appid_patch"
    no_appid_dir.mkdir()
    (no_appid_dir / "patch.json").write_text(json.dumps({"title": "No ID"}))

    # Valid patch
    good_dir = repo_dir / "good_patch"
    good_dir.mkdir()
    (good_dir / "patch.json").write_text(json.dumps({"steam_app_id": 555, "title": "Good"}))

    cm = ConfigManager()
    cm.config["mode"] = "local"
    cm.config["local_path"] = str(repo_dir)

    repo = PatchRepository(cm)
    repo.refresh_patches()

    assert "555" in repo.available_patches
    assert "None" not in repo.available_patches
    assert "Error reading" in caplog.text


def test_scan_smb_missing_server_or_share(temp_config_dir):
    cm = ConfigManager()
    cm.config["mode"] = "smb"
    cm.config["smb_server"] = ""
    cm.config["smb_share"] = ""

    repo = PatchRepository(cm)
    with patch("smbclient.register_session") as mock_reg:
        repo.refresh_patches()
        mock_reg.assert_not_called()
        assert repo.available_patches == {}


def test_scan_smb_success(temp_config_dir):
    cm = ConfigManager()
    cm.config["mode"] = "smb"
    cm.config["smb_server"] = "192.168.1.100"
    cm.config["smb_share"] = "VNShare"
    cm.config["smb_path"] = "Patches/"
    cm.config["smb_username"] = "vnuser"
    cm.config["smb_password"] = "pass123"

    repo = PatchRepository(cm)

    # Mock directory items
    mock_items = ["SyntheticAlphaPatch", "File.txt", "SyntheticBetaPatch"]
    
    # Mock stat returning directory mode (0o040000) for dirs, regular file for File.txt
    def mock_stat(path):
        stat_res = MagicMock()
        if "SyntheticAlphaPatch" in path or "SyntheticBetaPatch" in path:
            stat_res.st_mode = 0o040755
        else:
            stat_res.st_mode = 0o100644
        return stat_res

    # Mock file contents for patch.json
    def mock_open_file(path, mode='r'):
        if r"SyntheticAlphaPatch\patch.json" in path:
            content = json.dumps({"steam_app_id": 900001, "title": "Synthetic VN Alpha SMB Patch"})
            return io.StringIO(content)
        elif r"SyntheticBetaPatch\patch.json" in path:
            content = json.dumps({"steam_app_id": 900002, "title": "Synthetic VN Beta SMB Patch"})
            return io.StringIO(content)
        else:
            raise OSError(2, "File not found")

    with patch("smbclient.register_session") as mock_reg, \
         patch("smbclient.listdir", return_value=mock_items) as mock_list, \
         patch("smbclient.stat", side_effect=mock_stat), \
         patch("smbclient.open_file", side_effect=mock_open_file):

        repo.refresh_patches()

        mock_reg.assert_called_once_with("192.168.1.100", username="vnuser", password="pass123")
        assert "900001" in repo.available_patches
        assert "900002" in repo.available_patches
        assert repo.available_patches["900001"]["title"] == "Synthetic VN Alpha SMB Patch"
        assert repo.available_patches["900001"]["patch_source_dir"] == r"\\192.168.1.100\VNShare\Patches\SyntheticAlphaPatch"


def test_scan_smb_connection_error(temp_config_dir, caplog):
    cm = ConfigManager()
    cm.config["mode"] = "smb"
    cm.config["smb_server"] = "192.168.1.100"
    cm.config["smb_share"] = "VNShare"

    repo = PatchRepository(cm)
    with patch("smbclient.register_session", side_effect=Exception("SMB Timeout")):
        repo.refresh_patches()
        assert repo.available_patches == {}
        assert "SMB Timeout" in caplog.text


def test_scan_local_recursive_and_auto_detection(temp_config_dir, tmp_path):
    repo_dir = tmp_path / "patches"
    repo_dir.mkdir()

    # 1. Ren'Py nested folder without patch.json
    renpy_dir = repo_dir / "Mock Series" / "Synthetic Renpy Adventure"
    renpy_dir.mkdir(parents=True)
    (renpy_dir / "assets.rpa").write_bytes(b"rpa data")

    # 2. Extracted engine payload nested folder without patch.json
    engine_dir = repo_dir / "Synthetic PFS Game" / "PFS_Patch_2026"
    engine_dir.mkdir(parents=True)
    (engine_dir / "game_data.pfs.040").write_bytes(b"pfs data")
    (engine_dir / "game_data.pfs.041").write_bytes(b"pfs data")

    # 3. Archive file without patch.json
    archive_dir = repo_dir / "Synthetic Zip Mystery"
    archive_dir.mkdir(parents=True)
    (archive_dir / "SyntheticMystery_R18patch.zip").write_bytes(b"zip data")

    # 4. Explicit patch.json taking priority
    explicit_dir = repo_dir / "Synthetic Explicit VN"
    explicit_dir.mkdir(parents=True)
    (explicit_dir / "patch.json").write_text(json.dumps({
        "steam_app_id": "900040",
        "game_name": "Synthetic Explicit VN",
        "actions": [{"type": "copy_file", "source": "patch_data", "destination": "{game_dir}/"}]
    }))

    cm = ConfigManager()
    cm.config["mode"] = "local"
    cm.config["local_path"] = str(repo_dir)

    repo = PatchRepository(cm)

    def mock_match(query):
        if "Synthetic Renpy Adventure" in query:
            return "900010", "Synthetic Renpy Adventure"
        if "Synthetic PFS Game" in query or "PFS_Patch" in query:
            return "900020", "Synthetic PFS Game"
        if "Synthetic Zip Mystery" in query or "SyntheticMystery" in query:
            return "900030", "Synthetic Zip Mystery"
        return None, None

    with patch.object(repo, "match_title_to_app_id", side_effect=mock_match):
        repo.refresh_patches()

    # Synthetic Renpy AppID 900010
    assert "900010" in repo.available_patches
    renpy_patch = repo.available_patches["900010"]
    assert renpy_patch["actions"][0]["destination"] == "{game_dir}/game/"

    # Synthetic PFS AppID 900020
    assert "900020" in repo.available_patches
    pfs_patch = repo.available_patches["900020"]
    assert pfs_patch["actions"][0]["destination"] == "{game_dir}/"

    # Synthetic Zip AppID 900030
    assert "900030" in repo.available_patches
    zip_patch = repo.available_patches["900030"]
    assert zip_patch["actions"][0]["type"] == "extract_archive"

    # Synthetic Explicit AppID 900040
    assert "900040" in repo.available_patches
    assert repo.available_patches["900040"]["actions"][0]["source"] == "patch_data"
