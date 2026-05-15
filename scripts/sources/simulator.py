"""
Simulator data source - Generates synthetic sensor data.
"""

import math
import threading
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .base import DataSource, SensorReading
from ..config import SimulationConfig


@dataclass
class SimulatorState:
    """Runtime state for the simulator."""
    time_elapsed: float = 0.0
    speed_pct: int = 100
    num_gauges: int = 1


class SimulatorSource(DataSource):
    """
    Generates synthetic multi-gauge strain data for testing.
    """

    def __init__(self, config: Optional[SimulationConfig] = None):
        self.config = config or SimulationConfig()
        self._state = SimulatorState()
        self._running = False
        self._lock = threading.Lock()

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

    def connect(self) -> bool:
        self._running = True
        return True

    def disconnect(self) -> None:
        self._running = False

    def is_connected(self) -> bool:
        return self._running

    def read(self) -> Optional[SensorReading]:
        """Generate the next sensor reading."""
        with self._lock:
            speed = self._state.speed_pct
            t = self._state.time_elapsed

        load_factor = speed / 100.0

        steady = self.config.base_strain * (load_factor ** 2)

        bending_1 = self.config.osc_amp * load_factor * math.sin(2 * math.pi * 4.2 * t)

        bending_2 = self.config.osc_amp * 0.3 * load_factor * math.sin(2 * math.pi * 11.5 * t + 0.4)

        torsion = self.config.osc_amp * 0.2 * load_factor * math.sin(2 * math.pi * 18.3 * t + 1.1)

        turb_amp = 20.0 * load_factor
        turbulence = turb_amp * np.random.normal(0, 1) * (1.0 + 0.5 * math.sin(2 * math.pi * 0.3 * t))

        gust = 0.0
        if np.random.random() < 1 / (60 * self.config.sample_rate):
            self._gust_remaining = int(0.5 * self.config.sample_rate)
        if getattr(self, '_gust_remaining', 0) > 0:
            gust = 150.0 * load_factor * math.sin(math.pi * (1 - self._gust_remaining / (0.5 * self.config.sample_rate)))
            self._gust_remaining -= 1

        noise = np.random.normal(0, self.config.noise_std * 0.5)

        strain = steady + bending_1 + bending_2 + torsion + turbulence + gust + noise

        gauge_positions = [1.0, 0.7, 0.4]
        strain_vector = np.array([
            strain * pos + np.random.normal(0, self.config.gauge_noise_std)
            for pos in gauge_positions
        ], dtype=np.float64)

        accel_z = -(bending_1 + bending_2) * 0.01 + np.random.normal(0, 0.5)

        with self._lock:
            self._state.time_elapsed += 1.0 / self.config.sample_rate

        if self._state.num_gauges == 1:
            return SensorReading(
                strain=float(strain),
                strain_vector=None,
                accel_z=accel_z,
                timestamp=int(t * 1000),
                gauge_id="primary"
            )
        else:
            return SensorReading(
                strain=float(strain_vector[0]),
                strain_vector=strain_vector,
                accel_z=accel_z,
                timestamp=int(t * 1000),
                gauge_id="vector"
            )