"""
S-N curve plotter.
"""

from pathlib import Path
import numpy as np

from wing_twin.io.logger import get_logger
from .base import BasePlotter

logger = get_logger(__name__)


class SnCurvePlotter(BasePlotter):
    """Plots the material S-N curve (Basquin equation)."""

    def plot(self, _cycles, filename: str = "04_sn_curve.png") -> Path:
        a, m = 10.0, 3.5

        plt = self._get_plt()
        fig, ax = plt.subplots(figsize=(10, 5))

        n = np.logspace(3, 10, 200)
        stress = 10 ** ((a - np.log10(n)) / m)

        ax.plot(n, stress, color="#cc8800", linewidth=2.5, label="S-N curve")

        ax.text(0.35, 0.85, f"log(N) = {a} - {m} log(\u03c3)",
                transform=ax.transAxes, fontsize=10, color="#cc8800",
                bbox=dict(boxstyle="round", facecolor="#fff8ee", edgecolor="#dddddd", alpha=0.9))

        ax.set_xscale("log")
        ax.set_xlabel("Cycles to Failure N")
        ax.set_ylabel("Stress Amplitude (MPa)")
        ax.set_title("Material S-N Curve (demo)")
        ax.legend(loc="upper right")
        ax.grid(True, which="both", alpha=0.3)
        ax.set_xlim(1e3, 1e10)
        ax.set_ylim(0, 300)

        fig.tight_layout()
        path = self.output_dir / filename
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        logger.debug("Saved %s", path)
        return path
