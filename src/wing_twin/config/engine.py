"""
Engine configuration - flight dynamics, lifecycle parameters, and physics defaults.
"""

from dataclasses import dataclass, field
from typing import Optional

from wing_twin.config.types import check_gt, check_ge, check_range
from wing_twin.config.fatigue import FatigueConfig
from wing_twin.config.calibration import CalibrationConfig
from wing_twin.config.wind import WindConfig


@dataclass
class EngineConfig:
    sample_rate: int = 50
    seed: Optional[int] = None
    matrix_dir: Optional[str] = None
    fatigue: FatigueConfig = field(default_factory=FatigueConfig)
    calibration: CalibrationConfig = field(default_factory=CalibrationConfig)

    reference_speed: float = 110.0
    lift_ref_N: float = 1.8
    climb_rate_gain: float = 5.0

    min_airspeed: float = 40.0
    yield_point: float = 80_000_000.0
    stress_limit: float = 45_000_000.0
    max_aoa: float = 12.0

    neuralfoil_model_size: str = "xlarge"

    max_angle_rate: float = 15.0
    max_speed_rate: float = 60.0

    # Flight lifecycle parameters
    takeoff_speed: float = 70.0
    takeoff_climb_angle: float = 10.0
    landing_approach_speed: float = 55.0
    landing_touchdown_speed: float = 5.0
    landing_approach_aoa_deg: float = 5.0
    landing_flare_aoa_deg: float = 8.0
    landing_altitude_threshold: float = 0.3
    max_landing_altitude: float = 50.0
    min_safe_altitude: float = 25.0
    altitude_recovery_aoa_deg: float = 8.0

    wind: WindConfig = field(default_factory=WindConfig)


    def __post_init__(self) -> None:
        check_gt(self.sample_rate, "EngineConfig.sample_rate", 0)
        check_gt(self.reference_speed, "EngineConfig.reference_speed", 0)
        check_ge(self.min_airspeed, "EngineConfig.min_airspeed", 0)
        check_gt(self.yield_point, "EngineConfig.yield_point", 0)
        check_gt(self.stress_limit, "EngineConfig.stress_limit", 0)
        if self.stress_limit > self.yield_point:
            raise ValueError(
                f"EngineConfig.stress_limit ({self.stress_limit}) must be "
                f"<= yield_point ({self.yield_point})"
            )
        check_range(self.max_aoa, "EngineConfig.max_aoa", -90, 90)
        check_gt(self.max_angle_rate, "EngineConfig.max_angle_rate (deg/s)", 0)
        check_gt(self.max_speed_rate, "EngineConfig.max_speed_rate (km/h/s)", 0)
        check_gt(self.takeoff_speed, "EngineConfig.takeoff_speed", 0)
        check_gt(self.landing_approach_speed, "EngineConfig.landing_approach_speed", 0)
        check_ge(self.landing_touchdown_speed, "EngineConfig.landing_touchdown_speed", 0)
        check_ge(self.min_safe_altitude, "EngineConfig.min_safe_altitude", 0)
        check_range(
            self.altitude_recovery_aoa_deg,
            "EngineConfig.altitude_recovery_aoa_deg", 0, 90,
        )
        check_range(
            self.landing_approach_aoa_deg,
            "EngineConfig.landing_approach_aoa_deg", 0, 90,
        )
        check_range(
            self.landing_flare_aoa_deg,
            "EngineConfig.landing_flare_aoa_deg", 0, 90,
        )



