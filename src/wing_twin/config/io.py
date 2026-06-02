"""
I/O configuration — MQTT broker, WebSocket server, logging.
"""

from dataclasses import dataclass

from wing_twin.config.types import check_range


@dataclass
class MqttConfig:
    broker: str = "localhost"
    port: int = 1883
    sensors_topic: str = "wing/sensors"
    control_topic: str = "wing/control"

    def __post_init__(self) -> None:
        check_range(self.port, "MqttConfig.port", 1, 65535)


@dataclass
class WebSocketConfig:
    port: int = 8765

    def __post_init__(self) -> None:
        check_range(self.port, "WebSocketConfig.port", 1, 65535)


DEFAULT_LOG_LEVEL: str = "INFO"
