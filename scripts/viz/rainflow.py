"""
Rainflow cycle histogram plotter.
"""

from pathlib import Path
import numpy as np

from ..logger import get_logger
from .base import BasePlotter

logger = get_logger(__name__)


class RainflowPlotter(BasePlotter):
    """Plots rainflow cycle histogram."""

    def plot(self, cycles, filename: str = "03_rainflow_histogram.png") -> Path:
        """Plot histogram of stress cycles."""
        plt = self._get_plt()
        rngs, cnts = self._parse_cycles(cycles)

        fig, ax = plt.subplots(figsize=(10, 4))

        if len(rngs) > 0:
            total_cycles = float(np.sum(cnts))

            if len(rngs) > 1:
                min_spacing = np.min(np.diff(np.sort(rngs)))
                bar_width = min(0.8, min_spacing * 0.9)
            else:
                bar_width = 0.8

            ax.bar(rngs, cnts, width=bar_width, color="#aa88ff", alpha=0.8, edgecolor="#ffffff44")
            ax.set_xlabel("Stress Range (MPa)")
            ax.set_ylabel("Cycle Count")
            ax.set_title(f"Rainflow Cycle Histogram  ({len(rngs)} bins, {total_cycles:.1f} total cycles)")
        else:
            ax.text(0.5, 0.5, "No cycles extracted", transform=ax.transAxes, ha="center", va="center")
            ax.set_title("Rainflow Cycle Histogram")

        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        path = self.output_dir / filename
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        logger.debug("Saved %s", path)
        return path

    def _parse_cycles(self, cycles):
        """Parse cycles into ranges and counts."""
        if not cycles:
            return np.array([]), np.array([])

        if isinstance(cycles[0], (list, tuple, np.ndarray)) and len(cycles[0]) == 2:
            ranges_arr = np.array([c[0] for c in cycles])
            counts_arr = np.array([c[1] for c in cycles])
            unique_ranges, _ = np.unique(ranges_arr, return_counts=True)
            total_counts = np.zeros_like(unique_ranges)
            for r, c in zip(ranges_arr, counts_arr):
                idx = np.searchsorted(unique_ranges, r)
                total_counts[idx] += c
            return unique_ranges, total_counts

        rngs = np.asarray(cycles)
        if rngs.ndim == 2 and rngs.shape[1] == 3:
            return rngs[:, 1], rngs[:, 2]
        return np.asarray(cycles), np.ones(len(cycles))