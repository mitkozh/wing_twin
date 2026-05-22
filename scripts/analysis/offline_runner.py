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
from dtwin.core.fatigue import (
    set_random_seed,
    update_confidence,
    accumulate_damage_at_nodes,
    sn_curve_for_material,
    FatigueConfig,
)

STRAIN_TO_RAW = 1e-6


@dataclass
class OfflineState:
    """State for offline analysis."""
    matrices = None
    num_gauges: int = 3


def _generate_force(t: float, load_factor: float = 1.0) -> float:
    """Generate a force signal in Newtons."""
    steady = 4000.0 * (load_factor ** 2)
    bending_1 = 2000.0 * load_factor * math.sin(2 * math.pi * 4.2 * t)
    bending_2 = 600.0 * load_factor * math.sin(2 * math.pi * 11.5 * t + 0.4)
    torsion = 400.0 * load_factor * math.sin(2 * math.pi * 18.3 * t + 1.1)
    return steady + bending_1 + bending_2 + torsion


def _make_reading(matrices, t: float, load_factor: float = 1.0) -> tuple[np.ndarray, float]:
    """Generate strain using forward model: epsilon = H @ F + noise."""
    F = np.array([_generate_force(t, load_factor)], dtype=np.float64)
    raw_strain = matrices.H @ F
    strain_ue = raw_strain.flatten() / STRAIN_TO_RAW
    noise = np.random.normal(0, 0.05, size=strain_ue.shape)
    return strain_ue + noise, F[0]


class OfflineRunner:
    """Runs offline fatigue analysis without MQTT."""

    def __init__(self, sample_rate: int = 10):
        self.sample_rate = sample_rate

    def run(self, duration_s: int, seed: Optional[int] = None) -> FatigueState:
        """Run offline analysis for specified duration."""
        if seed is not None:
            set_random_seed(seed)

        state = OfflineState()
        state.matrices = load_transfer_matrices()
        state.num_gauges = state.matrices.n_gauges

        fatigue_config = FatigueConfig()
        buffer = deque(maxlen=fatigue_config.strain_buffer_size)
        fatigue_state = FatigueState()
        t = 0.0
        dt = 1.0 / self.sample_rate

        for step in range(int(duration_s * self.sample_rate)):
            strain_vec, force = _make_reading(state.matrices, t)

            buffer.append(float(strain_vec[0]))
            t += dt

            if step % 6 == 0:
                F = solve_forces(state.matrices.H_inv, strain_vec)
                stress = compute_stress_field(state.matrices.S, F)
                deformation = compute_deformation_field(state.matrices.U, F)

                expected_raw = state.matrices.H @ F
                expected_ue = expected_raw / STRAIN_TO_RAW
                update_confidence(fatigue_state, strain_vec, expected_ue, config=fatigue_config)

                stress_mpa = stress / 1e6  # Pa -> MPa
                accumulate_damage_at_nodes(
                    stress_mpa,
                    fatigue_state,
                    sn_curve=sn_curve_for_material(fatigue_config.material),
                    config=fatigue_config,
                )

                accumulate_damage(buffer, fatigue_state, config=fatigue_config)
                cum_damage = fatigue_state.damage

                led_state, speed_pct = decide_control(cum_damage, fatigue_state.confidence, config=fatigue_config)
                if cum_damage >= fatigue_config.damage_critical:
                    state_str, speed_str = "CRITICAL", "0%"
                elif cum_damage >= fatigue_config.damage_warning:
                    state_str, speed_str = "WARNING", "50%"
                else:
                    state_str, speed_str = "SAFE", "100%"

                logger.info("%-8.1f %-12.4f %-12.4f %-12.2f %-14.6f %-10s %-8s", t, cum_damage, F[0], np.max(np.abs(stress)), np.max(np.abs(deformation)), state_str, speed_str)

        final_damage = fatigue_state.damage
        logger.info("Final damage: %.4f (%.1f%%)", final_damage, final_damage*100)
        if final_damage < fatigue_config.damage_warning:
            logger.info("VERDICT: Wing SAFE for continued operation")
        elif final_damage < fatigue_config.damage_critical:
            logger.info("VERDICT: Wing WARNING — reduce Vmax to 50%%")
        else:
            logger.info("VERDICT: Wing CRITICAL — block launch, request maintenance")

        return fatigue_state
