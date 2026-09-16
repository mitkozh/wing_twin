"""
Core digital twin processing engine.
"""

import logging
import math
from enum import Enum
from typing import Optional

import numpy as np

from wing_twin.fea.matrices import TransferMatrices, load_transfer_matrices
from wing_twin.fea.force_reconstruct import solve_forces
from wing_twin.fea.field_compute import compute_stress_field, compute_deformation_field
from wing_twin.fatigue.fatigue import FatigueState, set_random_seed
from wing_twin.io.channel_manager import ChannelManager
from wing_twin.physics.aero import (
    compute_aero_force,
    compute_aero_forces,
    force_to_steps,
    init_neuralfoil,
    NeuralFoilModel,
)
from wing_twin.physics.wind import WindModel, compute_apparent_wind
from wing_twin.config import EngineConfig  # noqa: E402
from wing_twin.engine.state import TwinState, EngineSnapshot
from wing_twin.engine.dynamics import FlightDynamics
from wing_twin.engine.fatigue_tracker import FatigueTracker
from wing_twin.engine.wind_tracker import WindTracker
from wing_twin.engine.flight_profile import (
    TakeoffProfile,
    LandingProfile,
    takeoff_desired,
    landing_desired,
)
from wing_twin.fatigue.life_prediction import LifePredictionState
from wing_twin.types import DataSource, RawSensorReading, ProcessedSensorReading, SensorReading, SimulatableDataSource

