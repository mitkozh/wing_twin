"""
Wind simulation configuration."""

from dataclasses import dataclass

from wing_twin.config.types import check_ge, check_gt


@dataclass
class WindConfig:
    # See Desmos: https://www.desmos.com/calculator/tt9d5etwya
    enabled: bool = True

    # u_mean_ms > 0 = sustained headwind
    # w_mean_ms > 0 = sustained updraft
    u_mean_ms: float = 0.0
    w_mean_ms: float = 0.0

    # Turbulence intensities (1-sigma) per component (m/s).
    sigma_u_ms: float = 1.5
    sigma_w_ms: float = 1.0

    amplification: float = 1.0

    base_freq_hz: float = 0.4
    mid_freq_hz: float = 1.9
    high_freq_hz: float = 3.0

    mid_sharpness: int = 3
    high_sharpness: int = 23

    base_power: float = 1.0
    mid_power: float = 0.5
    high_power: float = 0.2

    # Larger = smoother gusts
    tau_noise_s: float = 0.6

    sample_rate_hint: float = 50.0

    # Safe-target predictor settings
    tau_smooth_s: float = 1.5 # EMA time constant for safe predictions
    gust_margin_k: float = 1.5

    def __post_init__(self) -> None:
        check_ge(self.sigma_u_ms, "WindConfig.sigma_u_ms", 0.0)
        check_ge(self.sigma_w_ms, "WindConfig.sigma_w_ms", 0.0)
        check_ge(self.amplification, "WindConfig.amplification", 0.0)
        check_gt(self.base_freq_hz, "WindConfig.base_freq_hz", 0.0)
        check_gt(self.mid_freq_hz, "WindConfig.mid_freq_hz", 0.0)
        check_gt(self.high_freq_hz, "WindConfig.high_freq_hz", 0.0)
        check_ge(self.mid_sharpness, "WindConfig.mid_sharpness", 1)
        check_ge(self.high_sharpness, "WindConfig.high_sharpness", 1)
        check_gt(self.tau_noise_s, "WindConfig.tau_noise_s", 0.0)
        check_gt(self.tau_smooth_s, "WindConfig.tau_smooth_s", 0.0)
        check_ge(self.gust_margin_k, "WindConfig.gust_margin_k", 0.0)
        check_gt(self.sample_rate_hint, "WindConfig.sample_rate_hint", 0.0)
