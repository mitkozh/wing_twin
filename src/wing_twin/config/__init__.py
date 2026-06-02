"""
Centralized configuration for Wing Digital Twin.
"""

from dataclasses import dataclass, field

from wing_twin.config.paths import PROJECT_ROOT
from wing_twin.config.io import MqttConfig, WebSocketConfig, DEFAULT_LOG_LEVEL
from wing_twin.config.simulation import SimulationConfig
from wing_twin.config.fatigue import FatigueConfig
from wing_twin.config.calibration import CalibrationConfig
from wing_twin.config.engine import EngineConfig


@dataclass
class Config:
    mqtt: MqttConfig = field(default_factory=MqttConfig)
    websocket: WebSocketConfig = field(default_factory=WebSocketConfig)


__all__ = [
    "PROJECT_ROOT",
    "MqttConfig", "WebSocketConfig", "SimulationConfig",
    "FatigueConfig", "CalibrationConfig", "EngineConfig",
    "Config",
    "DEFAULT_LOG_LEVEL",
]
