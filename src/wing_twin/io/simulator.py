"""
Simulator data source - Generates synthetic sensor data.

epsilon = H @ F + noise.
"""

import math
import threading
from dataclasses import dataclass
from typing import Optional

import numpy as np

from wing_twin.config import SimulationConfig, WindConfig
from wing_twin.types import DataSource, SensorReading
from wing_twin.fea.matrices import TransferMatrices
from wing_twin.physics.aero import compute_aero_force, compute_wind_force, NeuralFoilModel


@dataclass
class SimulatorState:
    """Runtime state for the simulator."""
    time_elapsed: float = 0.0
    num_gauges: int = 1
    airspeed: float = 0.0
    angle_of_attack: float = 0.0


class SimulatorSource(DataSource):
    """Generates synthetic multi-gauge strain data using transfer matrices."""

    def __init__(
        self,
        config: Optional[SimulationConfig] = None,
        aero_model: Optional[NeuralFoilModel] = None,
        wind_config: Optional[WindConfig] = None,
    ):
        self.config = config or SimulationConfig()
        self.wind_config = wind_config or WindConfig(enabled=False)
        self._state = SimulatorState()
        self._running = False
        self._lock = threading.Lock()
        self._matrices: Optional[TransferMatrices] = None
        self._aero_model: Optional[NeuralFoilModel] = aero_model

    @property
    def state(self) -> SimulatorState:
        return self._state

    def set_airspeed(self, airspeed: float) -> None:
        with self._lock:
            self._state.airspeed = max(0.0, airspeed)

    def set_angle_of_attack(self, angle_deg: float) -> None:
        with self._lock:
            self._state.angle_of_attack = angle_deg

    def set_num_gauges(self, num: int) -> None:
        with self._lock:
            self._state.num_gauges = num

    def set_matrices(self, matrices: TransferMatrices) -> None:
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

    def _generate_force(self, t: float, airspeed: float, angle_deg: float) -> float:
        w = self.wind_config
        wind = compute_wind_force(
            t, w.amplification,
            w.base_freq_hz, w.mid_freq_hz, w.high_freq_hz,
            w.base_power, w.mid_power, w.high_power,
            w.mid_sharpness, w.high_sharpness,
        ) if w.enabled else 0.0

        return compute_aero_force(angle_deg, airspeed, model=self._aero_model) + wind

    def _read(self, t: float, airspeed: float, angle_deg: float) -> tuple[np.ndarray, float]:
        base_force = self._generate_force(t, airspeed, angle_deg)
        F = np.full(self._matrices.n_forces, base_force, dtype=np.float64)
        strain_raw = (self._matrices.H @ F).flatten()
        noise = np.random.normal(0, 5e-8, size=strain_raw.shape)
        strain_vector = strain_raw + noise
        accel_z = -strain_raw[0] * 10000 + np.random.normal(0, 0.5)
        return strain_vector, accel_z

    def read(self) -> Optional[SensorReading]:
        with self._lock:
            t = self._state.time_elapsed
            airspeed = self._state.airspeed
            angle_deg = self._state.angle_of_attack

        strain_vector, accel_z = self._read(t, airspeed, angle_deg)

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
