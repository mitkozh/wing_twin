"""
Incremental data recorder for simulation runs.
"""

import json
import tempfile
import time
from pathlib import Path
from typing import Optional

import h5py
import numpy as np

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

        target_path = self._h5_path
        write_path = target_path

        # First write uses temp file for atomicity
        if first:
            tmp_dir = target_path.parent
            with tempfile.NamedTemporaryFile(
                dir=tmp_dir, prefix=".h5_tmp_", suffix=".h5", delete=False
            ) as tmp:
                write_path = Path(tmp.name)

        try:
            with h5py.File(write_path, "w" if first else "a") as f:
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
            if first and write_path != target_path:
                write_path.unlink(missing_ok=True)
            return False

        # Atomic rename for first write
        if first and write_path != target_path:
            write_path.replace(target_path)

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


def save_engine_snapshot(engine, output_dir: Path) -> None:
    snapshot = engine.save_snapshot()
    path = Path(output_dir) / "state.json"
    snapshot.to_file(path)
    logger.info(
        "Engine snapshot saved to %s (D=%.4f, %d cycles, %d flights)",
        path,
        engine.fatigue.state.damage,
        len(engine.fatigue.state.cycles or []),
        engine.life_prediction_state.total_flights,
    )


def load_engine_snapshot(path: Path):
    from wing_twin.engine.state import EngineSnapshot
    path = Path(path)
    if path.is_dir():
        path = path / "state.json"
    try:
        return EngineSnapshot.from_file(path)
    except FileNotFoundError:
        logger.warning("No engine snapshot found at %s", path)
        return None
