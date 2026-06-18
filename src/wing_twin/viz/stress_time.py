"""
Stress over time plotter - max equivalent stress from field data.
"""

from pathlib import Path
import numpy as np

from wing_twin.io.logger import get_logger
from .base import BasePlotter

logger = get_logger(__name__)


class StressOverTimePlotter(BasePlotter):
    """Plots max and mean equivalent stress over time from recorded field data."""

    def plot(self, data: tuple, filename: str = "05_stress_over_time.png") -> Path:
        stress_field, field_times = data
        plt = self._get_plt()

        if stress_field is None or (isinstance(stress_field, np.ndarray) and stress_field.size == 0):
            return self._empty_plot(plt, filename, "No stress field data available", "Stress Over Time")

        sf = np.asarray(stress_field, dtype=np.float64)
        if sf.ndim == 1:
            sf = sf.reshape(1, -1)
        ft = np.asarray(field_times, dtype=np.float64) if field_times is not None else np.arange(sf.shape[0])

        max_stress = np.abs(sf).max(axis=1)
        mean_stress = np.abs(sf).mean(axis=1)

        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(ft, max_stress, color="#cc3333", linewidth=1.5, label="Max stress")
        ax.plot(ft, mean_stress, color="#dd7722", linewidth=1.5, alpha=0.9, label="Mean stress")
        ax.fill_between(ft, 0, max_stress, alpha=0.12, color="#cc3333")

        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Equivalent Stress (MPa)")
        ax.set_title("Stress Over Time")
        ax.legend(loc="upper right")
        ax.grid(True, alpha=0.3)
        ax.set_xlim(ft[0], ft[-1])

        textstr = f"peak={max_stress.max():.2f} MPa  mean overall={mean_stress.mean():.2f} MPa"
        ax.text(0.02, 0.95, textstr, transform=ax.transAxes, fontsize=8,
                verticalalignment="top", color="#555555",
                bbox=dict(boxstyle="round", facecolor="#eeeeee", alpha=0.9))

        fig.tight_layout()
        path = self.output_dir / filename
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        logger.debug("Saved %s", path)
        return path
