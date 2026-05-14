"""
Sensors module - Data generation and source interfaces.
"""

from .data_source import DataSource
from .simulator import SensorSimulator

__all__ = ["DataSource", "SensorSimulator"]