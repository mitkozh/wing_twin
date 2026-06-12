"""
Shared type definitions for the digital twin system.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING
import numpy as np

if TYPE_CHECKING:
    from wing_twin.config.calibration import CalibrationConfig


@dataclass
class RawSensorReading:
    """Sensor reading from a physical (MQTT/ESP32) device - raw ADC values."""
    raw_values: np.ndarray
    offset_values: Optional[np.ndarray] = None
    dummy_raw: Optional[int] = None
    saturated_flags: Optional[list[bool]] = None
    accel_z: float = 0.0
    timestamp: int = 0
    gauge_id: str = "esp32_raw"


@dataclass
class ProcessedSensorReading:
    """Sensor reading from a simulated source - already a strain vector."""
    strain_vector: np.ndarray
    accel_z: float = 0.0
    timestamp: int = 0
    gauge_id: str = "primary"


SensorReading = RawSensorReading | ProcessedSensorReading


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


class SimulatableDataSource(DataSource):
    """A DataSource that can be driven by simulated flight conditions."""

    @abstractmethod
    def set_airspeed(self, speed_kmh: float) -> None:
        """Update the simulated airspeed driving sensor generation."""

    @abstractmethod
    def set_angle_of_attack(self, angle_deg: float) -> None:
        """Update the simulated angle of attack driving sensor generation."""

    @abstractmethod
    def set_calibration(self, calibration: CalibrationConfig) -> None:
        """Apply calibration (force scaling, ADC mapping, ...) to generated readings."""
