from dataclasses import dataclass

from wing_twin.config.types import check_ge, check_gt


@dataclass
class SimulationConfig:
    sample_rate: int = 50
    strain_noise_std: float = 5e-8
    accel_scale: float = 10000.0
    accel_noise: float = 0.5

    def __post_init__(self) -> None:
        check_gt(self.sample_rate, "SimulationConfig.sample_rate", 0)
        check_ge(self.strain_noise_std, "SimulationConfig.strain_noise_std", 0)
        check_ge(self.accel_noise, "SimulationConfig.accel_noise", 0)
