"""
Damage progress plotter.
"""

from pathlib import Path
import numpy as np

from dtwin.core.fatigue import FatigueConfig

from ..logger import get_logger
from .base import BasePlotter

logger = get_logger(__name__)


class DamagePlotter(BasePlotter):
    """Plots accumulated damage over time with state thresholds."""

    def plot(self, data: tuple, filename: str = "02_damage_progress.png") -> Path:
        """
        Args:
            data: Tuple of (damage_history, times)
        """
        damage_history, times = data
        plt = self._get_plt()

        min_len = min(len(damage_history), len(times))
        if min_len == 0:
            return self._empty_plot(plt, filename, "No data available")

        times = np.array(times[:min_len])
        damage = np.array(damage_history[:min_len])

        config = FatigueConfig()
        damage_warning = config.damage_warning
        damage_critical = config.damage_critical

        fig, ax = plt.subplots(figsize=(10, 4))

        ax.fill_between(times, 0, damage_warning, alpha=0.15, color="#22cc66", label="SAFE")
        ax.fill_between(times, damage_warning, damage_critical, alpha=0.15, color="#ccaa22", label="WARNING")
        ax.fill_between(times, damage_critical, 1.0, alpha=0.15, color="#cc3322", label="CRITICAL")

        ax.axhline(damage_warning, color="#ccaa22", linestyle="--", linewidth=1, alpha=0.8)
        ax.axhline(damage_critical, color="#cc3322", linestyle="--", linewidth=1, alpha=0.8)

        ax.plot(times, damage, color="#66ddff", linewidth=2, label="Accumulated damage D")

        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Damage D")
        ax.set_title("Fatigue Damage (Miner's Rule)")
        ax.legend(loc="upper left")
        ax.grid(True, alpha=0.3)
        ax.set_xlim(times[0], times[-1])
        ax.set_ylim(0, 1.05)

        final_d = damage[-1]
        if final_d >= damage_critical:
            status, color = "CRITICAL", "#ff4444"
        elif final_d >= damage_warning:
            status, color = "WARNING", "#ffcc22"
        else:
            status, color = "SAFE", "#44ff88"

        ax.text(0.98, 0.05, f"Final D = {final_d:.4f} ({status})", transform=ax.transAxes,
                fontsize=10, ha="right", va="bottom", color=color, fontweight="bold",
                bbox=dict(boxstyle="round", facecolor="#222233", alpha=0.8))

        fig.tight_layout()
        path = self.output_dir / filename
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        logger.debug("Saved %s", path)
        return path

    def _empty_plot(self, plt, filename: str, message: str) -> Path:
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.text(0.5, 0.5, message, transform=ax.transAxes, ha="center")
        fig.tight_layout()
        path = self.output_dir / filename
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        return path