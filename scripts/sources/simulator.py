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

        effective_amp = self.config.osc_amp * (speed / 100.0)
        base = self.config.base_strain + np.random.uniform(-5, 5)
        oscillation = effective_amp * math.sin(2 * math.pi * self.config.osc_freq * t)
        noise = np.random.normal(0, self.config.noise_std)

        if self._state.num_gauges == 1:
            strain = base + oscillation + noise
            strain_vector = None
        else:
            strain = None
            strain_vector = np.array([
                base + oscillation * math.sin(i * 0.1) + noise + np.random.normal(0, self.config.gauge_noise_std)
                for i in range(self._state.num_gauges)
            ], dtype=np.float64)

        accel_z = -effective_amp * (2 * math.pi * self.config.osc_freq) ** 2 * math.sin(2 * math.pi * self.config.osc_freq * t)
        accel_z += np.random.normal(0, 50)

        with self._lock:
            self._state.time_elapsed += 1.0 / self.config.sample_rate

        return SensorReading(
            strain=strain if strain_vector is None else strain_vector[0],
            strain_vector=strain_vector,
            accel_z=accel_z,
            timestamp=int(t * 1000),
            gauge_id="primary" if self._state.num_gauges == 1 else "vector"
        )