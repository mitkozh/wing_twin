"""
Shared MQTT connection and data-collection utilities for stepper calibration tests.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import paho.mqtt.client as mqtt

SENSOR_TOPIC = "wing/sensors"
CONTROL_TOPIC = "wing/control"


def connect(host: str = "localhost", port: int = 1883) -> mqtt.Client:
    client = mqtt.Client()
    client.connect(host, port, 60)
    client.loop_start()
    return client


def disconnect(client: mqtt.Client) -> None:
    client.loop_stop()
    client.disconnect()


def subscribe_sensors(client: mqtt.Client) -> None:
    client.subscribe(SENSOR_TOPIC)


def publish_control(client: mqtt.Client, payload: dict) -> None:
    client.publish(CONTROL_TOPIC, json.dumps(payload))


def collect_samples(
    client: mqtt.Client,
    duration_s: float,
    on_message: Callable | None = None,
) -> list[dict]:
    records: list[dict] = []
    recording = True

    def _on_message(c, userdata, msg):
        if not recording:
            return
        try:
            data = json.loads(msg.payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        data["_wall_t"] = time.time()
        records.append(data)

    if on_message is None:
        client.on_message = _on_message
    else:
        original = client.on_message
        def combined(c, u, m):
            original(c, u, m)
            on_message(c, u, m)
        client.on_message = combined

    t0 = time.time()
    while time.time() - t0 < duration_s:
        time.sleep(0.05)

    return records


def wait_for_stable_position(
    client: mqtt.Client,
    target: int,
    timeout_s: float = 5.0,
    tolerance: int = 5,
) -> tuple[bool, int | None]:
    stable = [False]
    pos = [None]

    def on_msg(c, u, msg):
        try:
            data = json.loads(msg.payload)
            p = data.get("stepper_position")
            if p is not None:
                pos[0] = p
                if abs(p - target) <= tolerance:
                    stable[0] = True
        except (json.JSONDecodeError, KeyError):
            pass

    client.on_message = on_msg
    client.subscribe(SENSOR_TOPIC)

    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if stable[0]:
            return True, pos[0]
        time.sleep(0.05)

    return False, pos[0]


def command_and_wait(
    client: mqtt.Client,
    position: int,
    settle_s: float = 0.5,
    timeout_s: float = 5.0,
) -> int | None:
    publish_control(client, {"position": position})
    time.sleep(settle_s)
    ok, actual = wait_for_stable_position(client, position, timeout_s=timeout_s)
    return actual


def save_csv(filename: Path, records: list[dict], fieldnames: list[str]) -> None:
    import csv
    with open(filename, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(fieldnames)
        for rec in records:
            row = [rec.get(fn, "") for fn in fieldnames]
            w.writerow(row)


def load_stepper_calibration(calib_dir: Path) -> dict:
    path = calib_dir / "stepper_calibration.json"
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def save_stepper_calibration(calib_dir: Path, data: dict) -> None:
    path = calib_dir / "stepper_calibration.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=4)
    print(f"  Calibration saved to {path}")


def update_stepper_calibration(calib_dir: Path, updates: dict) -> dict:
    """Read existing calibration file, merge updates, write back, return full data."""
    existing = load_stepper_calibration(calib_dir)
    existing.update(updates)
    save_stepper_calibration(calib_dir, existing)
    return existing
