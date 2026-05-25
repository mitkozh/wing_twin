"""
Strain time series plotter.
"""

from pathlib import Path
from typing import Optional
import numpy as np

from ..logger import get_logger
from .base import BasePlotter

logger = get_logger(__name__)


class StrainPlotter(BasePlotter):
    """Plots strain time series with peak envelope."""

    def plot(self, data: tuple, filename: str = "01_strain_timeseries.png") -> Path:
        """
        Args:
            data: Tuple of (strain_history, times)
            filename: Output filename
        """
        strain_history, times = data
        plt = self._get_plt()

        min_len = min(len(strain_history), len(times))
        if min_len == 0:
            return self._empty_plot(plt, filename, "No data available")

        times = np.array(times[:min_len])
        strain = np.array(strain_history[:min_len])

        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(times, strain, color="#7ab8f5", linewidth=0.6, alpha=0.8, label="Strain")

        window = max(1, len(strain) // 10)
        envelope = np.array([np.max(strain[max(0, i-window):i+1]) for i in range(len(strain))])
        ax.plot(times, envelope, color="#ff9966", linewidth=0.8, alpha=0.5, label="Peak envelope")

        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Strain")
        ax.set_title("Wing Root Strain Time Series")
        ax.legend(loc="upper right")
        ax.grid(True, alpha=0.3)
        ax.set_xlim(times[0], times[-1])

        textstr = f"mean={np.mean(strain):.1e}  max={np.max(strain):.1e}  std={np.std(strain):.1e}"
        ax.text(0.02, 0.95, textstr, transform=ax.transAxes, fontsize=8,
                verticalalignment="top", color="#aaaaaa",
                bbox=dict(boxstyle="round", facecolor="#222233", alpha=0.8))

        fig.tight_layout()
        path = self.output_dir / filename
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        logger.debug("Saved %s", path)
        return path

