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


# Damage thresholds
DAMAGE_SAFE = 0.3      # Below this: green LED, 100% speed
DAMAGE_WARNING = 0.8   # Below safe but above this: yellow LED, 50% speed

# EMA filter for confidence monitoring
EMA_ALPHA = 0.1                    # Smoothing factor for EMA
CONFIDENCE_THRESHOLD = 50.0       # Alert threshold (percentage)
CONFIDENCE_FRAMES_THRESHOLD = 10   # Frames below threshold before alert

# Buffer and conversion
STRAIN_BUFFER_SIZE = 3000          # Maximum strain buffer size
MIN_BUFFER_FOR_DAMAGE = 100       # Minimum samples needed for damage calculation

# Strain to stress conversion for aluminum (Young's modulus ~70 GPa = 70e9 Pa)
# 1 µε = 1e-6 strain -> stress = 1e-6 * 70e9 = 70,000 Pa/µε = 0.07 MPa/µε
STRAIN_TO_STRESS = 70_000.0  # Pa/µε

# Rainflow parameters
RAINFLOW_RANGE_BIN_WIDTH = 2.0    # MPa bin width for cycle counting

# Critical node parameters
CRITICAL_STRESS_THRESHOLD = 50_000_000.0  # 50 MPa in Pa
CRITICAL_NODE_PERCENTILE = 90     # Top 10% of nodes by stress are critical
MAX_CRITICAL_NODES = 100           # Maximum critical nodes to track

# Demo mode: Use aggressive S-N curve for visible damage in short demos
# With intercept=8, stress=50MPa gives N=800 cycles -> 10 cycles = 1.25% damage
DEMO_SN_CURVE = SNCurve(
    slope=3.0,
    intercept=8.0,    # Lower = more damage per cycle (for demo visibility)
    endurance=1e4,
)

ALUMINUM_SN_CURVE = SNCurve(
    slope=3.0,
    intercept=15.0,
    endurance=1e7,
)


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


def sn_curve_for_material(material: str = "aluminum") -> SNCurve:
    """
    Get S-N curve parameters for common materials.

    Args:
        material: Material name ('aluminum' or 'steel')

    Returns:
        Configured SNCurve instance
    """
    curves = {
        "aluminum": SNCurve(slope=3.0, intercept=15.0, endurance=1e7),
        "steel": SNCurve(slope=5.0, intercept=17.0, endurance=1e7),
    }
    return curves.get(material.lower(), curves["aluminum"])


