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
)
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
        stress_field_pa: np.ndarray,
        expected_strain: np.ndarray,
        twin_state: TwinState,
        H: Optional[np.ndarray] = None,
        flight_phase: object = None,
        dead_channel_mask: Optional[np.ndarray] = None,
    ) -> tuple[bool, list[int]]:
        """Process one frame: confidence monitoring -> damage accumulation.

        The engine owns all FEA computation; this method only performs
        confidence tracking and fatigue accumulation.  Returns
        ``(has_new_bad_channels, all_bad_channels)`` so the engine can
        re-impute and recompute fields if needed.
        """
        fatigue_cfg = self.config
        sn_curve = sn_curve_for_material(fatigue_cfg.material)

        update_confidence(
            self.state, pre_impute_strain, expected_strain,
            config=fatigue_cfg, H=H,
            dead_channel_mask=dead_channel_mask,
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
        all_bad = sorted(set(low_conf_idxs))
        self.state.bad_channels = all_bad

        if flight_phase is not None and flight_phase.value != "on_ground":
            stress_mpa = stress_field_pa / 1e6
            accumulate_damage_at_nodes(
                stress_mpa, self.state, sn_curve=sn_curve, config=fatigue_cfg,
            )

        twin_state.damage.node_damages = dict(self.state.node_damages)
        twin_state.damage.confidence = self.state.confidence
        self._update_damage_metrics(twin_state)
        self._check_notifications(twin_state)
        return bool(new_bad), all_bad

    def reaccumulate_damage(
        self,
        stress_field_pa: np.ndarray,
        twin_state: TwinState,
        flight_phase: object = None,
    ) -> None:
        """Re-run damage accumulation with an updated stress field.

        Called by the engine after re-imputing channels and recomputing
        the FEA fields.  Skips confidence re-check since that was already
        done in the main ``process()`` call.
        """
        fatigue_cfg = self.config
        sn_curve = sn_curve_for_material(fatigue_cfg.material)

        if flight_phase is not None and flight_phase.value != "on_ground":
            stress_mpa = stress_field_pa / 1e6
            accumulate_damage_at_nodes(
                stress_mpa, self.state, sn_curve=sn_curve, config=fatigue_cfg,
            )

        twin_state.damage.node_damages = dict(self.state.node_damages)
        self._update_damage_metrics(twin_state)

    def _update_damage_metrics(self, twin_state: TwinState) -> None:
        if self.state.node_damages:
            values = list(self.state.node_damages.values())
            twin_state.damage.damage = max(values)
            sorted_vals = sorted(values, reverse=True)
            top_10_pct = sorted_vals[: max(1, len(sorted_vals) // 10)]
            twin_state.damage.avg_damage = (
                sum(top_10_pct) / len(top_10_pct) if top_10_pct else 0.0
            )
        else:
            twin_state.damage.damage = self.state.damage
            twin_state.damage.avg_damage = 0.0

        twin_state.structural.cycles_histogram = dict(self.state.cycles_histogram)

        rem = self.life_prediction.remaining_km
        avg_flight = self.life_prediction.ema_km_per_flight
        flight_allowed = rem >= avg_flight if avg_flight > 0 else rem > 0
        twin_state.flight.flight_allowed = flight_allowed

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
