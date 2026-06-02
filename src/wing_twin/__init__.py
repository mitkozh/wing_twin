"""
Wing Digital Twin - Real-time wing fatigue monitoring system.
"""

from wing_twin.config import (
    EngineConfig, FatigueConfig, MqttConfig, WebSocketConfig,
    SimulationConfig, CalibrationConfig, WindConfig, PROJECT_ROOT,
)

__version__ = "2.0.0"

__all__ = [
    "EngineConfig", "FatigueConfig", "MqttConfig", "WebSocketConfig",
    "SimulationConfig", "CalibrationConfig", "WindConfig", "PROJECT_ROOT",
]
