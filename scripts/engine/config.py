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

    # Prototype wing geometry
    wing_area: float = 0.012375   # m^2
    chord: float     = 0.0491     # m
    span: float      = 0.300      # m
    aspect_ratio: float = 7.27

    # todo: adjust based on actual steps and max newtons
    # 2720 steps / 13.3 N ≈ 204 steps/N
    steps_per_newton: float = 204.0
    F_max_newtons: float    = 13.3

    # Flight envelope
    reference_speed: float = 120.0   # km/h max
    max_aoa: float         = 15.0    # °
    Cmq: float = -1.5                # pitch damping coefficient
    air_density: float = 1.225
