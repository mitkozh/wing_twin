"""
Fatigue analysis module for digital twin.

Provides per-node rainflow cycle counting, Miner's Rule damage accumulation
using the FEA stress field, and 3-component sensor confidence monitoring.

Units:
  - Stress: MPa
  - Damage: dimensionless (0.0 to 1.0)
  - Confidence: percentage (0 to 100)
"""

import concurrent.futures
import logging
import threading
import numpy as np
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Tuple

from py_fatigue import CycleCount
from py_fatigue.material.sn_curve import SNCurve
from py_fatigue.damage.stress_life import calc_pm

from wing_twin.config.fatigue import FatigueConfig

logger = logging.getLogger(__name__)


@dataclass
class FatigueState:
    damage: float = 0.0
    confidence: float = 100.0
    filtered_residual: float = 0.0
    low_confidence_frames: int = 0
    node_buffers: dict = field(default_factory=dict)
    node_damages: dict = field(default_factory=dict)
    node_res_sigs: dict = field(default_factory=dict)
    per_channel_residual: np.ndarray = field(default_factory=lambda: np.array([], dtype=np.float64))
    per_channel_confidence: np.ndarray = field(default_factory=lambda: np.array([], dtype=np.float64))
    bad_channels: list[int] = field(default_factory=list)
    per_channel_low_frames: dict[int, int] = field(default_factory=dict)
    cycles_histogram: dict[float, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # Group cross-validation (3 groups: root, middle, tip)
    group_consistency: np.ndarray = field(
        default_factory=lambda: np.array([], dtype=np.float64)
    )
    # Expected strain ratios per group, computed from H matrix
    group_expected_ratios: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "damage": self.damage,
            "confidence": self.confidence,
            "filtered_residual": self.filtered_residual,
            "low_confidence_frames": self.low_confidence_frames,
            "node_damages": {str(k): v for k, v in self.node_damages.items()},
            "node_buffers": {
                str(k): list(v) for k, v in self.node_buffers.items()
            },
            "node_res_sigs": {
                str(k): v for k, v in self.node_res_sigs.items()
            },
            "per_channel_residual": self.per_channel_residual.tolist(),
            "per_channel_confidence": self.per_channel_confidence.tolist(),
            "bad_channels": self.bad_channels,
            "per_channel_low_frames": dict(self.per_channel_low_frames),
        }

    @staticmethod
    def from_dict(data: dict) -> "FatigueState":
        state = FatigueState()
        state.damage = data["damage"]
        state.confidence = data["confidence"]
        state.filtered_residual = data["filtered_residual"]
        state.low_confidence_frames = data["low_confidence_frames"]
        state.node_damages = {int(k): v for k, v in data["node_damages"].items()}
        node_buffers_raw = data["node_buffers"]
        node_res_sigs_raw = data["node_res_sigs"]
        all_node_keys = set(state.node_damages) | {
            int(k) for k in node_buffers_raw
        } | {int(k) for k in node_res_sigs_raw}
        for node_idx in all_node_keys:
            buf_data = node_buffers_raw.get(str(node_idx), [])
            state.node_buffers[node_idx] = deque(buf_data, maxlen=500)
            state.node_res_sigs[node_idx] = node_res_sigs_raw.get(str(node_idx), [])
        pcr = data.get("per_channel_residual", [])
        state.per_channel_residual = np.array(pcr, dtype=np.float64) if pcr else np.array([], dtype=np.float64)
        pcc = data.get("per_channel_confidence", [])
        state.per_channel_confidence = np.array(pcc, dtype=np.float64) if pcc else np.array([], dtype=np.float64)
        state.bad_channels = data.get("bad_channels", [])
        pclf = data.get("per_channel_low_frames", {})
        state.per_channel_low_frames = {int(k): int(v) for k, v in pclf.items()}
        return state


def sn_curve_for_material(material: str = "aluminum") -> SNCurve:
    curves = {
        "aluminum": SNCurve(slope=4.5, intercept=14.9, endurance=1e7),
        "steel": SNCurve(slope=5.0, intercept=17.0, endurance=1e7),
        "demo": SNCurve(slope=3.0, intercept=8.0, endurance=1e6),
    }
    return curves.get(material.lower(), curves["aluminum"])


def _safe_ratio(num: float, den: float, eps: float = 1e-12) -> float:
    """Compute num/den with sign preservation and division-by-zero guard."""
    if abs(den) < eps:
        return 0.0
    return num / den


