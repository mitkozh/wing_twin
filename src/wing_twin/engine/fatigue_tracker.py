"""
FatigueTracker - per-node fatigue accumulation and fatigue-life notifications.

Sensor confidence monitoring has moved to ``ChannelManager``.
"""

from typing import Optional

import numpy as np

from wing_twin.fatigue.fatigue import (
    FatigueState,
    accumulate_damage_at_nodes,
    sn_curve_for_material,
)
from wing_twin.config.fatigue import FatigueConfig
from wing_twin.fatigue.life_prediction import LifePredictionState
from wing_twin.engine.state import TwinState


class FatigueTracker:
    """Tracks per-node fatigue accumulation and fatigue-life notifications."""

    def __init__(
        self,
        config: FatigueConfig,
        initial_state: Optional[FatigueState] = None,
        initial_life_prediction: Optional[LifePredictionState] = None,
        tracker_snapshot: Optional[dict] = None,
    ):
        self.config = config
        self.state = initial_state or FatigueState()
        self._smoothed_damage = (
            tracker_snapshot.get("smoothed_damage", 0.0)
            if tracker_snapshot else 0.0
        )
        self._prev_flight_blocked = (
            tracker_snapshot.get("prev_flight_blocked", False)
            if tracker_snapshot else False
        )
        self.life_prediction = initial_life_prediction or LifePredictionState(
            initial_remaining_km=config.initial_remaining_km,
        )

    def tracker_snapshot(self) -> dict:
        return {
            "prev_flight_blocked": self._prev_flight_blocked,
            "smoothed_damage": self._smoothed_damage,
        }

    def reset(self, target: str = "all") -> None:
        if target in ("damage", "all"):
            self.state = FatigueState()
            self._smoothed_damage = 0.0
            self._prev_flight_blocked = False

    def accumulate_damage(
        self,
        stress_field_pa: np.ndarray,
        twin_state: TwinState,
        flight_phase: object = None,
    ) -> None:
        """Accumulate fatigue damage for one frame."""
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
            raw_damage = max(values)
            sorted_vals = sorted(values, reverse=True)
            top_10_pct = sorted_vals[: max(1, len(sorted_vals) // 10)]
            twin_state.damage.avg_damage = (
                sum(top_10_pct) / len(top_10_pct) if top_10_pct else 0.0
            )
        else:
            raw_damage = self.state.damage
            twin_state.damage.avg_damage = 0.0

        alpha = self.config.damage_smoothing_alpha
        if alpha > 0:
            self._smoothed_damage = alpha * raw_damage + (1.0 - alpha) * self._smoothed_damage
            twin_state.damage.damage = self._smoothed_damage
        else:
            twin_state.damage.damage = raw_damage

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
