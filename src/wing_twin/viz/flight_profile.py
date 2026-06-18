"""
Flight profile plotter - AoA and airspeed over time.
"""

from pathlib import Path
import numpy as np

from wing_twin.io.logger import get_logger
from .base import BasePlotter

logger = get_logger(__name__)


class FlightProfilePlotter(BasePlotter):
    """Plots angle of attack and airspeed over time."""

    def plot(self, data: tuple, filename: str = "04_flight_profile.png") -> Path:
        aoa, airspeed, times = data
        plt = self._get_plt()

        min_len = min(len(times), len(aoa), len(airspeed))
        if min_len == 0:
            return self._empty_plot(plt, filename, "No flight data available", "Flight Profile")

        times = np.array(times[:min_len])
        aoa = np.array(aoa[:min_len])
        airspeed = np.array(airspeed[:min_len])

        fig, ax1 = plt.subplots(figsize=(10, 4))
        ax2 = ax1.twinx()

        ax1.plot(times, aoa, color="#dd5522", linewidth=1.5, label="Angle of Attack")
        ax1.set_xlabel("Time (s)")
        ax1.set_ylabel("Angle of Attack (deg)", color="#dd5522")
        ax1.tick_params(axis="y", labelcolor="#dd5522")
        ax1.legend(loc="upper left")
        ax1.grid(True, alpha=0.3)

        ax2.plot(times, airspeed, color="#2277cc", linewidth=1.5, label="Airspeed")
        ax2.set_ylabel("Airspeed (km/h)", color="#2277cc")
        ax2.tick_params(axis="y", labelcolor="#2277cc")
        ax2.legend(loc="upper right")

        ax1.set_xlim(times[0], times[-1])
        ax1.set_ylim(bottom=0)
        ax2.set_ylim(bottom=0)

        fig.tight_layout()
        path = self.output_dir / filename
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        logger.debug("Saved %s", path)
        return path
