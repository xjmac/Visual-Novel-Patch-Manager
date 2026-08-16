"""Dynamic version resolver for VN Patch Manager.

Computes semantic versions automatically from Git tags and commit offsets:
- Tag 'v0.1.0' with 0 commits -> '0.1.0'
- Tag 'v0.1.0' with 3 commits -> '0.1.3'
- Tag 'v1.0.0' with 2 commits -> '1.0.2'
Falls back to importlib.metadata or DEFAULT_VERSION when running outside a git repository.
"""

from pathlib import Path
import re
import subprocess
from typing import Optional

DEFAULT_VERSION = "0.1.0"


def get_version(repo_root: Optional[Path] = None) -> str:
    """Returns the dynamic semantic version string computed from git repository metadata."""
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent

    # 1. Try resolving via git describe
    try:
        git_dir = repo_root / ".git"
        if git_dir.exists():
            # Describe against release tags matching vX.Y.Z
            res = subprocess.run(
                ["git", "describe", "--tags", "--match", "v[0-9]*", "--long"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=2,
                check=False
            )
            if res.returncode == 0 and res.stdout.strip():
                # Format: v0.1.0-3-g7628ea9
                out = res.stdout.strip()
                match = re.match(r"^v?(\d+)\.(\d+)\.(\d+)-(\d+)-g[0-9a-f]+$", out)
                if match:
                    major, minor, base_patch, commits = match.groups()
                    effective_patch = int(base_patch) + int(commits)
                    return f"{major}.{minor}.{effective_patch}"

            # If no semantic tags exist yet, compute relative to repository root
            res_count = subprocess.run(
                ["git", "rev-list", "--count", "HEAD"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=2,
                check=False
            )
            if res_count.returncode == 0 and res_count.stdout.strip().isdigit():
                count = int(res_count.stdout.strip())
                # First commit is 0.1.0, 2nd commit is 0.1.1, etc.
                patch_num = max(0, count - 1)
                return f"0.1.{patch_num}"
    except Exception:
        pass

    # 2. Try resolving via package metadata (installed wheel / egg)
    try:
        from importlib.metadata import version, PackageNotFoundError
        pkg_version = version("vnpatchmanager")
        if pkg_version:
            return pkg_version
    except Exception:
        pass

    # 3. Static fallback default
    return DEFAULT_VERSION
