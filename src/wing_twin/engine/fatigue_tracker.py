"""
FatigueTracker - Manages per-node fatigue accumulation, confidence monitoring,
and lifecycle notifications using the FEA stress field.
"""

from typing import Optional

import numpy as np

from wing_twin.fatigue.fatigue import (
    FatigueState,
    accumulate_damage_at_nodes,
    log_low_confidence_channels,
    sn_curve_for_material,
    update_confidence,
    warmup_numba,
)
from wing_twin.fea.field_compute import compute_deformation_field, compute_stress_field
from wing_twin.fea.force_reconstruct import solve_forces
from wing_twin.io.sensor_validation import impute_channels
from wing_twin.config.fatigue import FatigueConfig
from wing_twin.config.calibration import CalibrationConfig
from wing_twin.fatigue.life_prediction import LifePredictionState
from wing_twin.engine.state import TwinState


class FatigueTracker:
    """Tracks per-node fatigue accumulation, confidence, and notifications."""

    def __init__(
        self,
        config: FatigueConfig,
        initial_state: Optional[FatigueState] = None,
        initial_life_prediction: Optional[LifePredictionState] = None,
        tracker_snapshot: Optional[dict] = None,
        channel_names: Optional[list[str]] = None,
    ):
        self.config = config
        self.state = initial_state or FatigueState()
        self._channel_names = channel_names or list(CalibrationConfig().channel_names)
        if tracker_snapshot:
            self._prev_low_confidence = tracker_snapshot.get("prev_low_confidence", False)
            self._prev_flight_blocked = tracker_snapshot.get("prev_flight_blocked", False)
        else:
            self._prev_low_confidence = False
            self._prev_flight_blocked = False
        self.life_prediction = initial_life_prediction or LifePredictionState(
            initial_remaining_km=config.initial_remaining_km,
        )

        warmup_numba()

    def tracker_snapshot(self) -> dict:
        return {
            "prev_low_confidence": self._prev_low_confidence,
            "prev_flight_blocked": self._prev_flight_blocked,
        }

    def reset(self, target: str = "all") -> None:
        if target in ("damage", "all"):
            self.state = FatigueState()
            self._prev_low_confidence = False
            self._prev_flight_blocked = False
        if target == "confidence":
            self.state.filtered_residual = 0.0
            self.state.low_confidence_frames = 0
            self.state.per_channel_residual = np.array([], dtype=np.float64)
            self.state.per_channel_confidence = np.array([], dtype=np.float64)
            self.state.bad_channels = []
            self.state.per_channel_low_frames = {}
            self.state.group_consistency = np.array([], dtype=np.float64)
            self.state.group_expected_ratios = {}

    def process(
        self,
        pre_impute_strain: np.ndarray,
        strain_vector: np.ndarray,
        stress_field_pa: np.ndarray,
        expected_strain: np.ndarray,
        twin_state: TwinState,
        H: Optional[np.ndarray] = None,
        H_inv: Optional[np.ndarray] = None,
        S: Optional[np.ndarray] = None,
        U: Optional[np.ndarray] = None,
        cal: Optional[CalibrationConfig] = None,
        flight_phase: object = None,
    ) -> None:
        """Process one frame through confidence -> re-imputation -> damage."""
        fatigue_cfg = self.config
        sn_curve = sn_curve_for_material(fatigue_cfg.material)

        update_confidence(
            self.state, pre_impute_strain, expected_strain,
            config=fatigue_cfg, H=H,
        )

        log_low_confidence_channels(
            self.state, self._channel_names, config=fatigue_cfg,
        )

        low_conf_idxs = [
            i for i, c in enumerate(self.state.per_channel_confidence)
            if c < fatigue_cfg.confidence_threshold
        ]
        existing_bad = set(self.state.bad_channels)
        new_bad = sorted(set(low_conf_idxs) - existing_bad)
        all_bad = sorted(existing_bad | set(new_bad))

        if new_bad and H is not None and H_inv is not None and cal is not None:
            self.state.bad_channels = all_bad
            reimputed = impute_channels(pre_impute_strain.copy(), all_bad, H)
            F = solve_forces(H_inv, reimputed)
            F *= float(cal.H_matrix_scale)
            expected_strain = H @ F

            if S is not None:
                stress_field_pa = compute_stress_field(S, F)
            if U is not None:
                twin_state.deformation_field = (
                    compute_deformation_field(U, F).tolist()
                )

            twin_state.strain_vector = reimputed.tolist()
            twin_state.forces = F.tolist()
            twin_state.stress_field = stress_field_pa.tolist()
        else:
            self.state.bad_channels = all_bad

        if flight_phase is not None and flight_phase.value != "on_ground":
            stress_mpa = stress_field_pa / 1e6
            accumulate_damage_at_nodes(
                stress_mpa, self.state, sn_curve=sn_curve, config=fatigue_cfg,
            )

        twin_state.node_damages = dict(self.state.node_damages)
        twin_state.confidence = self.state.confidence
        self._update_damage_metrics(twin_state)
        self._check_notifications(twin_state)

    def _update_damage_metrics(self, twin_state: TwinState) -> None:
        if self.state.node_damages:
            values = list(self.state.node_damages.values())
            twin_state.damage = max(values)
            sorted_vals = sorted(values, reverse=True)
            top_10_pct = sorted_vals[: max(1, len(sorted_vals) // 10)]
            twin_state.avg_damage = (
                sum(top_10_pct) / len(top_10_pct) if top_10_pct else 0.0
            )
        else:
            twin_state.damage = self.state.damage
            twin_state.avg_damage = 0.0

        # Life prediction — read-only check; updates happen in _complete_flight
        rem = self.life_prediction.remaining_km
        avg_flight = self.life_prediction.ema_km_per_flight
        flight_allowed = rem >= avg_flight if avg_flight > 0 else rem > 0
        twin_state.flight_allowed = flight_allowed

        if not flight_allowed and not self._prev_flight_blocked:
            twin_state.add_notification(
                "fatigue_life_low", "critical",
                "Fatigue Life Low",
                "Estimated fatigue life is too low to allow for the next flight. "
                "Flying the plane is not advised.",
            )
        elif flight_allowed and self._prev_flight_blocked:
            twin_state.dismiss_notification("fatigue_life_low")
        self._prev_flight_blocked = not flight_allowed

    def _check_notifications(self, twin_state: TwinState) -> None:
        low_conf = self.state.low_confidence_frames >= self.config.confidence_frames_threshold
        if low_conf and not self._prev_low_confidence:
            bad = self.state.bad_channels or sorted(
                i for i, c in self.state.per_channel_low_frames.items()
                if c >= self.config.confidence_frames_threshold
            )
            if bad:
                names = [self._channel_names[i] for i in bad if i < len(self._channel_names)]
                msg = f"Sensor readings low confidence. Problematic channels: {', '.join(names)}."
            else:
                msg = "Sensor readings show low confidence."
            twin_state.add_notification(
                "maint_low_conf", "warning",
                "Maintenance Required",
                msg,
            )
        elif not low_conf and self._prev_low_confidence:
            twin_state.dismiss_notification("maint_low_conf")
        self._prev_low_confidence = low_conf
