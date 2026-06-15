"""
Centralised sensor channel state and imputation lifecycle.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

from wing_twin.config.fatigue import FatigueConfig

logger = logging.getLogger(__name__)


def _impute(strain_vec: np.ndarray, bad_indices: list[int], H: np.ndarray) -> np.ndarray:
    """Replace bad channels with H @ F where F solves the good-channel system."""
    result = strain_vec.copy()
    if not bad_indices:
        return result

    mask = np.ones(H.shape[0], dtype=bool)
    for k in bad_indices:
        mask[k] = False

    H_reduced = H[mask, :]
    strain_reduced = strain_vec[mask]

    if H_reduced.shape[0] < H_reduced.shape[1]:
        logger.warning(
            "Underdetermined system: %d gauges remain for %d force modes",
            H_reduced.shape[0], H_reduced.shape[1],
        )

    F, _, _, _ = np.linalg.lstsq(H_reduced, strain_reduced, rcond=None)
    for k in bad_indices:
        result[k] = float(H[k, :] @ F)

    return result


def _safe_ratio(num: float, den: float, eps: float = 1e-12) -> float:
    if abs(den) < eps:
        return 0.0
    return num / den


def _compute_model_fit(
    observed_strain: np.ndarray,
    expected_strain: np.ndarray,
    s_curve_threshold: float,
    dead_mask: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Per-channel residual and S-curve confidence.

    Returns (residual, confidence, score).
    """
    noise_floor = 1e-10
    denom = np.maximum(np.abs(expected_strain), noise_floor)
    residual = np.abs(observed_strain - expected_strain) / denom
    confidence = 100.0 / (1.0 + (residual / s_curve_threshold) ** 2)

    if dead_mask is not None:
        residual = residual.copy()
        confidence = confidence.copy()
        residual[dead_mask] = 0.0
        confidence[dead_mask] = 100.0
        alive = int(np.sum(~dead_mask))
        score = float(np.sum(confidence[~dead_mask]) / max(alive, 1))
    else:
        score = float(np.mean(confidence))

    return residual, confidence, score


