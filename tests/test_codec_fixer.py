"""
Comprehensive unit tests for CodecFixer module.
"""

from unittest.mock import patch
import vdf

from vnpatchmanager.codec_fixer import CodecFixer
from vnpatchmanager.steam_scanner import SteamScanner


def test_find_game_prefix_none_when_no_steam_root():
    with patch.object(SteamScanner, "get_steam_root", return_value=None):
        assert CodecFixer.find_game_prefix("12345") is None


def test_find_game_prefix_primary_root(tmp_path):
    steam_root = tmp_path / "Steam"
    pfx_dir = steam_root / "steamapps" / "compatdata" / "12345" / "pfx"
    pfx_dir.mkdir(parents=True)
    (pfx_dir / "user.reg").write_text("[test]")

    with patch.object(SteamScanner, "get_steam_root", return_value=steam_root):
        found = CodecFixer.find_game_prefix("12345")
        assert found == pfx_dir


def test_find_game_prefix_custom_library(tmp_path):
    steam_root = tmp_path / "Steam"
    steamapps = steam_root / "steamapps"
    steamapps.mkdir(parents=True)

    custom_lib = tmp_path / "SDCard"
    custom_pfx = custom_lib / "steamapps" / "compatdata" / "99999" / "pfx"
    custom_pfx.mkdir(parents=True)
    (custom_pfx / "user.reg").write_text("[test]")

    # Create libraryfolders.vdf
    vdf_content = {
        "libraryfolders": {
            "0": {"path": str(steam_root)},
            "1": {"path": str(custom_lib)},
        }
    }
    (steamapps / "libraryfolders.vdf").write_text(vdf.dumps(vdf_content))

    with patch.object(SteamScanner, "get_steam_root", return_value=steam_root):
        found = CodecFixer.find_game_prefix("99999")
        assert found == custom_pfx


def test_find_game_prefix_not_found(tmp_path):
    steam_root = tmp_path / "Steam"
    (steam_root / "steamapps").mkdir(parents=True)

    with patch.object(SteamScanner, "get_steam_root", return_value=steam_root):
        assert CodecFixer.find_game_prefix("55555") is None


def test_apply_video_fixes_prefix_not_found():
    with patch.object(CodecFixer, "find_game_prefix", return_value=None):
        success, msg = CodecFixer.apply_video_fixes("11111")
        assert success is False
        assert "not found" in msg.lower()


def test_apply_video_fixes_user_reg_missing(tmp_path):
    pfx_dir = tmp_path / "pfx"
    pfx_dir.mkdir()
    with patch.object(CodecFixer, "find_game_prefix", return_value=pfx_dir):
        success, msg = CodecFixer.apply_video_fixes("11111")
        assert success is False
        assert "user.reg not found" in msg


def test_apply_video_fixes_new_section(tmp_path):
    pfx_dir = tmp_path / "pfx"
    pfx_dir.mkdir()
    user_reg = pfx_dir / "user.reg"
    user_reg.write_text('WINE REGISTRY Version 2\n;; All keys relative to \\\\User\n\n[Software\\\\Wine]\n"Version"="1.0"\n')

    with patch.object(CodecFixer, "find_game_prefix", return_value=pfx_dir):
        success, msg = CodecFixer.apply_video_fixes("22222")
        assert success is True
        assert "Successfully applied" in msg

        # Verify user.reg was updated
        content = user_reg.read_text()
        assert "DllOverrides" in content
        assert '"mfplay"="native,builtin"' in content
        assert '"quartz"="native,builtin"' in content

        # Verify backup was created
        backup_reg = pfx_dir / "user.reg.vnpm_bak"
        assert backup_reg.exists()
        assert "DllOverrides" not in backup_reg.read_text()


def test_apply_video_fixes_existing_section(tmp_path):
    pfx_dir = tmp_path / "pfx"
    pfx_dir.mkdir()
    user_reg = pfx_dir / "user.reg"
    initial_content = (
        'WINE REGISTRY Version 2\n\n'
        '[Software\\\\Wine\\\\DllOverrides]\n'
        '"d3d9"="builtin"\n\n'
        '[Software\\\\Other]\n'
        '"Key"="Val"\n'
    )
    user_reg.write_text(initial_content)

    with patch.object(CodecFixer, "find_game_prefix", return_value=pfx_dir):
        success, msg = CodecFixer.apply_video_fixes("33333")
        assert success is True

        content = user_reg.read_text()
        assert '"d3d9"="builtin"' in content
        assert '"mfplay"="native,builtin"' in content
        assert '"quartz"="native,builtin"' in content


def test_apply_video_fixes_atomic_replace_failure(tmp_path):
    pfx_dir = tmp_path / "pfx"
    pfx_dir.mkdir()
    user_reg = pfx_dir / "user.reg"
    user_reg.write_text('WINE REGISTRY Version 2\n')

    with patch.object(CodecFixer, "find_game_prefix", return_value=pfx_dir), \
         patch("os.replace", side_effect=OSError("Disk full")):
        success, msg = CodecFixer.apply_video_fixes("44444")
        assert success is False
        assert "Failed to apply fixes" in msg
