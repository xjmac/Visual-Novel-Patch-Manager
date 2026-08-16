from unittest.mock import patch, MagicMock
from vnpatchmanager.steamos_helper import SteamOSHelper


def test_is_steam_deck_env_var(monkeypatch):
    monkeypatch.setenv("STEAM_DECK", "1")
    assert SteamOSHelper.is_steam_deck() is True

    monkeypatch.delenv("STEAM_DECK", raising=False)
    with patch("os.path.exists", return_value=False):
        assert SteamOSHelper.is_steam_deck() is False


def test_is_steam_deck_os_release(monkeypatch, tmp_path):
    monkeypatch.delenv("STEAM_DECK", raising=False)
    fake_os_release = tmp_path / "os-release"
    fake_os_release.write_text('NAME="SteamOS"\nID=steamos\nPRETTY_NAME="SteamOS"\n')

    assert SteamOSHelper.is_steam_deck(os_release_path=str(fake_os_release)) is True


def test_show_onscreen_keyboard_steam_command():
    with patch("shutil.which", side_effect=lambda cmd: "/usr/bin/steam" if cmd == "steam" else None), \
         patch("subprocess.Popen") as mock_popen:
        res = SteamOSHelper.show_onscreen_keyboard()
        assert res is True
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert "steam://open/keyboard" in args


def test_show_onscreen_keyboard_xdg_fallback():
    with patch("shutil.which", side_effect=lambda cmd: "/usr/bin/xdg-open" if cmd == "xdg-open" else None), \
         patch("subprocess.Popen") as mock_popen:
        res = SteamOSHelper.show_onscreen_keyboard()
        assert res is True
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert "steam://open/keyboard" in args


def test_hide_onscreen_keyboard():
    with patch("shutil.which", side_effect=lambda cmd: "/usr/bin/steam" if cmd == "steam" else None), \
         patch("subprocess.Popen") as mock_popen:
        res = SteamOSHelper.hide_onscreen_keyboard()
        assert res is True
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert "steam://close/keyboard" in args


def test_osk_exceptions_and_no_binaries():
    # 1. No steam or xdg-open binary available
    with patch("shutil.which", return_value=None):
        assert SteamOSHelper.show_onscreen_keyboard() is False
        assert SteamOSHelper.hide_onscreen_keyboard() is False

    # 2. Popen exception
    with patch("shutil.which", return_value="/usr/bin/steam"), \
         patch("subprocess.Popen", side_effect=OSError("Exec format error")):
        assert SteamOSHelper.show_onscreen_keyboard() is False
        assert SteamOSHelper.hide_onscreen_keyboard() is False

