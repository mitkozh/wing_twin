"""
TwinState - Data class representing the current digital twin state.
"""

from dataclasses import dataclass, field
import numpy as np


# Lazy-loaded node ID mapping for surface mesh
_surface_node_ids = None


def _get_surface_node_ids():
    global _surface_node_ids
    if _surface_node_ids is None:
        try:
            import json
            from pathlib import Path
            mesh_path = Path(__file__).parent.parent.parent / "mesh" / "FinalMesh_surface.json"
            with open(mesh_path) as f:
                data = json.load(f)
            _surface_node_ids = data.get("node_ids")
        except Exception:
            _surface_node_ids = []
    return _surface_node_ids


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
        node_ids = _get_surface_node_ids()
        
        # Extract only surface node stress values
        surface_stress = []
        if node_ids and self.stress_field:
            for nid in node_ids:
                if nid < len(self.stress_field):
                    surface_stress.append(round(self.stress_field[nid], 2))
                elif self.stress_field:
                    surface_stress.append(round(self.stress_field[-1], 2))
                else:
                    surface_stress.append(0.0)
        elif self.stress_field:
            n_surface = len(node_ids) if node_ids else 9102
            surface_stress = [round(s, 2) for s in self.stress_field[:n_surface]]
        
        surface_deform = []
        if node_ids and self.deformation_field:
            for nid in node_ids:
                if nid < len(self.deformation_field):
                    surface_deform.append(round(self.deformation_field[nid], 6))
                elif self.deformation_field:
                    surface_deform.append(round(self.deformation_field[-1], 6))
                else:
                    surface_deform.append(0.0)
        elif self.deformation_field:
            n_surface = len(node_ids) if node_ids else 9102
            surface_deform = [round(u, 6) for u in self.deformation_field[:n_surface]]
        
        return {
            "strain": float(np.mean(self.strain_vector)) if self.strain_vector else 0.0,
            "forces": [round(f, 4) for f in self.forces],
            "stress_field": surface_stress,
            "deformation_field": surface_deform,
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