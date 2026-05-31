"""
S-N curve plotter.
"""

from pathlib import Path
import numpy as np

from wing_twin.io.logger import get_logger
from .base import BasePlotter

logger = get_logger(__name__)


class SnCurvePlotter(BasePlotter):
    """Plots S-N curve with operating points."""

    def plot(self, cycles, filename: str = "04_sn_curve.png") -> Path:
        a, m = 8.0, 3.0

        plt = self._get_plt()
        fig, ax = plt.subplots(figsize=(10, 5))

        n_points = np.logspace(3, 10, 100)
        stress_curve = 10 ** ((a - np.log10(n_points)) / m)

        ax.plot(n_points, stress_curve, color="#ffaa44", linewidth=2.5,
                label="S-N curve (demo)")
        ax.axhline(100, color="#22cc66", linestyle=":", linewidth=1, alpha=0.7,
                   label="Endurance limit (100 MPa)")

        rngs, cnts = self._parse_cycles(cycles)

        if len(rngs) > 0:
            op_amplitudes = rngs
            op_cycles = np.array([self._sn_cycles(a) for a in op_amplitudes])
            valid = (op_cycles < 1e12) & (op_cycles > 1e0)
            if valid.sum() > 0:
                sc = ax.scatter(op_cycles[valid], op_amplitudes[valid], c=cnts[valid],
                               cmap="plasma", s=100, zorder=5, alpha=0.9,
                               edgecolors="white", linewidths=0.5)
                plt.colorbar(sc, ax=ax, label="Cycle count", shrink=0.7)

        ax.set_xscale("log")
        ax.set_xlabel("Cycles to Failure N")
        ax.set_ylabel("Stress Amplitude (MPa)")
        ax.set_title("S-N Curve with Simulation Operating Points")
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

    def _sn_cycles(self, amp: float) -> float:
        if amp <= 0:
            return float("inf")
        a, m = 8.0, 3.0
        log_n = a - m * np.log10(amp)
        return 10 ** log_n
