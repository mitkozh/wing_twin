"""
Visualization generator - orchestrates all plotters.
"""

from pathlib import Path
from typing import Optional

from wing_twin.io.logger import get_logger
from wing_twin.recorder.loader import RecordingData
from .strain import StrainPlotter
from .damage import DamagePlotter
from .rainflow import RainflowPlotter
from .sn_curve import SnCurvePlotter
from .fields import StressFieldPlotter, DeformationFieldPlotter

logger = get_logger(__name__)


class VisualizationGenerator:
    """Generates all visualization plots for a simulation run."""

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or Path(__file__).resolve().parent.parent.parent.parent / "figures"
        self.output_dir.mkdir(exist_ok=True)

        self.plotters = [
            StrainPlotter(self.output_dir),
            DamagePlotter(self.output_dir),
            RainflowPlotter(self.output_dir),
            SnCurvePlotter(self.output_dir),
            StressFieldPlotter(self.output_dir),
            DeformationFieldPlotter(self.output_dir),
        ]

    def generate(self, data: RecordingData) -> None:
        logger.info("\n" + "=" * 50)
        logger.info("  Generating Figures...")
        logger.info("=" * 50)

        self.plotters[0].plot((data.strain, data.times))
        self.plotters[1].plot((data.damage, data.times))
        self.plotters[2].plot(data.cycles)
        self.plotters[3].plot(data.cycles)
        self.plotters[4].plot(data.stress_field)
        self.plotters[5].plot(data.deformation_field)

        logger.info("=" * 50)
        logger.info("  Figures saved to: %s/", self.output_dir)
        logger.info("=" * 50)


def generate_figures_from_recording(rec_dir: Path, output_dir: Path) -> None:
    from wing_twin.recorder.loader import DataLoader
    loader = DataLoader(rec_dir)
    data = loader.load_tuple()
    if data.strain is not None and len(data.strain) > 0:
        generator = VisualizationGenerator(Path(output_dir))
        generator.generate(data)
    else:
        logger.warning("No data found in recording %s", rec_dir)
