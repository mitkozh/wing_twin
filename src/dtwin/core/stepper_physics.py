"""
Stepper motor physics.
"""

import math
import numpy as np

AIR_DENSITY = 1.225  # kg/m^3 at sea level

PROTO_WING_AREA  = 0.012375  # m^2   (0.5 * (0.0725 + 0.010) * 0.300)
PROTO_CHORD      = 0.0491    # m    (mean aerodynamic chord)
PROTO_SPAN       = 0.300     # m
PROTO_AR         = 7.27      # aspect ratio b^2/S
PROTO_CL_ALPHA   = 2 * math.pi / (1 + 2 / PROTO_AR)  # finite-wing correction
CD0              = 0.015     # zero-lift drag coefficient
OSWALD_E         = 0.85      # Oswald efficiency factor

F_MAX_NEWTONS     = 40.0
MAX_STEPPER_STEPS = 2720 # 85 % of 3200


def compute_aero_force(
    angle_deg: float,
    airspeed_kmh: float,
) -> float:
    """
    Compute resultant aerodynamic force (N) on the prototype wing
    for the given simulated flight condition using thin-airfoil theory.
    """
    V = airspeed_kmh / 3.6          # km/h → m/s
    q = 0.5 * AIR_DENSITY * V ** 2  # dynamic pressure (Pa)
    alpha = math.radians(angle_deg)

    CL = PROTO_CL_ALPHA * alpha
    CD = CD0 + CL ** 2 / (math.pi * OSWALD_E * PROTO_AR)

    L = q * PROTO_WING_AREA * CL
    D = q * PROTO_WING_AREA * CD
    return math.sqrt(L ** 2 + D ** 2)


def compute_pitch_damping_force(
    angle_deg: float,
    airspeed_kmh: float,
    d_alpha_dt: float, # °/s
    chord: float = PROTO_CHORD,
    Cmq: float = -1.5,
) -> float:
    """
    Pitch-rate damping moment converted to an equivalent force correction.

    d_alpha_dt = rate of change of angle of attack (deg/s).
    Internally converted to rad/s for the physical model.
    """
    V = airspeed_kmh / 3.6
    q = 0.5 * AIR_DENSITY * V ** 2
    alpha_dot_rad = math.radians(abs(d_alpha_dt))
    sign = 1.0 if d_alpha_dt >= 0 else -1.0
    M_damp = q * PROTO_WING_AREA * chord * Cmq * alpha_dot_rad
    return sign * M_damp / chord


def force_to_steps(
    F_newtons: float,
    steps_per_newton: float = 204.0,
) -> int:
    """
    Convert aerodynamic force (N) to a stepper absolute position.
    """
    raw = int(round(abs(F_newtons) * steps_per_newton))
    return min(raw, MAX_STEPPER_STEPS)


