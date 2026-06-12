"""
Project path resolution.
"""

from pathlib import Path


_path = Path(__file__).resolve()
CONFIG_DIR = _path.parent
PACKAGE_DIR = CONFIG_DIR.parent
SRC_DIR = PACKAGE_DIR.parent
PROJECT_ROOT = SRC_DIR.parent


def find_project_root() -> Path:
    """Walk up from the wing_twin package to find the project root."""
    current = Path(__file__).resolve()
    for parent in [current.parent] + list(current.parents):
        if (parent / "pyproject.toml").exists() or (parent / "transfer_matrices").exists():
            return parent
    return SRC_DIR.parent
