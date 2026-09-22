from unittest.mock import patch, MagicMock
from pathlib import Path
from vnpatchmanager.version import get_version, DEFAULT_VERSION


def test_get_version_in_live_repo():
    ver = get_version()
    assert isinstance(ver, str)
    assert ver.startswith("0.1.") or ver.startswith("0.") or ver.startswith("1.")


def test_get_version_from_git_describe():
    # Tag v0.1.0 with 3 commits ahead -> 0.1.3
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = "v0.1.0-3-g7628ea9\n"

    with patch("subprocess.run", return_value=mock_res), \
         patch("pathlib.Path.exists", return_value=True):
        ver = get_version(repo_root=Path("/fake/repo"))
        assert ver == "0.1.3"


def test_get_version_major_version_bump():
    # Tag v1.0.0 with 2 commits ahead -> 1.0.2
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = "v1.0.0-2-gabc1234\n"

    with patch("subprocess.run", return_value=mock_res), \
         patch("pathlib.Path.exists", return_value=True):
        ver = get_version(repo_root=Path("/fake/repo"))
        assert ver == "1.0.2"


def test_get_version_exact_tag():
    # Exact tag v2.0.0 with 0 commits -> 2.0.0
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = "v2.0.0-0-gabc1234\n"

    with patch("subprocess.run", return_value=mock_res), \
         patch("pathlib.Path.exists", return_value=True):
        ver = get_version(repo_root=Path("/fake/repo"))
        assert ver == "2.0.0"


def test_get_version_commit_count_fallback():
    # Describe fails, but rev-list succeeds
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock()
        if "describe" in cmd:
            res.returncode = 1
            res.stdout = ""
        else:
            res.returncode = 0
            res.stdout = "5\n"
        return res

    with patch("subprocess.run", side_effect=mock_run), \
         patch("pathlib.Path.exists", return_value=True):
        ver = get_version(repo_root=Path("/fake/repo"))
        assert ver == "0.2.4"


def test_get_version_non_git_package_fallback():
    with patch("subprocess.run", side_effect=Exception("Git not found")), \
         patch("importlib.metadata.version", return_value="0.1.0"):
        ver = get_version(repo_root=Path("/fake/non_git_repo"))
        assert ver == "0.1.0"


def test_get_version_total_fallback():
    with patch("subprocess.run", side_effect=Exception("Git not found")), \
         patch("importlib.metadata.version", side_effect=Exception("No package")):
        ver = get_version(repo_root=Path("/fake/non_git_repo"))
        assert ver == DEFAULT_VERSION


def test_version_module_getattr_and_caching():
    import pytest
    import vnpatchmanager.version as vmod

    # 1. Test get_version caching
    vmod.get_version.cache_clear()
    v1 = vmod.get_version()
    assert isinstance(v1, str)

    # Calling get_version again must return cached value without executing subprocess
    with patch("subprocess.run") as mock_run:
        assert vmod.get_version() == v1
        mock_run.assert_not_called()

    # 2. Test __getattr__ for APP_VERSION and __version__
    # Remove from globals if present to force __getattr__ invocation
    vmod.__dict__.pop("APP_VERSION", None)
    vmod.__dict__.pop("__version__", None)

    app_ver = vmod.APP_VERSION
    mod_ver = vmod.__version__
    assert app_ver == v1
    assert mod_ver == v1

    # 3. Invalid attribute raises AttributeError
    with pytest.raises(AttributeError):
        _ = vmod.NON_EXISTENT_ATTR


