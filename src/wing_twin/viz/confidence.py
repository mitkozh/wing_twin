"""
Confidence over time plotter.
"""

from pathlib import Path
import numpy as np

from wing_twin.io.logger import get_logger
from .base import BasePlotter

logger = get_logger(__name__)


class ConfidencePlotter(BasePlotter):
    """Plots sensor confidence over time."""

    def plot(self, data: tuple, filename: str = "06_confidence_over_time.png") -> Path:
        confidence, times = data
        plt = self._get_plt()

        min_len = min(len(confidence), len(times))
        if min_len == 0:
            return self._empty_plot(plt, filename, "No confidence data available")

        times = np.array(times[:min_len])
        conf = np.array(confidence[:min_len])

        fig, ax = plt.subplots(figsize=(10, 4))

        ax.fill_between(times, 0, 1.0, alpha=0.08, color="#33aa55", label="HIGH")
        ax.fill_between(times, 0.5, 1.0, alpha=0.08, color="#ddaa22", label="MEDIUM")
        ax.fill_between(times, 0, 0.5, alpha=0.08, color="#cc3322", label="LOW")

        ax.axhline(0.5, color="#ddaa22", linestyle="--", linewidth=0.8, alpha=0.6)
        ax.axhline(0.8, color="#33aa55", linestyle="--", linewidth=0.8, alpha=0.6)

        ax.plot(times, conf, color="#2277cc", linewidth=1.5, label="Confidence")
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Confidence")
        ax.set_title("Sensor Confidence Over Time")
        ax.legend(loc="upper right")
        ax.grid(True, alpha=0.3)
        ax.set_xlim(times[0], times[-1])
        ax.set_ylim(0, 1.05)

        avg_conf = float(np.mean(conf))
        ax.text(0.02, 0.05, f"Mean confidence: {avg_conf:.3f}",
                transform=ax.transAxes, fontsize=9, color="#555555",
                bbox=dict(boxstyle="round", facecolor="#eeeeee", alpha=0.9))

        fig.tight_layout()
        path = self.output_dir / filename
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        logger.debug("Saved %s", path)
        return path
