"""
Shared type definitions for the digital twin system.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import numpy as np


@dataclass
class SensorReading:
    """A single measurement from any sensor source."""
    strain_vector: Optional[np.ndarray] = None
    raw_values: Optional[np.ndarray] = None
    offset_values: Optional[np.ndarray] = None
    dummy_raw: Optional[int] = None
    saturated_flags: Optional[list[bool]] = None
    accel_z: float = 0.0
    timestamp: int = 0
    gauge_id: str = "primary"


@dataclass
class StepperState:
    """State of the stepper motor ESP32."""
    position: int = 0
    target: int = 0
    enabled: bool = True
    moving: bool = False
    mid_move: bool = False
    last_seen: float = 0.0


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

    def set_airspeed(self, speed_kmh: float) -> None:
        """Update the simulated airspeed driving sensor generation.
        No-op for physical (MQTT) sources.
        """

    def set_angle_of_attack(self, angle_deg: float) -> None:
        """Update the simulated angle of attack driving sensor generation.
        No-op for physical (MQTT) sources.
        """


