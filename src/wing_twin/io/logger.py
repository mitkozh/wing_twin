"""
Centralized logging configuration for Wing Digital Twin.

To enable debug output:
    WING_TWIN_LOG_LEVEL=DEBUG
"""

import logging
import os
import sys
from typing import Optional

_DEFAULT_LOG_LEVEL = os.getenv("WING_LOG_LEVEL") or os.getenv("WING_TWIN_LOG_LEVEL", "INFO")
_DEFAULT_LOG_LEVEL = _DEFAULT_LOG_LEVEL.upper()

_FORMATTER = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def configure_logging(
    level: str = _DEFAULT_LOG_LEVEL,
    output: Optional[str] = None,
) -> None:
    numeric_level = getattr(logging, level, logging.INFO)
    root = logging.getLogger()
    root.setLevel(numeric_level)
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    if output:
        handler = logging.FileHandler(output)
    else:
        handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(numeric_level)
    handler.setFormatter(_FORMATTER)
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


configure_logging()
