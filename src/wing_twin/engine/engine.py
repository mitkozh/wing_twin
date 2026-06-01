"""
Core digital twin processing engine.
"""

import math
from enum import Enum
from typing import Optional

import numpy as np

from wing_twin.fea.matrices import TransferMatrices, load_transfer_matrices
from wing_twin.fea.force_reconstruct import solve_forces
from wing_twin.fea.field_compute import compute_stress_field, compute_deformation_field
from wing_twin.fatigue.fatigue import FatigueState, set_random_seed
from wing_twin.physics.aero import (
    compute_aero_force,
    compute_aero_forces,
    force_to_steps,
    init_neuralfoil,
    NeuralFoilModel,
)
from wing_twin.control.control import decide_control, decide_control_stress
from wing_twin.config import EngineConfig
from wing_twin.engine.state import TwinState
from wing_twin.engine.dynamics import FlightDynamics
from wing_twin.engine.fatigue_tracker import FatigueTracker
from wing_twin.fatigue.life_prediction import LifePredictionState
from wing_twin.types import DataSource, SensorReading


class FlightPhase(str, Enum):
    ON_GROUND = "on_ground"
    TAKING_OFF = "taking_off"
    IN_FLIGHT = "in_flight"
    LANDING = "landing"


class DigitalTwinEngine:
    """Orchestrates the digital twin pipeline."""

    def __init__(
        self,
        config: Optional[EngineConfig] = None,
        data_source: Optional[DataSource] = None,
        initial_fatigue_state: Optional[FatigueState] = None,
        initial_life_prediction: Optional[LifePredictionState] = None,
        initial_flight_state: Optional[dict] = None,
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
            initial_life_prediction=initial_life_prediction,
        )

        self.state.yield_point_pa = self.config.stress_limit
        self.state.max_angle_deg = self.config.max_aoa
        self.state.max_speed_kmh = self.config.reference_speed
        self.state.max_stepper_steps = self.config.max_stepper_steps
        self.state.max_landing_altitude = self.config.max_landing_altitude

        # Flight state machine
        self._flight_phase: FlightPhase = FlightPhase.ON_GROUND
        self._takeoff_timer: float = 0.0
        self._landing_timer: float = 0.0
        self._km_this_flight: float = 0.0
        self._last_flight_damage: float = 0.0

        # Process aborted flight data from previous run
        if initial_flight_state:
            self._resolve_aborted_flight(initial_flight_state)

        # Initialise NeuralFoil aerodynamic model
        self._aero_model: NeuralFoilModel = init_neuralfoil(
            model_size=self.config.neuralfoil_model_size,
        )

        # Sync TwinState from LifePredictionState
        self._sync_twin_from_life_prediction()

        if self.config.seed is not None:
            set_random_seed(self.config.seed)

        if data_source:
            self.data_source = data_source

    @property
    def flight_phase(self) -> FlightPhase:
        return self._flight_phase

    @flight_phase.setter
    def flight_phase(self, phase: FlightPhase) -> None:
        self._flight_phase = phase
        self.state.flight_phase = phase.value

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
        if target in ("flight", "all"):
            self._km_this_flight = 0.0
            self._last_flight_damage = 0.0
            self.state.altitude = 0.0
            self.state.km_this_flight = 0.0
            self.flight_phase = FlightPhase.ON_GROUND

    def _sync_twin_from_life_prediction(self) -> None:
        self.state.total_km_flown = self.life_prediction_state.total_km_flown
        self.state.flight_number = self.life_prediction_state.total_flights
        self.state.remaining_km = self.life_prediction_state.remaining_km
        rem = self.state.remaining_km
        avg_flight = self.life_prediction_state.ema_km_per_flight
        self.state.flight_allowed = rem >= avg_flight if avg_flight > 0 else rem > 0

    def _resolve_aborted_flight(self, flight_state: dict) -> None:
        km = flight_state.get("km_this_flight", 0.0)
        if km <= 0:
            return
        last_damage = flight_state.get("last_flight_damage", 0.0)
        damage_delta = max(self.fatigue.state.damage - last_damage, 0.0)
        self._km_this_flight = km
        self.life_prediction_state.update_after_flight(
            damage_delta=damage_delta,
            km_delta=km,
        )

    def request_takeoff(self) -> bool:
        if self._flight_phase != FlightPhase.ON_GROUND:
            return False
        if not self.state.flight_allowed:
            return False
        self.dynamics.reset()
        self._takeoff_timer = 0.0
        self._km_this_flight = 0.0
        self._last_flight_damage = self.state.damage
        self.state.altitude = 0.0
        self.state.airspeed = 0.0
        self.state.angle_of_attack = 0.0
        self.state.stepper_position = 0
        self.state.km_this_flight = 0.0
        self.state.desired_angle_of_attack = 0.0
        self.state.desired_airspeed = 0.0
        self.state.target_angle_of_attack = 0.0
        self.state.target_airspeed = 0.0
        self.flight_phase = FlightPhase.TAKING_OFF
        return True

    def request_landing(self) -> bool:
        if self._flight_phase != FlightPhase.IN_FLIGHT:
            return False
        if self.state.altitude > self.config.max_landing_altitude:
            return False
        self._landing_timer = 0.0
        self.flight_phase = FlightPhase.LANDING
        return True

    def _complete_flight(self) -> None:
        damage_delta = self.state.damage - self._last_flight_damage
        km_delta = self._km_this_flight
        if km_delta > 0:
            self.life_prediction_state.update_after_flight(
                damage_delta=damage_delta,
                km_delta=km_delta,
            )
        self._km_this_flight = 0.0
        self._last_flight_damage = self.state.damage
        self._sync_twin_from_life_prediction()

    def _update_takeoff(self, dt: float) -> None:
        self._takeoff_timer += dt
        t = self._takeoff_timer

        V_takeoff = self.config.takeoff_speed
        climb_angle = self.config.takeoff_climb_angle

        if t < 3.0:
            frac = t / 3.0
            target_speed = V_takeoff * frac
            target_angle = 0.0
        elif t < 5.0:
            frac = (t - 3.0) / 2.0
            target_speed = V_takeoff
            target_angle = climb_angle * frac
        else:
            frac = min((t - 5.0) / 5.0, 1.0)
            target_speed = V_takeoff + (self.config.reference_speed - V_takeoff) * frac
            target_angle = climb_angle

        target_angle = max(-self.config.max_aoa, min(self.config.max_aoa, target_angle))
        target_speed = max(0.0, min(self.config.reference_speed, target_speed))

        self.state.target_angle_of_attack = target_angle
        self.state.target_airspeed = target_speed

        self.dynamics.update(self.state, dt)

        self.state.desired_angle_of_attack = target_angle
        self.state.desired_airspeed = target_speed

        self._update_stepper()

        if hasattr(self._data_source, 'set_airspeed'):
            self._data_source.set_airspeed(self.state.airspeed)
        if hasattr(self._data_source, 'set_angle_of_attack'):
            self._data_source.set_angle_of_attack(self.state.angle_of_attack)

        self._update_altitude_km(dt)

        if self.state.altitude >= self.config.takeoff_altitude_threshold or t > 15.0:
            self.flight_phase = FlightPhase.IN_FLIGHT

    def _update_landing(self, dt: float) -> None:
        self._landing_timer += dt
        t = self._landing_timer
        alt = self.state.altitude

        touchdown_alt = 0.3
        flare_alt = self.config.landing_altitude_threshold
        if alt > flare_alt * 6:
            frac = min(t / 5.0, 1.0)
            target_speed = self.state.airspeed + (self.config.landing_approach_speed - self.state.airspeed) * frac * 0.1
            target_angle = -2.0
        elif alt > touchdown_alt:
            target_speed = max(self.config.landing_touchdown_speed, self.state.airspeed - 5.0 * dt)
            target_angle = -1.0
        else:
            target_speed = max(0.0, self.state.airspeed - 10.0 * dt)
            target_angle = 0.0
            self.state.altitude = max(0.0, self.state.altitude - 0.5 * dt)

        target_angle = max(-self.config.max_aoa, min(self.config.max_aoa, target_angle))
        target_speed = max(0.0, target_speed)

        self.state.target_angle_of_attack = target_angle
        self.state.target_airspeed = target_speed

        self.dynamics.update(self.state, dt)

        self.state.desired_angle_of_attack = target_angle
        self.state.desired_airspeed = target_speed

        self._update_stepper()

        if hasattr(self._data_source, 'set_airspeed'):
            self._data_source.set_airspeed(self.state.airspeed)
        if hasattr(self._data_source, 'set_angle_of_attack'):
            self._data_source.set_angle_of_attack(self.state.angle_of_attack)

        self._update_altitude_km(dt)

        if self.state.altitude <= 0.01 and self.state.airspeed < self.config.landing_touchdown_speed:
            self.state.altitude = 0.0
            self.state.airspeed = 0.0
            self.state.angle_of_attack = 0.0
            self.state.stepper_position = 0
            self._complete_flight()
            self.flight_phase = FlightPhase.ON_GROUND

    def _update_stepper(self) -> None:
        F_aero = compute_aero_force(
            self.state.angle_of_attack,
            self.state.airspeed,
            model=self._aero_model,
        )
        self.state.stepper_position = force_to_steps(
            F_aero, self.config.steps_per_newton
        )

    # this is a synthetic altitude, used for simulating the different transitions. Don't treat it too seriously!
    def _update_altitude_km(self, dt: float) -> None:
        V_ms = self.state.airspeed / 3.6
        if V_ms < 0.1:
            climb_rate = 0.0
        elif self._flight_phase == FlightPhase.LANDING:
            climb_rate = V_ms * math.sin(math.radians(self.state.angle_of_attack))
        else:
            L, _D, _CL, _CD = compute_aero_forces(
                self.state.angle_of_attack,
                self.state.airspeed,
                model=self._aero_model,
            )
            climb_rate = self.config.climb_rate_gain * (L / self.config.lift_ref_N - 1.0)
            climb_rate = max(-V_ms, min(V_ms, climb_rate))

        self.state.altitude = max(0.0, self.state.altitude + climb_rate * dt)
        self._km_this_flight += (self.state.airspeed / 3600.0) * dt
        self.state.km_this_flight = self._km_this_flight

    def step(self) -> bool:
        """Execute one processing step. Returns True if new data was processed."""
        if self._data_source is None:
            return False

        dt = 1.0 / self.config.sample_rate

        if self._flight_phase == FlightPhase.ON_GROUND:
            self._step_ground(dt)
        elif self._flight_phase == FlightPhase.TAKING_OFF:
            self._update_takeoff(dt)
        elif self._flight_phase == FlightPhase.IN_FLIGHT:
            self._step_flight(dt)
        elif self._flight_phase == FlightPhase.LANDING:
            self._update_landing(dt)

        reading = self._data_source.read()
        if reading is not None:
            self._process_reading(reading)
            return True
        return False

    def _step_ground(self, dt: float) -> None:
        self.state.angle_of_attack = 0.0
        self.state.airspeed = 0.0
        self.state.stepper_position = 0
        self.state.target_angle_of_attack = 0.0
        self.state.target_airspeed = 0.0
        self.state.desired_angle_of_attack = 0.0
        self.state.desired_airspeed = 0.0
        self.state.altitude = 0.0
        self.state.km_this_flight = 0.0

    def _step_flight(self, dt: float) -> None:
        self._update_safe_targets()
        self.dynamics.update(self.state, dt)

        self._update_stepper()

        if hasattr(self._data_source, 'set_airspeed'):
            self._data_source.set_airspeed(self.state.airspeed)
        if hasattr(self._data_source, 'set_angle_of_attack'):
            self._data_source.set_angle_of_attack(self.state.angle_of_attack)

        self._update_altitude_km(dt)

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

        # Only accumulate fatigue during active flight phases
        if self._flight_phase != FlightPhase.ON_GROUND:
            self.fatigue.process(
                strain_vector=strain_vec,
                stress_field_pa=stress,
                expected_strain=expected_strain,
                twin_state=self.state,
                matrices=self._matrices,
                single_strain=reading.strain,
            )
        else:
            self.state.damage = self.fatigue.state.damage
            self.state.confidence = self.fatigue.state.confidence

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

        if self._matrices is not None and self.state.forces:
            F_current = np.array(self.state.forces, dtype=np.float64)
            F_current_mag = float(np.linalg.norm(F_current))

            if F_current_mag > 1e-12:
                F_aero_current = compute_aero_force(
                    self.state.angle_of_attack, self.state.airspeed,
                    model=self._aero_model,
                )
                F_aero_target = compute_aero_force(
                    target_angle, target_speed, model=self._aero_model,
                )

                min_aero = max(0.01 * F_aero_target, 1e-9)
                stress_scale = F_aero_target / max(F_aero_current, min_aero)
                F_predicted = F_current * stress_scale
                stress_predicted = compute_stress_field(self._matrices.S, F_predicted)
                max_stress_pred = float(np.max(np.abs(stress_predicted)))

                if max_stress_pred > self.config.stress_limit and max_stress_pred > 0.0:
                    reduction = (self.config.stress_limit / max_stress_pred) ** 0.5
                    target_speed = max(self.config.min_airspeed, target_speed * reduction)
                    if target_speed == self.config.min_airspeed:
                        target_angle *= self.config.stress_limit / max_stress_pred

        if self.state.altitude < self.config.min_safe_altitude and self._flight_phase == FlightPhase.IN_FLIGHT:
            if target_angle < 2.0:
                target_angle = 2.0

        self.state.target_angle_of_attack = target_angle
        self.state.target_airspeed = target_speed
