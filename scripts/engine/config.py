"""
Engine configuration.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class EngineConfig:
    """Configuration for the digital twin engine."""
    sample_rate: int = 10
    seed: Optional[int] = None
    matrix_dir: Optional[str] = None