logger = logging.getLogger(__name__)


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
            max_angle_rate=self.config.max_angle_rate,
            max_speed_rate=self.config.max_speed_rate,
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
                "prev_flight_blocked": engine_snapshot.prev_flight_blocked,
            }
            if engine_snapshot.dynamics:
                self.dynamics.from_dict(engine_snapshot.dynamics)

        self.fatigue = FatigueTracker(
            self.config.fatigue,
            initial_state=initial_fatigue,
            initial_life_prediction=initial_life,
            tracker_snapshot=tracker_snap,
        )

        self.state.structural.yield_point_pa = self.config.yield_point
        self.state.structural.stress_limit_pa = self.config.stress_limit
        self.state.control.max_angle_deg = self.config.max_aoa
        self.state.control.max_speed_kmh = self.config.reference_speed
        self.state.control.max_stepper_steps = self.config.calibration.stepper_wing_safe_limit
        self.state.flight.max_landing_altitude = self.config.max_landing_altitude

        # Flight state machine
        if engine_snapshot and engine_snapshot.flight:
            self._km_this_flight = engine_snapshot.flight.get("km_this_flight", 0.0)
            self._last_flight_damage = engine_snapshot.flight.get("last_flight_damage", 0.0)
            phase_str = engine_snapshot.flight.get("flight_phase", "on_ground")
            self._flight_phase = FlightPhase(phase_str)
            self._takeoff_timer = engine_snapshot.flight.get("takeoff_timer", 0.0)
            self._landing_timer = engine_snapshot.flight.get("landing_timer", 0.0)
            self._prev_altitude = self.state.flight.altitude
            self._altitude_recovery_active = self.state.flight.altitude < self.config.min_safe_altitude
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

        wind_model = WindModel(self.config.wind, seed=self.config.seed)
        self._wind_tracker = WindTracker(wind_model, self.config.wind)

        if engine_snapshot and engine_snapshot.wind:
            self._wind_tracker.from_dict(engine_snapshot.wind)
            self._wind_tracker.apply_smoothed_to_state(self.state)

        # Sync TwinState from LifePredictionState
        self._sync_twin_from_life_prediction()

        if self.config.seed is not None:
            set_random_seed(self.config.seed)

        channel_names = list(self.config.calibration.channel_names)
        if engine_snapshot and engine_snapshot.channels:
            self._channel_mgr = ChannelManager.from_dict(engine_snapshot.channels, channel_names)
        else:
            self._channel_mgr = ChannelManager(channel_names)
        self._prev_low_conf_notified: bool = (
            engine_snapshot.prev_low_confidence
            if engine_snapshot else False
        )

        self._tare_vector: Optional[np.ndarray] = None

        dead_mask = self.config.calibration.dead_channel_mask()
        n_dead = sum(dead_mask)
        n_total = len(dead_mask)
        if n_dead > 0:
            dead_names = [
                self.config.calibration.channel_names[i]
                for i, d in enumerate(dead_mask) if d
            ]
            logger.info(
                "Operating with %d/%d active channels. Dead: %s",
                n_total - n_dead, n_total, dead_names,
            )
        else:
            logger.info("Operating with all %d channels active", n_total)

        if data_source:
            self.data_source = data_source

    @property
    def flight_phase(self) -> FlightPhase:
        return self._flight_phase

    @flight_phase.setter
    def flight_phase(self, phase: FlightPhase) -> None:
        self._flight_phase = phase
        self.state.flight.flight_phase = phase.value

    @property
    def data_source(self) -> Optional[DataSource]:
        return self._data_source

    @data_source.setter
    def data_source(self, source: DataSource) -> None:
        self._data_source = source
        self._data_source.connect()
        if self._matrices is not None:
            self._num_gauges = self._matrices.n_gauges
        if isinstance(self._data_source, SimulatableDataSource):
            self._data_source.set_calibration(self.config.calibration)

    def _push_flight_state_to_source(self) -> None:
        if isinstance(self._data_source, SimulatableDataSource):
            self._data_source.set_airspeed(self.state.control.airspeed)
            self._data_source.set_angle_of_attack(self.state.control.angle_of_attack)

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

    @property
    def wind_model(self):
        """Underlying WindModel, shared with SimulatorSource."""
        return self._wind_tracker.wind_model

    def load_matrices(self, matrix_dir: Optional[str] = None) -> None:
        matrix_path = matrix_dir or self.config.matrix_dir
        self._matrices = load_transfer_matrices(matrix_path)
        self._num_gauges = self._matrices.n_gauges

    def set_tare(self, tare_vector: np.ndarray) -> None:
        """Set the tare baseline to subtract from (raw - dummy - offset) before scaling.

        Should be called with the mean of (raw - dummy - offset) sampled at
        zero load (stepper at position 0) during startup.
        """
        self._tare_vector = np.asarray(tare_vector, dtype=np.float64)
        logger.info(
            "Tare set (%d channels, max component=%.2f)",
            len(self._tare_vector), float(np.max(np.abs(self._tare_vector))),
        )

    def reset(self, target: str = "all") -> None:
        self.fatigue.reset(target)
        if target in ("confidence", "all"):
            self._channel_mgr.reset_confidence()
            self._prev_low_conf_notified = False
        if target in ("strain", "all"):
            self.state.structural.strain_vector = []
            self.state.structural.forces = []
            self.state.structural.stress_field = []
            self.state.structural.deformation_field = []
        if target in ("damage", "all"):
            self.state.damage.damage = 0.0
            self.state.structural.cycles_histogram.clear()
        if target in ("flight", "all"):
            self._km_this_flight = 0.0
            self._last_flight_damage = 0.0
            self.state.flight.altitude = 0.0
            self.state.flight.km_this_flight = 0.0
            self.flight_phase = FlightPhase.ON_GROUND
            self._altitude_recovery_active = False
            self._wind_tracker.reset()
            self.state.wind.wind_horizontal_ms = 0.0
            self.state.wind.wind_vertical_ms = 0.0
            self.state.wind.wind_horizontal_smoothed_ms = 0.0
            self.state.wind.wind_vertical_smoothed_ms = 0.0
            self.state.wind.effective_airspeed_kmh = 0.0
            self.state.wind.effective_aoa_deg = 0.0

    def _sync_twin_from_life_prediction(self) -> None:
        self.state.flight.total_km_flown = self.life_prediction_state.total_km_flown
        self.state.flight.flight_number = self.life_prediction_state.total_flights
        self.state.flight.remaining_km = self.life_prediction_state.remaining_km
        rem = self.state.flight.remaining_km
        avg_flight = self.life_prediction_state.ema_km_per_flight
        self.state.flight.flight_allowed = rem >= avg_flight if avg_flight > 0 else rem > 0

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
            count_as_flight=False,
        )

    def save_snapshot(self) -> EngineSnapshot:
        ts = self.fatigue.tracker_snapshot()
        return EngineSnapshot(
            twin=self.state.to_snapshot_dict(),
            fatigue=self.fatigue.state.to_dict(),
            channels=self._channel_mgr.to_dict(),
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
            prev_low_confidence=self._prev_low_conf_notified,
            prev_flight_blocked=ts.get("prev_flight_blocked", False),
            wind=self._wind_tracker.to_dict(),
        )

    def request_takeoff(self) -> bool:
        if self._flight_phase != FlightPhase.ON_GROUND:
            return False
        if not self.state.flight.flight_allowed:
            return False
        self.dynamics.reset()
        self._channel_mgr.reset_confidence()
        self._takeoff_timer = 0.0
        self._km_this_flight = 0.0
        self._last_flight_damage = self.state.damage.damage
        self.state.flight.altitude = 0.0
        self.state.control.airspeed = 0.0
        self.state.control.angle_of_attack = 0.0
        self.state.stepper.stepper_position = 0
        self.state.flight.km_this_flight = 0.0
        self.state.control.desired_angle_of_attack = 0.0
        self.state.control.desired_airspeed = 0.0
        self.state.control.target_angle_of_attack = 0.0
        self.state.control.target_airspeed = 0.0
        self._altitude_recovery_active = False
        self._wind_tracker.reset()
        self.state.wind.wind_horizontal_ms = 0.0
        self.state.wind.wind_vertical_ms = 0.0
        self.state.wind.wind_horizontal_smoothed_ms = 0.0
        self.state.wind.wind_vertical_smoothed_ms = 0.0
        self.state.wind.effective_airspeed_kmh = 0.0
        self.state.wind.effective_aoa_deg = 0.0
        self.flight_phase = FlightPhase.TAKING_OFF
        self.state.add_notification(
            "takeoff_started", "info", "Takeoff",
            "Takeoff sequence initiated.",
        )
        return True

    def request_landing(self) -> bool:
        if self._flight_phase != FlightPhase.IN_FLIGHT:
            return False
        if self.state.flight.altitude > self.config.max_landing_altitude:
            return False
        self._landing_timer = 0.0
        self.flight_phase = FlightPhase.LANDING
        self.state.add_notification(
            "landing_started", "info", "Landing",
            "Landing sequence initiated.",
        )
        return True

    def _complete_flight(self) -> None:
        damage_delta = self.state.damage.damage - self._last_flight_damage
        km_delta = self._km_this_flight
        if km_delta > 0:
            self.life_prediction_state.update_after_flight(
                damage_delta=damage_delta,
                km_delta=km_delta,
            )
        self._km_this_flight = 0.0
        self._last_flight_damage = self.state.damage.damage
        self._altitude_recovery_active = False
        self._sync_twin_from_life_prediction()

    def _update_takeoff(self, dt: float) -> None:
        self._takeoff_timer += dt
        profile = TakeoffProfile(
            takeoff_speed_kmh=self.config.takeoff_speed,
            takeoff_climb_angle_deg=self.config.takeoff_climb_angle,
            reference_speed_kmh=self.config.reference_speed,
            max_aoa_deg=self.config.max_aoa,
            cruise_aoa_deg=self.config.takeoff_cruise_aoa_deg,
            transition_altitude_m=self.config.takeoff_transition_altitude_m,
        )
        desired_angle, desired_speed = takeoff_desired(
            self._takeoff_timer, self.state.flight.altitude, profile,
        )

        self.state.control.desired_angle_of_attack = desired_angle
        self.state.control.desired_airspeed = desired_speed
        self._update_safe_targets()
        self.dynamics.update(self.state, dt)
        self._update_stepper()
        self._push_flight_state_to_source()
        self._update_altitude_km(dt)

        if self.state.flight.altitude >= self.config.min_safe_altitude or self._takeoff_timer > 30.0:
            self.flight_phase = FlightPhase.IN_FLIGHT
            self.state.add_notification(
                "in_flight_reached", "info", "In Flight",
                "Takeoff complete, now in flight.",
            )

    def _update_landing(self, dt: float) -> None:
        self._landing_timer += dt
        alt = self.state.flight.altitude

        profile = LandingProfile(
            approach_speed_kmh=self.config.landing_approach_speed,
            touchdown_speed_kmh=self.config.landing_touchdown_speed,
            approach_aoa_deg=self.config.landing_approach_aoa_deg,
            flare_aoa_deg=self.config.landing_flare_aoa_deg,
            flare_altitude_m=self.config.landing_altitude_threshold,
            approach_altitude_m=self.config.landing_altitude_threshold * 6.0,
            max_aoa_deg=self.config.max_aoa,
            reference_speed_kmh=self.config.reference_speed,
        )
        desired_angle, desired_speed = landing_desired(alt, profile)

        self.state.control.desired_angle_of_attack = desired_angle
        self.state.control.desired_airspeed = desired_speed
        self._update_safe_targets()
        self.dynamics.update(self.state, dt)
        self._update_stepper()
        self._push_flight_state_to_source()

        touchdown_alt = profile.flare_altitude_m
        if alt <= touchdown_alt:
            self.state.flight.altitude = max(0.0, self.state.flight.altitude - 0.5 * dt)
        else:
            self._update_altitude_km(dt)

        if self.state.flight.altitude <= 0.01 and self.state.control.airspeed < self.config.landing_touchdown_speed:
            completed_km = self._km_this_flight
            self.state.flight.altitude = 0.0
            self.state.control.airspeed = 0.0
            self.state.control.angle_of_attack = 0.0
            self.state.stepper.stepper_position = 0
            self._complete_flight()
            self.flight_phase = FlightPhase.ON_GROUND
            self.state.add_notification(
                "flight_completed", "info", "Flight Complete",
                f"Flight {self.state.flight.flight_number} completed. "
                f"{completed_km:.2f} km flown.",
            )

    def _update_stepper(self) -> None:
        u_w, w_w = self._sample_wind(self.state.control.airspeed)
        v_eff, alpha_eff = compute_apparent_wind(
            self.state.control.airspeed,
            self.state.control.angle_of_attack,
            u_w,
            w_w,
        )

        self._wind_tracker.update_state(self.state, u_w, w_w, v_eff, alpha_eff)

        F_aero = compute_aero_force(
            alpha_eff,
            v_eff,
            model=self._aero_model,
            calibration=self.config.calibration,
        )
        F_aero *= self.config.calibration.force_scale
        self.state.stepper.stepper_position = force_to_steps(
            F_aero,
            self.config.calibration.steps_per_newton,
            max_steps=self.config.calibration.stepper_wing_safe_limit,
        )

    def _sample_wind(self, current_airspeed_kmh: float) -> tuple[float, float]:
        return self._wind_tracker.sample(
            self._time_elapsed, current_airspeed_kmh, self._flight_phase.value,
            takeoff_speed_kmh=self.config.takeoff_speed,
        )

    def _safe_apparent(
        self, target_airspeed_kmh: float, target_angle_deg: float
    ) -> tuple[float, float]:
        return self._wind_tracker.safe_apparent(target_airspeed_kmh, target_angle_deg)

    # this is a synthetic altitude, used for simulating the different transitions. Don't treat it too seriously!
    def _update_altitude_km(self, dt: float) -> None:
        self._prev_altitude = self.state.flight.altitude
        V_ms = self.state.control.airspeed / 3.6
        if V_ms < 0.1:
            climb_rate = 0.0
        else:
            v_eff = self.state.wind.effective_airspeed_kmh or self.state.control.airspeed
            alpha_eff = self.state.wind.effective_aoa_deg or self.state.control.angle_of_attack
            L, _D, _CL, _CD = compute_aero_forces(
                alpha_eff,
                v_eff,
                model=self._aero_model,
                calibration=self.config.calibration,
            )

            climb_rate = self.config.climb_rate_gain * (L / self.config.lift_ref_N - 1.0)
            climb_rate = max(-V_ms, min(V_ms, climb_rate))

        self.state.flight.altitude = max(0.0, self.state.flight.altitude + climb_rate * dt)
        self._km_this_flight += (self.state.control.airspeed / 3600.0) * dt
        self.state.flight.km_this_flight = self._km_this_flight

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
        self.state.control.angle_of_attack = 0.0
        self.state.control.airspeed = 0.0
        self.state.stepper.stepper_position = 0
        self.state.control.target_angle_of_attack = 0.0
        self.state.control.target_airspeed = 0.0
        self.state.control.desired_angle_of_attack = 0.0
        self.state.control.desired_airspeed = 0.0
        self.state.flight.altitude = 0.0
        self.state.flight.km_this_flight = 0.0
        # Wind is gated off in ON_GROUND; clear apparent fields so the
        # HUD doesn't show stale numbers from a previous flight.
        self.state.wind.wind_horizontal_ms = 0.0
        self.state.wind.wind_vertical_ms = 0.0
        self.state.wind.effective_airspeed_kmh = 0.0
        self.state.wind.effective_aoa_deg = 0.0

    def _step_flight(self, dt: float) -> None:
        self._update_safe_targets()
        self.dynamics.update(self.state, dt)
        self._update_stepper()
        self._push_flight_state_to_source()
        self._update_altitude_km(dt)

    def _to_strain_vec(self, reading: SensorReading) -> tuple[np.ndarray, Optional[list[bool]]]:
        """Convert a sensor reading to a strain vector + saturated flags."""
        cal = self.config.calibration
        if isinstance(reading, RawSensorReading):
            raw = np.array(reading.raw_values, dtype=np.float64)
            off = np.array(reading.offset_values if reading.offset_values is not None else [], dtype=np.float64)
            scale = (
                np.array(cal.per_channel_adc_to_strain_scale, dtype=np.float64)
                if cal.per_channel_adc_to_strain_scale is not None
                else cal.adc_to_strain_scale
            )
            compensated = raw - reading.dummy_raw - off
            if self._tare_vector is not None:
                compensated = compensated - self._tare_vector
            return compensated * scale, reading.saturated_flags
        if isinstance(reading, ProcessedSensorReading):
            return np.array(reading.strain_vector, dtype=np.float64), None
        raise ValueError(f"Unknown SensorReading type: {type(reading).__name__}")

    def _compute_fea(self, strain: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Solve forces + FEA fields from a (possibly imputed) strain vector.

        Returns (forces, expected_strain, stress_field, deformation_field).
        """
        cal = self.config.calibration
        H = self._matrices.H
        F = solve_forces(self._matrices.H_inv, strain)
        F *= cal.H_matrix_scale
        expected = H @ F
        stress = compute_stress_field(self._matrices.S, F)
        deformation = compute_deformation_field(self._matrices.U, F)
        return F, expected, stress, deformation

    def _store_fea(self, strain: np.ndarray, F: np.ndarray, stress: np.ndarray, deformation: np.ndarray) -> None:
        self.state.structural.strain_vector = strain.tolist()
        self.state.structural.forces = F.tolist()
        self.state.structural.stress_field = stress.tolist()
        self.state.structural.deformation_field = deformation.tolist()

    def _update_low_confidence_notification(self) -> None:
        """Show/hide the low-confidence maintenance notification."""
        threshold = self.config.fatigue.confidence_frames_threshold
        low_conf = self._channel_mgr.low_confidence_frames >= threshold
        if low_conf and not self._prev_low_conf_notified:
            bad = self._channel_mgr.bad_indices()
            if bad:
                names = [self.config.calibration.channel_names[i] for i in bad]
                msg = f"Sensor readings low confidence. Problematic channels: {', '.join(names)}."
            else:
                msg = "Sensor readings show low confidence."
            self.state.add_notification("maint_low_conf", "warning", "Maintenance Required", msg)
        elif not low_conf and self._prev_low_conf_notified:
            self.state.dismiss_notification("maint_low_conf")
        self._prev_low_conf_notified = low_conf

    def _process_reading(self, reading: SensorReading) -> None:
        """Process a sensor reading through ingestion → imputation → FEA → fatigue."""
        if self._matrices is None:
            raise RuntimeError("Call load_matrices() before processing readings")

        cal = self.config.calibration
        H = self._matrices.H

        strain_vec, saturated_flags = self._to_strain_vec(reading)
        dead_mask = cal.dead_channel_mask()

        self._channel_mgr.ingest(strain_vec, saturated_flags, dead_mask, cal.strain_saturation_threshold)

        # First-pass imputation -> FEA
        strain_clean = self._channel_mgr.impute(H)
        F, expected_strain, stress, deformation = self._compute_fea(strain_clean)
        self._store_fea(strain_clean, F, stress, deformation)

        # Confidence tracking -> re-imputation if needed
        dead_mask_np = np.array(dead_mask, dtype=bool) if cal.per_channel_adc_to_strain_scale is not None else None
        has_new_bad, _ = self._channel_mgr.update_confidence(expected_strain, self.config.fatigue, H, dead_mask_np)
        self._channel_mgr.log_low_confidence_channels(self.config.fatigue)

        if has_new_bad and not self.config.fatigue.disable_confidence_imputation:
            reimputed = self._channel_mgr.reimpute(H)
            F_re, _, stress_re, deformation_re = self._compute_fea(reimputed)
            self._store_fea(reimputed, F_re, stress_re, deformation_re)
            self.fatigue.accumulate_damage(stress_re, self.state, flight_phase=self._flight_phase)

        # Damage accumulation (uses latest stored stress from either pass)
        self.fatigue.accumulate_damage(stress, self.state, flight_phase=self._flight_phase)

        # Sync confidence & notifications
        self.state.damage.confidence = self._channel_mgr.confidence
        self._update_low_confidence_notification()
        self._channel_mgr.to_health_events()

    def _update_safe_targets(self) -> None:
        """Convert desired angle/speed into safe targets."""
        desired_angle = float(self.state.control.desired_angle_of_attack)
        desired_speed = float(self.state.control.desired_airspeed)

        target_angle = max(-self.config.max_aoa, min(self.config.max_aoa, desired_angle))
        if self._flight_phase == FlightPhase.LANDING:
            speed_floor = 0.0
        else:
            speed_floor = self.config.min_airspeed

        target_speed = max(speed_floor, min(self.config.reference_speed, desired_speed))

        # Altitude recovery
        if self._flight_phase == FlightPhase.IN_FLIGHT:
            self._altitude_recovery_active = self.state.flight.altitude < self.config.min_safe_altitude
        else:
            self._altitude_recovery_active = False

        if self._altitude_recovery_active:
            target_speed = max(target_speed, self.config.reference_speed)
            target_angle = max(target_angle, self.config.altitude_recovery_aoa_deg)

        # Damage-based stress limit reduction: 5% at damage=0.3, 15% at damage=1.0
        stress_limit = self.config.stress_limit
        if self.state.damage.damage > 0.3:
            t = min((self.state.damage.damage - 0.3) / 0.7, 1.0)
            reduction_pct = 0.05 + 0.10 * t
            stress_limit *= (1.0 - reduction_pct)
        self.state.structural.stress_limit_pa = stress_limit

        # When maintenance assist is off, bypass all stress limiting
        if not self.state.notifications.maintenance_assist:
            self.state.control.target_angle_of_attack = target_angle
            self.state.control.target_airspeed = target_speed
            return

        if self._matrices is not None and self.state.structural.forces:
            F_current = np.array(self.state.structural.forces, dtype=np.float64)
            F_current_mag = float(np.linalg.norm(F_current))

            if F_current_mag > 1e-12:
                v_eff_cur = self.state.wind.effective_airspeed_kmh or self.state.control.airspeed
                alpha_eff_cur = self.state.wind.effective_aoa_deg or self.state.control.angle_of_attack
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

        self.state.control.target_angle_of_attack = target_angle
        self.state.control.target_airspeed = target_speed
