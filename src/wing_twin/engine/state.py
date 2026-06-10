"""
TwinState - Data class representing the current digital twin state.
EngineSnapshot - Unified save/restore container for full engine state.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from wing_twin.control.control import decide_control, decide_control_stress


# Lazy-loaded node ID mapping for surface mesh
_surface_node_ids = None
_section_nodes = None


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


def _get_section_nodes():
    global _section_nodes
    if _section_nodes is not None:
        return _section_nodes

    import json
    from pathlib import Path
    mesh_path = Path(__file__).resolve().parent.parent.parent.parent / "mesh" / "FinalMesh_surface.json"

    if not mesh_path.exists():
        _section_nodes = {"root": [], "middle": [], "tip": []}
        return _section_nodes

    with open(mesh_path) as f:
        data = json.load(f)

    vertices = data.get("vertices", [])
    node_ids = data.get("node_ids", [])

    if not vertices or not node_ids or len(vertices) != len(node_ids):
        _section_nodes = {"root": [], "middle": [], "tip": []}
        return _section_nodes

    span_min = min(v[0] for v in vertices)
    span_max = max(v[0] for v in vertices)
    span_range = span_max - span_min

    if span_range <= 0:
        _section_nodes = {"root": [], "middle": [], "tip": []}
        return _section_nodes

    third = span_range / 3.0
    sections = {"root": [], "middle": [], "tip": []}
    for i, v in enumerate(vertices):
        nid = node_ids[i]
        pos = v[0] - span_min
        if pos < third:
            sections["root"].append(nid)
        elif pos < 2 * third:
            sections["middle"].append(nid)
        else:
            sections["tip"].append(nid)

    _section_nodes = sections
    return _section_nodes


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
    node_damages: dict = field(default_factory=dict)

    desired_angle_of_attack: float = 0.0
    desired_airspeed: float = 0.0

    target_angle_of_attack: float = 0.0
    target_airspeed: float = 0.0

    angle_of_attack: float = 0.0
    airspeed: float = 0.0

    yield_point_pa: float = 80_000_000.0
    stress_limit_pa: float = 65_000_000.0
    max_angle_deg: float = 12.0
    max_speed_kmh: float = 110.0
    max_stepper_steps: int = 2720

    flight_allowed: bool = True

    stepper_position: int = 0
    esp32_reported_position: Optional[int] = None
    esp32_reported_home_offset: Optional[int] = None
    heatmap_mode: str = "damage"
    cycles_histogram: dict = field(default_factory=dict)

    notifications: list = field(default_factory=list)

    # Flight lifecycle state
    flight_phase: str = "on_ground"
    altitude: float = 0.0
    km_this_flight: float = 0.0
    total_km_flown: float = 0.0
    flight_number: int = 0

    max_landing_altitude: float = 50.0

    # Remaining safe flight distance (from life prediction)
    remaining_km: float = float('inf')

    # Maintenance assist toggle
    maintenance_assist: bool = True

    # Pre-flight planning state
    planned_km: float = 0.0
    pre_flight_safe: bool = True
    pre_flight_warning: str = ""

    # Apparent (wind-corrected) flight state
    wind_horizontal_ms: float = 0.0
    wind_vertical_ms: float = 0.0
    wind_horizontal_smoothed_ms: float = 0.0
    wind_vertical_smoothed_ms: float = 0.0
    effective_airspeed_kmh: float = 0.0
    effective_aoa_deg: float = 0.0

    def add_notification(self, nid: str, ntype: str, title: str, message: str) -> None:
        if any(n["id"] == nid for n in self.notifications):
            return
        self.notifications.append({
            "id": nid,
            "type": ntype,
            "title": title,
            "message": message,
            "timestamp": time.time(),
        })

    def dismiss_notification(self, nid: str) -> None:
        self.notifications[:] = [n for n in self.notifications if n["id"] != nid]

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
            "notifications": list(self.notifications),
            "new_angle_of_attack": self.angle_of_attack,
            "target_angle_of_attack": self.target_angle_of_attack,
            "new_speed": self.airspeed,
            "target_speed": self.target_airspeed,
            "desired_angle_of_attack": self.desired_angle_of_attack,
            "desired_speed": self.desired_airspeed,
            "stepper_position": self.stepper_position,
            "esp32_reported_position": self.esp32_reported_position,
            "esp32_reported_home_offset": self.esp32_reported_home_offset,
            "heatmap_mode": self.heatmap_mode,
            "yield_point_pa": self.yield_point_pa,
            "stress_limit_pa": self.stress_limit_pa,
            "max_angle_deg": self.max_angle_deg,
            "max_speed_kmh": self.max_speed_kmh,
            "max_stepper_steps": self.max_stepper_steps,
            "cycles_binned": cycles_binned,
            "flight_allowed": self.flight_allowed,
            # Flight lifecycle
            "flight_phase": self.flight_phase,
            "altitude": round(self.altitude, 2),
            "km_this_flight": round(self.km_this_flight, 3),
            "total_km_flown": round(self.total_km_flown, 2),
            "flight_number": self.flight_number,
            # Config values for Unity decision-making
            "max_landing_altitude": self.max_landing_altitude,
            # Remaining distance (from life prediction)
            "remaining_km": round(self.remaining_km, 1),
            # Maintenance assist
            "maintenance_assist": self.maintenance_assist,
            # Pre-flight planning
            "planned_km": round(self.planned_km, 1),
            "pre_flight_safe": self.pre_flight_safe,
            "pre_flight_warning": self.pre_flight_warning,
            # Apparent (wind-corrected) flow
            "wind_horizontal_ms": round(self.wind_horizontal_ms, 3),
            "wind_vertical_ms": round(self.wind_vertical_ms, 3),
            "wind_horizontal_smoothed_ms": round(self.wind_horizontal_smoothed_ms, 3),
            "wind_vertical_smoothed_ms": round(self.wind_vertical_smoothed_ms, 3),
            "effective_airspeed_kmh": round(self.effective_airspeed_kmh, 3),
            "effective_aoa_deg": round(self.effective_aoa_deg, 3),
        }

    def _compute_led_colors(self) -> list:
        sections = _get_section_nodes()
        colors = []
        for section_name in ["tip", "middle", "root"]:
            node_ids = sections[section_name]
            if not node_ids:
                colors.append("green")
                continue

            if self.heatmap_mode == "damage":
                damages = [self.node_damages.get(nid, 0.0) for nid in node_ids]
                max_damage = max(damages)
                color, _ = decide_control(max_damage, self.confidence)
            else:
                sf = self.stress_field
                if not sf or len(sf) == 0:
                    colors.append("green")
                    continue
                max_stress = 0.0
                for nid in node_ids:
                    if nid < len(sf):
                        stress_val = abs(sf[nid])
                        if stress_val > max_stress:
                            max_stress = stress_val
                color = decide_control_stress(max_stress, self.yield_point_pa)

            colors.append(color)

        return colors

    def for_esp32(self) -> dict:
        """Format state for ESP32 control."""
        return {
            "position": self.stepper_position,
            "leds": self._compute_led_colors(),
        }

    def to_snapshot_dict(self) -> dict:
        fields_to_save = [
            "damage", "avg_damage", "confidence",
            "desired_angle_of_attack", "desired_airspeed",
            "target_angle_of_attack", "target_airspeed",
            "angle_of_attack", "airspeed",
            "flight_allowed", "stepper_position", "esp32_reported_position", "esp32_reported_home_offset", "heatmap_mode", "maintenance_assist",
            "flight_phase", "altitude", "km_this_flight",
            "total_km_flown", "flight_number",
            "remaining_km", "planned_km", "pre_flight_safe", "pre_flight_warning",
            "cycles_histogram", "notifications",
            "strain_vector", "forces", "stress_field", "deformation_field",
            "node_damages",
            "wind_horizontal_ms", "wind_vertical_ms",
            "wind_horizontal_smoothed_ms", "wind_vertical_smoothed_ms",
            "effective_airspeed_kmh", "effective_aoa_deg",
        ]
        return {k: getattr(self, k) for k in fields_to_save}

    @staticmethod
    def from_snapshot_dict(data: dict) -> "TwinState":
        state = TwinState()
        for k, v in data.items():
            if hasattr(state, k):
                setattr(state, k, v)
        if state.node_damages:
            state.node_damages = {int(k): v for k, v in state.node_damages.items()}
        return state


SNAPSHOT_VERSION = 2


@dataclass
class EngineSnapshot:
    version: int = SNAPSHOT_VERSION
    twin: Optional[dict] = None
    fatigue: Optional[dict] = None
    life: Optional[dict] = None
    flight: Optional[dict] = None
    dynamics: Optional[dict] = None
    prev_low_confidence: bool = False
    prev_flight_blocked: bool = False
    wind: Optional[dict] = None

    def to_file(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": self.version,
            "twin": self.twin,
            "fatigue": self.fatigue,
            "life": self.life,
            "flight": self.flight,
            "dynamics": self.dynamics,
            "prev_low_confidence": self.prev_low_confidence,
            "prev_flight_blocked": self.prev_flight_blocked,
            "wind": self.wind,
        }
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        tmp.replace(path)

    @staticmethod
    def from_file(path: Path) -> "EngineSnapshot":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Engine snapshot not found: {path}")
        with open(path) as f:
            data = json.load(f)
        version = data["version"]
        if version > SNAPSHOT_VERSION:
            raise ValueError(
                f"Snapshot version {version} is newer than supported {SNAPSHOT_VERSION}"
            )
        return EngineSnapshot(
            version=version,
            twin=data.get("twin"),
            fatigue=data.get("fatigue"),
            life=data.get("life"),
            flight=data.get("flight"),
            dynamics=data.get("dynamics"),
            prev_low_confidence=data.get("prev_low_confidence", False),
            prev_flight_blocked=data.get("prev_flight_blocked", False),
            wind=data.get("wind"),
        )
