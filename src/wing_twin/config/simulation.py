"""
Simulation configuration.
"""

from dataclasses import dataclass

from wing_twin.config.types import check_gt


@dataclass
class SimulationConfig:
    sample_rate: int = 50

    def __post_init__(self) -> None:
        check_gt(self.sample_rate, "SimulationConfig.sample_rate", 0)
