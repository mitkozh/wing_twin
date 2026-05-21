"""
Fatigue analysis module for digital twin.

Provides rainflow cycle counting, Miner's Rule damage accumulation,
and confidence monitoring via EMA-filtered residuals.
"""

import numpy as np
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, List, Tuple

from py_fatigue import CycleCount
from py_fatigue.material.sn_curve import SNCurve
from py_fatigue.damage.stress_life import calc_pm


@dataclass
class FatigueConfig:
    min_buffer_size: int = 50
    strain_buffer_size: int = 3000
    strain_to_stress: float = 70_000.0  # Pa/ue
    rainflow_range_bin_width: float = 2.0  # MPa
    critical_stress_threshold: float = 50.0  # MPa instead of Pa
    critical_node_percentile: float = 90.0
    max_critical_nodes: int = 100
    node_buffer_size: int = 500
    overlap_size: int = 20  # Keep last N points for continuity
    ema_alpha: float = 0.1  # Smoothing factor for EMA
    confidence_threshold: float = 50.0  # Alert threshold (percentage)
    confidence_frames_threshold: int = 10  # Frames below threshold before alert
    damage_safe: float = 0.3      # Below this: green LED, 100% speed
    damage_warning: float = 0.8   # Below safe but above this: yellow LED, 50% speed


@dataclass
class FatigueState:
    """
    State container for fatigue analysis.

    Attributes:
        damage: Accumulated fatigue damage (0.0 to 1.0)
        confidence: Model confidence percentage (0 to 100)
        filtered_residual: EMA-filtered residual value
        low_confidence_frames: Consecutive frames below confidence threshold
        alert_active: True if maintenance alert should be triggered
        cycles: List of (stress_range, cycle_count) tuples for histogram
    """
    damage: float = 0.0
    confidence: float = 100.0
    filtered_residual: float = 0.0
    low_confidence_frames: int = 0
    alert_active: bool = False
    cycles: Optional[List[Tuple[float, float]]] = field(default_factory=list)
    node_buffers: dict = field(default_factory=dict)
    node_damages: dict = field(default_factory=dict)

def sn_curve_for_material(material: str = "aluminum") -> SNCurve:
    """
    Get S-N curve parameters for common materials.

    Args:
        material: Material name ('aluminum', 'steel', or 'demo')

    Returns:
        Configured SNCurve instance
    """
    curves = {
        "aluminum": SNCurve(slope=3.0, intercept=15.0, endurance=1e7),
        "steel": SNCurve(slope=5.0, intercept=17.0, endurance=1e7),
        "demo": SNCurve(slope=3.0, intercept=12.0, endurance=1e6),
    }
    return curves.get(material.lower(), curves["aluminum"])


def accumulate_damage(
    strain_buffer: deque,
    state: FatigueState,
    sn_curve: Optional[SNCurve] = None,
    config: Optional[FatigueConfig] = None,
) -> Tuple[float, List[Tuple[float, float]]]:
    """
    Accumulate fatigue damage using rainflow cycle counting and Miner's Rule.

    This function only processes new samples since the last call to avoid
    double-counting cycles. The internal state tracks buffer length between calls.

    Args:
        strain_buffer: Deque of strain values (microstrain)
        state: FatigueState instance to update
        sn_curve: S-N curve for damage calculation (defaults to DEMO_SN_CURVE)
        config: Configuration containing buffer sizes and parameters

    Returns:
        Tuple of (incremental_damage, cycles_extracted)
    """
    if config is None:
        config = FatigueConfig()

    if len(strain_buffer) < config.min_buffer_size:
        return 0.0, []

    strain_arr = np.array(strain_buffer, dtype=np.float64)
    
    # Rather than completely clearing and losing continuity, we retain an overlap
    # to catch cycles that span boundaries. We then pop the rest.
    # Note: A true streaming rainflow is ideal, but retaining last N points helps.
    overlap = min(len(strain_buffer) - 1, config.overlap_size)
    # Convert Pa to MPa. The config factor translates microstrain to Pa. We divide by 1e6 to get MPa.
    stress_arr = strain_arr * config.strain_to_stress / 1e6

    # Remove all but the overlap elements from the buffer
    for _ in range(len(strain_buffer) - overlap):
        strain_buffer.popleft()

    if sn_curve is None:
        sn_curve = sn_curve_for_material("demo")

    cc = CycleCount.from_timeseries(
        stress_arr,
        unit="MPa",
        range_bin_width=config.rainflow_range_bin_width,
    )

    df = cc.to_df()
    cycles_for_hist = [
        (float(row.stress_range), float(row.count_cycle))
        for _, row in df.iterrows()
        if row.count_cycle > 0
    ]
    state.cycles.extend(cycles_for_hist)

    damage_per_bin = calc_pm(cc.stress_range, cc.count_cycle, sn_curve)
    damage = float(np.sum(damage_per_bin))
    state.damage = min(state.damage + damage, 1.0)
    return damage, cycles_for_hist


