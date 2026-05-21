"""
Wing Digital Twin Visualizer CLI Entry Point.
"""

import argparse

from pathlib import Path

from scripts.config import PROJECT_ROOT
from scripts.viz import VisualizationGenerator
from scripts.analysis import DataLoader
from scripts.logger import get_logger

logger = get_logger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Wing Digital Twin Visualization Generator")
    parser.add_argument(
        "--data-dir",
        type=str,
        default=str(PROJECT_ROOT / "figures"),
        help="Directory containing sim_data.json",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(PROJECT_ROOT / "figures"),
        help="Output directory for figures",
    )
    args = parser.parse_args()

    from pathlib import Path

    data_loader = DataLoader(Path(args.data_dir))
    strain, times, damage, forces, stress_fields, deformations, cycles = data_loader.load_tuple()

    if not strain:
        logger.warning("No data found. Run demo.py with --figures first.")
        return

    generator = VisualizationGenerator(Path(args.output_dir))
    generator.generate(
        strain,
        times,
        damage,
        cycles or [],
        stress_fields,
        deformations,
    )


if __name__ == "__main__":
    main()