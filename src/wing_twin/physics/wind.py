"""
Wind physics - velocity-based wind model and apparent-flow calculation.

Wind is represented as a velocity vector (u_wind, w_wind) in m/s:
u_wind is the headwind component along the flight path (positive = headwind)
w_wind is the vertical gust component (positive = updraft)
"""

import math
from typing import Optional

import numpy as np

from wing_twin.config.wind import WindConfig


def apparent_wind(
    airspeed_kmh: float,
    alpha_geom_deg: float,
    u_wind_ms: float,
    w_wind_ms: float,
) -> tuple[float, float]:
    """Compute the effective (apparent) airspeed and AoA seen by the wing."""
    v_ms = airspeed_kmh / 3.6
    vx = v_ms + u_wind_ms
    vz = w_wind_ms
    v_eff_ms = math.hypot(vx, vz)
    delta_alpha_rad = math.atan2(vz, vx)
    v_eff_kmh = v_eff_ms * 3.6
    alpha_eff_deg = alpha_geom_deg - math.degrees(delta_alpha_rad) # We subtract not add
    return v_eff_kmh, alpha_eff_deg


class WindModel:
    """Two-component wind velocity generator with mean + turbulent fluctuations."""

    def __init__(self, config: Optional[WindConfig] = None, seed: Optional[int] = None):
        self.config = config or WindConfig()
        self._rng = np.random.default_rng(seed)

        # Harmonic phase accumulators (radians) per component
        self._phi_u = 0.0
        self._phi_w = 0.0

        # Low-pass filtered stochastic terms (m/s)
        # First-order IIR with time constant tau_noise_s
        tau = self.config.tau_noise_s
        if tau <= 0.0:
            self._alpha_lpf = 0.0
        else:
            dt_ref = 1.0 / max(self.config.sample_rate_hint, 1.0)
            self._alpha_lpf = 1.0 - math.exp(-dt_ref / tau)
        self._u_lpf = 0.0
        self._w_lpf = 0.0

    def reset(self) -> None:
        self._phi_u = 0.0
        self._phi_w = 0.0
        self._u_lpf = 0.0
        self._w_lpf = 0.0

    def sample(self, t: float, dt: float) -> tuple[float, float]:
        """Return instantaneous (u_wind_ms, w_wind_ms) at absolute time ``t``."""
        if not self.config.enabled:
            return 0.0, 0.0

        c = self.config
        if dt > 0.0:
            self._phi_u = (self._phi_u + 2.0 * math.pi * c.base_freq_hz * dt) % (2.0 * math.pi)
            self._phi_w = (self._phi_w + 2.0 * math.pi * c.base_freq_hz * dt) % (2.0 * math.pi)

        # Deterministic harmonics
        base_u = c.base_power * math.sin(self._phi_u)
        base_w = c.base_power * math.sin(self._phi_w)
        mid_u = c.mid_power * math.sin(2.0 * math.pi * c.mid_freq_hz * t) ** c.mid_sharpness
        mid_w = c.mid_power * math.sin(2.0 * math.pi * c.mid_freq_hz * t + math.pi / 3.0) ** c.mid_sharpness
        high_u = c.high_power * math.sin(2.0 * math.pi * c.high_freq_hz * t) ** c.high_sharpness
        high_w = c.high_power * math.sin(2.0 * math.pi * c.high_freq_hz * t + math.pi / 2.0) ** c.high_sharpness

        harm_u = base_u + mid_u + high_u
        harm_w = base_w + mid_w + high_w

        # Stochastic term
        if dt > 0.0 and self._alpha_lpf > 0.0:
            alpha = 1.0 - math.exp(-dt / max(self.config.tau_noise_s, 1e-6))
            self._u_lpf += alpha * (self._rng.normal(0.0, c.sigma_u_ms) - self._u_lpf)
            self._w_lpf += alpha * (self._rng.normal(0.0, c.sigma_w_ms) - self._w_lpf)

        u = c.u_mean_ms + c.amplification * (harm_u + self._u_lpf)
        w = c.w_mean_ms + c.amplification * (harm_w + self._w_lpf)
        return u, w
