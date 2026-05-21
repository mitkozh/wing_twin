"""
Offline runner - runs fatigue analysis without MQTT.
"""

import math
from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np

from dtwin import (
    load_transfer_matrices,
    solve_forces,
    compute_stress_field,
    compute_deformation_field,
    accumulate_damage,
    decide_control,
)
from dtwin.core import FatigueState
from dtwin.core.fatigue import set_random_seed, FatigueConfig
from scripts.logger import get_logger

logger = get_logger(__name__)


@dataclass
class OfflineState:
    """State for offline analysis."""
    matrices = None
    num_gauges: int = 3


def make_strain_signal(t: float, rates=(0.5, 1.0, 2.0), amps=(50, 30, 15), noise=5.0) -> float:
    """Generate multi-frequency strain signal."""
    strain = 100.0 + sum(
        amp * math.sin(2 * math.pi * freq * t)
        for freq, amp in zip(rates, amps)
    ) + np.random.normal(0, noise)
    return strain


class OfflineRunner:
    """
    Runs offline fatigue analysis without MQTT.
    """

    def __init__(self, sample_rate: int = 10):
        self.sample_rate = sample_rate

    def run(self, duration_s: int, seed: Optional[int] = None) -> FatigueState:
        """
        Run offline analysis for specified duration.

        Returns:
            Final FatigueState after the run.
        """
        if seed is not None:
            set_random_seed(seed)

        state = OfflineState()

        logger.info("=" * 60)
        logger.info("  Wing Digital Twin - Offline Fatigue Analysis")
        logger.info("=" * 60)

        try:
            state.matrices = load_transfer_matrices()
            state.num_gauges = state.matrices.H_inv.shape[1]
            logger.info("  Transfer matrices: loaded")
            logger.info("  H_inv: %s", state.matrices.H_inv.shape)
            logger.info("  S:     %s", state.matrices.S.shape)
            logger.info("  U:     %s", state.matrices.U.shape)
        except FileNotFoundError as e:
            logger.warning("  Transfer matrices: %s", e)
            logger.warning("  Running in scalar fallback mode")

        logger.info("  Sample rate: %d Hz, duration: %d s", self.sample_rate, duration_s)
        logger.info("=" * 60)

        fatigue_config = FatigueConfig()
        buffer = deque(maxlen=fatigue_config.strain_buffer_size)
        fatigue_state = FatigueState()
        t = 0.0
        dt = 1.0 / self.sample_rate

        logger.info("%-8s %-12s %-12s %-12s %-14s %-10s %-8s", "Time", "Damage", "F[0]", "sigma_max", "u_max", "State", "Speed")
        logger.info("-" * 82)

        for step in range(int(duration_s * self.sample_rate)):
            strain = make_strain_signal(t)
            buffer.append(strain)
            t += dt

            if step % 6 == 0:
                strain_vec = np.array([strain] * state.num_gauges, dtype=np.float64)

                if state.matrices is not None:
                    F = solve_forces(state.matrices.H_inv, strain_vec)
                    stress = compute_stress_field(state.matrices.S, F)
                    deformation = compute_deformation_field(state.matrices.U, F)
                else:
                    F = np.array([0.0])
                    stress = np.array([0.0])
                    deformation = np.array([0.0])

                accumulate_damage(buffer, fatigue_state, config=fatigue_config)
                cum_damage = fatigue_state.damage

                led_state, speed_pct = decide_control(cum_damage, fatigue_state.confidence, config=fatigue_config)
                if cum_damage >= fatigue_config.damage_warning:
                    state_str, speed_str = "CRITICAL", "0%"
                elif cum_damage >= fatigue_config.damage_safe:
                    state_str, speed_str = "WARNING", "50%"
                else:
                    state_str, speed_str = "SAFE", "100%"

                logger.info("%-8.1f %-12.4f %-12.4f %-12.2f %-14.6f %-10s %-8s", t, cum_damage, F[0], np.max(np.abs(stress)), np.max(np.abs(deformation)), state_str, speed_str)

        final_damage = fatigue_state.damage
        logger.info("Final damage: %.4f (%.1f%%)", final_damage, final_damage*100)
        if final_damage < fatigue_config.damage_safe:
            logger.info("VERDICT: Wing SAFE for continued operation")
        elif final_damage < fatigue_config.damage_warning:
            logger.info("VERDICT: Wing WARNING — reduce Vmax to 50%%")
        else:
            logger.info("VERDICT: Wing CRITICAL — block launch, request maintenance")

        return fatigue_state