"""
Control module for digital twin decision making based on damage state.
"""

from typing import Optional

from wing_twin.fatigue.fatigue import FatigueConfig


def decide_control(
    damage: float,
    confidence: float = 100.0,
    config: Optional[FatigueConfig] = None
) -> tuple[str, int]:
    if config is None:
        config = FatigueConfig()

    base_speed = 100
    if damage >= config.damage_critical:
        led = "red"
        base_speed = 0
    elif damage >= config.damage_warning:
        led = "yellow"
        base_speed = 50
    else:
        led = "green"
        base_speed = 100

    if confidence < config.confidence_threshold:
        speed = min(base_speed, 50)
    else:
        speed = base_speed

    return led, speed


def decide_control_stress(stress_max_pa: float, speed_pct: int = 100) -> tuple[str, int]:
    stress_mpa = stress_max_pa / 1e6
    if stress_mpa >= 0.8:
        return "red", max(0, speed_pct)
    elif stress_mpa >= 0.3:
        return "yellow", speed_pct
    return "green", speed_pct
