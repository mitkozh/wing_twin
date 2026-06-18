"""
Base plotter class - abstract base for all visualization plotters.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any
import numpy as np


class BasePlotter(ABC):
    """Abstract base class for plotters."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(exist_ok=True)
        self._setup_style()

    def _setup_style(self) -> None:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        plt.style.use("default")
        matplotlib.rcParams.update({
            "font.family": "sans-serif",
            "axes.facecolor": "#ffffff",
            "figure.facecolor": "#ffffff",
            "axes.edgecolor": "#333333",
            "axes.labelcolor": "#222222",
            "xtick.color": "#222222",
            "ytick.color": "#222222",
            "grid.color": "#dddddd",
            "grid.linewidth": 0.5,
            "axes.titlesize": 11,
            "axes.labelsize": 9,
            "figure.dpi": 120,
        })
        self.plt = plt

    @abstractmethod
    def plot(self, data: Any, filename: str) -> Path:
        pass

    def _get_plt(self):
        return self.plt

    def _empty_plot(self, plt, filename: str, message: str, title: str = "") -> Path:
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
        if not cycles:
            return np.array([], dtype=np.float64), np.array([], dtype=np.float64)

        if isinstance(cycles, dict):
            items = sorted(cycles.items())
            return np.array([k for k, _ in items], dtype=np.float64), np.array([v for _, v in items], dtype=np.float64)

        if isinstance(cycles[0], (list, tuple, np.ndarray)) and len(cycles[0]) == 2:
            ranges_arr = np.array([c[0] for c in cycles], dtype=np.float64)
            counts_arr = np.array([c[1] for c in cycles], dtype=np.float64)
            if len(ranges_arr) == 0:
                return np.array([]), np.array([])
            unique_ranges, inverse = np.unique(ranges_arr, return_inverse=True)
            total_counts = np.zeros_like(unique_ranges)
            np.add.at(total_counts, inverse, counts_arr)
            return unique_ranges, total_counts

        rngs = np.asarray(cycles, dtype=np.float64)
        if rngs.ndim == 2 and rngs.shape[1] == 3:
            return rngs[:, 1], rngs[:, 2]
        return rngs, np.ones(len(rngs), dtype=np.float64)
