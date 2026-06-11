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
from wing_twin.io.sensor_validation import (
    ChannelHealthTracker,
    detect_bad_channels,
    impute_channels,
)
from wing_twin.physics.aero import (
    compute_aero_force,
    compute_aero_forces,
    force_to_steps,
    init_neuralfoil,
    NeuralFoilModel,
)
from wing_twin.physics.wind import WindModel, apparent_wind
from wing_twin.config import EngineConfig
from wing_twin.engine.state import TwinState, EngineSnapshot
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
        engine_snapshot: Optional[EngineSnapshot] = None,
    ):
        self.config = config or EngineConfig()
        self._matrices: Optional[TransferMatrices] = None
        self._num_gauges: Optional[int] = None
        self._data_source: Optional[DataSource] = None

        # Restore TwinState from snapshot or start fresh
        if engine_snapshot and engine_snapshot.twin:
            self.state = TwinState.from_snapshot_dict(engine_snapshot.twin)
        else:
            self.state = TwinState()

        self.dynamics = FlightDynamics(
            angle_accel=self.config.angle_accel,
            speed_accel=self.config.speed_accel,
        )

        # Prepare FatigueTracker inputs from snapshot
        initial_fatigue = None
        initial_life = None
        tracker_snap = None
        if engine_snapshot:
            if engine_snapshot.fatigue:
                initial_fatigue = FatigueState.from_dict(engine_snapshot.fatigue)
            if engine_snapshot.life:
                initial_life = LifePredictionState.from_dict(engine_snapshot.life)
            tracker_snap = {
                "prev_low_confidence": engine_snapshot.prev_low_confidence,
                "prev_flight_blocked": engine_snapshot.prev_flight_blocked,
            }
            if engine_snapshot.dynamics:
                self.dynamics.from_dict(engine_snapshot.dynamics)

        self.fatigue = FatigueTracker(
            self.config.fatigue,
            initial_state=initial_fatigue,
            initial_life_prediction=initial_life,
            tracker_snapshot=tracker_snap,
            channel_names=list(self.config.calibration.channel_names),
        )

        self.state.yield_point_pa = self.config.yield_point
        self.state.stress_limit_pa = self.config.stress_limit
        self.state.max_angle_deg = self.config.max_aoa
        self.state.max_speed_kmh = self.config.reference_speed
        self.state.max_stepper_steps = self.config.calibration.stepper_wing_safe_limit
        self.state.max_landing_altitude = self.config.max_landing_altitude

        # Flight state machine
        if engine_snapshot and engine_snapshot.flight:
            self._km_this_flight = engine_snapshot.flight.get("km_this_flight", 0.0)
            self._last_flight_damage = engine_snapshot.flight.get("last_flight_damage", 0.0)
            phase_str = engine_snapshot.flight.get("flight_phase", "on_ground")
            self._flight_phase = FlightPhase(phase_str)
            self._takeoff_timer = engine_snapshot.flight.get("takeoff_timer", 0.0)
            self._landing_timer = engine_snapshot.flight.get("landing_timer", 0.0)
            self._prev_altitude = self.state.altitude
            self._altitude_recovery_active = self.state.altitude < self.config.min_safe_altitude
            self._time_elapsed = engine_snapshot.flight.get("time_elapsed", 0.0)
        else:
            self._flight_phase: FlightPhase = FlightPhase.ON_GROUND
            self._takeoff_timer: float = 0.0
            self._landing_timer: float = 0.0
            self._km_this_flight: float = 0.0
            self._time_elapsed: float = 0.0
            self._last_flight_damage: float = 0.0
            self._prev_altitude: float = 0.0
            self._altitude_recovery_active: bool = False

        # Process aborted flight data from previous run
        if engine_snapshot and engine_snapshot.flight:
            self._resolve_aborted_flight(engine_snapshot.flight)

        # Initialise NeuralFoil aerodynamic model
        self._aero_model: NeuralFoilModel = init_neuralfoil(
            model_size=self.config.neuralfoil_model_size,
        )

        self._wind = WindModel(self.config.wind, seed=self.config.seed)
        self._u_ema: float = 0.0
        self._w_ema: float = 0.0
        self._u_var: float = 0.0
        self._w_var: float = 0.0
        self._wind_ema_initialised: bool = False
        self._prev_step_t: float = -1.0

        if engine_snapshot and engine_snapshot.wind:
            w_snap = engine_snapshot.wind
            self._u_ema = float(w_snap.get("u_ema", 0.0))
            self._w_ema = float(w_snap.get("w_ema", 0.0))
            self._u_var = float(w_snap.get("u_var", 0.0))
            self._w_var = float(w_snap.get("w_var", 0.0))
            self._wind_ema_initialised = bool(w_snap.get("initialised", False))
            self._prev_step_t = float(w_snap.get("prev_step_t", -1.0))
            self.state.wind_horizontal_smoothed_ms = self._u_ema
            self.state.wind_vertical_smoothed_ms = self._w_ema

        # Sync TwinState from LifePredictionState
        self._sync_twin_from_life_prediction()

        if self.config.seed is not None:
            set_random_seed(self.config.seed)

        self._channel_health = ChannelHealthTracker(
            list(self.config.calibration.channel_names),
        )

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
            self._altitude_recovery_active = False
            self._wind.reset()
            self._u_ema = 0.0
            self._w_ema = 0.0
            self._u_var = 0.0
            self._w_var = 0.0
            self._wind_ema_initialised = False
            self._prev_step_t = -1.0
            self.state.wind_horizontal_ms = 0.0
            self.state.wind_vertical_ms = 0.0
            self.state.wind_horizontal_smoothed_ms = 0.0
            self.state.wind_vertical_smoothed_ms = 0.0
            self.state.effective_airspeed_kmh = 0.0
            self.state.effective_aoa_deg = 0.0

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

    def save_snapshot(self) -> EngineSnapshot:
        ts = self.fatigue.tracker_snapshot()
        return EngineSnapshot(
            twin=self.state.to_snapshot_dict(),
            fatigue=self.fatigue.state.to_dict(),
            life=self.life_prediction_state.to_dict(),
            flight={
                "km_this_flight": self._km_this_flight,
                "last_flight_damage": self._last_flight_damage,
                "flight_phase": self._flight_phase.value,
                "takeoff_timer": self._takeoff_timer,
                "landing_timer": self._landing_timer,
                "time_elapsed": self._time_elapsed,
            },
            dynamics=self.dynamics.to_dict(),
            prev_low_confidence=ts["prev_low_confidence"],
            prev_flight_blocked=ts["prev_flight_blocked"],
            wind={
                "u_ema": self._u_ema,
                "w_ema": self._w_ema,
                "u_var": self._u_var,
                "w_var": self._w_var,
                "initialised": self._wind_ema_initialised,
                "prev_step_t": self._prev_step_t,
            },
        )

    def request_takeoff(self) -> bool:
        if self._flight_phase != FlightPhase.ON_GROUND:
            return False
        if not self.state.flight_allowed:
            return False
        self.dynamics.reset()
        self.fatigue.reset(target="confidence")
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
        self._altitude_recovery_active = False
        self._wind.reset()
        self._u_ema = 0.0
        self._w_ema = 0.0
        self._u_var = 0.0
        self._w_var = 0.0
        self._wind_ema_initialised = False
        self._prev_step_t = -1.0
        self.state.wind_horizontal_ms = 0.0
        self.state.wind_vertical_ms = 0.0
        self.state.wind_horizontal_smoothed_ms = 0.0
        self.state.wind_vertical_smoothed_ms = 0.0
        self.state.effective_airspeed_kmh = 0.0
        self.state.effective_aoa_deg = 0.0
        self.flight_phase = FlightPhase.TAKING_OFF
        self.state.add_notification(
            "takeoff_started", "info", "Takeoff",
            "Takeoff sequence initiated.",
        )
        return True

    def request_landing(self) -> bool:
        if self._flight_phase != FlightPhase.IN_FLIGHT:
            return False
        if self.state.altitude > self.config.max_landing_altitude:
            return False
        self._landing_timer = 0.0
        self.flight_phase = FlightPhase.LANDING
        self.state.add_notification(
            "landing_started", "info", "Landing",
            "Landing sequence initiated.",
        )
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
        self._altitude_recovery_active = False
        self._sync_twin_from_life_prediction()

    def _update_takeoff(self, dt: float) -> None:
        self._takeoff_timer += dt
        t = self._takeoff_timer

        V_takeoff = self.config.takeoff_speed
        climb_angle = self.config.takeoff_climb_angle

        if t < 3.0:
            frac = t / 3.0
            desired_speed = V_takeoff * frac
            desired_angle = 0.0
        elif t < 5.0:
            frac = (t - 3.0) / 2.0
            desired_speed = V_takeoff
            desired_angle = climb_angle * frac
        else:
            frac = min((t - 5.0) / 5.0, 1.0)
            desired_speed = V_takeoff + (self.config.reference_speed - V_takeoff) * frac
            desired_angle = climb_angle

        desired_angle = max(-self.config.max_aoa, min(self.config.max_aoa, desired_angle))
        desired_speed = max(0.0, min(self.config.reference_speed, desired_speed))

        self.state.desired_angle_of_attack = desired_angle
        self.state.desired_airspeed = desired_speed
        self._update_safe_targets()

        self.dynamics.update(self.state, dt)

        self._update_stepper()

        if hasattr(self._data_source, 'set_airspeed'):
            self._data_source.set_airspeed(self.state.airspeed)
        if hasattr(self._data_source, 'set_angle_of_attack'):
            self._data_source.set_angle_of_attack(self.state.angle_of_attack)

        self._update_altitude_km(dt)

        if self.state.altitude >= self.config.min_safe_altitude or t > 30.0:
            self.flight_phase = FlightPhase.IN_FLIGHT
            self.state.add_notification(
                "in_flight_reached", "info", "In Flight",
                "Takeoff complete, now in flight.",
            )

    def _update_landing(self, dt: float) -> None:
        self._landing_timer += dt
        alt = self.state.altitude

        touchdown_alt = 0.3
        flare_alt = self.config.landing_altitude_threshold
        approach_end = flare_alt * 6.0  # ~3 m

        V_approach = self.config.landing_approach_speed
        V_touchdown = self.config.landing_touchdown_speed
        aoa_approach = self.config.landing_approach_aoa_deg
        aoa_flare = self.config.landing_flare_aoa_deg

        if alt > approach_end:
            t = self._landing_timer
            speed_ramp = min(t / 10.0, 1.0)
            desired_speed = self.state.airspeed + (V_approach - self.state.airspeed) * speed_ramp
            desired_angle = aoa_approach
        elif alt > touchdown_alt:
            flare_frac = (approach_end - alt) / (approach_end - touchdown_alt)
            flare_frac = max(0.0, min(1.0, flare_frac))
            desired_speed = V_approach + (V_touchdown - V_approach) * flare_frac
            desired_angle = aoa_approach + (aoa_flare - aoa_approach) * flare_frac
        else:
            touchdown_frac = (touchdown_alt - alt) / touchdown_alt
            touchdown_frac = max(0.0, min(1.0, touchdown_frac))
            desired_speed = V_touchdown * (1.0 - touchdown_frac)
            desired_angle = aoa_flare * (1.0 - touchdown_frac)

        desired_angle = max(-self.config.max_aoa, min(self.config.max_aoa, desired_angle))
        desired_speed = max(0.0, min(self.config.reference_speed, desired_speed))

        self.state.desired_angle_of_attack = desired_angle
        self.state.desired_airspeed = desired_speed
        self._update_safe_targets()

        self.dynamics.update(self.state, dt)

        self._update_stepper()

        if hasattr(self._data_source, 'set_airspeed'):
            self._data_source.set_airspeed(self.state.airspeed)
        if hasattr(self._data_source, 'set_angle_of_attack'):
            self._data_source.set_angle_of_attack(self.state.angle_of_attack)

        if alt <= touchdown_alt:
            self.state.altitude = max(0.0, self.state.altitude - 0.1 * dt)
        else:
            self._update_altitude_km(dt)

        if self.state.altitude <= 0.01 and self.state.airspeed < self.config.landing_touchdown_speed:
            self.state.altitude = 0.0
            self.state.airspeed = 0.0
            self.state.angle_of_attack = 0.0
            self.state.stepper_position = 0
            self._complete_flight()
            self.flight_phase = FlightPhase.ON_GROUND
            self.state.add_notification(
                "flight_completed", "info", "Flight Complete",
                f"Flight {self.state.flight_number} completed. "
                f"{self._km_this_flight:.2f} km flown.",
            )

    def _update_stepper(self) -> None:
        u_w, w_w = self._sample_wind(self.state.airspeed)
        v_eff, alpha_eff = apparent_wind(
            self.state.airspeed,
            self.state.angle_of_attack,
            u_w,
            w_w,
        )

        self.state.wind_horizontal_ms = u_w
        self.state.wind_vertical_ms = w_w
        self.state.effective_airspeed_kmh = v_eff
        self.state.effective_aoa_deg = alpha_eff

        F_aero = compute_aero_force(
            alpha_eff,
            v_eff,
            model=self._aero_model,
            calibration=self.config.calibration,
        )
        self.state.stepper_position = force_to_steps(
            F_aero,
            self.config.calibration.steps_per_newton,
            max_steps=self.config.calibration.stepper_wing_safe_limit,
        )

    def _sample_wind(self, current_airspeed_kmh: float) -> tuple[float, float]:
        """Sample wind, apply ground/takeoff ramp-in, and update EMA/variance.

        The EMA is updated on the *unramped* wind so its statistics track
        the true turbulence intensity.  Returns the ramped wind used to
        perturb the flight state this tick.
        """
        t = self._time_elapsed
        dt = 0.0 if self._prev_step_t < 0.0 else max(0.0, t - self._prev_step_t)
        self._prev_step_t = t

        u_raw, w_raw = self._wind.sample(t, dt)
        self._update_wind_ema(u_raw, w_raw, dt)

        # Ground / takeoff gating
        if not self.config.wind.enabled:
            return 0.0, 0.0
        if self._flight_phase == FlightPhase.ON_GROUND:
            return 0.0, 0.0

        ramp_denom = max(self.config.takeoff_speed * 0.5, 1.0)
        if self._flight_phase == FlightPhase.TAKING_OFF:
            r = max(0.0, min(1.0, current_airspeed_kmh / ramp_denom))
        else:
            r = 1.0
        return u_raw * r, w_raw * r

    def _update_wind_ema(self, u: float, w: float, dt: float) -> None:
        tau = self.config.wind.tau_smooth_s
        if dt <= 0.0 or tau <= 0.0:
            # Fall back to plain assignment on the first sample.
            if not self._wind_ema_initialised:
                self._u_ema, self._w_ema = u, w
                self._u_var = self._w_var = 0.0
                self._wind_ema_initialised = True
            return

        if not self._wind_ema_initialised:
            self._u_ema, self._w_ema = u, w
            self._u_var = self._w_var = 0.0
            self._wind_ema_initialised = True
            self.state.wind_horizontal_smoothed_ms = u
            self.state.wind_vertical_smoothed_ms = w
            return

        alpha = 1.0 - math.exp(-dt / tau)
        du = u - self._u_ema
        dw = w - self._w_ema
        self._u_ema += alpha * du
        self._w_ema += alpha * dw
        # EMA of squared deviation from the mean
        self._u_var = (1.0 - alpha) * self._u_var + alpha * du * du
        self._w_var = (1.0 - alpha) * self._w_var + alpha * dw * dw
        self.state.wind_horizontal_smoothed_ms = self._u_ema
        self.state.wind_vertical_smoothed_ms = self._w_ema

    def _safe_apparent(
        self, target_airspeed_kmh: float, target_angle_deg: float
    ) -> tuple[float, float]:
        """Conservative apparent state for the safe-target predictor.

        Biases the smoothed wind toward the more stressful direction:
        stronger headwind (u - k*sigma) and stronger updraft (w + k*sigma).
        """
        if not self._wind_ema_initialised:
            return target_airspeed_kmh, target_angle_deg
        k = self.config.wind.gust_margin_k
        u_safe = self._u_ema - k * math.sqrt(max(self._u_var, 0.0))
        w_safe = self._w_ema + k * math.sqrt(max(self._w_var, 0.0))
        return apparent_wind(target_airspeed_kmh, target_angle_deg, u_safe, w_safe)

    # this is a synthetic altitude, used for simulating the different transitions. Don't treat it too seriously!
    def _update_altitude_km(self, dt: float) -> None:
        self._prev_altitude = self.state.altitude
        V_ms = self.state.airspeed / 3.6
        if V_ms < 0.1:
            climb_rate = 0.0
        else:
            v_eff = self.state.effective_airspeed_kmh or self.state.airspeed
            alpha_eff = self.state.effective_aoa_deg or self.state.angle_of_attack
            L, _D, _CL, _CD = compute_aero_forces(
                alpha_eff,
                v_eff,
                model=self._aero_model,
                calibration=self.config.calibration,
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
        self._time_elapsed += dt

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
        # Wind is gated off in ON_GROUND; clear apparent fields so the
        # HUD doesn't show stale numbers from a previous flight.
        self.state.wind_horizontal_ms = 0.0
        self.state.wind_vertical_ms = 0.0
        self.state.effective_airspeed_kmh = 0.0
        self.state.effective_aoa_deg = 0.0

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
        """Process a sensor reading through -> FEA -> fatigue."""
        if self._matrices is None:
            raise RuntimeError("Call load_matrices() before processing readings")

        cal = self.config.calibration
        H = self._matrices.H

        if reading.raw_values is not None:
            raw = np.array(reading.raw_values, dtype=np.float64)
            off_vals = reading.offset_values if reading.offset_values is not None else []
            off = np.array(off_vals, dtype=np.float64)
            if cal.per_channel_adc_to_strain_scale is not None:
                scale = np.array(cal.per_channel_adc_to_strain_scale, dtype=np.float64)
            else:
                scale = cal.adc_to_strain_scale
            strain_vec = (raw - reading.dummy_raw - off) * scale
        elif reading.strain_vector is not None:
            strain_vec = np.array(reading.strain_vector, dtype=np.float64)
        else:
            raise ValueError("SensorReading has neither raw_values nor strain_vector")

        bad_idxs = detect_bad_channels(strain_vec, cal.strain_saturation_threshold)
        if reading.saturated_flags is not None:
            for i, flagged in enumerate(reading.saturated_flags):
                if flagged and i not in bad_idxs:
                    bad_idxs.append(i)
            bad_idxs.sort()

        pre_impute = strain_vec.copy()
        strain_clean = strain_vec.copy()
        if bad_idxs:
            strain_clean = impute_channels(strain_clean, bad_idxs, H)

        F = solve_forces(self._matrices.H_inv, strain_clean)
        F *= cal.H_matrix_scale
        expected_strain = H @ F

        self.fatigue.state.bad_channels = bad_idxs

        stress = compute_stress_field(self._matrices.S, F)
        deformation = compute_deformation_field(self._matrices.U, F)

        self.state.strain_vector = strain_clean.tolist()
        self.state.forces = F.tolist()
        self.state.stress_field = stress.tolist()
        self.state.deformation_field = deformation.tolist()

        self.fatigue.process(
            pre_impute_strain=pre_impute,
            strain_vector=strain_clean,
            stress_field_pa=stress,
            expected_strain=expected_strain,
            twin_state=self.state,
            H=H,
            H_inv=self._matrices.H_inv,
            S=self._matrices.S,
            U=self._matrices.U,
            cal=cal,
            flight_phase=self._flight_phase,
        )

        self._channel_health.update(self.fatigue.state.bad_channels)

    def _update_safe_targets(self) -> None:
        """Convert desired angle/speed into safe targets."""
        desired_angle = float(self.state.desired_angle_of_attack)
        desired_speed = float(self.state.desired_airspeed)

        target_angle = max(-self.config.max_aoa, min(self.config.max_aoa, desired_angle))
        if self._flight_phase == FlightPhase.LANDING:
            speed_floor = 0.0
        else:
            speed_floor = self.config.min_airspeed

        target_speed = max(speed_floor, min(self.config.reference_speed, desired_speed))

        # Altitude recovery
        if self._flight_phase == FlightPhase.IN_FLIGHT:
            self._altitude_recovery_active = self.state.altitude < self.config.min_safe_altitude
        else:
            self._altitude_recovery_active = False

        if self._altitude_recovery_active:
            target_speed = max(target_speed, self.config.reference_speed)
            target_angle = max(target_angle, self.config.altitude_recovery_aoa_deg)

        # Damage-based stress limit reduction: 5% at damage=0.3, 15% at damage=1.0
        stress_limit = self.config.stress_limit
        if self.state.damage > 0.3:
            t = min((self.state.damage - 0.3) / 0.7, 1.0)
            reduction_pct = 0.05 + 0.10 * t
            stress_limit *= (1.0 - reduction_pct)
        self.state.stress_limit_pa = stress_limit

        # When maintenance assist is off, bypass all stress limiting
        if not self.state.maintenance_assist:
            self.state.target_angle_of_attack = target_angle
            self.state.target_airspeed = target_speed
            return

        if self._matrices is not None and self.state.forces:
            F_current = np.array(self.state.forces, dtype=np.float64)
            F_current_mag = float(np.linalg.norm(F_current))

            if F_current_mag > 1e-12:
                v_eff_cur = self.state.effective_airspeed_kmh or self.state.airspeed
                alpha_eff_cur = self.state.effective_aoa_deg or self.state.angle_of_attack
                F_aero_current = compute_aero_force(
                    alpha_eff_cur, v_eff_cur,
                    model=self._aero_model,
                    calibration=self.config.calibration,
                )
                v_eff_safe, alpha_eff_safe = self._safe_apparent(target_speed, target_angle)
                F_aero_target = compute_aero_force(
                    alpha_eff_safe, v_eff_safe,
                    model=self._aero_model,
                    calibration=self.config.calibration,
                )

                F_total_current = F_aero_current
                F_total_target = F_aero_target

                min_total = max(0.01 * abs(F_total_target), 1e-9)
                denom_mag = max(abs(F_total_current), min_total)
                denom = math.copysign(denom_mag, F_total_current) if F_total_current != 0 else denom_mag
                stress_scale = F_total_target / denom
                F_predicted = F_current * stress_scale
                stress_predicted = compute_stress_field(self._matrices.S, F_predicted)
                max_stress_pred = float(np.max(np.abs(stress_predicted)))

                if max_stress_pred > stress_limit and max_stress_pred > 0.0:
                    reduction = (stress_limit / max_stress_pred) ** 0.5
                    target_speed = max(speed_floor, target_speed * reduction)
                    if target_speed == speed_floor:
                        target_angle *= stress_limit / max_stress_pred

        self.state.target_angle_of_attack = target_angle
        self.state.target_airspeed = target_speed
