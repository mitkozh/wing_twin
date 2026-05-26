"""
Engine configuration.
"""

from dataclasses import dataclass, field
from typing import Optional

from dtwin.core.fatigue import FatigueConfig


@dataclass
class EngineConfig:
    """Configuration for the digital twin engine."""

    sample_rate: int = 50
    seed: Optional[int] = None
    matrix_dir: Optional[str] = None
    fatigue: FatigueConfig = field(default_factory=FatigueConfig)

    # Prototype wing geometry
    wing_area: float = 0.012375   # m^2
    chord: float     = 0.0491     # m
    span: float      = 0.300      # m
    aspect_ratio: float = 7.27

    steps_per_newton: float = 204.0
    F_max_newtons: float    = 13.3

    # Flight envelope
    reference_speed: float = 120.0   # km/h max
    Cmq: float = -1.5                # pitch damping coefficient
    air_density: float = 1.225       # kg/m^3

    # Flight safety limits
    min_airspeed: float = 40.0
    stress_limit: float = 100_000_000.0  # artificial test limit # It's too big to test the angle or speed adjustment
    max_stepper_steps: int = 2720
    max_aoa: float         = 15.0    # °

    # Second-order dynamics for flight state tracking
    angle_accel: float = 15.0   # deg/s^2
    speed_accel: float = 60.0   # km/h/s^2
