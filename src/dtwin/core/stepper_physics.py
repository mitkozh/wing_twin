"""
Stepper motor physics.
"""

import math
import numpy as np

AIR_DENSITY = 1.225  # kg/m^3 at sea level


def _speed_ratio(airspeed: float, reference_speed: float) -> float:
    if airspeed <= 0 or reference_speed <= 0:
        return 0.0
    return airspeed / reference_speed


def _dynamic_pressure_ratio(airspeed: float, reference_speed: float) -> float:
    sr = _speed_ratio(airspeed, reference_speed)
    return sr * sr


def _lift_force(angle_deg: float) -> float:
    """Sinusoidal lift profile, asymmetric for positive/negative AoA."""
    angle_rad = math.radians(angle_deg)
    if angle_deg >= 0:
        return 6000.0 * math.sin(angle_rad)
    return 3000.0 * math.sin(angle_rad)


def _drag_force(speed_ratio: float) -> float:
    """Parasitic drag grows with speed."""
    return 1500.0 * speed_ratio


def compute_aero_force(
    angle_deg: float,
    airspeed: float,
    reference_speed: float = 500.0,
) -> float:
    """
    Compute the steady aerodynamic force (N) at a given flight condition.

    Returns the total force magnitude combining lift and drag, scaled by
    dynamic pressure ratio (q/q_ref).  This is the mean force that the
    stepper must emulate; dynamic excitation (gust, turbulence, etc.) is
    handled by the simulator separately.
    """
    q = _dynamic_pressure_ratio(airspeed, reference_speed)
    sr = _speed_ratio(airspeed, reference_speed)
    lift = _lift_force(angle_deg) * q
    drag = _drag_force(sr) * q
    return lift + drag


def compute_pitch_damping_force(
    angle_deg: float,
    airspeed: float,
    d_alpha_dt: float,
    chord: float = 0.3,
    Cmq: float = -0.5,
) -> float:
    """
    Pitch-damping moment converted to an equivalent force correction.

    d_alpha_dt = rate of change of angle of attack (rad/s or deg/s).
    Internally converted to rad/s for the physical model.
    """
    v = airspeed / 3.6  # km/h -> m/s
    q_dyn = 0.5 * AIR_DENSITY * v * v
    alpha_dot = math.radians(abs(d_alpha_dt))
    sign = 1.0 if d_alpha_dt >= 0 else -1.0
    return sign * q_dyn * chord * Cmq * alpha_dot


def force_to_steps(F_newtons: float, steps_per_newton: float = 50.0) -> int:
    """Convert aerodynamic force (N) to an absolute stepper position."""
    return int(round(F_newtons * steps_per_newton))


def steps_to_force(steps: int, steps_per_newton: float = 50.0) -> float:
    """Convert stepper position back to force (N)."""
    if steps_per_newton <= 0:
        return 0.0
    return steps / steps_per_newton
