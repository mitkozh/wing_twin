"""
Calibration configuration for physical model parameters.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from wing_twin.config.types import check_ge, check_gt
from wing_twin.config.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)


def _load_calibration_file() -> tuple[float, ...] | None:
    calib_path = PROJECT_ROOT / "calibration" / "strain" / "calibration_data.json"
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


def _load_stepper_calibration() -> dict[str, float | int] | None:
    calib_path = PROJECT_ROOT / "calibration" / "stepper" / "stepper_calibration.json"
    if not calib_path.exists():
        logger.info("Stepper calibration file not found at %s — using defaults", calib_path)
        return None
    try:
        with open(calib_path) as f:
            data = json.load(f)
        return {
            "steps_per_newton": data.get("steps_per_newton"),
            "stepper_motor_max_steps": data.get("stepper_motor_max_steps"),
            "stepper_wing_safe_limit": data.get("stepper_wing_safe_limit"),
            "stepper_max_frequency": data.get("stepper_max_frequency"),
        }
    except (json.JSONDecodeError, OSError, KeyError) as exc:
        logger.warning("Failed to load %s: %s — using defaults", calib_path, exc)
        return None


@dataclass
class CalibrationConfig:
    adc_to_strain_scale: float = 1.862645149230957e-9

    per_channel_adc_to_strain_scale: tuple[float, ...] | None = None

    # Force reconstruction
    H_matrix_scale: float = 1.0

    # Stepper motor
    steps_per_newton: float = 204.0
    stepper_motor_max_steps: int = 2720        # physical limit of the stepper motor
    stepper_wing_safe_limit: int = 2500        # hard limit to prevent wing damage (<= motor max)
    stepper_max_frequency: float = 1000.0      # Hz (max step rate)
    stepper_min_position: int = -500           # software min (safe retract, neg = reverse)
    stepper_coarse_step: int = 20              # coarse search increment during zero cal
    stepper_strain_threshold: float = 5000.0   # ADC delta that indicates contact
    stepper_slack_threshold: float = 500.0     # ADC delta that indicates free movement
    stepper_contact_confirm: int = 3           # consecutive above-threshold reads to confirm contact
    stepper_calibration_num_samples: int = 10  # strain samples per baseline measurement
    stepper_calibration_poll_s: float = 0.02   # poll interval for stepper-idle wait in seconds
    stepper_calibration_retract_timeout_s: float = 10.0
    stepper_calibration_move_timeout_s: float = 5.0

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
        check_gt(self.stepper_motor_max_steps, "CalibrationConfig.stepper_motor_max_steps", 0)
        check_gt(self.stepper_wing_safe_limit, "CalibrationConfig.stepper_wing_safe_limit", 0)
        check_gt(self.stepper_max_frequency, "CalibrationConfig.stepper_max_frequency", 0)
        check_gt(self.H_matrix_scale, "CalibrationConfig.H_matrix_scale", 0)

        if self.stepper_wing_safe_limit > self.stepper_motor_max_steps:
            logger.warning(
                "stepper_wing_safe_limit (%d) exceeds stepper_motor_max_steps (%d) — clamping",
                self.stepper_wing_safe_limit, self.stepper_motor_max_steps,
            )
            object.__setattr__(self, "stepper_wing_safe_limit", self.stepper_motor_max_steps)

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

        # Auto-load stepper calibration file, overriding defaults
        stepper_cal = _load_stepper_calibration()
        if stepper_cal is not None:
            for key, default_val in [
                ("steps_per_newton", self.steps_per_newton),
                ("stepper_motor_max_steps", self.stepper_motor_max_steps),
                ("stepper_wing_safe_limit", self.stepper_wing_safe_limit),
                ("stepper_max_frequency", self.stepper_max_frequency),
            ]:
                val = stepper_cal.get(key)
                if val is not None:
                    expected_type = type(default_val)
                    if isinstance(val, expected_type):
                        object.__setattr__(self, key, val)
                    else:
                        logger.warning(
                            "stepper_cal.json key '%s' has wrong type (expected %s, got %s) — skipping",
                            key, expected_type.__name__, type(val).__name__,
                        )
            # Re-check wing safe limit ≤ motor max after loading
            if self.stepper_wing_safe_limit > self.stepper_motor_max_steps:
                logger.warning(
                    "Calibrated stepper_wing_safe_limit (%d) exceeds motor max (%d) - clamping",
                    self.stepper_wing_safe_limit, self.stepper_motor_max_steps,
                )
                object.__setattr__(self, "stepper_wing_safe_limit", self.stepper_motor_max_steps)

            logger.info(
                "Loaded stepper calibration: steps/N=%.1f, motor_max=%d, wing_limit=%d, freq=%.0f Hz",
                self.steps_per_newton, self.stepper_motor_max_steps,
                self.stepper_wing_safe_limit, self.stepper_max_frequency,
            )
