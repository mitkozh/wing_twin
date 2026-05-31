"""
Core digital twin processing engine.
"""

from typing import Optional

import numpy as np

from wing_twin.fea.matrices import TransferMatrices, load_transfer_matrices
from wing_twin.fea.force_reconstruct import solve_forces
from wing_twin.fea.field_compute import compute_stress_field, compute_deformation_field
from wing_twin.fatigue.fatigue import FatigueState, set_random_seed
from wing_twin.physics.aero import (
    compute_aero_force,
    compute_pitch_damping_force,
    force_to_steps,
)
from wing_twin.control.control import decide_control, decide_control_stress
from wing_twin.config import EngineConfig
from wing_twin.engine.state import TwinState
from wing_twin.engine.dynamics import FlightDynamics
from wing_twin.engine.fatigue_tracker import FatigueTracker
from wing_twin.types import DataSource, SensorReading


class DigitalTwinEngine:
    """Orchestrates the digital twin pipeline."""

    def __init__(
        self,
        config: Optional[EngineConfig] = None,
        data_source: Optional[DataSource] = None,
        initial_fatigue_state: Optional[FatigueState] = None,
    ):
        self.config = config or EngineConfig()
        self._matrices: Optional[TransferMatrices] = None
        self._num_gauges: Optional[int] = None
        self._data_source: Optional[DataSource] = None

        self.state = TwinState()
        self.dynamics = FlightDynamics(
            angle_accel=self.config.angle_accel,
            speed_accel=self.config.speed_accel,
        )
        self.fatigue = FatigueTracker(
            self.config.fatigue,
            initial_state=initial_fatigue_state,
        )

        self.state.yield_point_pa = self.config.stress_limit
        self.state.max_angle_deg = self.config.max_aoa
        self.state.max_speed_kmh = self.config.reference_speed
        self.state.max_stepper_steps = self.config.max_stepper_steps

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
            self._num_gauges = self._matrices.n_gauges

    @property
    def fatigue_state(self) -> FatigueState:
        return self.fatigue.state

    @property
    def matrices(self) -> Optional[TransferMatrices]:
        return self._matrices

    @property
    def life_prediction_state(self):
        return self.fatigue.life_prediction

    @property
    def cycles(self) -> list:
        return self.fatigue.cycles

    def clear_cycles(self) -> None:
        self.fatigue.clear_cycles()

    @property
    def num_gauges(self) -> int:
        return self._num_gauges

    def load_matrices(self, matrix_dir: Optional[str] = None) -> None:
        matrix_path = matrix_dir or self.config.matrix_dir
        self._matrices = load_transfer_matrices(matrix_path)
        self._num_gauges = self._matrices.n_gauges

    def reset(self, target: str = "all") -> None:
        self.fatigue.reset(target)
        if target in ("strain", "all"):
            self.state.strain_vector = []
            self.state.forces = []
            self.state.stress_field = []
            self.state.deformation_field = []
        if target in ("damage", "all"):
            self.state.damage = 0.0
            self.state.cycles_histogram.clear()

    def step(self) -> bool:
        """Execute one processing step. Returns True if new data was processed."""
        if self._data_source is None:
            return False

        dt = 1.0 / self.config.sample_rate

        self._update_safe_targets()

        self.dynamics.update(self.state, dt)

        F_aero = compute_aero_force(
            self.state.angle_of_attack,
            self.state.airspeed,
        )
        d_alpha_dt = self.dynamics.d_alpha_dt(
            self.state.angle_of_attack, self.config.sample_rate
        )
        F_damping = compute_pitch_damping_force(
            self.state.angle_of_attack,
            self.state.airspeed,
            d_alpha_dt,
            chord=self.config.chord,
            Cmq=self.config.Cmq,
        )
        self.state.stepper_position = force_to_steps(
            F_aero + F_damping, self.config.steps_per_newton
        )

        if hasattr(self._data_source, 'set_airspeed'):
            self._data_source.set_airspeed(self.state.airspeed)
        if hasattr(self._data_source, 'set_angle_of_attack'):
            self._data_source.set_angle_of_attack(self.state.angle_of_attack)

        reading = self._data_source.read()
        if reading is not None:
            self._process_reading(reading)
            return True
        return False

    def _process_reading(self, reading: SensorReading) -> None:
        """Process a sensor reading through FEA -> fatigue -> control."""
        if self._matrices is None:
            raise RuntimeError("Call load_matrices() before processing readings")

        if reading.strain_vector is not None:
            strain_vec = reading.strain_vector
        else:
            strain_vec = np.array(
                [reading.strain] * self._num_gauges, dtype=np.float64
            )

        self.state.strain_vector = strain_vec.tolist()

        F = solve_forces(self._matrices.H_inv, strain_vec)
        stress = compute_stress_field(self._matrices.S, F)
        deformation = compute_deformation_field(self._matrices.U, F)

        self.state.forces = F.tolist()
        self.state.stress_field = stress.tolist()
        self.state.deformation_field = deformation.tolist()

        expected_strain = self._matrices.H @ F

        self.fatigue.process(
            strain_vector=strain_vec,
            stress_field_pa=stress,
            expected_strain=expected_strain,
            twin_state=self.state,
            matrices=self._matrices,
            single_strain=reading.strain,
        )

        if self.state.heatmap_mode == "stress" and self.state.stress_field:
            max_stress_pa = max(abs(s) for s in self.state.stress_field)
            self.state.led_state, self.state.speed_pct = decide_control_stress(
                max_stress_pa, speed_pct=self.state.speed_pct,
            )
        else:
            self.state.led_state, self.state.speed_pct = decide_control(
                self.state.damage,
                self.state.confidence,
                config=self.config.fatigue,
            )

    def _update_safe_targets(self) -> None:
        """Convert desired angle/speed into safe targets."""
        desired_angle = float(self.state.desired_angle_of_attack)
        desired_speed = float(self.state.desired_airspeed)

        target_angle = max(-self.config.max_aoa, min(self.config.max_aoa, desired_angle))
        target_speed = max(self.config.min_airspeed, min(self.config.reference_speed, desired_speed))

        if self.state.stress_field:
            max_stress = max(abs(s) for s in self.state.stress_field)
            if max_stress > self.config.stress_limit and max_stress > 0.0:
                speed_scale = (self.config.stress_limit / max_stress) ** 0.5
                target_speed = max(self.config.min_airspeed, target_speed * speed_scale)
                if target_speed == self.config.min_airspeed:
                    target_angle *= self.config.stress_limit / max_stress

        self.state.target_angle_of_attack = target_angle
        self.state.target_airspeed = target_speed
