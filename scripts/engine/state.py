"""
TwinState - Data class representing the current digital twin state.
"""

from dataclasses import dataclass, field
import numpy as np


@dataclass
class TwinState:
    """Current state of the wing digital twin."""
    strain_vector: list = field(default_factory=list)
    forces: list = field(default_factory=list)
    stress_field: list = field(default_factory=list)
    deformation_field: list = field(default_factory=list)
    damage: float = 0.0
    confidence: float = 100.0
    speed_pct: int = 100
    led_state: str = "green"
    maintenance_alert: bool = False

    def for_unity(self) -> dict:
        """Format state for Unity WebSocket."""
        return {
            "strain": float(np.mean(self.strain_vector)) if self.strain_vector else 0.0,
            "forces": [round(f, 4) for f in self.forces],
            "stress_field": [round(s, 2) for s in self.stress_field],
            "deformation_field": [round(u, 6) for u in self.deformation_field],
            "damage": round(self.damage, 4),
            "confidence": round(self.confidence, 2),
            "speed": self.speed_pct,
            "led_state": self.led_state,
            "maintenance_alert": self.maintenance_alert,
        }

    def for_esp32(self) -> dict:
        """Format state for ESP32 control."""
        return {
            "servo": self.speed_pct,
            "led": self.led_state,
        }