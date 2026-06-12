"""
WindTracker - wind sampling, EMA tracking, and gust-margin estimation."""

import math

from wing_twin.config.wind import WindConfig
from wing_twin.physics.wind import WindModel, compute_apparent_wind
from wing_twin.engine.state import TwinState


class WindTracker:
    """Wind sampling, smoothing, and gust-margin estimation."""

    def __init__(self, wind_model: WindModel, config: WindConfig):
        self._wind = wind_model
        self._config = config
        self._u_ema: float = 0.0
        self._w_ema: float = 0.0
        self._u_var: float = 0.0
        self._w_var: float = 0.0
        self._initialised: bool = False
        self._prev_step_t: float = -1.0

    @property
    def wind_model(self):
        """Underlying WindModel instance (needed by SimulatorSource)."""
        return self._wind

    def sample(
        self, time_elapsed: float, airspeed_kmh: float, flight_phase: str,
    ) -> tuple[float, float]:
        """Sample wind, update EMA/variance, return ramped (u_w, w_w).

        The EMA tracks the *unramped* wind so its statistics reflect the
        true turbulence intensity.  The returned wind is ramped to zero
        during ground / early takeoff.
        """
        t = time_elapsed
        dt = 0.0 if self._prev_step_t < 0.0 else max(0.0, t - self._prev_step_t)
        self._prev_step_t = t

        u_raw, w_raw = self._wind.sample(t, dt)
        self._update_ema(u_raw, w_raw, dt)

        # Ground / takeoff gating
        if not self._config.enabled:
            return 0.0, 0.0
        if flight_phase == "on_ground":
            return 0.0, 0.0

        ramp_denom = max(self._config.sample_rate_hint * 1.0, 1.0)
        if flight_phase == "taking_off":
            r = max(0.0, min(1.0, airspeed_kmh / ramp_denom))
        else:
            r = 1.0
        return u_raw * r, w_raw * r

    def safe_apparent(
        self, target_airspeed_kmh: float, target_angle_deg: float,
    ) -> tuple[float, float]:
        """Conservative apparent state for the safe-target predictor.

        Biases smoothed wind toward the more stressful direction:
        stronger headwind (u - k*sigma) and stronger updraft (w + k*sigma).
        """
        if not self._initialised:
            return target_airspeed_kmh, target_angle_deg
        k = self._config.gust_margin_k
        u_safe = self._u_ema - k * math.sqrt(max(self._u_var, 0.0))
        w_safe = self._w_ema + k * math.sqrt(max(self._w_var, 0.0))
        return compute_apparent_wind(target_airspeed_kmh, target_angle_deg, u_safe, w_safe)

    def apply_smoothed_to_state(self, state: TwinState) -> None:
        """Write only the smoothed (EMA) wind values to TwinState.

        Used during initialisation and snapshot restore when we do not
        have instantaneous wind / apparent-flow values yet.
        """
        state.wind_horizontal_smoothed_ms = self._u_ema
        state.wind_vertical_smoothed_ms = self._w_ema

    def update_state(
        self, state: TwinState, u_w: float, w_w: float,
        v_eff: float, alpha_eff: float,
    ) -> None:
        state.wind_horizontal_ms = u_w
        state.wind_vertical_ms = w_w
        state.wind_horizontal_smoothed_ms = self._u_ema
        state.wind_vertical_smoothed_ms = self._w_ema
        state.effective_airspeed_kmh = v_eff
        state.effective_aoa_deg = alpha_eff

    def to_dict(self) -> dict:
        return {
            "u_ema": self._u_ema,
            "w_ema": self._w_ema,
            "u_var": self._u_var,
            "w_var": self._w_var,
            "initialised": self._initialised,
            "prev_step_t": self._prev_step_t,
        }

    def from_dict(self, data: dict) -> None:
        self._u_ema = float(data.get("u_ema", 0.0))
        self._w_ema = float(data.get("w_ema", 0.0))
        self._u_var = float(data.get("u_var", 0.0))
        self._w_var = float(data.get("w_var", 0.0))
        self._initialised = bool(data.get("initialised", False))
        self._prev_step_t = float(data.get("prev_step_t", -1.0))

    def reset(self) -> None:
        self._wind.reset()
        self._u_ema = 0.0
        self._w_ema = 0.0
        self._u_var = 0.0
        self._w_var = 0.0
        self._initialised = False
        self._prev_step_t = -1.0

    # ── internal ──────────────────────────────────────────────────

    def _update_ema(self, u: float, w: float, dt: float) -> None:
        tau = self._config.tau_smooth_s
        if dt <= 0.0 or tau <= 0.0:
            if not self._initialised:
                self._u_ema, self._w_ema = u, w
                self._u_var = self._w_var = 0.0
                self._initialised = True
            return

        if not self._initialised:
            self._u_ema, self._w_ema = u, w
            self._u_var = self._w_var = 0.0
            self._initialised = True
            return

        alpha = 1.0 - math.exp(-dt / tau)
        du = u - self._u_ema
        dw = w - self._w_ema
        self._u_ema += alpha * du
        self._w_ema += alpha * dw
        self._u_var = (1.0 - alpha) * self._u_var + alpha * du * du
        self._w_var = (1.0 - alpha) * self._w_var + alpha * dw * dw
