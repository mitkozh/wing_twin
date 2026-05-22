"""
Engine configuration.
"""

from dataclasses import dataclass, field
from typing import Optional

from dtwin.core.fatigue import FatigueConfig


@dataclass
class EngineConfig:
    """Configuration for the digital twin engine."""

    sample_rate: int = 10
    seed: Optional[int] = None
    matrix_dir: Optional[str] = None
    fatigue: FatigueConfig = field(default_factory=FatigueConfig)