def compute_group_expected_ratios(H: np.ndarray) -> dict:
    """Pre-compute expected pairwise strain ratios within each 3-gauge group.

    Returns a dict keyed by section name ('root', 'middle', 'tip') with
    the expected ratios r45_0, r90_0, r45_90 and the raw H matrix entries.
    """
    groups = {0: "root", 3: "middle", 6: "tip"}
    ratios = {}
    for start, name in groups.items():
        h0 = float(H[start, 0])
        h45 = float(H[start + 1, 0])
        h90 = float(H[start + 2, 0])
        ratios[name] = {
            "h0": h0,
            "h45": h45,
            "h90": h90,
            "r45_0": _safe_ratio(h45, h0),
            "r90_0": _safe_ratio(h90, h0),
            "r45_90": _safe_ratio(h45, h90),
        }
    return ratios


def _group_consistency_score(
    observed_strain: np.ndarray,
    expected_ratios: dict,
) -> np.ndarray:
    """Compute per-group consistency scores (0–100) for the 3 section groups.

    Checks that sign and pairwise strain ratios within each 3-gauge triplet
    match the expected pattern from the FEA model (H matrix).  This check is
    force-magnitude-independent, catching drift or failure in individual gauges
    even when the load is small.
    """
    groups = [(0, "root"), (3, "middle"), (6, "tip")]
    scores = np.zeros(3, dtype=np.float64)

    for gi, (start, name) in enumerate(groups):
        chunk = observed_strain[start:start + 3]
        e = expected_ratios.get(name)
        if e is None or np.any(np.isnan(chunk)):
            scores[gi] = 100.0
            continue

        obs_0, obs_45, obs_90 = chunk[0], chunk[1], chunk[2]

        if max(np.abs(chunk)) < 1e-10:
            scores[gi] = 100.0
            continue

        sign_ok = 0
        for obs_val, exp_key in [(obs_0, "h0"), (obs_45, "h45"), (obs_90, "h90")]:
            if abs(obs_val) > 1e-10 and abs(e[exp_key]) > 1e-10:
                if np.sign(obs_val) == np.sign(e[exp_key]):
                    sign_ok += 1
        sign_score = sign_ok / 3.0

        r45_0_meas = _safe_ratio(obs_45, obs_0)
        r90_0_meas = _safe_ratio(obs_90, obs_0)
        r45_90_meas = _safe_ratio(obs_45, obs_90)

        ratio_errors = []
        for r_meas, exp_key in [
            (r45_0_meas, "r45_0"),
            (r90_0_meas, "r90_0"),
            (r45_90_meas, "r45_90"),
        ]:
            exp_val = e[exp_key]
            if abs(exp_val) > 1e-10 and abs(r_meas) > 1e-10:
                rel_err = abs(r_meas - exp_val) / abs(exp_val)
                ratio_errors.append(rel_err)

        if ratio_errors:
            ratio_score = 100.0 * np.exp(-2.0 * np.mean(ratio_errors))
        else:
            ratio_score = 100.0

        scores[gi] = 0.4 * sign_score * 100.0 + 0.6 * ratio_score

    return scores


def _force_consistency_score(
    observed_strain: np.ndarray,
    H: np.ndarray,
    eps: float = 1e-10,
    groups: tuple = (
        (0, 1, 2), (3, 4, 5), (6, 7, 8),
        (0, 3, 6), (1, 4, 7), (2, 5, 8),
    ),
) -> float:
    """Score (0–100) how consistently different gauge subsets estimate F."""
    F_groups = []
    for idxs in groups:
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
    mean_dev = float(np.mean(deviations))

    return float(np.clip(100.0 * np.exp(-3.0 * mean_dev), 0.0, 100.0))


