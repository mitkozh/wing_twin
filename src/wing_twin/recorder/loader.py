"""
Provides structured access to recorded simulation data for figure generation and analysis.
"""

from pathlib import Path
from typing import NamedTuple, Optional

import numpy as np

from wing_twin.io.logger import get_logger

logger = get_logger(__name__)


class RecordingData(NamedTuple):
    """Structured data extracted from a recording directory."""
    strain: Optional[np.ndarray]
    times: Optional[np.ndarray]
    damage: Optional[np.ndarray]
    confidence: Optional[np.ndarray]
    angle_of_attack: Optional[np.ndarray]
    airspeed: Optional[np.ndarray]
    stress_field: Optional[np.ndarray]
    stress_field_times: Optional[np.ndarray]
    cycles: list


class DataLoader:
    """Loads simulation data from HDF5 recordings."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)

    def load(self) -> Optional[dict]:
        h5_path = self.data_dir / "data.h5"
        if not h5_path.exists():
            logger.warning("No recording found at %s", h5_path)
            return None
        from .recorder import load_recording
        return load_recording(h5_path)

    def load_tuple(self) -> RecordingData:
        data = self.load()
        has_h5 = data is not None

        if not has_h5 and not (self.data_dir / "state.json").exists():
            return RecordingData(None, None, None, None, None, None, None, None, [])

        scalars = data.get("observations/scalars") if has_h5 else None
        times = data.get("observations/timestamps", None) if has_h5 else None

        strain = scalars[:, 0] if scalars is not None and scalars.size > 0 else None
        damage = scalars[:, 1] if scalars is not None and scalars.size > 0 and scalars.ndim > 1 and scalars.shape[1] > 1 else None
        confidence = scalars[:, 2] if scalars is not None and scalars.size > 0 and scalars.ndim > 1 and scalars.shape[1] > 2 else None
        angle_of_attack = scalars[:, 3] if scalars is not None and scalars.size > 0 and scalars.ndim > 1 and scalars.shape[1] > 3 else None
        airspeed = scalars[:, 4] if scalars is not None and scalars.size > 0 and scalars.ndim > 1 and scalars.shape[1] > 4 else None

        stress_field = data.get("fields/stress", None) if has_h5 else None
        if stress_field is not None and stress_field.size == 0:
            stress_field = None

        stress_field_times = data.get("fields/timestamps", None) if has_h5 else None
        if stress_field_times is not None and stress_field_times.size == 0:
            stress_field_times = None

        cycles = _load_cycles(data or {}, self.data_dir)

        return RecordingData(
            strain=strain,
            times=times,
            damage=damage,
            confidence=confidence,
            angle_of_attack=angle_of_attack,
            airspeed=airspeed,
            stress_field=stress_field,
            stress_field_times=stress_field_times,
            cycles=cycles,
        )


def _load_cycles(data: dict, data_dir: Path) -> list:
    ranges = data.get("cycles/ranges")
    counts = data.get("cycles/counts")
    if ranges is not None and counts is not None and ranges.size > 0:
        return list(zip(ranges.tolist(), counts.tolist()))

    state_path = data_dir / "state.json"
    if state_path.exists():
        import json
        with open(state_path) as f:
            snapshot = json.load(f)
        cycles = (
            snapshot.get("twin", {})
            .get("structural", {})
            .get("cycles_histogram", {})
        )
        if cycles:
            return [(float(k), float(v)) for k, v in cycles.items()]

    return []
