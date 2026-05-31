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
    stress_field: Optional[np.ndarray]
    deformation_field: Optional[np.ndarray]
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
        if data is None:
            return RecordingData(None, None, None, None, None, [])

        scalars = data.get("observations/scalars")
        strain = scalars[:, 0] if scalars is not None and scalars.size > 0 else None
        damage = scalars[:, 1] if scalars is not None and scalars.size > 0 and scalars.ndim > 1 and scalars.shape[1] > 1 else None
        times = data.get("observations/timestamps", None)

        stress_field = data.get("fields/stress", None)
        if stress_field is not None and stress_field.size == 0:
            stress_field = None

        deformation_field = data.get("fields/deformation", None)
        if deformation_field is not None and deformation_field.size == 0:
            deformation_field = None

        cycles = _load_cycles(data, self.data_dir)

        return RecordingData(
            strain=strain,
            times=times,
            damage=damage,
            stress_field=stress_field,
            deformation_field=deformation_field,
            cycles=cycles,
        )


def _load_cycles(data: dict, data_dir: Path) -> list:
    ranges = data.get("cycles/ranges")
    counts = data.get("cycles/counts")
    if ranges is not None and counts is not None and ranges.size > 0:
        return list(zip(ranges.tolist(), counts.tolist()))

    fatigue_path = data_dir / "fatigue_state.json"
    if fatigue_path.exists():
        import json
        with open(fatigue_path) as f:
            fatigue_data = json.load(f)
        return [tuple(c) for c in fatigue_data.get("cycles", [])]

    return []
