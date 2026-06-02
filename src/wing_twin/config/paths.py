"""
Project path resolution.
"""

from pathlib import Path


_path = Path(__file__).resolve()
CONFIG_DIR = _path.parent
PACKAGE_DIR = CONFIG_DIR.parent
SRC_DIR = PACKAGE_DIR.parent
PROJECT_ROOT = SRC_DIR.parent