def _compute_model_fit(
    observed_strain: np.ndarray,
    expected_strain: np.ndarray,
    noise_floor: float = 1e-10,
    s_curve_threshold: float = 0.15,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Per-channel residual and S-curve confidence from |obs − exp| / |exp|.

    Returns (per_channel_residual, per_channel_confidence, model_score).
    """
    denom = np.maximum(np.abs(expected_strain), noise_floor)
    residual = np.abs(observed_strain - expected_strain) / denom
    confidence = 100.0 / (1.0 + (residual / s_curve_threshold) ** 2)
    score = float(np.mean(confidence))
    return residual, confidence, score


def _compute_group_consistency(
    observed_strain: np.ndarray,
    H: Optional[np.ndarray],
    group_expected_ratios: dict,
    expected_norm: float,
    noise_floor: float = 1e-10,
) -> tuple[np.ndarray, float]:
    """Per-group ratio consistency score, or 100 if no load / no H."""
    if H is not None and expected_norm > noise_floor * 10:
        scores = _group_consistency_score(observed_strain, group_expected_ratios)
        return scores, float(np.mean(scores))
    return np.full(3, 100.0, dtype=np.float64), 100.0


def _track_low_confidence_frames(
    state: FatigueState,
    per_channel_confidence: np.ndarray,
    overall_confidence: float,
    threshold: float,
) -> None:
    """Update per-channel and overall low-confidence frame counters."""
    if overall_confidence < threshold:
        state.low_confidence_frames += 1
    else:
        state.low_confidence_frames = 0

    for i in range(len(per_channel_confidence)):
        if per_channel_confidence[i] < threshold:
            state.per_channel_low_frames[i] = state.per_channel_low_frames.get(i, 0) + 1
        else:
            state.per_channel_low_frames[i] = 0


def update_confidence(
    state: FatigueState,
    observed_strain: np.ndarray,
    expected_strain: np.ndarray,
    config: Optional[FatigueConfig] = None,
    H: Optional[np.ndarray] = None,
) -> float:
    """Update per-channel and overall confidence from observed vs expected strain.
    Returns the overall confidence (0–100).
    """
    if config is None:
        config = FatigueConfig()

    noise_floor = 1e-10
    expected_norm = float(np.linalg.norm(expected_strain))
    if expected_norm < config.low_load_threshold:
        state.confidence = 100.0
        state.low_confidence_frames = 0
        state.per_channel_low_frames = {}
        return state.confidence

    # Lazy-compute group ratios from H on first call
    if H is not None and not state.group_expected_ratios:
        state.group_expected_ratios = compute_group_expected_ratios(H)

    # 1  Model-fit residual
    residual, per_channel_conf, model_score = _compute_model_fit(
        observed_strain, expected_strain, noise_floor,
    )
    state.per_channel_residual = residual.copy()
    state.per_channel_confidence = per_channel_conf.copy()

    # 2  Group ratio consistency
    group_scores, group_score = _compute_group_consistency(
        observed_strain, H, state.group_expected_ratios,
        expected_norm, noise_floor,
    )
    state.group_consistency = group_scores.copy()

    # 3  Force-estimate cross-validation
    force_score = (
        _force_consistency_score(observed_strain, H)
        if H is not None else 100.0
    )

    # 4  Blended overall confidence
    state.filtered_residual = float(
        np.linalg.norm(observed_strain - expected_strain)
    ) / max(expected_norm, noise_floor)
    state.confidence = float(np.clip(
        0.30 * model_score + 0.30 * group_score + 0.40 * force_score,
        0.0, 100.0,
    ))

    # 5  Low-confidence frame tracking
    _track_low_confidence_frames(
        state, per_channel_conf, state.confidence,
        config.confidence_threshold,
    )

    return state.confidence


def log_low_confidence_channels(
    state: FatigueState,
    channel_names: Optional[list[str]],
    config: Optional[FatigueConfig] = None,
) -> None:
    if config is None:
        config = FatigueConfig()
    if state.per_channel_confidence.size == 0:
        return

    new_low = sorted(
        i for i, c in state.per_channel_low_frames.items()
        if c == config.confidence_frames_threshold
    )
    if not new_low:
        return

    names = channel_names or [str(i) for i in range(state.per_channel_confidence.size)]
    for i in new_low:
        logger.warning(
            "Sustained low confidence on %s: conf=%.1f%% resid=%.4f",
            names[i] if i < len(names) else str(i),
            state.per_channel_confidence[i],
            state.per_channel_residual[i],
        )


def _warmup_numba() -> None:
    import numba as _nb
    _nb.config.DISABLE_JIT = 0
    sn = sn_curve_for_material("demo")
    dummy_sr = np.array([10.0, 20.0, 30.0, 50.0, 100.0], dtype=np.float64)
    dummy_cc = np.array([1.0, 0.5, 0.2, 0.1, 0.05], dtype=np.float64)
    try:
        calc_pm(dummy_sr, dummy_cc, sn)
    except Exception:
        pass
    try:
        _ = CycleCount.from_timeseries(
            np.array([0.0, 1.0, -1.0, 0.5, -0.5, 0.0], dtype=np.float64),
            unit="MPa", range_bin_width=2.0,
        )
    except Exception:
        pass


_warmup_numba()


def set_random_seed(seed: Optional[int] = None) -> None:
    if seed is not None:
        np.random.seed(seed)


def identify_critical_nodes(
    stress_field: np.ndarray,
    config: Optional[FatigueConfig] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    if config is None:
        config = FatigueConfig()

    stress_field = np.asarray(stress_field, dtype=np.float64)
    if stress_field.size == 0:
        return np.array([], dtype=int), np.array([])

    abs_stress = np.abs(stress_field)
    above_threshold = np.where(abs_stress >= config.critical_stress_threshold)[0]

    if len(above_threshold) > 0:
        critical_indices = above_threshold
    else:
        p = np.percentile(abs_stress, config.critical_node_percentile)
        critical_indices = np.where(abs_stress >= p)[0]

    if len(critical_indices) > config.max_critical_nodes:
        top_indices = np.argsort(abs_stress[critical_indices])[-config.max_critical_nodes:]
        critical_indices = critical_indices[top_indices]

    critical_stresses = abs_stress[critical_indices]
    return critical_indices, critical_stresses


def _process_single_node(
    node_idx: int,
    stress_val: float,
    state: FatigueState,
    sn_curve: SNCurve,
    config: FatigueConfig,
) -> float:
    """Rainflow + Miner for one critical node. Returns incremental damage."""
    with state._lock:
        if node_idx not in state.node_buffers:
            state.node_buffers[node_idx] = deque(maxlen=config.node_buffer_size)
            state.node_res_sigs[node_idx] = []
            if node_idx not in state.node_damages:
                state.node_damages[node_idx] = 0.0

        state.node_buffers[node_idx].append(stress_val)

        if len(state.node_buffers[node_idx]) < config.min_buffer_size:
            return 0.0

        pending = list(state.node_res_sigs[node_idx])
        state.node_res_sigs[node_idx] = []

        stress_arr = np.array(state.node_buffers[node_idx], dtype=np.float64)
        state.node_buffers[node_idx].clear()

    combined = np.concatenate([np.array(pending), stress_arr]) if pending else stress_arr

    try:
        cc = CycleCount.from_timeseries(
            combined, unit="MPa", range_bin_width=config.rainflow_range_bin_width,
        )
    except ValueError:
        with state._lock:
            state.node_res_sigs[node_idx] = []
        return 0.0

    result_dict = cc.as_dict()
    with state._lock:
        state.node_res_sigs[node_idx] = result_dict.get("res_sig", [])
        bin_width = config.rainflow_range_bin_width
        for sr, cnt in zip(cc.stress_range, cc.count_cycle):
            bin_key = round(sr / bin_width) * bin_width
            state.cycles_histogram[bin_key] = state.cycles_histogram.get(bin_key, 0.0) + cnt

    if len(cc.stress_range) == 0:
        return 0.0

    damage_per_bin = calc_pm(cc.stress_range, cc.count_cycle, sn_curve)
    node_damage = float(np.sum(damage_per_bin))
    with state._lock:
        state.node_damages[node_idx] = min(state.node_damages[node_idx] + node_damage, 1.0)
    return node_damage


def accumulate_damage_at_nodes(
    stress_field: np.ndarray,
    state: FatigueState,
    sn_curve: Optional[SNCurve] = None,
    config: Optional[FatigueConfig] = None,
) -> Tuple[float, int]:
    if config is None:
        config = FatigueConfig()

    if stress_field.size == 0:
        return 0.0, 0

    critical_indices, critical_stresses = identify_critical_nodes(stress_field, config)

    if len(critical_indices) == 0:
        return 0.0, 0

    if sn_curve is None:
        sn_curve = sn_curve_for_material("demo")

    total_damage = 0.0
    n_workers = min(4, len(critical_indices))

    if n_workers <= 1:
        for node_idx, stress_val in zip(critical_indices, critical_stresses):
            total_damage += _process_single_node(
                int(node_idx), float(stress_val), state, sn_curve, config,
            )
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as executor:
            futures = [
                executor.submit(
                    _process_single_node,
                    int(node_idx), float(stress_val), state, sn_curve, config,
                )
                for node_idx, stress_val in zip(critical_indices, critical_stresses)
            ]
            for future in concurrent.futures.as_completed(futures):
                total_damage += future.result()

    return total_damage, len(critical_indices)