def _group_consistency_score(
    observed_strain: np.ndarray,
    expected_ratios: dict,
    dead_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Per-group (root/middle/tip) consistency scores, 0–100."""
    groups = [(0, "root"), (3, "middle"), (6, "tip")]
    scores = np.zeros(3, dtype=np.float64)

    for gi, (start, name) in enumerate(groups):
        if dead_mask is not None and np.any(dead_mask[start:start + 3]):
            scores[gi] = 100.0
            continue

        chunk = observed_strain[start:start + 3]
        e = expected_ratios.get(name)
        if e is None or np.any(np.isnan(chunk)):
            scores[gi] = 100.0
            continue

        if max(np.abs(chunk)) < 1e-10:
            scores[gi] = 100.0
            continue

        obs_0, obs_45, obs_90 = chunk[0], chunk[1], chunk[2]
        sign_ok = sum(
            1 for obs, key in [(obs_0, "h0"), (obs_45, "h45"), (obs_90, "h90")]
            if abs(obs) > 1e-10 and abs(e[key]) > 1e-10 and np.sign(obs) == np.sign(e[key])
        )
        ratio_errors = []
        for r_meas, key in [
            (_safe_ratio(obs_45, obs_0), "r45_0"),
            (_safe_ratio(obs_90, obs_0), "r90_0"),
            (_safe_ratio(obs_45, obs_90), "r45_90"),
        ]:
            exp_val = e[key]
            if abs(exp_val) > 1e-10 and abs(r_meas) > 1e-10:
                ratio_errors.append(abs(r_meas - exp_val) / abs(exp_val))

        ratio_score = 100.0 * np.exp(-2.0 * np.mean(ratio_errors)) if ratio_errors else 100.0
        scores[gi] = 0.4 * (sign_ok / 3.0) * 100.0 + 0.6 * ratio_score

    return scores


def _force_consistency_score(
    observed_strain: np.ndarray,
    H: np.ndarray,
    dead_mask: np.ndarray | None = None,
) -> float:
    """Cross-validation score (0–100) across different gauge subsets."""
    groups = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8))
    eps = 1e-10

    if dead_mask is not None and dead_mask.any():
        groups = tuple(
            idxs for idxs in groups if not any(dead_mask[i] for i in idxs)
        )

    F_groups = []
    for idxs in groups:
        if not idxs:
            continue
        H_sub = H[list(idxs), 0]
        obs_sub = observed_strain[list(idxs)]
        H2 = float(H_sub @ H_sub)
        if H2 > eps:
            F_g = float(H_sub @ obs_sub) / H2
            if abs(F_g) > eps:
                F_groups.append(F_g)

    if len(F_groups) < 2:
        return 100.0

    F_ref = float(np.median(F_groups))
    if abs(F_ref) < eps:
        return 100.0

    deviations = [abs(f - F_ref) / abs(F_ref) for f in F_groups]
    return float(np.clip(100.0 * np.exp(-3.0 * np.mean(deviations)), 0.0, 100.0))


def _compute_group_consistency(
    observed_strain: np.ndarray,
    H: Optional[np.ndarray],
    expected_ratios: dict,
    expected_norm: float,
    dead_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, float]:
    """Group ratio consistency, or 100 if no load / no H."""
    noise_floor = 1e-10
    if H is not None and expected_norm > noise_floor * 10:
        scores = _group_consistency_score(observed_strain, expected_ratios, dead_mask)
        return scores, float(np.mean(scores))
    return np.full(3, 100.0, dtype=np.float64), 100.0


def _compute_group_expected_ratios(H: np.ndarray) -> dict:
    """Pre-compute expected strain ratios for the 3-gauge groups."""
    groups = {0: "root", 3: "middle", 6: "tip"}
    ratios = {}
    for start, name in groups.items():
        h0 = float(H[start, 0])
        h45 = float(H[start + 1, 0])
        h90 = float(H[start + 2, 0])
        ratios[name] = {
            "h0": h0, "h45": h45, "h90": h90,
            "r45_0": _safe_ratio(h45, h0),
            "r90_0": _safe_ratio(h90, h0),
            "r45_90": _safe_ratio(h45, h90),
        }
    return ratios


@dataclass
class ChannelState:
    """Complete per-channel status for a single frame."""
    index: int
    name: str

    is_hardware_dead: bool = False
    is_saturated: bool = False
    is_hardware_saturated: bool = False
    is_low_confidence: bool = False

    raw_strain: float = 0.0
    imputed_strain: float = 0.0

    residual: float = 0.0
    confidence: float = 100.0
    low_confidence_frames: int = 0


class ChannelManager:
    """Single source of truth for all per-channel state and imputation.

    Usage::

        mgr = ChannelManager(names)
        mgr.ingest(strain, saturated_flags, dead_mask, threshold)
        clean = mgr.impute(H)
        has_new, all_bad = mgr.update_confidence(expected, config, H, dead_np)
        if has_new:
            clean = mgr.reimpute(H)
        events = mgr.to_health_events()
    """

    def __init__(self, channel_names: list[str]):
        self._channels = [ChannelState(index=i, name=n) for i, n in enumerate(channel_names)]
        self._pre_impute_buffer: Optional[np.ndarray] = None
        self._prev_low_set: set[int] = set()
        self._health_prev_bad: set[int] = set()

        self.confidence: float = 100.0
        self.filtered_residual: float = 0.0
        self.low_confidence_frames: int = 0

        self.group_consistency: np.ndarray = np.array([], dtype=np.float64)
        self._group_expected_ratios: dict = {}


    def ingest(
        self,
        strain_vec: np.ndarray,
        saturated_flags: Optional[list[bool]],
        dead_mask: list[bool],
        saturation_threshold: float,
    ) -> None:
        self._pre_impute_buffer = strain_vec.copy()
        for i, ch in enumerate(self._channels):
            ch.raw_strain = float(strain_vec[i])
            ch.is_hardware_dead = bool(dead_mask[i])
            ch.is_saturated = bool(abs(strain_vec[i]) > saturation_threshold)
            ch.is_hardware_saturated = bool(saturated_flags[i]) if saturated_flags else False

    def impute(self, H: np.ndarray) -> np.ndarray:
        """First-pass: impute saturated / dead channels only."""
        return self._do_impute(H, self._saturated_or_dead_indices())

    def reimpute(self, H: np.ndarray) -> np.ndarray:
        """Second-pass: impute ALL bad channels (incl. low-confidence)."""
        return self._do_impute(H, self.bad_indices())

    def _do_impute(self, H: np.ndarray, bad: list[int]) -> np.ndarray:
        result = _impute(self._pre_impute_buffer.copy(), bad, H)
        for i, ch in enumerate(self._channels):
            ch.imputed_strain = float(result[i])
        return result

    def update_confidence(
        self,
        expected_strain: np.ndarray,
        config: FatigueConfig,
        H: np.ndarray,
        dead_mask_np: Optional[np.ndarray],
    ) -> tuple[bool, list[int]]:
        """Per-channel confidence from expected vs. observed (pre-impute) strain.

        Returns ``(has_new_bad_channels, all_bad_indices)``.
        """
        observed = self._pre_impute_buffer
        if observed is None:
            return False, []

        noise_floor = 1e-10
        expected_norm = float(np.linalg.norm(expected_strain))

        if expected_norm < config.low_load_threshold:
            self.confidence = 100.0
            self.low_confidence_frames = 0
            self._reset_per_channel_confidence()
            self._prev_low_set = set()
            return False, self.bad_indices()

        if H is not None and not self._group_expected_ratios:
            self._group_expected_ratios = _compute_group_expected_ratios(H)

        # 1  Model-fit residual
        residual, per_channel_conf, model_score = _compute_model_fit(
            observed, expected_strain, config.s_curve_threshold, dead_mask_np,
        )
        for i, ch in enumerate(self._channels):
            ch.residual = float(residual[i])
            ch.confidence = float(per_channel_conf[i])

        # 2  Group consistency
        group_scores, group_score = _compute_group_consistency(
            observed, H, self._group_expected_ratios, expected_norm, dead_mask_np,
        )
        self.group_consistency = group_scores.copy()

        # 3  Force consistency
        force_score = (
            _force_consistency_score(observed, H, dead_mask_np)
            if H is not None else 100.0
        )

        # 4  Blended overall confidence
        raw_residual = float(
            np.linalg.norm(observed - expected_strain)
        ) / max(expected_norm, noise_floor)

        if config.ema_alpha < 1.0:
            self.filtered_residual = (
                config.ema_alpha * raw_residual
                + (1.0 - config.ema_alpha) * self.filtered_residual
            )
        else:
            self.filtered_residual = raw_residual

        self.confidence = float(np.clip(
            config.confidence_weight_model * model_score
            + config.confidence_weight_group * group_score
            + config.confidence_weight_force * force_score,
            0.0, 100.0,
        ))

        # 5  Low-confidence frame tracking
        self.low_confidence_frames = (
            self.low_confidence_frames + 1
            if self.confidence < config.confidence_threshold
            else 0
        )

        dead_mask = dead_mask_np if dead_mask_np is not None else np.zeros(len(self._channels), dtype=bool)
        for i, ch in enumerate(self._channels):
            if not dead_mask[i]:
                if per_channel_conf[i] < config.confidence_threshold:
                    ch.low_confidence_frames += 1
                    ch.is_low_confidence = True
                else:
                    ch.low_confidence_frames = 0
                    ch.is_low_confidence = False

        # 6  Detect new-bad transition
        current_low_set = set(self._low_confidence_indices())
        has_new = bool(current_low_set - self._prev_low_set)
        self._prev_low_set = current_low_set

        return has_new, self.bad_indices()

    def reset_confidence(self) -> None:
        self.confidence = 100.0
        self.filtered_residual = 0.0
        self.low_confidence_frames = 0
        self._prev_low_set = set()
        self._health_prev_bad = set()
        self.group_consistency = np.array([], dtype=np.float64)
        self._group_expected_ratios = {}
        self._reset_per_channel_confidence()


    def bad_indices(self) -> list[int]:
        """Union of ALL problem channels."""
        return sorted(
            i for i, ch in enumerate(self._channels)
            if ch.is_saturated or ch.is_hardware_saturated or ch.is_hardware_dead or ch.is_low_confidence
        )

    @property
    def n_channels(self) -> int:
        return len(self._channels)

    def channel_state(self, index: int) -> ChannelState:
        return self._channels[index]


    def to_health_events(self) -> list[dict]:
        """Entry/recovery events since the last call."""
        current = set(self._low_confidence_indices())
        events = []
        for i in sorted(current - self._health_prev_bad):
            events.append({"channel": i, "name": self._channels[i].name, "type": "bad"})
        for i in sorted(self._health_prev_bad - current):
            events.append({"channel": i, "name": self._channels[i].name, "type": "recovered"})
        self._health_prev_bad = current
        return events

    def log_low_confidence_channels(self, config: FatigueConfig) -> None:
        """Log channels that just crossed the sustained low-confidence threshold."""
        new_low = sorted(
            i for i, ch in enumerate(self._channels)
            if ch.low_confidence_frames == config.confidence_frames_threshold
        )
        for i in new_low:
            logger.warning(
                "Sustained low confidence on %s: conf=%.1f%% resid=%.4f",
                self._channels[i].name, self._channels[i].confidence, self._channels[i].residual,
            )


    def to_dict(self) -> dict:
        return {
            "confidence": self.confidence,
            "filtered_residual": self.filtered_residual,
            "low_confidence_frames": self.low_confidence_frames,
            "per_channel_residual": [ch.residual for ch in self._channels],
            "per_channel_confidence": [ch.confidence for ch in self._channels],
            "bad_channels": self._low_confidence_indices(),
            "per_channel_low_frames": {
                str(ch.index): ch.low_confidence_frames
                for ch in self._channels if ch.low_confidence_frames > 0
            },
            "group_consistency": (
                self.group_consistency.tolist() if self.group_consistency.size > 0 else []
            ),
            "group_expected_ratios": self._group_expected_ratios,
        }

    @staticmethod
    def from_dict(data: dict, channel_names: list[str]) -> "ChannelManager":
        mgr = ChannelManager(channel_names)
        mgr.confidence = data.get("confidence", 100.0)
        mgr.filtered_residual = data.get("filtered_residual", 0.0)
        mgr.low_confidence_frames = data.get("low_confidence_frames", 0)

        residuals = data.get("per_channel_residual", [])
        confs = data.get("per_channel_confidence", [])
        low_frames = data.get("per_channel_low_frames", {})
        bad = set(data.get("bad_channels", []))

        for i, ch in enumerate(mgr._channels):
            if i < len(residuals):
                ch.residual = residuals[i]
            if i < len(confs):
                ch.confidence = confs[i]
            ch.low_confidence_frames = low_frames.get(str(i), 0)
            ch.is_low_confidence = i in bad

        mgr._prev_low_set = set(bad)
        mgr._health_prev_bad = set(bad)

        gc = data.get("group_consistency", [])
        if gc:
            mgr.group_consistency = np.array(gc, dtype=np.float64)
        mgr._group_expected_ratios = data.get("group_expected_ratios", {})

        return mgr


    def _saturated_or_dead_indices(self) -> list[int]:
        return sorted(
            i for i, ch in enumerate(self._channels)
            if ch.is_saturated or ch.is_hardware_saturated or ch.is_hardware_dead
        )

    def _low_confidence_indices(self) -> list[int]:
        return [i for i, ch in enumerate(self._channels) if ch.is_low_confidence]

    def _reset_per_channel_confidence(self) -> None:
        for ch in self._channels:
            ch.residual = 0.0
            ch.confidence = 100.0
            ch.is_low_confidence = False
            ch.low_confidence_frames = 0
