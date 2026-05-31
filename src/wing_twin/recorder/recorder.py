"""
Incremental data recorder for simulation runs.
"""

import json
import time
from pathlib import Path
from typing import Optional

import h5py
import numpy as np

from wing_twin.fatigue.fatigue import FatigueState
from wing_twin.fatigue.life_prediction import LifePredictionState
from wing_twin.io.logger import get_logger

logger = get_logger(__name__)

SCHEMA_VERSION = 1

SCALAR_NAMES = [
    "strain_mean", "damage", "confidence",
    "angle_of_attack", "airspeed", "stepper_position",
]


class DataRecorder:
    """Records simulation data incrementally to HDF5."""

    def __init__(
        self,
        output_dir: Path,
        scalar_interval: int = 1,
        field_interval: int = 50,
        flush_interval: int = 10000,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.scalar_interval = scalar_interval
        self.field_interval = field_interval
        self.flush_interval = flush_interval

        self._buf: dict[str, list] = {
            "timestamps": [],
            "scalars": [],
            "field_timestamps": [],
            "field_stress": [],
            "field_damage": [],
            "field_deform": [],
        }
        self._frame = 0
        self._flushes = 0
        self._start_time = time.time()
        self._h5_path = self.output_dir / "data.h5"

    def record_frame(self, engine) -> None:
        self._frame += 1
        state = engine.state
        now = time.time() - self._start_time

        if self._frame % self.scalar_interval == 0:
            strain = (
                float(np.mean(state.strain_vector))
                if state.strain_vector
                else 0.0
            )
            self._buf["timestamps"].append(now)
            self._buf["scalars"].append([
                strain,
                state.damage,
                state.confidence,
                state.angle_of_attack,
                state.airspeed,
                state.stepper_position,
            ])

        if self._frame % self.field_interval == 0 and state.stress_field:
            self._buf["field_timestamps"].append(now)
            try:
                unity = state.for_unity()
                self._buf["field_stress"].append(unity["stress_field"])
                self._buf["field_damage"].append(unity["node_damages"])
                self._buf["field_deform"].append(unity["deformation_field"])
            except Exception as exc:
                logger.warning("Field recording skipped: %s", exc)

        if self._frame % self.flush_interval == 0:
            self.flush()

    def flush(self) -> bool:
        if not any(v for v in self._buf.values()):
            return False

        first = self._flushes == 0
        self._flushes += 1

        try:
            with h5py.File(self._h5_path, "w" if first else "a") as f:
                if first:
                    f.create_dataset("metadata/schema_version", data=SCHEMA_VERSION)
                    f.create_dataset("metadata/start_time", data=self._start_time)
                    f.create_dataset("metadata/scalar_interval", data=self.scalar_interval)
                    f.create_dataset("metadata/field_interval", data=self.field_interval)

                def _append(name, data_list, dtype=np.float64):
                    if not data_list:
                        return
                    arr = np.array(data_list, dtype=dtype)
                    if name in f:
                        ds = f[name]
                        old = ds.shape[0]
                        ds.resize(old + arr.shape[0], axis=0)
                        ds[old:] = arr
                    else:
                        f.create_dataset(
                            name, data=arr,
                            maxshape=(None,) + arr.shape[1:],
                            compression="gzip",
                            shuffle=True,
                        )

                _append("observations/timestamps", self._buf["timestamps"])
                _append("observations/scalars", self._buf["scalars"])
                _append("fields/timestamps", self._buf["field_timestamps"])
                _append("fields/stress", self._buf["field_stress"])
                _append("fields/damage", self._buf["field_damage"])
                _append("fields/deformation", self._buf["field_deform"])
        except (OSError, RuntimeError) as exc:
            logger.error("Failed to flush recording: %s", exc)
            return False

        for key in self._buf:
            self._buf[key].clear()
        logger.debug("Flushed chunk %d to %s", self._flushes, self._h5_path)
        return True

    def finalize(self) -> Optional[Path]:
        try:
            if self._buf["timestamps"] or self._buf["field_timestamps"]:
                self.flush()
        except Exception as exc:
            logger.error("Final flush failed: %s", exc)

        meta = {
            "start_time": self._start_time,
            "duration_s": round(time.time() - self._start_time, 1),
            "scalar_interval": self.scalar_interval,
            "field_interval": self.field_interval,
            "total_frames": self._frame,
            "total_flushes": self._flushes,
            "file": str(self._h5_path),
            "scalar_names": SCALAR_NAMES,
        }
        try:
            meta_path = self.output_dir / "metadata.json"
            with open(meta_path, "w") as f:
                json.dump(meta, f, indent=2)
        except Exception as exc:
            logger.error("Failed to write recording metadata: %s", exc)
            return None

        logger.info(
            "Recording saved: %s (%.1f s, %d frames)",
            self.output_dir,
            meta["duration_s"],
            self._frame,
        )
        return self._h5_path


def load_recording(path: Path) -> dict:
    path = Path(path)
    if path.is_dir():
        h5_path = path / "data.h5"
    else:
        h5_path = path

    if not h5_path.exists():
        raise FileNotFoundError(f"Recording not found: {h5_path}")

    result: dict = {}
    with h5py.File(h5_path, "r") as f:
        def _visit(name, obj):
            if isinstance(obj, h5py.Dataset):
                result[name] = obj[()]

        f.visititems(_visit)

    result["_path"] = h5_path
    return result


def save_fatigue_state(fatigue_state: FatigueState, output_dir: Path) -> None:
    data = fatigue_state.to_dict()
    path = Path(output_dir) / "fatigue_state.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    logger.info("Fatigue state saved to %s", path)


def load_fatigue_state(path: Path) -> Optional[FatigueState]:
    path = Path(path)
    if path.is_dir():
        path = path / "fatigue_state.json"
    if not path.exists():
        logger.warning("No fatigue state found at %s", path)
        return None
    with open(path) as f:
        data = json.load(f)
    logger.info("Loaded fatigue state from %s (D=%.4f, %d cycles)",
                path, data.get("damage", 0.0), len(data.get("cycles", [])))
    return FatigueState.from_dict(data)


def save_life_prediction_state(prediction_state: LifePredictionState, output_dir: Path) -> None:
    data = prediction_state.to_dict()
    path = Path(output_dir) / "prediction_state.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    logger.info("Prediction state saved to %s", path)


def load_life_prediction_state(path: Path) -> Optional[LifePredictionState]:
    path = Path(path)
    if path.is_dir():
        path = path / "prediction_state.json"
    if not path.exists():
        logger.warning("No prediction state found at %s", path)
        return None
    with open(path) as f:
        data = json.load(f)
    logger.info("Loaded prediction state from %s", path)
    return LifePredictionState.from_dict(data)
