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

    def _ensure_array(self, data: Any) -> np.ndarray:
        """Convert data to numpy array."""
        if data is None:
            return np.array([])
        return np.asarray(data)