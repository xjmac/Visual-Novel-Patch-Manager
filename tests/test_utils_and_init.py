import pytest
from pathlib import Path
from typing import Dict, List, get_type_hints
from unittest.mock import MagicMock
import vnpatchmanager
from vnpatchmanager.ipc_service import VNPMService
from vnpatchmanager.patch_execution import PatchExecutionEngine
from vnpatchmanager.types import GameData, PatchAction, PatchData, ScanGameSummary
from vnpatchmanager.utils import find_database_file, is_mocked
from vnpatchmanager.exceptions import (
    VNPatchError,
    PatchSecurityError,
    PatchExtractionError,
    ProtonExecutionError,
    BackupError,
    ConfigError,
    NetworkError,
    SteamScanError,
    ShortcutsVdfError,
)


def test_find_database_file_explicit(tmp_path):
    explicit = tmp_path / "custom_db.json"
    explicit.write_text("{}")
    found = find_database_file(explicit)
    assert found == explicit


def test_find_database_file_fallback(tmp_path):
    nonexistent = tmp_path / "missing.json"
    found = find_database_file(nonexistent)
    assert isinstance(found, Path)


def test_is_mocked():
    def real_func():
        pass
    assert not is_mocked(real_func)
    mock_func = MagicMock()
    assert is_mocked(mock_func)


def test_exception_hierarchy():
    for exc_cls in [
        PatchSecurityError,
        PatchExtractionError,
        ProtonExecutionError,
        BackupError,
        ConfigError,
        NetworkError,
        SteamScanError,
        ShortcutsVdfError,
    ]:
        err = exc_cls("Test error")
        assert isinstance(err, VNPatchError)
        assert isinstance(err, Exception)
        assert str(err) == "Test error"


def test_boundary_typed_dicts():
    apply_hints = get_type_hints(PatchExecutionEngine.apply_patch)
    assert apply_hints["game_data"] is GameData
    assert apply_hints["patch_data"] is PatchData

    scan_hints = get_type_hints(VNPMService.scan_games)
    assert scan_hints["return"] == Dict[str, ScanGameSummary]

    assert get_type_hints(PatchAction)["args"] == List[str]
    assert vnpatchmanager.ScanGameSummary is ScanGameSummary
    assert vnpatchmanager.PatchAction is PatchAction


def test_init_lazy_getattr():
    # VNPatchManagerApp loads via __getattr__
    app_cls = getattr(vnpatchmanager, "VNPatchManagerApp")
    assert app_cls.__name__ == "VNPatchManagerApp"

    # Nonexistent attribute raises AttributeError
    with pytest.raises(AttributeError):
        getattr(vnpatchmanager, "NonExistentAttribute")
