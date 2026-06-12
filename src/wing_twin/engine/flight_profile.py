"""
FlightProfile - takeoff and landing desired angle/speed profiles."""

from dataclasses import dataclass


@dataclass
class TakeoffProfile:
    takeoff_speed_kmh: float = 70.0
    takeoff_climb_angle_deg: float = 10.0
    reference_speed_kmh: float = 110.0
    max_aoa_deg: float = 12.0


@dataclass
class LandingProfile:
    approach_speed_kmh: float = 55.0
    touchdown_speed_kmh: float = 5.0
    approach_aoa_deg: float = 5.0
    flare_aoa_deg: float = 8.0
    flare_altitude_m: float = 0.5
    approach_altitude_m: float = 3.0
    max_aoa_deg: float = 12.0
    reference_speed_kmh: float = 110.0


def takeoff_desired(timer: float, profile: TakeoffProfile) -> tuple[float, float]:
    """Return (desired_angle_deg, desired_speed_kmh) for the given takeoff timer."""
    V_to = profile.takeoff_speed_kmh
    climb = profile.takeoff_climb_angle_deg
    V_ref = profile.reference_speed_kmh
    max_a = profile.max_aoa_deg

    if timer < 3.0:
        frac = timer / 3.0
        speed = V_to * frac
        angle = 0.0
    elif timer < 5.0:
        frac = (timer - 3.0) / 2.0
        speed = V_to
        angle = climb * frac
    else:
        frac = min((timer - 5.0) / 5.0, 1.0)
        speed = V_to + (V_ref - V_to) * frac
        angle = climb

    angle = max(-max_a, min(max_a, angle))
    speed = max(0.0, min(V_ref, speed))
    return angle, speed


def landing_desired(
    altitude_m: float, profile: LandingProfile,
) -> tuple[float, float]:
    """Return (desired_angle_deg, desired_speed_kmh) for the given altitude."""
    td = profile.touchdown_speed_kmh
    V_app = profile.approach_speed_kmh
    aoa_app = profile.approach_aoa_deg
    aoa_flare = profile.flare_aoa_deg
    flare_alt = profile.flare_altitude_m
    approach_end = profile.approach_altitude_m
    max_a = profile.max_aoa_deg
    V_ref = profile.reference_speed_kmh
    touchdown_alt = flare_alt

    if altitude_m > approach_end:
        speed = V_app
        angle = aoa_app
    elif altitude_m > touchdown_alt:
        flare_frac = (approach_end - altitude_m) / (approach_end - touchdown_alt)
        flare_frac = max(0.0, min(1.0, flare_frac))
        speed = V_app + (td - V_app) * flare_frac
        angle = aoa_app + (aoa_flare - aoa_app) * flare_frac
    else:
        touchdown_frac = (touchdown_alt - altitude_m) / touchdown_alt
        touchdown_frac = max(0.0, min(1.0, touchdown_frac))
        speed = td * (1.0 - touchdown_frac)
        angle = aoa_flare * (1.0 - touchdown_frac)

    angle = max(-max_a, min(max_a, angle))
    speed = max(0.0, min(V_ref, speed))
    return angle, speed
