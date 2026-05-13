"""
Control module for digital twin decision making based on damage state.
Per SSA Level 3: combines damage-based and confidence-based control.
"""

from dtwin.core.fatigue import DAMAGE_SAFE, DAMAGE_WARNING, CONFIDENCE_THRESHOLD


def decide_control(damage: float, confidence: float = 100.0) -> tuple[str, int]:
    """
    Determine LED state and speed percentage based on damage and confidence.
    Args:
        damage: Accumulated fatigue damage (0.0 to 1.0)
        confidence: Model confidence percentage (0 to 100)

    Returns:
        Tuple of (led_state: str, speed_pct: int)
    """
    base_speed = 100
    if damage >= DAMAGE_WARNING:
        led = "red"
        base_speed = 0
    elif damage >= DAMAGE_SAFE:
        led = "yellow"
        base_speed = 50
    else:
        led = "green"
        base_speed = 100

    if confidence < CONFIDENCE_THRESHOLD:
        speed = min(base_speed, 50)
    else:
        speed = base_speed

    return led, speed


def describe_state(damage: float, led: str, speed: int) -> str:
    """
    Generate a human-readable description of the current wing state.

    Args:
        damage: Accumulated fatigue damage (0.0 to 1.0)
        led: Current LED state
        speed: Current speed percentage

    Returns:
        Formatted state description string
    """
    if damage >= DAMAGE_WARNING:
        return f"CRITICAL — D={damage:.4f} — LED={led} — Vmax={speed}%"
    elif damage >= DAMAGE_SAFE:
        return f"WARNING — D={damage:.4f} — LED={led} — Vmax={speed}%"
    return f"SAFE — D={damage:.4f} — LED={led} — Vmax={speed}%"