from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import paho.mqtt.client as mqtt

from wing_twin.config.io import (
    SENSOR_DATA_TOPIC,
    SENSOR_COMMAND_TOPIC,
    STEPPER_COMMAND_TOPIC,
    STEPPER_STATUS_TOPIC,
)

EMPIRICAL_FILE = "stepper_calibration_empirical.json"
MODEL_FILE = "stepper_calibration_model.json"


class MqttSession:
    def __init__(self, host: str = "131.155.209.40", port: int = 1884,
                 esp32_timeout_s: float = 5.0, stepper_timeout_s: float = 5.0) -> None:
        self.client = mqtt.Client()
        self._esp32_timeout_s = esp32_timeout_s
        self._stepper_timeout_s = stepper_timeout_s
        self._latest_stepper_pos: int | None = None
        self._latest_stepper_last_seen: float = 0.0
        self._esp32_last_seen: float = 0.0
        self._esp32_home_offset: int | None = None
        self._callbacks: list[Callable] = []
        self.client.on_message = self._dispatcher
        self.client.connect(host, port, 60)
        self.client.loop_start()

    def _dispatcher(self, _client: mqtt.Client, _userdata, msg: mqtt.MQTTMessage) -> None:
        try:
            data = json.loads(msg.payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        if msg.topic == STEPPER_STATUS_TOPIC:
            self._latest_stepper_pos = data.get("position")
            self._latest_stepper_last_seen = time.monotonic()
        elif msg.topic == SENSOR_DATA_TOPIC and "raw" in data:
            self._esp32_last_seen = time.monotonic()
            self._esp32_home_offset = data.get("home_offset")
        for cb in self._callbacks:
            cb(_client, _userdata, msg)

    @property
    def latest_stepper_pos(self) -> int | None:
        return self._latest_stepper_pos

    @property
    def esp32_home_offset(self) -> int | None:
        return self._esp32_home_offset

    def is_esp32_connected(self) -> bool:
        return (time.monotonic() - self._esp32_last_seen) < self._esp32_timeout_s

    def is_stepper_connected(self) -> bool:
        return (time.monotonic() - self._latest_stepper_last_seen) < self._stepper_timeout_s

    def add_callback(self, cb: Callable) -> Callable[[], None]:
        self._callbacks.append(cb)
        def _remove() -> None:
            if cb in self._callbacks:
                self._callbacks.remove(cb)
        return _remove

    def subscribe_sensors(self) -> None:
        self.client.subscribe(SENSOR_DATA_TOPIC)
        self.client.subscribe(STEPPER_STATUS_TOPIC)

    def publish_control(self, payload: dict) -> None:
        if "position" in payload or "stepper_enable" in payload or "reset_position" in payload:
            self.client.publish(STEPPER_COMMAND_TOPIC, json.dumps(payload))
        else:
            self.client.publish(SENSOR_COMMAND_TOPIC, json.dumps(payload))

    def collect_samples(self, duration_s: float) -> list[dict]:
        records: list[dict] = []
        def _collector(_c, _u, msg):
            try:
                data = json.loads(msg.payload)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return
            if msg.topic != SENSOR_DATA_TOPIC:
                return
            data["_wall_t"] = time.time()
            data["stepper_position"] = self.latest_stepper_pos
            records.append(data)
        remove = self.add_callback(_collector)
        t0 = time.time()
        while time.time() - t0 < duration_s:
            time.sleep(0.05)
        remove()
        return records

    def wait_for_stable_position(self, target: int, timeout_s: float = 5.0, tolerance: int = 5) -> tuple[bool, int | None]:
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            pos = self.latest_stepper_pos
            if pos is not None and abs(pos - target) <= tolerance:
                return True, pos
            time.sleep(0.05)
        return False, self.latest_stepper_pos

    def command_and_wait(self, position: int, settle_s: float = 0.5, timeout_s: float = 5.0) -> int | None:
        self.publish_control({"position": position})
        time.sleep(settle_s)
        _, actual = self.wait_for_stable_position(position, timeout_s=timeout_s)
        return actual

    def disconnect(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()


def load_stepper_calibration(calib_dir: Path, filename: str = EMPIRICAL_FILE) -> dict:
    path = calib_dir / filename
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def save_stepper_calibration(calib_dir: Path, data: dict, filename: str = EMPIRICAL_FILE) -> None:
    path = calib_dir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=4)
    print(f"  Calibration saved to {path}")


def update_stepper_calibration(calib_dir: Path, updates: dict, filename: str = EMPIRICAL_FILE) -> dict:
    existing = load_stepper_calibration(calib_dir, filename)
    existing.update(updates)
    save_stepper_calibration(calib_dir, existing, filename=filename)
    return existing
