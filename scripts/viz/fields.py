"""
Stress and deformation field plotters.
"""

from pathlib import Path
import numpy as np

from ..logger import get_logger
from .base import BasePlotter

logger = get_logger(__name__)


class StressFieldPlotter(BasePlotter):
    """Plots stress field across wing nodes."""

    def plot(self, stress_field_history, filename: str = "05_stress_field.png") -> Path:
        """Plot latest stress field."""
        plt = self._get_plt()

        if stress_field_history is None or (isinstance(stress_field_history, np.ndarray) and stress_field_history.size == 0):
            return self._empty_plot(plt, filename, "No stress field data available", "Stress Field")

        latest = np.array(stress_field_history[-1])
        fig, ax = plt.subplots(figsize=(10, 4))

        ax.plot(latest, color="#ff6666", linewidth=1.5, label="Equivalent stress (MPa)")
        ax.fill_between(np.arange(len(latest)), latest, alpha=0.3, color="#ff6666")
        ax.set_xlabel("Node index")
        ax.set_ylabel("Stress (MPa)")
        ax.set_title(f"Equivalent Stress Field ({len(latest)} nodes)")
        ax.grid(True, alpha=0.3)
        ax.text(0.02, 0.95, f"max={latest.max():.2f} MPa  mean={latest.mean():.2f} MPa",
                transform=ax.transAxes, fontsize=8, va="top", color="#aaaaaa",
                bbox=dict(boxstyle="round", facecolor="#222233", alpha=0.8))

        fig.tight_layout()
        path = self.output_dir / filename
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        logger.debug("Saved %s", path)
        return path




class DeformationFieldPlotter(BasePlotter):
    """Plots deformation field across wing nodes."""

    def plot(self, deformation_field_history, filename: str = "06_deformation_field.png") -> Path:
        """Plot latest deformation field."""
        plt = self._get_plt()

        if deformation_field_history is None or (isinstance(deformation_field_history, np.ndarray) and deformation_field_history.size == 0):
            return self._empty_plot(plt, filename, "No deformation field data available", "Deformation Field")

        latest = np.array(deformation_field_history[-1])
        abs_latest = np.abs(latest)

        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(abs_latest, color="#66ffaa", linewidth=1.5, label="Total deformation magnitude (m)")
        ax.fill_between(np.arange(len(abs_latest)), abs_latest, alpha=0.3, color="#66ffaa")
        ax.set_xlabel("Node index")
        ax.set_ylabel("Deformation magnitude (m)")
        ax.set_title(f"Total Deformation Field ({len(latest)} nodes)")
        ax.grid(True, alpha=0.3)
        ax.text(0.02, 0.95, f"max={abs_latest.max():.2e} m  mean={abs_latest.mean():.2e} m",
                transform=ax.transAxes, fontsize=8, va="top", color="#aaaaaa",
                bbox=dict(boxstyle="round", facecolor="#222233", alpha=0.8))

        fig.tight_layout()
        path = self.output_dir / filename
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        logger.debug("Saved %s", path)
        return path

