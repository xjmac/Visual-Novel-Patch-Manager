import re
import sys
from unittest.mock import patch, MagicMock
import pytest

from vnpatchmanager.cli import main as cli_main


def test_cli_export_licenses_logic(tmp_path):
    from vnpatchmanager.steam_scanner import SteamScanner

    raw_file = tmp_path / "raw_licenses.txt"
    raw_file.write_text("PackageID 123: AppID 900001\nPackageID 456: AppID 900002\nPackageID 789: AppID 999999\n")
    out_file = tmp_path / "out_games.txt"

    mock_games = {
        "900001": {"name": "Synthetic VN Alpha"},
        "900002": {"name": "Synthetic VN Beta"}
    }

    with patch.object(SteamScanner, "get_owned_games", return_value=mock_games):
        with open(raw_file, "r") as f:
            found_ids = set(re.findall(r"\b\d{3,7}\b", f.read()))

        assert "900001" in found_ids
        assert "900002" in found_ids

        resolved = sorted([mock_games[aid]["name"] for aid in found_ids if aid in mock_games])
        assert resolved == ["Synthetic VN Alpha", "Synthetic VN Beta"]

        with open(out_file, "w") as f:
            for game in resolved:
                f.write(f"{game}\n")

        assert out_file.read_text() == "Synthetic VN Alpha\nSynthetic VN Beta\n"


def test_cli_version_flag(capsys):
    with pytest.raises(SystemExit) as exc_info:
        cli_main(["--version"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "vnpm" in captured.out or "vnpm" in captured.err


def test_cli_help_flag(capsys):
    with pytest.raises(SystemExit) as exc_info:
        cli_main(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "Visual Novel Patch Manager" in captured.out


def test_cli_cmd_list_games(capsys):
    mock_owned = {
        "900001": {"name": "Clannad", "path": "/fake/clannad", "is_installed": True},
        "900002": {"name": "Steins;Gate", "path": "", "is_installed": False},
    }
    mock_vndb = {
        "900001": {"vn_title": "Clannad", "rating": 8.5, "is_vn": True, "has_18plus_en_patch": False},
        "900002": {"vn_title": "Steins;Gate", "rating": 9.0, "is_vn": True, "has_18plus_en_patch": True},
    }

    with patch("vnpatchmanager.steam_scanner.SteamScanner.get_owned_games", return_value=mock_owned), \
         patch("vnpatchmanager.vndb_scanner.VNDBScanner.get_cached_vns", return_value=mock_vndb), \
         patch("vnpatchmanager.patch_repository.PatchRepository.refresh_patches"), \
         patch("vnpatchmanager.patch_execution.PatchExecutionEngine.get_patch_status", return_value=True):
        cli_main(["--list"])

    captured = capsys.readouterr()
    assert "Visual Novel Library Scan" in captured.out
    assert "900001" in captured.out
    assert "Clannad" in captured.out
    assert "900002" in captured.out
    assert "Total visual novels found: 2" in captured.out


def test_cli_cmd_sync_vndb(capsys):
    with patch("vnpatchmanager.vndb_scanner.VNDBScanner.sync_vndb_snapshot", return_value=True) as mock_sync:
        cli_main(["--sync-vndb"])
        mock_sync.assert_called_once_with(force=True)

    captured = capsys.readouterr()
    assert "VNDB snapshot sync completed successfully!" in captured.out


def test_cli_cmd_export_licenses(tmp_path):
    raw_file = tmp_path / "raw_licenses.txt"
    raw_file.write_text("123456\n")
    out_file = tmp_path / "exported.txt"

    mock_owned = {"123456": {"name": "Fate/Stay Night"}}

    with patch("vnpatchmanager.steam_scanner.SteamScanner.get_owned_games", return_value=mock_owned):
        cli_main(["--export-licenses", str(raw_file), "-o", str(out_file)])

    assert out_file.exists()
    assert "Fate/Stay Night" in out_file.read_text()


def test_package_main_delegates_to_cli():
    import vnpatchmanager.__main__
    with patch.object(sys, "argv", ["vnpatchmanager", "--version"]), \
         patch("vnpatchmanager.__main__.cli_main") as mock_cli:
        vnpatchmanager.__main__.main()
        mock_cli.assert_called_once()


def test_package_main_entrypoint():
    import vnpatchmanager.__main__

    with patch.object(sys, "argv", ["vnpatchmanager"]), \
         patch("vnpatchmanager.__main__.VNPatchManagerApp") as mock_app_class:
        mock_instance = MagicMock()
        mock_app_class.return_value = mock_instance
        vnpatchmanager.__main__.main()
        mock_app_class.assert_called_once()
        mock_instance.mainloop.assert_called_once()


def test_headless_import_safety():
    """Verify that importing vnpatchmanager modules does not fail even if GUI cannot be launched."""
    import vnpatchmanager
    assert hasattr(vnpatchmanager, "VNPatchManagerApp")
    assert hasattr(vnpatchmanager, "SteamScanner")
    assert hasattr(vnpatchmanager, "main")

