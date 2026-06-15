"""
Fatigue analysis - per-node rainflow cycle counting and Miner's Rule damage
accumulation using the FEA stress field.

Sensor confidence monitoring has moved to ``ChannelManager``.
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
    """Fatigue-specific state (damage, node buffers, cycles)."""
    damage: float = 0.0
    node_buffers: dict = field(default_factory=dict)
    node_damages: dict = field(default_factory=dict)
    node_res_sigs: dict = field(default_factory=dict)
    cycles_histogram: dict[float, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def to_dict(self) -> dict:
        return {
            "damage": self.damage,
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
        state.damage = data.get("damage", 0.0)
        state.node_damages = {int(k): v for k, v in data.get("node_damages", {}).items()}
        node_buffers_raw = data.get("node_buffers", {})
        node_res_sigs_raw = data.get("node_res_sigs", {})
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
