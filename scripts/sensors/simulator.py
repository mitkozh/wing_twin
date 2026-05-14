"""
Sensor data simulator - generates synthetic strain data.
"""

import math
import time
import threading
from dataclasses import dataclass, field
from typing import Optional
import numpy as np

from .data_source import DataSource, SensorReading
from ..config import SimulationConfig


@dataclass
class SimulatorState:
    """Runtime state for the simulator."""
    time_elapsed: float = 0.0
    current_damage: float = 0.0
    speed_pct: int = 100
    num_gauges: int = 1
    matrices: any = None


class SensorSimulator(DataSource):
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
        """Update the speed percentage (e.g., from control command)."""
        with self._lock:
            self._state.speed_pct = max(0, min(100, speed_pct))

    def set_damage(self, damage: float) -> None:
        """Update the current damage (e.g., from orchestrator)."""
        with self._lock:
            self._state.current_damage = damage

    def set_num_gauges(self, num: int) -> None:
        """Set the number of strain gauges."""
        with self._lock:
            self._state.num_gauges = num

    def set_matrices(self, matrices: any) -> None:
        """Set transfer matrices to determine gauge count."""
        self._state.matrices = matrices
        if matrices is not None:
            self._state.num_gauges = matrices.H_inv.shape[1]

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

        accel_z = self._generate_accel_z(t, speed)

        with self._lock:
            self._state.time_elapsed += 1.0 / self.config.sample_rate

        return SensorReading(
            strain=strain if strain_vector is None else strain_vector[0],
            strain_vector=strain_vector,
            accel_z=accel_z,
            timestamp=int(t * 1000),
            gauge_id="primary" if self._state.num_gauges == 1 else "vector"
        )

    def _generate_accel_z(self, t: float, speed: int) -> float:
        """Calculate vertical acceleration from wing oscillation."""
        effective_amp = self.config.osc_amp * (speed / 100.0)
        accel = -effective_amp * (2 * math.pi * self.config.osc_freq) ** 2 * math.sin(2 * math.pi * self.config.osc_freq * t)
        return accel + np.random.normal(0, 50)

    def generate_strain_vector(self) -> list:
        """Generate a strain vector for direct use."""
        reading = self.read()
        if reading.strain_vector is not None:
            return reading.strain_vector.tolist()
        return [reading.strain]

    def run_offline(self, duration_s: Optional[float] = None) -> None:
        """Run simulator in offline mode, printing to console."""
        print("\n=== Offline Mode (no MQTT) ===")
        print(f"{'Time':<10} {'Strain':<12} {'AccelZ':<12} {'Damage':<10}")
        print("-" * 44)

        try:
            while True:
                reading = self.read()
                strain_val = reading.strain if reading.strain_vector is None else reading.strain_vector[0]
                print(f"{self._state.time_elapsed:<10.1f} {strain_val:<12.2f} {reading.accel_z:<12.0f} {self._state.current_damage:<10.4f}")

                if duration_s and self._state.time_elapsed >= duration_s:
                    break
                if self._state.current_damage >= 1.0:
                    print("\n=== Wing Failed! ===")
                    break

                time.sleep(1 / self.config.sample_rate)
        except KeyboardInterrupt:
            pass