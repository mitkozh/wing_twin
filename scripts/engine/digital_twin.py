"""
Core digital twin processing engine.
"""

import math
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
    decide_control_stress,
    compute_aero_force,
    compute_pitch_damping_force,
    force_to_steps,
)
from dtwin.core import FatigueState
from dtwin.core.fatigue import (
    set_random_seed,
    accumulate_damage_at_nodes,
    sn_curve_for_material,
    update_confidence,
)
from dtwin.core.matrices import TransferMatrices
from dtwin.core.life_prediction import LifePredictionState

from .config import EngineConfig
from .state import TwinState
from ..types import DataSource, SensorReading


class DigitalTwinEngine:
    """Processes sensor data and computes digital twin state."""

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
        self.fatigue_state = initial_fatigue_state or FatigueState()
        self._strain_buffer: deque = deque(
            maxlen=self.config.fatigue.strain_buffer_size
        )
        self._cycles: list = []
        self._prev_angle_of_attack: float = 0.0
        self._angle_velocity: float = 0.0
        self._speed_velocity: float = 0.0

        self.state.yield_point_pa = self.config.stress_limit
        self.state.max_angle_deg = self.config.max_aoa
        self.state.max_speed_kmh = self.config.reference_speed
        self.state.max_stepper_steps = self.config.max_stepper_steps

        self.life_prediction_state = LifePredictionState()

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
    def matrices(self) -> Optional[TransferMatrices]:
        """Transfer matrices for force reconstruction and field computation."""
        return self._matrices

    def load_matrices(self, matrix_dir: Optional[str] = None) -> None:
        """Load transfer matrices from disk."""
        matrix_path = matrix_dir or self.config.matrix_dir
        self._matrices = load_transfer_matrices(matrix_path)
        self._num_gauges = self._matrices.n_gauges

    def reset(self, target: str = "all") -> None:
        """Reset engine state."""
        if target in ("damage", "all"):
            self.state.damage = 0.0
            self.fatigue_state = FatigueState()
            self._cycles.clear()
            self.state.cycles_histogram.clear()
        if target in ("strain", "all"):
            self._strain_buffer.clear()
            self.state.strain_vector = []
            self.state.forces = []
            self.state.stress_field = []
            self.state.deformation_field = []

    def process_reading(self, reading: SensorReading) -> None:
        """Process a single sensor reading."""
        if self._matrices is None:
            raise RuntimeError("Call load_matrices() before process_reading()")
        self._strain_buffer.append(reading.strain)

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

        expected_raw = self._matrices.H @ F
        update_confidence(
            self.fatigue_state,
            strain_vec,
            expected_raw,
            config=self.config.fatigue,
        )

        stress_mpa = stress / 1e6  # Pa -> MPa
        accumulate_damage_at_nodes(
            stress_mpa,
            self.fatigue_state,
            sn_curve=sn_curve_for_material(self.config.fatigue.material),
            config=self.config.fatigue,
        )

        self.state.node_damages = dict(self.fatigue_state.node_damages)

        _, new_cycles = accumulate_damage(
            self._strain_buffer,
            self.fatigue_state,
            sn_curve=sn_curve_for_material(self.config.fatigue.material),
            config=self.config.fatigue,
        )
        self._cycles.extend(new_cycles)
        bin_width = self.config.fatigue.rainflow_range_bin_width
        for r, c in new_cycles:
            idx = int(r / bin_width)
            key = round((idx + 0.5) * bin_width, 1)
            self.state.cycles_histogram[key] = self.state.cycles_histogram.get(key, 0.0) + c

        if self.fatigue_state.node_damages:
            values = list(self.fatigue_state.node_damages.values())
            self.state.damage = max(values)
            sorted_vals = sorted(values, reverse=True)
            top_10_pct = sorted_vals[: max(1, len(sorted_vals) // 10)]
            self.state.avg_damage = (
                sum(top_10_pct) / len(top_10_pct) if top_10_pct else 0.0
            )
        else:
            self.state.damage = self.fatigue_state.damage
            self.state.avg_damage = 0.0

        self.state.confidence = self.fatigue_state.confidence
        self.state.maintenance_alert = self.fatigue_state.alert_active

        if self.state.heatmap_mode == "stress" and self.state.stress_field:
            max_stress_pa = max(abs(s) for s in self.state.stress_field)
            self.state.led_state, self.state.speed_pct = decide_control_stress(
                max_stress_pa,
                speed_pct=self.state.speed_pct,
            )
        else:
            self.state.led_state, self.state.speed_pct = decide_control(
                self.state.damage,
                self.fatigue_state.confidence,
                config=self.config.fatigue,
            )

    def _accel_towards(
        self, pos: float, vel: float, target: float, accel: float, dt: float
    ) -> tuple[float, float]:
        """Move `pos` towards `target` with acceleration-limited velocity.
        Returns (new_pos, new_vel).
        """
        error = target - pos
        if abs(error) < 1e-6 and abs(vel) < 1e-6:
            return target, 0.0

        braking_dist = (vel * vel) / (2 * accel) if abs(vel) > 0.0 else 0.0

        if abs(error) <= braking_dist:
            vel -= math.copysign(accel * dt, vel)
        else:
            vel += math.copysign(accel * dt, error)

        if vel * error < 0:
            vel = 0.0

        pos += vel * dt

        if (pos - target) * error > 0.0:
            pos = target
            vel = 0.0

        return pos, vel

    def step(self) -> bool:
        """Process one step from the data source. Returns True if new data processed."""
        if self._data_source is None:
            return False

        dt = 1.0 / self.config.sample_rate

        self._update_safe_targets()

        self.state.angle_of_attack, self._angle_velocity = self._accel_towards(
            self.state.angle_of_attack,
            self._angle_velocity,
            self.state.target_angle_of_attack,
            self.config.angle_accel,
            dt,
        )
        self.state.airspeed, self._speed_velocity = self._accel_towards(
            self.state.airspeed,
            self._speed_velocity,
            self.state.target_airspeed,
            self.config.speed_accel,
            dt,
        )

        F_aero = compute_aero_force(
            self.state.angle_of_attack,
            self.state.airspeed,
        )

        d_alpha_dt = (
            self.state.angle_of_attack - self._prev_angle_of_attack
        ) * self.config.sample_rate
        F_damping = compute_pitch_damping_force(
            self.state.angle_of_attack,
            self.state.airspeed,
            d_alpha_dt,
            chord=self.config.chord,
            Cmq=self.config.Cmq,
        )

        F_target = F_aero + F_damping
        self.state.stepper_position = force_to_steps(
            F_target, self.config.steps_per_newton
        )
        self._prev_angle_of_attack = self.state.angle_of_attack

        if hasattr(self._data_source, 'set_airspeed'):
            self._data_source.set_airspeed(self.state.airspeed)
        if hasattr(self._data_source, 'set_angle_of_attack'):
            self._data_source.set_angle_of_attack(self.state.angle_of_attack)

        reading = self._data_source.read()
        if reading is not None:
            self.process_reading(reading)
            return True
        return False
    
    def _update_safe_targets(self) -> None:
        """Convert desired angle of attack and speed into safe ones."""
        desired_angle = float(self.state.desired_angle_of_attack)
        desired_speed = float(self.state.desired_airspeed)

        max_aoa = self.config.max_aoa
        min_speed = self.config.min_airspeed
        max_speed = self.config.reference_speed
        stress_limit = self.config.stress_limit

        # 1. Avoid desired angle being too high or too low (to prevent stalling)
        target_angle = max(-max_aoa, min(max_aoa, desired_angle))

        # 2. Also clamp the speed in allowable range
        target_speed = max(min_speed, min(max_speed, desired_speed))

        # 3. If current stress is too high, reduce speed first.
        if self.state.stress_field:
            max_stress = max(abs(s) for s in self.state.stress_field)

            if max_stress > stress_limit and max_stress > 0.0:
                speed_scale = (stress_limit / max_stress) ** 0.5
                target_speed = max(min_speed, target_speed * speed_scale)

                # 4. If speed cannot reduce enough, then reduce AoA.
                if target_speed == min_speed:
                    angle_scale = stress_limit / max_stress
                    target_angle *= angle_scale

        # It's purely conceptual and no physics is done as it is quite difficult to model
        # without extra data which is usually kept secret. We focus on the fatigue after all.
        self.state.target_angle_of_attack = target_angle
        self.state.target_airspeed = target_speed
        
        print(
    f"[SPEED] desired={self.state.desired_airspeed:.1f}, "
    f"target={self.state.target_airspeed:.1f}, "
    f"current={self.state.airspeed:.1f}"
)

    @property
    def cycles(self) -> list:
        """Get accumulated fatigue cycles."""
        return self._cycles

    def clear_cycles(self) -> None:
        """Clear accumulated cycles."""
        self._cycles.clear()

    @property
    def num_gauges(self) -> int:
        return self._num_gauges
