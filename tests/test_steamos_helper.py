from unittest.mock import patch, MagicMock
from vnpatchmanager.steamos_helper import SteamOSHelper


def test_is_steam_deck_env_var(monkeypatch):
    monkeypatch.setenv("STEAM_DECK", "1")
    assert SteamOSHelper.is_steam_deck() is True

    monkeypatch.delenv("STEAM_DECK", raising=False)
    monkeypatch.setenv("SteamDeck", "1")
    assert SteamOSHelper.is_steam_deck() is True

    monkeypatch.delenv("SteamDeck", raising=False)
    with patch("os.path.exists", return_value=False):
        assert SteamOSHelper.is_steam_deck() is False


def test_is_steam_deck_dmi_hardware(monkeypatch, tmp_path):
    monkeypatch.delenv("STEAM_DECK", raising=False)
    monkeypatch.delenv("SteamDeck", raising=False)

    fake_dmi_jupiter = tmp_path / "product_name_jupiter"
    fake_dmi_jupiter.write_text("Jupiter\n")
    assert SteamOSHelper.is_steam_deck(dmi_product_path=str(fake_dmi_jupiter)) is True

    fake_dmi_galileo = tmp_path / "product_name_galileo"
    fake_dmi_galileo.write_text("Galileo\n")
    assert SteamOSHelper.is_steam_deck(dmi_product_path=str(fake_dmi_galileo)) is True

    fake_dmi_pc = tmp_path / "product_name_pc"
    fake_dmi_pc.write_text("Custom Desktop PC\n")
    assert SteamOSHelper.is_steam_deck(dmi_product_path=str(fake_dmi_pc)) is False


def test_is_steam_deck_os_release(monkeypatch, tmp_path):
    monkeypatch.delenv("STEAM_DECK", raising=False)
    monkeypatch.delenv("SteamDeck", raising=False)
    fake_os_release = tmp_path / "os-release"
    fake_os_release.write_text('NAME="SteamOS"\nID=steamos\nPRETTY_NAME="SteamOS"\n')

    assert SteamOSHelper.is_steam_deck(os_release_path=str(fake_os_release)) is True


def test_is_game_mode(monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "gamescope")
    assert SteamOSHelper.is_game_mode() is True

    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.setenv("SteamGamepadUI", "1")
    assert SteamOSHelper.is_game_mode() is True

    monkeypatch.delenv("SteamGamepadUI", raising=False)
    assert SteamOSHelper.is_game_mode() is False


def test_show_onscreen_keyboard_deck_only_filter(monkeypatch):
    monkeypatch.delenv("STEAM_DECK", raising=False)
    monkeypatch.delenv("SteamDeck", raising=False)
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")

    with patch.object(SteamOSHelper, "is_steam_deck", return_value=False), \
         patch.object(SteamOSHelper, "is_game_mode", return_value=False), \
         patch("subprocess.Popen") as mock_popen:
        # Default only_if_deck=True should skip OSK on desktop
        res = SteamOSHelper.show_onscreen_keyboard(only_if_deck=True)
        assert res is False
        mock_popen.assert_not_called()

        # Explicit override only_if_deck=False
        with patch("shutil.which", return_value="/usr/bin/steam"):
            res2 = SteamOSHelper.show_onscreen_keyboard(only_if_deck=False)
            assert res2 is True
            mock_popen.assert_called_once()


def test_show_onscreen_keyboard_steam_command():
    with patch.object(SteamOSHelper, "is_steam_deck", return_value=True), \
         patch("shutil.which", side_effect=lambda cmd: "/usr/bin/steam" if cmd == "steam" else None), \
         patch("subprocess.Popen") as mock_popen:
        res = SteamOSHelper.show_onscreen_keyboard()
        assert res is True
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert "steam://open/keyboard" in args


def test_show_onscreen_keyboard_xdg_fallback():
    with patch.object(SteamOSHelper, "is_steam_deck", return_value=True), \
         patch("shutil.which", side_effect=lambda cmd: "/usr/bin/xdg-open" if cmd == "xdg-open" else None), \
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
    with patch.object(SteamOSHelper, "is_steam_deck", return_value=True), \
         patch("shutil.which", return_value=None):
        assert SteamOSHelper.show_onscreen_keyboard() is False
        assert SteamOSHelper.hide_onscreen_keyboard() is False

    # 2. Popen exception
    with patch.object(SteamOSHelper, "is_steam_deck", return_value=True), \
         patch("shutil.which", return_value="/usr/bin/steam"), \
         patch("subprocess.Popen", side_effect=OSError("Exec format error")):
        assert SteamOSHelper.show_onscreen_keyboard() is False
        assert SteamOSHelper.hide_onscreen_keyboard() is False
