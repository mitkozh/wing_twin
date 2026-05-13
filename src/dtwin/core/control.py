"""
Control module for digital twin decision making based on damage state.
"""

from dtwin.core.fatigue import DAMAGE_SAFE, DAMAGE_WARNING


def decide_control(damage: float) -> tuple[str, int]:
    """
    Determine LED state and speed percentage based on accumulated damage.

    Args:
        damage: Accumulated fatigue damage (0.0 to 1.0)

    Returns:
        Tuple of (led_state: str, speed_pct: int)
    """
    if damage >= DAMAGE_WARNING:
        return "red", 0
    elif damage >= DAMAGE_SAFE:
        return "yellow", 50
    return "green", 100


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