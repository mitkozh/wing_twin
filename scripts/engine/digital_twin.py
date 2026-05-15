"""
Core digital twin processing engine.
"""

from collections import deque
from typing import Optional

import numpy as np

from dtwin import (
    load_transfer_matrices,
    solve_forces,
    compute_stress_field,
    compute_deformation_field,
    accumulate_damage,
    decide_control,
)
from dtwin.core import FatigueState
from dtwin.core.fatigue import STRAIN_BUFFER_SIZE, set_random_seed, ALUMINUM_SN_CURVE
from dtwin.core.matrices import TransferMatrices

from .config import EngineConfig
from .state import TwinState
from ..sources.base import DataSource, SensorReading


class DigitalTwinEngine:
    """Processes sensor data and computes digital twin state."""

    def __init__(self, config: Optional[EngineConfig] = None, data_source: Optional[DataSource] = None):
        self.config = config or EngineConfig()
        self._matrices: Optional[TransferMatrices] = None
        self._num_gauges: int = 3
        self._data_source: Optional[DataSource] = None

        self.state = TwinState()
        self.fatigue_state = FatigueState()
        self._strain_buffer: deque = deque(maxlen=STRAIN_BUFFER_SIZE)
        self._cycles: list = []

        if self.config.seed is not None:
            set_random_seed(self.config.seed)

        if data_source:
            self.data_source = data_source

    @property
    def data_source(self) -> Optional[DataSource]:
        return self._data_source

    @data_source.setter
    def data_source(self, source: DataSource) -> None:
        self._data_source = source
        self._data_source.connect()
        if self._matrices is not None:
            self._num_gauges = self._matrices.H_inv.shape[1]

    def load_matrices(self, matrix_dir: Optional[str] = None) -> None:
        """Load transfer matrices from disk."""
        matrix_path = matrix_dir or self.config.matrix_dir
        self._matrices = load_transfer_matrices(matrix_path)
        self._num_gauges = self._matrices.H_inv.shape[1]

    def reset(self, target: str = "all") -> None:
        """Reset engine state."""
        if target in ("damage", "all"):
            self.state.damage = 0.0
            self.fatigue_state = FatigueState()
            self._cycles.clear()
        if target in ("strain", "all"):
            self._strain_buffer.clear()
            self.state.strain_vector = []
            self.state.forces = []
            self.state.stress_field = []
            self.state.deformation_field = []

    def process_reading(self, reading: SensorReading) -> None:
        """Process a single sensor reading."""
        if reading.strain_vector is not None:
            strain_vec = reading.strain_vector
        else:
            strain_vec = np.array([reading.strain], dtype=np.float64)

        self._strain_buffer.append(strain_vec)
        self.state.strain_vector = strain_vec.tolist()

        if self._matrices is not None and len(self._strain_buffer) >= self._num_gauges:
            arr = np.array(list(self._strain_buffer)[-self._num_gauges:], dtype=np.float64).ravel()

            F = solve_forces(self._matrices.H_inv, arr)
            stress = compute_stress_field(self._matrices.S, F)
            deformation = compute_deformation_field(self._matrices.U, F)

            self.state.forces = F.tolist()
            self.state.stress_field = stress.tolist()
            self.state.deformation_field = deformation.tolist()

        _, new_cycles = accumulate_damage(self._strain_buffer, self.fatigue_state, sn_curve=ALUMINUM_SN_CURVE)
        self._cycles.extend(new_cycles)
        self.state.damage = self.fatigue_state.damage
        self.state.confidence = self.fatigue_state.confidence

        self.state.led_state, self.state.speed_pct = decide_control(
            self.state.damage, self.fatigue_state.confidence
        )

    def step(self) -> bool:
        """Process one step from the data source. Returns True if new data processed."""
        if self._data_source is None:
            return False

        reading = self._data_source.read()
        if reading is not None:
            self.process_reading(reading)
            return True
        return False

    @property
    def cycles(self) -> list:
        """Get accumulated fatigue cycles."""
        return self._cycles

    def clear_cycles(self) -> None:
        """Clear accumulated cycles."""
        self._cycles.clear()

    @property
    def matrices_loaded(self) -> bool:
        return self._matrices is not None

    @property
    def num_gauges(self) -> int:
        return self._num_gauges