def accumulate_damage(
    strain_buffer: deque,
    state: FatigueState,
    sn_curve: Optional[SNCurve] = None,
) -> Tuple[float, List[Tuple[float, float]]]:
    """
    Accumulate fatigue damage using rainflow cycle counting and Miner's Rule.

    This function only processes new samples since the last call to avoid
    double-counting cycles. The internal state tracks buffer length between calls.

    Args:
        strain_buffer: Deque of strain values (microstrain)
        state: FatigueState instance to update
        sn_curve: S-N curve for damage calculation (defaults to DEMO_SN_CURVE)

    Returns:
        Tuple of (incremental_damage, cycles_extracted)
    """
    if len(strain_buffer) < MIN_BUFFER_FOR_DAMAGE:
        return 0.0, []

    prev_len = getattr(state, "_prev_buffer_len", 0)
    new_samples = len(strain_buffer) - prev_len
    if new_samples <= 0:
        return 0.0, []

    state._prev_buffer_len = len(strain_buffer)

    if sn_curve is None:
        sn_curve = DEMO_SN_CURVE  # Use demo curve for visible damage

    strain_arr = np.array(strain_buffer, dtype=np.float64)
    stress_arr = strain_arr * STRAIN_TO_STRESS / 1e6  # Convert Pa to MPa for py_fatigue

    cc = CycleCount.from_timeseries(
        stress_arr,
        unit="MPa",
        range_bin_width=RAINFLOW_RANGE_BIN_WIDTH,
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


def update_confidence(state: FatigueState, observed: float, expected: float) -> float:
    """
    Update confidence metric using EMA-filtered residuals.

    Compares observed strain against expected (reconstructed) strain to
    assess model accuracy. Low confidence indicates potential structural
    degradation or model mismatch.

    Args:
        state: FatigueState instance to update
        observed: Actual measured strain
        expected: Reconstructed/predicted strain

    Returns:
        Updated confidence percentage
    """
    if expected == 0 or np.isnan(expected):
        return state.confidence

    residual = (observed - expected) / expected
    state.filtered_residual = EMA_ALPHA * residual + (1 - EMA_ALPHA) * state.filtered_residual
    state.confidence = np.clip(100.0 * (1.0 - state.filtered_residual), 0.0, 100.0)

    if state.confidence < CONFIDENCE_THRESHOLD:
        state.low_confidence_frames += 1
    else:
        state.low_confidence_frames = 0

    state.alert_active = state.low_confidence_frames >= CONFIDENCE_FRAMES_THRESHOLD

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
    threshold: float = CRITICAL_STRESS_THRESHOLD,
    percentile: float = CRITICAL_NODE_PERCENTILE,
    max_nodes: int = MAX_CRITICAL_NODES,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Identify critical (high-stress) nodes from stress field.

    Nodes are selected based on:
    1. Absolute stress above threshold
    2. Within top percentile of all nodes

    Args:
        stress_field: Stress values at each node (MPa)
        threshold: Minimum stress to consider (MPa)
        percentile: Percentile for top stress nodes (0-100)
        max_nodes: Maximum number of critical nodes to return

    Returns:
        Tuple of (critical_node_indices, critical_stresses)
    """
    stress_field = np.asarray(stress_field, dtype=np.float64)
    if stress_field.size == 0:
        return np.array([], dtype=int), np.array([])

    abs_stress = np.abs(stress_field)

    above_threshold = np.where(abs_stress >= threshold)[0]

    if len(above_threshold) > 0:
        critical_indices = above_threshold
    else:
        p = np.percentile(abs_stress, percentile)
        critical_indices = np.where(abs_stress >= p)[0]

    if len(critical_indices) > max_nodes:
        top_indices = np.argsort(abs_stress[critical_indices])[-max_nodes:]
        critical_indices = critical_indices[top_indices]

    critical_stresses = abs_stress[critical_indices]

    return critical_indices, critical_stresses


def accumulate_damage_at_nodes(
    stress_field: np.ndarray,
    state: FatigueState,
    sn_curve: Optional[SNCurve] = None,
) -> Tuple[float, int]:
    """
    Accumulate fatigue damage only at critical nodes (per-node rainfall).

    Args:
        stress_field: Stress values at each node (MPa)
        state: FatigueState with buffers for each critical node
        sn_curve: S-N curve for damage calculation

    Returns:
        Tuple of (incremental_damage, num_critical_nodes)
    """
    if stress_field.size == 0:
        return 0.0, 0

    if not hasattr(state, "node_buffers"):
        state.node_buffers = {}
        state.node_damages = {}

    critical_indices, critical_stresses = identify_critical_nodes(stress_field)

    if len(critical_indices) == 0:
        return 0.0, 0

    if sn_curve is None:
        sn_curve = DEMO_SN_CURVE

    total_damage = 0.0
    buffer_size = 500

    for node_idx, stress_val in zip(critical_indices, critical_stresses):
        if node_idx not in state.node_buffers:
            state.node_buffers[node_idx] = deque(maxlen=buffer_size)
            state.node_damages[node_idx] = 0.0

        state.node_buffers[node_idx].append(stress_val)

        if len(state.node_buffers[node_idx]) >= MIN_BUFFER_FOR_DAMAGE:
            stress_arr = np.array(state.node_buffers[node_idx], dtype=np.float64)

            cc = CycleCount.from_timeseries(
                stress_arr,
                unit="MPa",
                range_bin_width=RAINFLOW_RANGE_BIN_WIDTH,
            )

            damage_per_bin = calc_pm(cc.stress_range, cc.count_cycle, sn_curve)
            node_damage = float(np.sum(damage_per_bin))

            state.node_damages[node_idx] = min(state.node_damages[node_idx] + node_damage, 1.0)
            total_damage += node_damage

    return total_damage, len(critical_indices)