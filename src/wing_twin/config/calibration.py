"""
Calibration configuration for physical model parameters.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from wing_twin.config.types import check_ge, check_gt

logger = logging.getLogger(__name__)


def _find_project_root() -> Path:
    current = Path(__file__).resolve()
    for parent in [current.parent] + list(current.parents):
        if (parent / "pyproject.toml").exists():
            return parent
    return current.parent.parent.parent


def _load_calibration_file() -> tuple[float, ...] | None:
    calib_path = _find_project_root() / "calibration_regression" / "calibration_data.json"
    if not calib_path.exists():
        logger.warning("Calibration file not found at %s — using global scale", calib_path)
        return None
    try:
        with open(calib_path) as f:
            data = json.load(f)
        raw = data.get("per_channel_adc_to_strain_scale")
        if raw is None or len(raw) != 9:
            logger.warning("Invalid calibration data in %s — using global scale", calib_path)
            return None
        return tuple(float(v) for v in raw)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load %s: %s — using global scale", calib_path, exc)
        return None


@dataclass
class CalibrationConfig:
    adc_to_strain_scale: float = 1.862645149230957e-9

    per_channel_adc_to_strain_scale: tuple[float, ...] | None = None

    # Force reconstruction
    H_matrix_scale: float = 1.0

    # Stepper motor
    steps_per_newton: float = 204.0
    stepper_max_steps: int = 2720
    stepper_max_frequency: float = 1000.0  # Hz (max step rate)

    # Aerodynamic force biases (additive corrections)
    lift_bias: float = 0.0
    drag_bias: float = 0.0

    strain_saturation_threshold: float = 0.003

    # Channel names matching ESP32 firmware ordering (9 active gauges)
    channel_names: tuple[str, ...] = (
        "root_0", "root_45", "root_90",
        "middle_0", "middle_45", "middle_90",
        "tip_0", "tip_45", "tip_90",
    )

    def __post_init__(self) -> None:
        check_ge(self.adc_to_strain_scale, "CalibrationConfig.adc_to_strain_scale", 0)
        check_ge(self.steps_per_newton, "CalibrationConfig.steps_per_newton", 0)
        check_gt(self.stepper_max_steps, "CalibrationConfig.stepper_max_steps", 0)
        check_gt(self.stepper_max_frequency, "CalibrationConfig.stepper_max_frequency", 0)
        check_gt(self.H_matrix_scale, "CalibrationConfig.H_matrix_scale", 0)

        if self.per_channel_adc_to_strain_scale is not None:
            if len(self.per_channel_adc_to_strain_scale) != 9:
                raise ValueError(
                    f"per_channel_adc_to_strain_scale must have 9 elements, "
                    f"got {len(self.per_channel_adc_to_strain_scale)}"
                )
        else:
            loaded = _load_calibration_file()
            if loaded is not None:
                object.__setattr__(self, "per_channel_adc_to_strain_scale", loaded)
                logger.info("Loaded per-channel calibration from file")
