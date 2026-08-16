import json
from pathlib import Path
from unittest.mock import patch
from vnpatchmanager import ConfigManager
import vnpatchmanager


def test_default_config(temp_config_dir):
    cfg_dir, cfg_file = temp_config_dir
    cm = ConfigManager()
    assert cm.config["mode"] == "local"
    assert "local_path" in cm.config
    assert "smb_server" in cm.config
    assert cm.config["smb_username"] == ""
    assert cm.config["smb_password"] == ""


def test_load_existing_config(temp_config_dir):
    cfg_dir, cfg_file = temp_config_dir
    cfg_dir.mkdir(parents=True, exist_ok=True)
    custom_data = {
        "mode": "smb",
        "smb_server": "10.0.0.50",
        "smb_share": "Games",
        "smb_path": "VN/Patches",
        "smb_username": "user",
        "smb_password": "secretpassword"
    }
    with open(cfg_file, "w") as f:
        json.dump(custom_data, f)

    cm = ConfigManager()
    assert cm.config["mode"] == "smb"
    assert cm.config["smb_server"] == "10.0.0.50"
    assert cm.config["smb_share"] == "Games"
    assert cm.config["smb_username"] == "user"
    assert cm.config["smb_password"] == "secretpassword"
    # Ensure default fields not in custom_data are preserved
    assert "local_path" in cm.config


def test_load_corrupted_config(temp_config_dir, caplog):
    cfg_dir, cfg_file = temp_config_dir
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_file.write_text("{invalid json content")

    cm = ConfigManager()
    # Should not crash, keeps defaults
    assert cm.config["mode"] == "local"
    assert "Failed to load config" in caplog.text


def test_save_config(temp_config_dir):
    cfg_dir, cfg_file = temp_config_dir
    cm = ConfigManager()
    cm.config["mode"] = "smb"
    cm.config["smb_server"] = "192.168.1.200"
    cm.save_config()

    assert cfg_file.exists()
    with open(cfg_file, "r") as f:
        saved = json.load(f)
    assert saved["mode"] == "smb"
    assert saved["smb_server"] == "192.168.1.200"


def test_save_config_exception_handling(temp_config_dir, caplog):
    cfg_dir, cfg_file = temp_config_dir
    cm = ConfigManager()
    with patch("builtins.open", side_effect=PermissionError("Mock Permission Denied")):
        cm.save_config()
    assert "Failed to save config" in caplog.text
