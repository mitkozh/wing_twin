"""
FatigueTracker - Manages fatigue state accumulation, confidence monitoring,
and lifecycle notifications.
"""

from collections import deque
from typing import Optional

import numpy as np

from wing_twin.fatigue.fatigue import (
    FatigueState,
    accumulate_damage, accumulate_damage_at_nodes,
    update_confidence, sn_curve_for_material,
)
from wing_twin.config.fatigue import FatigueConfig
from wing_twin.fatigue.life_prediction import LifePredictionState
from wing_twin.engine.state import TwinState


class FatigueTracker:
    """Tracks fatigue accumulation, confidence, and notifications."""

    def __init__(
        self,
        config: FatigueConfig,
        initial_state: Optional[FatigueState] = None,
        initial_life_prediction: Optional[LifePredictionState] = None,
        tracker_snapshot: Optional[dict] = None,
    ):
        self.config = config
        self.state = initial_state or FatigueState()
        if tracker_snapshot:
            buf = tracker_snapshot.get("strain_buffer", [])
            self._strain_buffer: deque = deque(buf, maxlen=config.strain_buffer_size)
            self._cycles: list = list(tracker_snapshot.get("cycles", []))
            self._prev_low_confidence = tracker_snapshot.get("prev_low_confidence", False)
            self._prev_flight_blocked = tracker_snapshot.get("prev_flight_blocked", False)
        else:
            self._strain_buffer: deque = deque(maxlen=config.strain_buffer_size)
            self._cycles: list = []
            self._prev_low_confidence = False
            self._prev_flight_blocked = False
        self.life_prediction = initial_life_prediction or LifePredictionState(
            initial_remaining_km=config.initial_remaining_km,
        )

    @property
    def cycles(self) -> list:
        return self._cycles

    def clear_cycles(self) -> None:
        self._cycles.clear()

    def tracker_snapshot(self) -> dict:
        return {
            "strain_buffer": list(self._strain_buffer),
            "cycles": list(self._cycles),
            "prev_low_confidence": self._prev_low_confidence,
            "prev_flight_blocked": self._prev_flight_blocked,
        }

    def reset(self, target: str = "all") -> None:
        if target in ("damage", "all"):
            self.state = FatigueState()
            self._prev_low_confidence = False
            self._prev_flight_blocked = False
            self._cycles.clear()
        if target in ("strain", "all"):
            self._strain_buffer.clear()

    def process(
        self,
        strain_vector: np.ndarray,
        stress_field_pa: np.ndarray,
        expected_strain: np.ndarray,
        twin_state: TwinState,
        matrices,
        single_strain: float,
    ) -> None:
        """Process one frame of data through fatigue analysis.

        Updates twin_state with damage, confidence, node_damages,
        cycles_histogram, and notifications.
        """
        self._strain_buffer.append(single_strain)
        fatigue_cfg = self.config
        sn_curve = sn_curve_for_material(fatigue_cfg.material)

        # Confidence
        update_confidence(self.state, strain_vector, expected_strain, config=fatigue_cfg)

        # Per-node fatigue
        stress_mpa = stress_field_pa / 1e6
        accumulate_damage_at_nodes(stress_mpa, self.state, sn_curve=sn_curve, config=fatigue_cfg)

        twin_state.node_damages = dict(self.state.node_damages)

        # Global fatigue
        _, new_cycles = accumulate_damage(
            self._strain_buffer, self.state, sn_curve=sn_curve, config=fatigue_cfg,
        )
        self._cycles.extend(new_cycles)
        self._bin_cycles(new_cycles, fatigue_cfg.rainflow_range_bin_width, twin_state)

        # Damage tracking
        self._update_damage_metrics(twin_state)

        # Confidence to twin state
        twin_state.confidence = self.state.confidence

        # Notifications
        self._check_notifications(twin_state)

    def _bin_cycles(self, new_cycles, bin_width: float, twin_state: TwinState) -> None:
        for r, c in new_cycles:
            idx = int(r / bin_width)
            key = round((idx + 0.5) * bin_width, 1)
            twin_state.cycles_histogram[key] = twin_state.cycles_histogram.get(key, 0.0) + c

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
            twin_state.add_notification(
                "maint_low_conf", "warning",
                "Maintenance Required",
                "Sensor readings show low confidence.",
            )
        elif not low_conf and self._prev_low_confidence:
            twin_state.dismiss_notification("maint_low_conf")
        self._prev_low_confidence = low_conf
