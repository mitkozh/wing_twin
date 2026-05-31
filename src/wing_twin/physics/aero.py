"""
Stepper motor physics - aerodynamic force model.
"""

import math

AIR_DENSITY = 1.225

PROTO_WING_AREA = 0.012375
PROTO_CHORD = 0.0491
PROTO_SPAN = 0.300
PROTO_AR = 7.27
PROTO_CL_ALPHA = 2 * math.pi / (1 + 2 / PROTO_AR)
CD0 = 0.015
OSWALD_E = 0.85

F_MAX_NEWTONS = 40.0
MAX_STEPPER_STEPS = 2720


def compute_aero_force(
    angle_deg: float,
    airspeed_kmh: float,
) -> float:
    V = airspeed_kmh / 3.6
    q = 0.5 * AIR_DENSITY * V ** 2
    alpha = math.radians(angle_deg)

    CL = PROTO_CL_ALPHA * alpha
    CD = CD0 + CL ** 2 / (math.pi * OSWALD_E * PROTO_AR)

    L = q * PROTO_WING_AREA * CL
    D = q * PROTO_WING_AREA * CD
    return math.sqrt(L ** 2 + D ** 2)


def compute_pitch_damping_force(
    angle_deg: float,
    airspeed_kmh: float,
    d_alpha_dt: float,
    chord: float = PROTO_CHORD,
    Cmq: float = -1.5,
) -> float:
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
    raw = int(round(abs(F_newtons) * steps_per_newton))
    return min(raw, MAX_STEPPER_STEPS)
