"""
Data export utilities - save/load simulation data to JSON.
"""

import json
from pathlib import Path
from typing import Optional, Tuple, List, Any

from ..logger import get_logger

logger = get_logger(__name__)


class DataExporter:
    """Exports simulation data to JSON."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(exist_ok=True)

    def save(
        self,
        strain_history: List[float],
        times: List[float],
        damage_history: List[float],
        cycles: List[Any],
        force_history: Optional[List[List[float]]] = None,
        stress_field_history: Optional[List[List[float]]] = None,
        deformation_field_history: Optional[List[List[float]]] = None,
        filename: str = "sim_data.json",
    ) -> Path:
        """Save simulation data to JSON file."""
        path = self.output_dir / filename
        data = {
            "strain": strain_history,
            "times": times,
            "damage": damage_history,
            "cycles": cycles,
        }
        if force_history is not None:
            data["forces"] = force_history
        if stress_field_history is not None:
            data["stress_field"] = stress_field_history
        if deformation_field_history is not None:
            data["deformation_field"] = deformation_field_history

        with open(path, "w") as f:
            json.dump(data, f)
        logger.info("Saved to %s", path)
        return path


class DataLoader:
    """Loads simulation data from JSON."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    def load(self, filename: str = "sim_data.json") -> Optional[dict]:
        """Load simulation data from JSON file."""
        path = self.data_dir / filename
        if not path.exists():
            logger.warning("No saved data at %s", path)
            return None
        with open(path) as f:
            data = json.load(f)
        logger.info("Loaded %d samples", len(data['strain']))
        return data

    def load_tuple(
        self, filename: str = "sim_data.json"
    ) -> Tuple:
        """Load data and return as tuple of arrays."""
        data = self.load(filename)
        if data is None:
            return (None,) * 7
        return (
            data.get("strain"),
            data.get("times"),
            data.get("damage"),
            data.get("forces"),
            data.get("stress_field"),
            data.get("deformation_field"),
            data.get("cycles", []),
        )