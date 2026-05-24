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
    steps_per_degree: float = 10.0
    max_angle_degrees: float = 30.0
    reference_speed: float = 500.0
    steps_per_newton: float = 0.1
    chord: float = 0.3
    Cmq: float = -1.5
    air_density: float = 1.225
