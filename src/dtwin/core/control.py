"""
Control module for digital twin decision making based on damage state.
Per SSA Level 3: combines damage-based and confidence-based control.
"""

from typing import Optional
from dtwin.core.fatigue import FatigueConfig


def decide_control(damage: float, confidence: float = 100.0, config: Optional[FatigueConfig] = None) -> tuple[str, int]:
    """
    Determine LED state and speed percentage based on damage and confidence.
    Args:
        damage: Accumulated fatigue damage (0.0 to 1.0)
        confidence: Model confidence percentage (0 to 100)
        config: Configuration containing thresholds

    Returns:
        Tuple of (led_state: str, speed_pct: int)
    """
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
    """
    Determine LED state based on stress level (for stress heatmap mode).
    Uses same threshold convention as damage: green < 0.3MPa, yellow < 0.8MPa, red >= 0.8MPa.

    Args:
        stress_max_pa: Maximum stress in Pascals
        speed_pct: Current speed percentage

    Returns:
        Tuple of (led_state: str, speed_pct: int)
    """
    stress_mpa = stress_max_pa / 1e6
    if stress_mpa >= 0.8:
        return "red", max(0, speed_pct)
    elif stress_mpa >= 0.3:
        return "yellow", speed_pct
    return "green", speed_pct


def _describe_state(damage: float, led: str, speed: int, config: Optional[FatigueConfig] = None) -> str:
    """
    Generate a human-readable description of the current wing state.

    Args:
        damage: Accumulated fatigue damage (0.0 to 1.0)
        led: Current LED state
        speed: Current speed percentage
        config: Configuration containing thresholds

    Returns:
        Formatted state description string
    """
    if config is None:
        config = FatigueConfig()

    if damage >= config.damage_critical:
        return f"CRITICAL D={damage:.4f} LED={led} Vmax={speed}%"
    elif damage >= config.damage_warning:
        return f"WARNING D={damage:.4f} LED={led} Vmax={speed}%"
    return f"SAFE D={damage:.4f} LED={led} Vmax={speed}%"