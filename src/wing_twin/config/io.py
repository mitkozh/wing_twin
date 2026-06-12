"""
I/O configuration - MQTT broker, WebSocket server, logging.
"""

from dataclasses import dataclass

from wing_twin.config.types import check_range

SENSOR_DATA_TOPIC = "wing/sensor/data"
SENSOR_COMMAND_TOPIC = "wing/sensor/command"
STEPPER_COMMAND_TOPIC = "wing/stepper/command"
STEPPER_STATUS_TOPIC = "wing/stepper/status"


@dataclass
class MqttConfig:
    broker: str = "localhost"
    port: int = 1883
    sensors_topic: str = SENSOR_DATA_TOPIC
    control_topic: str = SENSOR_COMMAND_TOPIC
    stepper_command_topic: str = STEPPER_COMMAND_TOPIC
    stepper_status_topic: str = STEPPER_STATUS_TOPIC
    esp32_timeout_s: float = 5.0     # seconds without sensor data → considered offline
    stepper_timeout_s: float = 5.0   # seconds without stepper status → considered offline

    def __post_init__(self) -> None:
        check_range(self.port, "MqttConfig.port", 1, 65535)
        check_range(self.esp32_timeout_s, "MqttConfig.esp32_timeout_s", 0.1, 300.0)
        check_range(self.stepper_timeout_s, "MqttConfig.stepper_timeout_s", 0.1, 300.0)


@dataclass
class WebSocketConfig:
    port: int = 8765

    def __post_init__(self) -> None:
        check_range(self.port, "WebSocketConfig.port", 1, 65535)


DEFAULT_LOG_LEVEL: str = "INFO"
