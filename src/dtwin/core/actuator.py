"""
Actuator calibration module.

Provides inverse model to convert desired force to servo command.
The calibration is empirically measured: servo PWM duty cycle -> force at wingtip.

Example calibration (replace with actual measurements):
    pwm_values:    [1000, 1200, 1400, 1500, 1600, 1800, 2000]
    force_values:  [-50, -30, -10, 0, 10, 30, 50]  # Newtons
"""

import numpy as np
from typing import List, Optional, Tuple


DEFAULT_CALIBRATION: Tuple[List[int], List[float]] = (
    [1000, 1200, 1400, 1500, 1600, 1800, 2000],
    [-50.0, -30.0, -10.0, 0.0, 10.0, 30.0, 50.0],
)


class ActuatorModel:
    def __init__(
        self,
        pwm_values: Optional[List[int]] = None,
        force_values: Optional[List[float]] = None,
    ):
        if pwm_values is None or force_values is None:
            pwm_values, force_values = DEFAULT_CALIBRATION

        self.pwm_values = np.array(pwm_values, dtype=np.float64)
        self.force_values = np.array(force_values, dtype=np.float64)

        if len(self.pwm_values) != len(self.force_values):
            raise ValueError("PWM and force arrays must have same length")

        if len(self.pwm_values) < 2:
            raise ValueError("Need at least 2 calibration points")

    def force_to_pwm(self, force: float) -> float:
        return float(np.interp(force, self.force_values, self.pwm_values))

    def pwm_to_force(self, pwm: float) -> float:
        return float(np.interp(pwm, self.pwm_values, self.force_values))

    def get_range(self) -> Tuple[float, float]:
        return float(self.force_values.min()), float(self.force_values.max())


def force_to_servo_pwm(force: float, model: Optional[ActuatorModel] = None) -> int:
    if model is None:
        model = ActuatorModel()
    pwm = model.force_to_pwm(force)
    return int(np.clip(pwm, 1000, 2000))


def apply_force_target(
    force_target: float,
    model: Optional[ActuatorModel] = None,
) -> Tuple[int, int]:
    if model is None:
        model = ActuatorModel()

    min_f, max_f = model.get_range()
    if force_target < min_f or force_target > max_f:
        force_target = np.clip(force_target, min_f, max_f)

    pwm = model.force_to_pwm(force_target)
    pwm_int = int(np.clip(pwm, 1000, 2000))

    speed_pct = int(((pwm_int - 1000) / 1000.0) * 100)
    speed_pct = np.clip(speed_pct, 0, 100)

    return pwm_int, speed_pct