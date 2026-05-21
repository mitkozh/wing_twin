"""
Centralized configuration for Wing Digital Twin scripts.
"""

from dataclasses import dataclass, field
from pathlib import Path
import os

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent


@dataclass
class MqttConfig:
    broker: str = "localhost"
    port: int = 1883
    sensors_topic: str = "wing/sensors"
    control_topic: str = "wing/control"
    qos: int = 0


@dataclass
class WebSocketConfig:
    host: str = ""
    port: int = 8765


@dataclass
class SimulationConfig:
    sample_rate: int = 50
    base_strain: float = 350.0
    osc_amp: float = 180.0
    osc_freq: float = 4.2
    noise_std: float = 5.0
    gauge_noise_std: float = 2.0
    gauge_positions: list = field(default_factory=lambda: [1.0, 0.7, 0.4])


@dataclass
class VisualizationConfig:
    output_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "figures")
    style: str = "dark_background"
    dpi: int = 120

    def __post_init__(self):
        self.output_dir.mkdir(exist_ok=True)


@dataclass
class Paths:
    mesh_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "mesh")
    transfer_matrices_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "transfer_matrices")
    figures_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "figures")


@dataclass
class Config:
    mqtt: MqttConfig = field(default_factory=MqttConfig)
    websocket: WebSocketConfig = field(default_factory=WebSocketConfig)
    simulation: SimulationConfig = field(default_factory=SimulationConfig)
    visualization: VisualizationConfig = field(default_factory=VisualizationConfig)
    paths: Paths = field(default_factory=Paths)

    @classmethod
    def from_env(cls) -> "Config":
        """Create config from environment variables."""
        config = cls()
        config.mqtt.broker = os.environ.get("WING_MQTT_BROKER", config.mqtt.broker)
        config.mqtt.port = int(os.environ.get("WING_MQTT_PORT", config.mqtt.port))
        return config


DEFAULT_CONFIG = Config()