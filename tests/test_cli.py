import os
import re
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest


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
