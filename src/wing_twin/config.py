"""
Centralized configuration for Wing Digital Twin.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import os


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent


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
    reference_speed: float = 120.0


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
        config = cls()
        config.mqtt.broker = os.environ.get("WING_MQTT_BROKER", config.mqtt.broker)
        config.mqtt.port = int(os.environ.get("WING_MQTT_PORT", config.mqtt.port))
        return config


from wing_twin.fatigue.fatigue import FatigueConfig


@dataclass
class EngineConfig:
    sample_rate: int = 50
    seed: Optional[int] = None
    matrix_dir: Optional[str] = None
    fatigue: FatigueConfig = field(default_factory=FatigueConfig)

    wing_area: float = 0.012375
    chord: float = 0.0491
    span: float = 0.300
    aspect_ratio: float = 7.27

    steps_per_newton: float = 204.0
    F_max_newtons: float = 13.3

    reference_speed: float = 120.0
    Cmq: float = -1.5
    air_density: float = 1.225

    min_airspeed: float = 40.0
    stress_limit: float = 100_000_000.0
    max_stepper_steps: int = 2720
    max_aoa: float = 15.0

    angle_accel: float = 15.0
    speed_accel: float = 60.0

    # Flight lifecycle parameters
    takeoff_speed: float = 72.0
    takeoff_climb_angle: float = 10.0
    takeoff_altitude_threshold: float = 8.0
    landing_approach_speed: float = 65.0
    landing_touchdown_speed: float = 5.0
    landing_altitude_threshold: float = 0.5
    max_landing_altitude: float = 50.0
    min_safe_altitude: float = 25.0
