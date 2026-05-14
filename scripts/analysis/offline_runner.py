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
from dtwin.core.fatigue import STRAIN_BUFFER_SIZE, DAMAGE_SAFE, DAMAGE_WARNING, set_random_seed


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

        print("=" * 60)
        print("  Wing Digital Twin - Offline Fatigue Analysis")
        print("=" * 60)

        try:
            state.matrices = load_transfer_matrices()
            state.num_gauges = state.matrices.H_inv.shape[1]
            print(f"  Transfer matrices: loaded")
            print(f"  H_inv: {state.matrices.H_inv.shape}")
            print(f"  S:     {state.matrices.S.shape}")
            print(f"  U:     {state.matrices.U.shape}")
        except FileNotFoundError as e:
            print(f"  Transfer matrices: {e}")
            print("  Running in scalar fallback mode")

        print(f"  Sample rate: {self.sample_rate} Hz, duration: {duration_s} s")
        print("=" * 60)

        buffer = deque(maxlen=STRAIN_BUFFER_SIZE)
        fatigue_state = FatigueState()
        t = 0.0
        dt = 1.0 / self.sample_rate

        print(f"\n{'Time':<8} {'Damage':<12} {'F[0]':<12} {'sigma_max':<12} {'u_max':<14} {'State':<10} {'Speed':<8}")
        print("-" * 82)

        for step in range(int(duration_s * self.sample_rate)):
            strain = make_strain_signal(t)
            buffer.append(strain)
            t += dt

            if step % 6 == 0 and len(buffer) >= state.num_gauges:
                arr = np.array(buffer, dtype=np.float64)
                strain_vec = arr[-state.num_gauges:] if len(arr) >= state.num_gauges else arr

                if state.matrices is not None:
                    F = solve_forces(state.matrices.H_inv, strain_vec)
                    stress = compute_stress_field(state.matrices.S, F)
                    deformation = compute_deformation_field(state.matrices.U, F)
                else:
                    F = np.array([0.0])
                    stress = np.array([0.0])
                    deformation = np.array([0.0])

                accumulate_damage(buffer, fatigue_state)
                cum_damage = fatigue_state.damage

                led_state, speed_pct = decide_control(cum_damage, fatigue_state.confidence)
                if cum_damage >= DAMAGE_WARNING:
                    state_str, speed_str = "CRITICAL", "0%"
                elif cum_damage >= DAMAGE_SAFE:
                    state_str, speed_str = "WARNING", "50%"
                else:
                    state_str, speed_str = "SAFE", "100%"

                print(f"{t:<8.1f} {cum_damage:<12.4f} {F[0]:<12.4f} {np.max(np.abs(stress)):<12.2f} {np.max(np.abs(deformation)):<14.6f} {state_str:<10} {speed_str:<8}")

        final_damage = fatigue_state.damage
        print(f"\nFinal damage: {final_damage:.4f} ({final_damage*100:.1f}%)")
        if final_damage < DAMAGE_SAFE:
            print("VERDICT: Wing SAFE for continued operation")
        elif final_damage < DAMAGE_WARNING:
            print("VERDICT: Wing WARNING — reduce Vmax to 50%")
        else:
            print("VERDICT: Wing CRITICAL — block launch, request maintenance")

        return fatigue_state