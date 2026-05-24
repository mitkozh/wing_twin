"""
Stepper motor calibration.

The physical wing's angle of attack is controlled by a stepper motor
driving a linear actuator.  The calibration constant STEPS_PER_DEGREE
must be determined empirically.
"""


def _speed_factor(speed: float, reference_speed: float) -> float:
    if speed <= 0:
        return 5.0
    return max(0.1, min(5.0, reference_speed / speed))


def stepper_steps_from_angle(
    angle_deg: float, speed: float, steps_per_degree: float,
    reference_speed: float = 500.0,
) -> int:
    """Convert angle of attack (degrees) and speed (km/h) to stepper position."""
    spd = steps_per_degree * _speed_factor(speed, reference_speed)
    return int(round(angle_deg * spd))


def angle_from_stepper_steps(
    steps: int, speed: float, steps_per_degree: float,
    reference_speed: float = 500.0,
) -> float:
    """Convert stepper position back to angle of attack (degrees)."""
    spd = steps_per_degree * _speed_factor(speed, reference_speed)
    return steps / spd
