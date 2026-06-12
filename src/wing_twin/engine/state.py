"""
TwinState - Container for focused sub-dataclasses representing digital twin state.
EngineSnapshot - Unified save/restore container for full engine state.
"""

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from wing_twin.control.control import heatmap_color
from wing_twin.mesh.exporter import load_section_nodes, load_surface_node_ids


_SECTION_NODES_CACHE = None


def _get_section_nodes():
    global _SECTION_NODES_CACHE
    if _SECTION_NODES_CACHE is None:
        _SECTION_NODES_CACHE = load_section_nodes()
    return _SECTION_NODES_CACHE


@dataclass
class StructuralState:
    """Structural FEA results and cycle counting."""
    strain_vector: list = field(default_factory=list)
    forces: list = field(default_factory=list)
    stress_field: list = field(default_factory=list)
    deformation_field: list = field(default_factory=list)
    cycles_histogram: dict = field(default_factory=dict)
    yield_point_pa: float = 80_000_000.0
    stress_limit_pa: float = 45_000_000.0


@dataclass
class DamageState:
    """Cumulative damage tracking and node-level health."""
    damage: float = 0.0
    avg_damage: float = 0.0
    confidence: float = 100.0
    node_damages: dict = field(default_factory=dict)


@dataclass
class FlightState:
    """Flight lifecycle - phase, position, distances, pre-flight planning."""
    flight_phase: str = "on_ground"
    altitude: float = 0.0
    km_this_flight: float = 0.0
    total_km_flown: float = 0.0
    flight_number: int = 0
    remaining_km: float = float('inf')
    max_landing_altitude: float = 50.0
    flight_allowed: bool = True
    planned_km: float = 0.0
    pre_flight_safe: bool = True
    pre_flight_warning: str = ""


@dataclass
class ControlState:
    """Current, target, and desired flight control surfaces."""
    angle_of_attack: float = 0.0
    airspeed: float = 0.0
    target_angle_of_attack: float = 0.0
    target_airspeed: float = 0.0
    desired_angle_of_attack: float = 0.0
    desired_airspeed: float = 0.0
    max_angle_deg: float = 12.0
    max_speed_kmh: float = 110.0
    max_stepper_steps: int = 2720


@dataclass
class StepperHardwareState:
    """ESP32 stepper hardware state and display mode."""
    stepper_position: int = 0
    esp32_reported_position: Optional[int] = None
    esp32_reported_home_offset: Optional[int] = None
    heatmap_mode: str = "damage"


@dataclass
class WindState:
    """Apparent (wind-corrected) aerodynamic flow state."""
    wind_horizontal_ms: float = 0.0
    wind_vertical_ms: float = 0.0
    wind_horizontal_smoothed_ms: float = 0.0
    wind_vertical_smoothed_ms: float = 0.0
    effective_airspeed_kmh: float = 0.0
    effective_aoa_deg: float = 0.0


@dataclass
class NotificationState:
    """In-app notification stack and assist toggles."""
    items: list = field(default_factory=list)
    maintenance_assist: bool = True


