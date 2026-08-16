from pathlib import Path
from unittest.mock import patch
import vdf
from vnpatchmanager import SteamScanner


def test_get_steam_root_paths(tmp_path, monkeypatch):
    fake_home = tmp_path / "home_user"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    # Initially none exist -> returns None
    assert SteamScanner.get_steam_root() is None

    # Test fallback 3: .steam/root
    steam_root_3 = fake_home / ".steam" / "root"
    (steam_root_3 / "steamapps").mkdir(parents=True)
    assert SteamScanner.get_steam_root() == steam_root_3

    # Test fallback 2: .steam/steam (higher priority than .steam/root)
    steam_root_2 = fake_home / ".steam" / "steam"
    (steam_root_2 / "steamapps").mkdir(parents=True)
    assert SteamScanner.get_steam_root() == steam_root_2

    # Test path 1: .local/share/Steam (highest priority)
    steam_root_1 = fake_home / ".local" / "share" / "Steam"
    (steam_root_1 / "steamapps").mkdir(parents=True)
    assert SteamScanner.get_steam_root() == steam_root_1


def test_get_installed_games_no_steam_root(caplog):
    with patch.object(SteamScanner, "get_steam_root", return_value=None):
        games = SteamScanner.get_installed_games()
        assert games == {}
        assert "Steam installation not found" in caplog.text


def test_get_installed_games_no_library_vdf(tmp_path):
    fake_steam = tmp_path / "steam_no_vdf"
    (fake_steam / "steamapps").mkdir(parents=True)
    with patch.object(SteamScanner, "get_steam_root", return_value=fake_steam):
        games = SteamScanner.get_installed_games()
        assert games == {}


def test_get_installed_games_success(mock_steam_structure):
    steam_root = mock_steam_structure["steam_root"]
    with patch.object(SteamScanner, "get_steam_root", return_value=steam_root):
        games = SteamScanner.get_installed_games()

    assert len(games) == 2
    assert "900001" in games
    assert "900002" in games

    game1 = games["900001"]
    assert game1["name"] == "Synthetic VN Alpha"
    assert game1["path"] == mock_steam_structure["game1"]["path"]
    assert game1["library_path"] == mock_steam_structure["game1"]["library_path"]

    game2 = games["900002"]
    assert game2["name"] == "Synthetic VN Beta"
    assert game2["path"] == mock_steam_structure["game2"]["path"]
    assert game2["library_path"] == mock_steam_structure["game2"]["library_path"]


def test_get_installed_games_corrupted_acf_and_vdf(mock_steam_structure, caplog):
    steam_root = mock_steam_structure["steam_root"]
    steamapps = steam_root / "steamapps"

    # Add a broken ACF file
    bad_acf = steamapps / "appmanifest_9999.acf"
    bad_acf.write_text("INVALID { { VDF CONTENT")

    with patch.object(SteamScanner, "get_steam_root", return_value=steam_root):
        games = SteamScanner.get_installed_games()

    # Valid games should still load
    assert "900001" in games
    assert "900002" in games
    assert "Failed to parse" in caplog.text


def test_get_installed_games_corrupted_library_vdf(mock_steam_structure, caplog):
    steam_root = mock_steam_structure["steam_root"]
    vdf_file = steam_root / "steamapps" / "libraryfolders.vdf"
    vdf_file.write_text('"unclosed_key" { "unterminated_val"')

    with patch.object(SteamScanner, "get_steam_root", return_value=steam_root):
        games = SteamScanner.get_installed_games()

    assert games == {}
    assert "Error reading libraryfolders.vdf" in caplog.text


def test_get_installed_games_nonexistent_library_path(mock_steam_structure):
    steam_root = mock_steam_structure["steam_root"]
    vdf_file = steam_root / "steamapps" / "libraryfolders.vdf"
    
    # Point a library entry to a folder without steamapps
    bad_library_data = {
        "libraryfolders": {
            "0": {
                "path": str(steam_root / "nonexistent_lib")
            }
        }
    }
    with open(vdf_file, "w") as f:
        vdf.dump(bad_library_data, f)

    with patch.object(SteamScanner, "get_steam_root", return_value=steam_root):
        games = SteamScanner.get_installed_games()

    assert games == {}


def test_get_owned_games_includes_installed_and_uninstalled(mock_steam_structure):
    steam_root = mock_steam_structure["steam_root"]
    userdata_dir = steam_root / "userdata" / "12345678" / "config"
    userdata_dir.mkdir(parents=True, exist_ok=True)

    # Mock localconfig.vdf
    localconfig_file = userdata_dir / "localconfig.vdf"
    localconfig_data = {
        "UserLocalConfigStore": {
            "Software": {
                "Valve": {
                    "Steam": {
                        "apps": {
                            "900004": {
                                "name": "Synthetic VN Delta",
                                "Playtime": "120"
                            }
                        }
                    }
                }
            }
        }
    }
    with open(localconfig_file, "w") as f:
        vdf.dump(localconfig_data, f)

    # Mock appcache/librarycache
    appcache_dir = steam_root / "appcache" / "librarycache"
    appcache_dir.mkdir(parents=True, exist_ok=True)
    (appcache_dir / "900005_header.jpg").touch()

    with patch.object(SteamScanner, "get_steam_root", return_value=steam_root):
        owned = SteamScanner.get_owned_games()

    # Should contain installed (900001, 900002) and uninstalled (900004, 900005)
    assert "900001" in owned
    assert owned["900001"]["is_installed"] is True

    assert "900002" in owned
    assert owned["900002"]["is_installed"] is True

    assert "900004" in owned
    assert owned["900004"]["name"] == "Synthetic VN Delta"
    assert owned["900004"]["is_installed"] is False

    assert "900005" in owned
    assert owned["900005"]["is_installed"] is False


def test_get_owned_games_no_steam_root():
    with patch.object(SteamScanner, "get_steam_root", return_value=None):
        owned = SteamScanner.get_owned_games()
        assert owned == {}


def test_is_dlc_or_addon_filtering(mock_steam_structure):
    steam_root = mock_steam_structure["steam_root"]
    userdata_dir = steam_root / "userdata" / "12345678" / "config"
    userdata_dir.mkdir(parents=True, exist_ok=True)

    localconfig_file = userdata_dir / "localconfig.vdf"
    localconfig_data = {
        "UserLocalConfigStore": {
            "Software": {
                "Valve": {
                    "Steam": {
                        "apps": {
                            "900011": {"name": "Synthetic Base Visual Novel Game"},
                            "900012": {"name": "Synthetic Base Game - Extra Fluffy Edition"},
                            "900013": {"name": "Synthetic Base Game - Soundtrack"},
                            "900014": {"name": "Synthetic Base Game - Artbook"},
                            "900015": {"name": "Synthetic Base Game - DLC"},
                            "900016": {"name": "Synthetic Base Game Season Pass"},
                            "900017": {"name": "Synthetic Base Game (Demo)"},
                            "900018": {"name": "Proton 9.0"}
                        }
                    }
                }
            }
        }
    }
    with open(localconfig_file, "w") as f:
        vdf.dump(localconfig_data, f)

    with patch.object(SteamScanner, "get_steam_root", return_value=steam_root):
        owned = SteamScanner.get_owned_games()

    assert "900011" in owned
    assert "900012" not in owned
    assert "900013" not in owned
    assert "900014" not in owned
    assert "900015" not in owned
    assert "900016" not in owned
    assert "900017" not in owned
    assert "900018" not in owned