def update_confidence(state: FatigueState, observed: float, expected: float, config: Optional[FatigueConfig] = None) -> float:
    """
    Update confidence metric using EMA-filtered residuals.

    Compares observed strain against expected (reconstructed) strain to
    assess model accuracy. Low confidence indicates potential structural
    degradation or model mismatch.

    Args:
        state: FatigueState instance to update
        observed: Actual measured strain
        expected: Reconstructed/predicted strain
        config: Configuration containing confidence thresholds

    Returns:
        Updated confidence percentage
    """
    if config is None:
        config = FatigueConfig()

    if expected == 0 or np.isnan(expected):
        return state.confidence

    residual = (observed - expected) / expected
    state.filtered_residual = config.ema_alpha * residual + (1 - config.ema_alpha) * state.filtered_residual
    state.confidence = np.clip(100.0 * (1.0 - state.filtered_residual), 0.0, 100.0)

    if state.confidence < config.confidence_threshold:
        state.low_confidence_frames += 1
    else:
        state.low_confidence_frames = 0

    state.alert_active = state.low_confidence_frames >= config.confidence_frames_threshold

    return state.confidence


def check_maintenance_needed(state: FatigueState) -> bool:
    """
    Check if maintenance alert should be triggered.

    Args:
        state: FatigueState instance

    Returns:
        True if maintenance is needed
    """
    return state.alert_active


def set_random_seed(seed: Optional[int] = None) -> None:
    """
    Set random seed for reproducible simulation results.

    Args:
        seed: Integer seed for random number generator.
              If None, seed is not changed.
    """
    if seed is not None:
        np.random.seed(seed)


def identify_critical_nodes(
    stress_field: np.ndarray,
    config: Optional[FatigueConfig] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Identify critical (high-stress) nodes from stress field.

    Nodes are selected based on:
    1. Absolute stress above threshold
    2. Within top percentile of all nodes

    Args:
        stress_field: Stress values at each node (MPa)
        config: Configuration for critical node thresholds

    Returns:
        Tuple of (critical_node_indices, critical_stresses)
    """
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


def accumulate_damage_at_nodes(
    stress_field: np.ndarray,
    state: FatigueState,
    sn_curve: Optional[SNCurve] = None,
    config: Optional[FatigueConfig] = None,
) -> Tuple[float, int]:
    """
    Accumulate fatigue damage only at critical nodes (per-node rainfall).

    Args:
        stress_field: Stress values at each node (MPa)
        state: FatigueState with buffers for each critical node
        sn_curve: S-N curve for damage calculation
        config: Configuration containing buffer sizes and parameters

    Returns:
        Tuple of (incremental_damage, num_critical_nodes)
    """
    if config is None:
        config = FatigueConfig()

    if stress_field.size == 0:
        return 0.0, 0

    if not hasattr(state, "node_buffers"):
        state.node_buffers = {}
        state.node_damages = {}

    critical_indices, critical_stresses = identify_critical_nodes(stress_field, config)

    if len(critical_indices) == 0:
        return 0.0, 0

    if sn_curve is None:
        sn_curve = sn_curve_for_material("demo")

    total_damage = 0.0

    for node_idx, stress_val in zip(critical_indices, critical_stresses):
        if node_idx not in state.node_buffers:
            state.node_buffers[node_idx] = deque(maxlen=config.node_buffer_size)
            state.node_damages[node_idx] = 0.0

        state.node_buffers[node_idx].append(stress_val)

        if len(state.node_buffers[node_idx]) >= config.min_buffer_size:
            stress_arr = np.array(state.node_buffers[node_idx], dtype=np.float64)

            # Preserve cycle continuity with a small overlap (e.g. 1 point stitches exactly)
            overlap = min(len(state.node_buffers[node_idx]) - 1, config.overlap_size)
            for _ in range(len(state.node_buffers[node_idx]) - overlap):
                state.node_buffers[node_idx].popleft()

            cc = CycleCount.from_timeseries(
                stress_arr,
                unit="MPa",
                range_bin_width=config.rainflow_range_bin_width,
            )

            damage_per_bin = calc_pm(cc.stress_range, cc.count_cycle, sn_curve)
            node_damage = float(np.sum(damage_per_bin))

            state.node_damages[node_idx] = min(state.node_damages[node_idx] + node_damage, 1.0)
            total_damage += node_damage

    return total_damage, len(critical_indices)