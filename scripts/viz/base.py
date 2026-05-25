"""
Base plotter class - abstract base for all visualization plotters.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Any
import numpy as np


class BasePlotter(ABC):
    """
    Abstract base class for plotters.
    Each plotter handles one type of visualization.
    """

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(exist_ok=True)
        self._setup_style()

    def _setup_style(self) -> None:
        """Configure matplotlib style."""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        plt.style.use("dark_background")
        matplotlib.rcParams.update({
            "font.family": "monospace",
            "axes.facecolor": "#1e1e2e",
            "figure.facecolor": "#111118",
            "axes.edgecolor": "#555566",
            "axes.labelcolor": "#cccccc",
            "xtick.color": "#aaaaaa",
            "ytick.color": "#aaaaaa",
            "grid.color": "#333344",
            "grid.linewidth": 0.5,
            "axes.titlesize": 11,
            "axes.labelsize": 9,
            "figure.dpi": 120,
        })
        self.plt = plt

    @abstractmethod
    def plot(self, data: Any, filename: str) -> Path:
        """Generate and save the plot. Returns path to saved file."""
        pass

    def _get_plt(self):
        """Get matplotlib.pyplot module."""
        return self.plt

    def _empty_plot(self, plt, filename: str, message: str, title: str = "") -> Path:
        """Generate a placeholder plot when no data is available."""
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.text(0.5, 0.5, message, transform=ax.transAxes, ha="center", va="center")
        if title:
            ax.set_title(title)
        fig.tight_layout()
        path = self.output_dir / filename
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
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