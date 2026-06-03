"""
Fatigue analysis module for digital twin.

Provides rainflow cycle counting, Miner's Rule damage accumulation,
and confidence monitoring via EMA-filtered residuals.

Units:
  - Strain input: raw (dimensionless)
  - Stress: MPa
  - Damage: dimensionless (0.0 to 1.0)
  - Confidence: percentage (0 to 100)
"""

import concurrent.futures
import numpy as np
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, List, Tuple

from py_fatigue import CycleCount
from py_fatigue.material.sn_curve import SNCurve
from py_fatigue.damage.stress_life import calc_pm

from wing_twin.config.fatigue import FatigueConfig


@dataclass
class FatigueState:
    damage: float = 0.0
    confidence: float = 100.0
    filtered_residual: float = 0.0
    low_confidence_frames: int = 0
    cycles: Optional[List[Tuple[float, float]]] = field(default_factory=list)
    res_sig: List[float] = field(default_factory=list)
    node_buffers: dict = field(default_factory=dict)
    node_damages: dict = field(default_factory=dict)
    node_res_sigs: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "damage": self.damage,
            "confidence": self.confidence,
            "filtered_residual": self.filtered_residual,
            "low_confidence_frames": self.low_confidence_frames,
            "cycles": self.cycles,
            "res_sig": self.res_sig,
            "node_damages": {str(k): v for k, v in self.node_damages.items()},
            "node_buffers": {
                str(k): list(v) for k, v in self.node_buffers.items()
            },
            "node_res_sigs": {
                str(k): v for k, v in self.node_res_sigs.items()
            },
        }

    @staticmethod
    def from_dict(data: dict) -> "FatigueState":
        state = FatigueState()
        state.damage = data["damage"]
        state.confidence = data["confidence"]
        state.filtered_residual = data["filtered_residual"]
        state.low_confidence_frames = data["low_confidence_frames"]
        state.cycles = [tuple(c) for c in data["cycles"]]
        state.res_sig = data["res_sig"]
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
        return state


def sn_curve_for_material(material: str = "aluminum") -> SNCurve:
    curves = {
        "aluminum": SNCurve(slope=4.5, intercept=14.9, endurance=1e7),
        "steel": SNCurve(slope=5.0, intercept=17.0, endurance=1e7),
        "demo": SNCurve(slope=3.0, intercept=8.0, endurance=1e6),
    }
    return curves.get(material.lower(), curves["aluminum"])


def accumulate_damage(
    strain_buffer: deque,
    state: FatigueState,
    sn_curve: Optional[SNCurve] = None,
    config: Optional[FatigueConfig] = None,
) -> Tuple[float, List[Tuple[float, float]]]:
    if config is None:
        config = FatigueConfig()

    if len(strain_buffer) < config.min_buffer_size:
        return 0.0, []

    pending = list(state.res_sig)
    state.res_sig = []

    strain_arr = np.array(strain_buffer, dtype=np.float64)
    stress_arr = strain_arr * config.strain_to_stress

    if pending:
        combined = np.concatenate([np.array(pending), stress_arr])
    else:
        combined = stress_arr

    strain_buffer.clear()

    if sn_curve is None:
        sn_curve = sn_curve_for_material("demo")

    try:
        cc = CycleCount.from_timeseries(
            combined,
            unit="MPa",
            range_bin_width=config.rainflow_range_bin_width,
        )
    except ValueError:
        return 0.0, []

    result_dict = cc.as_dict()
    state.res_sig = result_dict.get("res_sig", [])

    df = cc.to_df()
    cycles_for_hist = [
        (float(row.stress_range), float(row.count_cycle))
        for _, row in df.iterrows()
        if row.count_cycle > 0
    ]
    state.cycles.extend(cycles_for_hist)

    if len(cc.stress_range) > 0:
        damage_per_bin = calc_pm(cc.stress_range, cc.count_cycle, sn_curve)
        damage = float(np.sum(damage_per_bin))
    else:
        damage = 0.0
    state.damage = min(state.damage + damage, 1.0)
    return damage, cycles_for_hist


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

    residual_norm = float(np.linalg.norm(observed_strain - expected_strain))
    residual = residual_norm / expected_norm

    state.filtered_residual = (
        config.ema_alpha * residual + (1 - config.ema_alpha) * state.filtered_residual
    )
    state.confidence = np.clip(100.0 * (1.0 - abs(state.filtered_residual)), 0.0, 100.0)

    if state.confidence < config.confidence_threshold:
        state.low_confidence_frames += 1
    else:
        state.low_confidence_frames = 0

    return state.confidence


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