class TwinState:
    """Container for all digital-twin sub-states.

    Access fields explicitly, e.g. ``state.flight.flight_phase``.
    """

    def __init__(self) -> None:
        self.structural = StructuralState()
        self.damage = DamageState()
        self.flight = FlightState()
        self.control = ControlState()
        self.stepper = StepperHardwareState()
        self.wind = WindState()
        self.notifications = NotificationState()

    # -- notification helpers --
    def add_notification(self, nid: str, ntype: str, title: str, message: str) -> None:
        if any(n["id"] == nid for n in self.notifications.items):
            return
        self.notifications.items.append({
            "id": nid,
            "type": ntype,
            "title": title,
            "message": message,
            "timestamp": time.time(),
        })

    def dismiss_notification(self, nid: str) -> None:
        self.notifications.items[:] = [
            n for n in self.notifications.items if n["id"] != nid
        ]

    # -- serialization --
    def for_unity(self) -> dict:
        """Format state for Unity WebSocket."""
        node_ids = load_surface_node_ids()
        n_surface = len(node_ids) if node_ids else 0

        s = self.structural
        has_stress = s.stress_field is not None and len(s.stress_field) > 0
        has_deform = s.deformation_field is not None and len(s.deformation_field) > 0

        if n_surface > 0 and has_stress:
            sf = np.asarray(s.stress_field, dtype=np.float64)
            valid = np.array([nid for nid in node_ids if nid < len(sf)], dtype=np.int32)
            clipped = np.clip(valid, 0, len(sf) - 1)
            surface_stress = np.round(sf[clipped], 2).tolist()
        elif has_stress:
            surface_stress = [round(s2, 2) for s2 in s.stress_field[:n_surface]]
        else:
            surface_stress = []

        if n_surface > 0 and has_deform:
            df = np.asarray(s.deformation_field, dtype=np.float64)
            valid = np.array([nid for nid in node_ids if nid < len(df)], dtype=np.int32)
            clipped = np.clip(valid, 0, len(df) - 1)
            surface_deform = np.round(df[clipped], 6).tolist()
        elif has_deform:
            surface_deform = [round(u, 6) for u in s.deformation_field[:n_surface]]
        else:
            surface_deform = []

        d = self.damage
        if n_surface > 0 and d.node_damages:
            surface_damage = [round(d.node_damages.get(int(nid), 0.0), 4) for nid in node_ids]
        else:
            surface_damage = [0.0] * n_surface if n_surface else []

        stress_arr = np.array(surface_stress, dtype=np.float64) if surface_stress else np.array([])
        stress_abs = np.abs(stress_arr)
        stress_min = float(np.min(stress_abs)) if stress_abs.size > 0 else 0.0
        stress_max = float(np.max(stress_abs)) if stress_abs.size > 0 else 0.0

        cycles_binned = [
            {"range": r, "count": round(c, 2)}
            for r, c in sorted(s.cycles_histogram.items())
        ] if s.cycles_histogram else []

        ctrl = self.control
        fl = self.flight
        stp = self.stepper
        w = self.wind
        ntf = self.notifications

        return {
            "strain": float(np.mean(s.strain_vector)) if s.strain_vector else 0.0,
            "forces": [round(f, 4) for f in s.forces],
            "stress_field": surface_stress,
            "stress_min": round(stress_min, 2),
            "stress_max": round(stress_max, 2),
            "deformation_field": surface_deform,
            "damage": round(d.damage, 4),
            "avg_damage": round(d.avg_damage, 4),
            "node_damages": surface_damage,
            "confidence": round(d.confidence, 2),
            "notifications": list(ntf.items),
            "new_angle_of_attack": ctrl.angle_of_attack,
            "target_angle_of_attack": ctrl.target_angle_of_attack,
            "new_speed": ctrl.airspeed,
            "target_speed": ctrl.target_airspeed,
            "desired_angle_of_attack": ctrl.desired_angle_of_attack,
            "desired_speed": ctrl.desired_airspeed,
            "stepper_position": stp.stepper_position,
            "esp32_reported_position": stp.esp32_reported_position,
            "esp32_reported_home_offset": stp.esp32_reported_home_offset,
            "heatmap_mode": stp.heatmap_mode,
            "yield_point_pa": s.yield_point_pa,
            "stress_limit_pa": s.stress_limit_pa,
            "max_angle_deg": ctrl.max_angle_deg,
            "max_speed_kmh": ctrl.max_speed_kmh,
            "max_stepper_steps": ctrl.max_stepper_steps,
            "cycles_binned": cycles_binned,
            "flight_allowed": fl.flight_allowed,
            "flight_phase": fl.flight_phase,
            "altitude": round(fl.altitude, 2),
            "km_this_flight": round(fl.km_this_flight, 3),
            "total_km_flown": round(fl.total_km_flown, 2),
            "flight_number": fl.flight_number,
            "max_landing_altitude": fl.max_landing_altitude,
            "remaining_km": round(fl.remaining_km, 1),
            "maintenance_assist": ntf.maintenance_assist,
            "planned_km": round(fl.planned_km, 1),
            "pre_flight_safe": fl.pre_flight_safe,
            "pre_flight_warning": fl.pre_flight_warning,
            "wind_horizontal_ms": round(w.wind_horizontal_ms, 3),
            "wind_vertical_ms": round(w.wind_vertical_ms, 3),
            "wind_horizontal_smoothed_ms": round(w.wind_horizontal_smoothed_ms, 3),
            "wind_vertical_smoothed_ms": round(w.wind_vertical_smoothed_ms, 3),
            "effective_airspeed_kmh": round(w.effective_airspeed_kmh, 3),
            "effective_aoa_deg": round(w.effective_aoa_deg, 3),
        }

    def compute_led_colors(self) -> list[list[float]]:
        sections = _get_section_nodes()
        colors: list[list[float]] = []
        for section_name in ["tip", "middle", "root"]:
            node_ids = sections[section_name]
            if not node_ids:
                colors.append([0.0, 1.0, 0.0])
                continue

            if self.stepper.heatmap_mode == "damage":
                damages = [self.damage.node_damages.get(nid, 0.0) for nid in node_ids]
                t = max(damages)
            else:
                sf = self.structural.stress_field
                if not sf or len(sf) == 0:
                    colors.append([0.0, 1.0, 0.0])
                    continue
                max_stress = 0.0
                for nid in node_ids:
                    if nid < len(sf):
                        stress_val = abs(sf[nid])
                        if stress_val > max_stress:
                            max_stress = stress_val
                yp = self.structural.yield_point_pa
                t = max_stress / yp if yp > 0 else 0.0

            colors.append(list(heatmap_color(t)))

        return colors

    def to_snapshot_dict(self) -> dict:
        return {
            "structural": asdict(self.structural),
            "damage": asdict(self.damage),
            "flight": asdict(self.flight),
            "control": asdict(self.control),
            "stepper": asdict(self.stepper),
            "wind": asdict(self.wind),
            "notifications": asdict(self.notifications),
        }

    @staticmethod
    def from_snapshot_dict(data: dict) -> "TwinState":
        state = TwinState()
        if "structural" in data:
            state.structural = StructuralState(**data["structural"])
        if "damage" in data:
            state.damage = DamageState(**data["damage"])
            if state.damage.node_damages:
                state.damage.node_damages = {int(k): v for k, v in state.damage.node_damages.items()}
        if "flight" in data:
            state.flight = FlightState(**data["flight"])
        if "control" in data:
            state.control = ControlState(**data["control"])
        if "stepper" in data:
            state.stepper = StepperHardwareState(**data["stepper"])
        if "wind" in data:
            state.wind = WindState(**data["wind"])
        if "notifications" in data:
            state.notifications = NotificationState(**data["notifications"])
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
