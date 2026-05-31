"""
TwinState - Data class representing the current digital twin state.
"""

import time
from dataclasses import dataclass, field

import numpy as np


# Lazy-loaded node ID mapping for surface mesh
_surface_node_ids = None


def _get_surface_node_ids():
    global _surface_node_ids
    if _surface_node_ids is None:
        import json
        from pathlib import Path
        mesh_path = Path(__file__).resolve().parent.parent.parent.parent / "mesh" / "FinalMesh_surface.json"

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
    node_damages: dict = field(default_factory=dict)

    desired_angle_of_attack: float = 0.0
    desired_airspeed: float = 0.0

    target_angle_of_attack: float = 0.0
    target_airspeed: float = 0.0

    angle_of_attack: float = 0.0
    airspeed: float = 0.0

    yield_point_pa: float = 100_000_000.0
    max_angle_deg: float = 12.0
    max_speed_kmh: float = 80.0
    max_stepper_steps: int = 2720

    cycles_remaining: float = 0.0
    flight_allowed: bool = True
    prediction_warning: str = ""

    stepper_position: int = 0
    heatmap_mode: str = "damage"
    cycles_histogram: dict = field(default_factory=dict)

    notifications: list = field(default_factory=list)
    _notification_history: set = field(default_factory=set)
    _notification_counter: int = 0

    def add_notification(self, nid: str, ntype: str, title: str, message: str) -> None:
        if nid in self._notification_history:
            return
        self.notifications.append({
            "id": nid,
            "type": ntype,
            "title": title,
            "message": message,
            "timestamp": time.time(),
        })
        self._notification_history.add(nid)

    def dismiss_notification(self, nid: str) -> None:
        self.notifications[:] = [n for n in self.notifications if n["id"] != nid]
        self._notification_history.add(nid)

    def for_unity(self) -> dict:
        """Format state for Unity WebSocket."""
        node_ids = _get_surface_node_ids()
        n_surface = len(node_ids) if node_ids else 0

        has_stress = self.stress_field is not None and len(self.stress_field) > 0
        has_deform = self.deformation_field is not None and len(self.deformation_field) > 0

        if n_surface > 0 and has_stress:
            sf = np.asarray(self.stress_field, dtype=np.float64)
            valid = np.array([nid for nid in node_ids if nid < len(sf)], dtype=np.int32)
            clipped = np.clip(valid, 0, len(sf) - 1)
            surface_stress = np.round(sf[clipped], 2).tolist()
        elif has_stress:
            surface_stress = [round(s, 2) for s in self.stress_field[:n_surface]]
        else:
            surface_stress = []

        if n_surface > 0 and has_deform:
            df = np.asarray(self.deformation_field, dtype=np.float64)
            valid = np.array([nid for nid in node_ids if nid < len(df)], dtype=np.int32)
            clipped = np.clip(valid, 0, len(df) - 1)
            surface_deform = np.round(df[clipped], 6).tolist()
        elif has_deform:
            surface_deform = [round(u, 6) for u in self.deformation_field[:n_surface]]
        else:
            surface_deform = []

        if n_surface > 0 and self.node_damages:
            surface_damage = [round(self.node_damages.get(int(nid), 0.0), 4) for nid in node_ids]
        else:
            surface_damage = [0.0] * n_surface if n_surface else []

        stress_arr = np.array(surface_stress, dtype=np.float64) if surface_stress else np.array([])
        stress_abs = np.abs(stress_arr)
        stress_min = float(np.min(stress_abs)) if stress_abs.size > 0 else 0.0
        stress_max = float(np.max(stress_abs)) if stress_abs.size > 0 else 0.0

        cycles_binned = [
            {"range": r, "count": round(c, 2)}
            for r, c in sorted(self.cycles_histogram.items())
        ] if self.cycles_histogram else []

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
            "notifications": list(self.notifications),
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
