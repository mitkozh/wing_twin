"""
Simulator data source - Generates synthetic sensor data.

epsilon = H @ F + noise.
"""

import math
import threading
from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..types import DataSource, SensorReading
from ..settings import SimulationConfig
from dtwin.core.matrices import TransferMatrices
from dtwin.core.stepper_physics import compute_aero_force


@dataclass
class SimulatorState:
    """Runtime state for the simulator."""
    time_elapsed: float = 0.0
    speed_pct: int = 100
    num_gauges: int = 1
    airspeed: float = 0.0
    angle_of_attack: float = 0.0


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

    def set_airspeed(self, airspeed: float) -> None:
        """Update the current airspeed in km/h."""
        with self._lock:
            self._state.airspeed = max(0.0, airspeed)

    def set_angle_of_attack(self, angle_deg: float) -> None:
        """Update the angle of attack in degrees."""
        with self._lock:
            self._state.angle_of_attack = angle_deg

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

    def _generate_force(self, t: float, airspeed: float, angle_deg: float) -> float:
        """Generate a force signal in Newtons based on airspeed and angle of attack."""

        # Steady aerodynamic force
        steady = compute_aero_force(angle_deg, airspeed)

        # Dynamic excitations as fractions of the steady force
        bending = 0.25 * steady * math.sin(2 * math.pi * 4.2 * t)
        torsion = 0.05 * steady * math.sin(2 * math.pi * 18.3 * t + 1.1)
        turbulence = 0.03 * steady * np.random.normal(0, 1) * (
            1.0 + 0.5 * math.sin(2 * math.pi * 0.3 * t)
        )

        gust = 0.0
        if np.random.random() < 1 / (60 * self.config.sample_rate):
            self._gust_remaining = int(0.5 * self.config.sample_rate)
        if getattr(self, "_gust_remaining", 0) > 0:
            gust = 0.04 * steady * math.sin(
                math.pi * (1 - self._gust_remaining / (0.5 * self.config.sample_rate))
            )
            self._gust_remaining -= 1

        noise = np.random.normal(0, 0.5)
        return steady + bending + torsion + turbulence + gust + noise

    def _read(self, t: float, airspeed: float, angle_deg: float) -> tuple[np.ndarray, float]:
        """Generate strain using forward model epsilon = H @ F + noise."""
        base_force = self._generate_force(t, airspeed, angle_deg)
        F = np.full(self._matrices.n_forces, base_force, dtype=np.float64)
        strain_raw = (self._matrices.H @ F).flatten()  # dimensionless
        noise = np.random.normal(0, 5e-8, size=strain_raw.shape)
        strain_vector = strain_raw + noise
        accel_z = -strain_raw[0] * 10000 + np.random.normal(0, 0.5)
        return strain_vector, accel_z

    def read(self) -> Optional[SensorReading]:
        """Generate the next sensor reading."""
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
