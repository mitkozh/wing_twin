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

STRAIN_TO_RAW = 1e-6


def _lift_force(angle_deg: float) -> float:
    """Sinusoidal lift profile, asymmetric for positive/negative AoA."""
    angle_rad = math.radians(angle_deg)
    if angle_deg >= 0:
        return 6000.0 * math.sin(angle_rad)
    return 3000.0 * math.sin(angle_rad)


def _drag_force(speed_ratio: float) -> float:
    """Parasitic drag grows with speed squared."""
    return 1500.0 * speed_ratio


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
        ref_speed = self.config.reference_speed
        speed_ratio = airspeed / ref_speed if airspeed > 0 else 0.0
        q = speed_ratio * speed_ratio  # dynamic pressure ratio

        # Aerodynamic forces at this flight condition
        lift = _lift_force(angle_deg) * q
        drag = _drag_force(speed_ratio) * q

        # Dynamic excitations scale with dynamic pressure
        bending = 2000.0 * q * math.sin(2 * math.pi * 4.2 * t)
        torsion = 400.0 * q * math.sin(2 * math.pi * 18.3 * t + 1.1)
        turbulence = 200.0 * q * np.random.normal(0, 1) * (
            1.0 + 0.5 * math.sin(2 * math.pi * 0.3 * t)
        )

        gust = 0.0
        if np.random.random() < 1 / (60 * self.config.sample_rate):
            self._gust_remaining = int(0.5 * self.config.sample_rate)
        if getattr(self, "_gust_remaining", 0) > 0:
            gust = 300.0 * q * math.sin(
                math.pi * (1 - self._gust_remaining / (0.5 * self.config.sample_rate))
            )
            self._gust_remaining -= 1

        noise = np.random.normal(0, 0.5)
        return lift + drag + bending + torsion + turbulence + gust + noise

    def _read(self, t: float, airspeed: float, angle_deg: float) -> tuple[np.ndarray, float]:
        """Generate strain using forward model epsilon = H @ F + noise."""
        base_force = self._generate_force(t, airspeed, angle_deg)
        F = np.full(self._matrices.n_forces, base_force, dtype=np.float64)
        expected_raw = self._matrices.H @ F  # raw strain (dimensionless)
        expected_ue = expected_raw.flatten() / STRAIN_TO_RAW  # convert to microstrain
        noise = np.random.normal(0, 0.05, size=expected_ue.shape)
        strain_vector = expected_ue + noise
        accel_z = -expected_ue[0] * 0.01 + np.random.normal(0, 0.5)
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
