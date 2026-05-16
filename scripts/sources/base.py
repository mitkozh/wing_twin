"""
Data source abstractions.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import numpy as np


@dataclass
class SensorReading:
    """Single sensor reading."""
    strain: float
    strain_vector: Optional[np.ndarray] = None
    accel_z: float = 0.0
    timestamp: int = 0
    gauge_id: str = "primary"


class DataSource(ABC):
    """Abstract interface for data sources."""

    @abstractmethod
    def connect(self) -> bool:
        """Establish connection to data source."""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Close connection."""
        pass

    @abstractmethod
    def read(self) -> Optional[SensorReading]:
        """Get next reading. Returns None if no data available."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Check connection status."""
        pass