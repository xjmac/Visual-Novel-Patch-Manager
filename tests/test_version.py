import subprocess
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
        assert ver == "0.1.4"


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
