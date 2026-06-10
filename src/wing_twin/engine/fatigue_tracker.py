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
    update_confidence, sn_curve_for_material,
    warmup_numba,
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

    def process(
        self,
        strain_vector: np.ndarray,
        stress_field_pa: np.ndarray,
        expected_strain: np.ndarray,
        twin_state: TwinState,
    ) -> None:
        """Process one frame of data through per-node fatigue analysis.

        Updates twin_state with damage, confidence, node_damages,
        and notifications.
        """
        fatigue_cfg = self.config
        sn_curve = sn_curve_for_material(fatigue_cfg.material)

        update_confidence(
            self.state, strain_vector, expected_strain,
            config=fatigue_cfg,
        )

        log_low_confidence_channels(
            self.state, self._channel_names, config=fatigue_cfg,
        )

        # Per-node fatigue using FEA stress field
        stress_mpa = stress_field_pa / 1e6
        accumulate_damage_at_nodes(stress_mpa, self.state, sn_curve=sn_curve, config=fatigue_cfg)

        twin_state.node_damages = dict(self.state.node_damages)

        # Damage tracking
        self._update_damage_metrics(twin_state)

        # Confidence to twin state
        twin_state.confidence = self.state.confidence

        # Notifications
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
            bad = self.state.saturated_channels or sorted(
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
