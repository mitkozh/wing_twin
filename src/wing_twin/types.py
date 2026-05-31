"""
Shared type definitions for the digital twin system.
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
        pass

    @abstractmethod
    def disconnect(self) -> None:
        pass

    @abstractmethod
    def read(self) -> Optional[SensorReading]:
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        pass
