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
        import json
        from pathlib import Path
        mesh_path = Path(__file__).parent.parent.parent / "mesh" / "FinalMesh_surface.json"

        if not mesh_path.exists():
            raise FileNotFoundError(f"Surface mesh not found: {mesh_path}")

        with open(mesh_path) as f:
            data = json.load(f)

        if "node_ids" not in data:
            raise KeyError(f"'node_ids' key missing from {mesh_path}")

        node_ids = data["node_ids"]
        if not node_ids:
            raise ValueError(f"node_ids is empty in {mesh_path}")

        _surface_node_ids = node_ids

    return _surface_node_ids


@dataclass
class TwinState:
    """Current state of the wing digital twin."""
    strain_vector: list = field(default_factory=list)
    forces: list = field(default_factory=list)
    stress_field: list = field(default_factory=list)
    deformation_field: list = field(default_factory=list)
    damage: float = 0.0
    avg_damage: float = 0.0
    confidence: float = 100.0
    speed_pct: int = 100
    led_state: str = "green"
    maintenance_alert: bool = False
    node_damages: dict = field(default_factory=dict)

    desired_angle_of_attack: float = 0.0 # Thats the requested angle of attack (from Unity)
    desired_airspeed: float = 0.0

    target_angle_of_attack: float = 0.0 # Thats the target, the one Python code approves
    target_airspeed: float = 0.0

    angle_of_attack: float = 0.0 # Thats the current angle of attack, the one we slowly change
    airspeed: float = 0.0

    # Yield strength of 6061-T6 aluminum
    # yield_point_pa = 276_000_000.0
    # Artificial test value to avoid damaging the real wing during testing
    yield_point_pa: float = 100_000_000.0
    max_angle_deg: float = 12.0
    max_speed_kmh: float = 80.0
    max_stepper_steps: int = 2720

    stepper_position: int = 0
    heatmap_mode: str = "damage"
    cycles: list = field(default_factory=list)

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

        surface_damage = []
        if node_ids and self.node_damages:
            for nid in node_ids:
                surface_damage.append(round(self.node_damages.get(int(nid), 0.0), 4))
        else:
            surface_damage = [0.0] * (len(node_ids) if node_ids else 0)

        stress_abs = [abs(s) for s in surface_stress]

        stress_min = min(stress_abs) if stress_abs else 0.0
        stress_max = max(stress_abs) if stress_abs else 0.0

        # Bin cycles for rainflow chart
        cycles_binned = []
        if self.cycles:
            bin_width = 2.0
            max_range = max(r for r, _ in self.cycles) if self.cycles else 0.0
            if max_range > 0:
                num_bins = int(np.ceil(max_range / bin_width))
                bins = [0.0] * num_bins
                for r, c in self.cycles:
                    idx = min(int(r / bin_width), num_bins - 1)
                    bins[idx] += c
                cycles_binned = [
                    {"range": round((i + 0.5) * bin_width, 1), "count": round(c, 2)}
                    for i, c in enumerate(bins)
                ]

        return {
            "strain": float(np.mean(self.strain_vector)) if self.strain_vector else 0.0,
            "forces": [round(f, 4) for f in self.forces],
            "stress_field": surface_stress,
            "stress_min": round(stress_min, 2),
            "stress_max": round(stress_max, 2),
            "deformation_field": surface_deform,
            "damage": round(self.damage, 4),
            "avg_damage": round(self.avg_damage, 4),
            "node_damages": surface_damage,
            "confidence": round(self.confidence, 2),
            "speed": self.speed_pct,
            "led_state": self.led_state,
            "maintenance_alert": self.maintenance_alert,
            "new_angle_of_attack": self.angle_of_attack,
            "target_angle_of_attack": self.target_angle_of_attack,
            "new_speed": self.airspeed,
            "target_speed": self.target_airspeed,
            "desired_angle_of_attack": self.desired_angle_of_attack,
            "desired_speed": self.desired_airspeed,
            "stepper_position": self.stepper_position,
            "heatmap_mode": self.heatmap_mode,
            "yield_point_pa": self.yield_point_pa,
            "max_angle_deg": self.max_angle_deg,
            "max_speed_kmh": self.max_speed_kmh,
            "max_stepper_steps": self.max_stepper_steps,
            "cycles_binned": cycles_binned,
        }

    def for_esp32(self) -> dict:
        """Format state for ESP32 control."""
        return {
            "position": self.stepper_position,
            "led": self.led_state,
        }