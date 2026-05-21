"""
Centralized logging configuration for Wing Digital Twin.

To enable debug output, set the environment variable:
    WING_TWIN_LOG_LEVEL=DEBUG

Or configure programmatically:
    from scripts.logger import configure_logging
    configure_logging(level="DEBUG")
"""

import logging
import os
import sys
from typing import Optional

_DEFAULT_LOG_LEVEL = os.getenv("WING_TWIN_LOG_LEVEL", "INFO").upper()

_FORMATTER = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def configure_logging(
    level: str = _DEFAULT_LOG_LEVEL,
    output: Optional[str] = None,
) -> None:
    """Configure the root logger for the application.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        output: Optional file path to write logs to. If None, logs to stderr.
    """
    numeric_level = getattr(logging, level, logging.INFO)

    root = logging.getLogger()
    root.setLevel(numeric_level)

    # Remove existing handlers to avoid duplicates
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
    """Get a logger instance for the given module name.

    Args:
        name: Typically ``__name__`` of the calling module.

    Returns:
        A configured logger instance.
    """
    return logging.getLogger(name)


configure_logging()
