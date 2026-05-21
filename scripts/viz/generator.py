"""
Visualization generator - orchestrates all plotters.
"""

from pathlib import Path
from typing import Optional

from ..logger import get_logger
from .strain import StrainPlotter
from .damage import DamagePlotter
from .rainflow import RainflowPlotter
from .sn_curve import SnCurvePlotter
from .fields import StressFieldPlotter, DeformationFieldPlotter

logger = get_logger(__name__)


class VisualizationGenerator:
    """
    Generates all visualization plots for a simulation run.
    """

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or Path(__file__).parent.parent / "figures"
        self.output_dir.mkdir(exist_ok=True)

        self.plotters = [
            StrainPlotter(self.output_dir),
            DamagePlotter(self.output_dir),
            RainflowPlotter(self.output_dir),
            SnCurvePlotter(self.output_dir),
            StressFieldPlotter(self.output_dir),
            DeformationFieldPlotter(self.output_dir),
        ]

    def generate(
        self,
        strain_history: list,
        times: list,
        damage_history: list,
        cycles: list,
        stress_field_history: Optional[list] = None,
        deformation_field_history: Optional[list] = None,
    ) -> None:
        """Generate all plots from simulation data."""
        logger.info("\n" + "=" * 50)
        logger.info("  Generating Figures...")
        logger.info("=" * 50)

        self.plotters[0].plot((strain_history, times))
        self.plotters[1].plot((damage_history, times))
        self.plotters[2].plot(cycles)
        self.plotters[3].plot(cycles)
        self.plotters[4].plot(stress_field_history or [])
        self.plotters[5].plot(deformation_field_history or [])

        logger.info("=" * 50)
        logger.info("  Figures saved to: %s/", self.output_dir)
        logger.info("=" * 50)