"""
ESP32 <-> Python communication protocol definitions.
"""

import json
from dataclasses import dataclass, field
from typing import Optional

SENSOR_DATA_TOPIC = "wing/sensor/data"
SENSOR_COMMAND_TOPIC = "wing/sensor/command"
STEPPER_COMMAND_TOPIC = "wing/stepper/command"
STEPPER_STATUS_TOPIC = "wing/stepper/status"


@dataclass
class SensorPayload:
    raw: list[int]
    offset: list[float] = field(default_factory=list)
    saturated: list[bool] = field(default_factory=list)
    dummy_raw: int = 0
    timestamp: int = 0
    home_offset: Optional[int] = None

    @staticmethod
    def from_json(payload: str | bytes) -> "SensorPayload":
        data = json.loads(payload)
        return SensorPayload(
            raw=data["raw"],
            offset=data.get("offset", []),
            saturated=data.get("saturated", []),
            dummy_raw=data.get("dummy_raw", 0),
            timestamp=data.get("timestamp", 0),
            home_offset=data.get("home_offset"),
        )


@dataclass
class StepperStatusPayload:
    position: int = 0
    target: int = 0
    enabled: bool = True
    moving: bool = False
    mid_move: bool = False

    @staticmethod
    def from_json(payload: str | bytes) -> "StepperStatusPayload":
        data = json.loads(payload)
        return StepperStatusPayload(
            position=data.get("position", 0),
            target=data.get("target", 0),
            enabled=data.get("enabled", True),
            moving=data.get("moving", False),
            mid_move=data.get("mid_move", False),
        )


@dataclass
class LedCommand:
    colors: list[list[float]]

    def to_json(self) -> str:
        return json.dumps({"leds": self.colors})


@dataclass
class StepperPositionCommand:
    position: int

    def to_json(self) -> str:
        return json.dumps({"position": self.position})


@dataclass
class StepperResetCommand:
    position: int = 0

    def to_json(self) -> str:
        return json.dumps({"reset_position": self.position})


@dataclass
class StepperEnableCommand:
    enabled: bool = True

    def to_json(self) -> str:
        return json.dumps({"enable": self.enabled})


@dataclass
class TareCommand:
    def to_json(self) -> str:
        return json.dumps({"tare": True})


@dataclass
class StatusRequestCommand:
    def to_json(self) -> str:
        return json.dumps({"status": True})
