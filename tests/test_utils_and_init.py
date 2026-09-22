import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import vnpatchmanager
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
    ]:
        err = exc_cls("Test error")
        assert isinstance(err, VNPatchError)
        assert isinstance(err, Exception)
        assert str(err) == "Test error"


def test_init_lazy_getattr():
    # VNPatchManagerApp loads via __getattr__
    app_cls = getattr(vnpatchmanager, "VNPatchManagerApp")
    assert app_cls.__name__ == "VNPatchManagerApp"

    # Nonexistent attribute raises AttributeError
    with pytest.raises(AttributeError):
        getattr(vnpatchmanager, "NonExistentAttribute")
