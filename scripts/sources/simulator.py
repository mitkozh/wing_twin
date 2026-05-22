"""
Simulator data source - Generates synthetic sensor data.

epsilon = H @ F + noise.
"""

import math
import threading
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .base import DataSource, SensorReading
from ..config import SimulationConfig
from dtwin.core.matrices import TransferMatrices

STRAIN_TO_RAW = 1e-6  # microstrain -> dimensionless


@dataclass
class SimulatorState:
    """Runtime state for the simulator."""
    time_elapsed: float = 0.0
    speed_pct: int = 100
    num_gauges: int = 1


class SimulatorSource(DataSource):
    """Generates synthetic multi-gauge strain data using transfer matrices."""

    def __init__(
        self,
        config: Optional[SimulationConfig] = None,
    ):
        self.config = config or SimulationConfig()
        self._state = SimulatorState()
        self._running = False
        self._lock = threading.Lock()
        self._matrices: Optional[TransferMatrices] = None

    @property
    def state(self) -> SimulatorState:
        return self._state

    def set_speed(self, speed_pct: int) -> None:
        """Update the speed percentage."""
        with self._lock:
            self._state.speed_pct = max(0, min(100, speed_pct))

    def set_num_gauges(self, num: int) -> None:
        """Set the number of strain gauges."""
        with self._lock:
            self._state.num_gauges = num

    def set_matrices(self, matrices: TransferMatrices) -> None:
        """Set transfer matrices for physically consistent strain generation."""
        with self._lock:
            self._matrices = matrices
            self._state.num_gauges = matrices.n_gauges

    def connect(self) -> bool:
        if self._matrices is None:
            raise RuntimeError("TransferMatrices required before connecting")
        self._running = True
        return True

    def disconnect(self) -> None:
        self._running = False

    def is_connected(self) -> bool:
        return self._running

    def _generate_force(self, t: float, load_factor: float) -> float:
        """Generate a force signal in Newtons."""
        steady = 4000.0 * (load_factor ** 2)
        bending_1 = 2000.0 * load_factor * math.sin(2 * math.pi * 4.2 * t)
        bending_2 = 600.0 * load_factor * math.sin(2 * math.pi * 11.5 * t + 0.4)
        torsion = 400.0 * load_factor * math.sin(2 * math.pi * 18.3 * t + 1.1)
        turbulence = 200.0 * load_factor * np.random.normal(0, 1) * (
            1.0 + 0.5 * math.sin(2 * math.pi * 0.3 * t)
        )
        gust = 0.0
        if np.random.random() < 1 / (60 * self.config.sample_rate):
            self._gust_remaining = int(0.5 * self.config.sample_rate)
        if getattr(self, "_gust_remaining", 0) > 0:
            gust = 30.0 * load_factor * math.sin(
                math.pi * (1 - self._gust_remaining / (0.5 * self.config.sample_rate))
            )
            self._gust_remaining -= 1
        noise = np.random.normal(0, 0.5)
        return steady + bending_1 + bending_2 + torsion + turbulence + gust + noise

    def _read(self, t: float, load_factor: float) -> tuple[np.ndarray, float]:
        """Generate strain using forward model epsilon = H @ F + noise."""
        F = np.array([self._generate_force(t, load_factor)], dtype=np.float64)
        expected_raw = self._matrices.H @ F  # raw strain (dimensionless)
        expected_ue = expected_raw.flatten() / STRAIN_TO_RAW  # convert to microstrain
        noise = np.random.normal(0, 0.05, size=expected_ue.shape)
        strain_vector = expected_ue + noise
        accel_z = -expected_ue[0] * 0.01 + np.random.normal(0, 0.5)
        return strain_vector, accel_z

    def read(self) -> Optional[SensorReading]:
        """Generate the next sensor reading."""
        with self._lock:
            speed = self._state.speed_pct
            t = self._state.time_elapsed

        load_factor = speed / 100.0
        strain_vector, accel_z = self._read(t, load_factor)

        with self._lock:
            self._state.time_elapsed += 1.0 / self.config.sample_rate

        if self._state.num_gauges == 1:
            return SensorReading(
                strain=float(strain_vector[0]),
                strain_vector=None,
                accel_z=accel_z,
                timestamp=int(t * 1000),
                gauge_id="primary",
            )
        return SensorReading(
            strain=float(strain_vector[0]),
            strain_vector=strain_vector,
            accel_z=accel_z,
            timestamp=int(t * 1000),
            gauge_id="vector",
        )
