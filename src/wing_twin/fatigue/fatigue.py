"""
Fatigue analysis module for digital twin.

Provides per-node rainflow cycle counting, Miner's Rule damage accumulation
using the FEA stress field, and confidence monitoring via EMA-filtered residuals.

Units:
  - Stress: MPa
  - Damage: dimensionless (0.0 to 1.0)
  - Confidence: percentage (0 to 100)
"""

import concurrent.futures
import logging
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


def update_confidence(
    state: FatigueState,
    observed_strain: np.ndarray,
    expected_strain: np.ndarray,
    config: Optional[FatigueConfig] = None,
) -> float:
    if config is None:
        config = FatigueConfig()

    expected_norm = float(np.linalg.norm(expected_strain))
    if expected_norm < 1e-10:
        return state.confidence

    diff = np.abs(observed_strain - expected_strain)
    denom = np.maximum(np.abs(expected_strain), 1e-12)
    per_channel = diff / denom
    state.per_channel_residual = per_channel.copy()
    state.per_channel_confidence = np.clip(100.0 * (1.0 - per_channel), 0.0, 100.0)

    global_residual = float(np.linalg.norm(diff)) / expected_norm
    state.filtered_residual = (
        config.ema_alpha * global_residual
        + (1.0 - config.ema_alpha) * state.filtered_residual
    )
    state.confidence = np.clip(100.0 * (1.0 - abs(state.filtered_residual)), 0.0, 100.0)

    if state.confidence < config.confidence_threshold:
        state.low_confidence_frames += 1
    else:
        state.low_confidence_frames = 0

    for i in range(len(per_channel)):
        if state.per_channel_confidence[i] < config.confidence_threshold:
            state.per_channel_low_frames[i] = state.per_channel_low_frames.get(i, 0) + 1
        else:
            state.per_channel_low_frames[i] = 0

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


def warmup_numba() -> None:
    """Pre-compile numba-jitted py_fatigue functions (calc_pm, CycleCount)."""
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
    combined = np.concatenate([np.array(pending), stress_arr]) if pending else stress_arr
    state.node_buffers[node_idx].clear()

    try:
        cc = CycleCount.from_timeseries(
            combined, unit="MPa", range_bin_width=config.rainflow_range_bin_width,
        )
    except ValueError:
        state.node_res_sigs[node_idx] = []
        return 0.0

    result_dict = cc.as_dict()
    state.node_res_sigs[node_idx] = result_dict.get("res_sig", [])

    if len(cc.stress_range) == 0:
        return 0.0

    damage_per_bin = calc_pm(cc.stress_range, cc.count_cycle, sn_curve)
    node_damage = float(np.sum(damage_per_bin))
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
