"""
MQTT module - client, handler, source, and publisher.
"""

import json
import threading
from collections import deque
from typing import Optional

import numpy as np
import paho.mqtt.client as mqtt

from wing_twin.config import MqttConfig
from wing_twin.types import DataSource, SensorReading
from wing_twin.io.logger import get_logger

logger = get_logger(__name__)


class MqttClientBase:
    """Shared MQTT connection lifecycle management."""

    def __init__(self, config: Optional[MqttConfig] = None):
        self.config = config or MqttConfig()
        self._client: Optional[mqtt.Client] = None
        self._connected = False

    def connect(self) -> bool:
        self._client = mqtt.Client()
        self._client.on_connect = self._on_connect
        self._register_callbacks()
        try:
            self._client.connect(self.config.broker, self.config.port, 60)
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
            return True
        except Exception as e:
            logger.error("Connection failed: %s", e)
            return False

    def _set_will(self, topic: str, payload: dict) -> None:
        """Set MQTT Last Will message (called before connect in subclasses)."""
        if self._client:
            self._client.will_set(topic, json.dumps(payload), qos=1)

    def _register_callbacks(self) -> None:
        pass

    def _loop(self) -> None:
        if self._client:
            self._client.loop_forever()

    def disconnect(self) -> None:
        if self._client:
            self._client.disconnect()

    def is_connected(self) -> bool:
        return self._connected

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc == 0:
            self._connected = True
            logger.info("Connected to %s", self.config.broker)
        else:
            logger.error("Connection failed: %s", rc)


class MqttHandler(MqttClientBase):
    """Handles MQTT connection and message processing for sensor data."""

    def __init__(self, config: Optional[MqttConfig] = None):
        super().__init__(config)
        self._sensor_buffers: dict[str, deque] = {}
        self._num_gauges = 9
        self._latest_esp32_stepper: Optional[int] = None
        self._latest_esp32_home_offset: Optional[int] = None

    @property
    def sensor_buffers(self) -> dict[str, deque]:
        return self._sensor_buffers

    @property
    def num_gauges(self) -> int:
        return self._num_gauges

    def _register_callbacks(self) -> None:
        self._client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc) -> None:
        super()._on_connect(client, userdata, flags, rc)
        if rc == 0:
            client.subscribe(self.config.sensors_topic)

    def _on_message(self, client, userdata, msg) -> None:
        try:
            payload = json.loads(msg.payload.decode())
            timestamp = payload.get("timestamp", 0)

            if "raw" not in payload:
                return

            raw_vals = np.array(payload["raw"], dtype=np.int64)
            dummy_raw = int(payload.get("dummy_raw", 0))
            offset_vals = np.array(payload.get("offset", []), dtype=np.float64)
            saturated = payload.get("saturated")
            self._num_gauges = len(raw_vals)
            key = "esp32"
            if key not in self._sensor_buffers:
                self._sensor_buffers[key] = deque(maxlen=1)
            self._sensor_buffers[key].clear()
            self._sensor_buffers[key].append(
                (raw_vals, offset_vals, dummy_raw, saturated, timestamp)
            )

            self._latest_esp32_stepper = payload.get("stepper_position")
            self._latest_esp32_home_offset = payload.get("home_offset")

        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.error("Parse error: %s", e)

    @property
    def latest_esp32_stepper(self) -> Optional[int]:
        return self._latest_esp32_stepper

    @property
    def latest_esp32_home_offset(self) -> Optional[int]:
        return self._latest_esp32_home_offset


class MqttSource(DataSource):
    """Data source that receives sensor data from MQTT broker."""

    def __init__(self, config: Optional[MqttConfig] = None):
        self.config = config or MqttConfig()
        self._handler = MqttHandler(self.config)
        self._connected = False

    @property
    def handler(self) -> MqttHandler:
        return self._handler

    def connect(self) -> bool:
        success = self._handler.connect()
        self._connected = success
        return success

    def disconnect(self) -> None:
        self._handler.disconnect()
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected and self._handler.is_connected()

    def read(self) -> Optional[SensorReading]:
        buffers = self._handler.sensor_buffers
        if "esp32" not in buffers or not buffers["esp32"]:
            return None

        raw_vals, offset_vals, dummy_raw, saturated, ts = buffers["esp32"].popleft()
        return SensorReading(
            raw_values=raw_vals,
            offset_values=offset_vals,
            dummy_raw=dummy_raw,
            saturated_flags=saturated,
            accel_z=0.0,
            timestamp=ts,
            gauge_id="esp32_raw",
        )


class MqttPublisher(MqttClientBase):
    """Publishes control output to ESP32 via MQTT."""

    def connect(self) -> bool:
        will_payload = {"position": 0, "leds": ["green", "green", "green"]}
        self._set_will(self.config.control_topic, will_payload)
        return super().connect()

    def publish(self, topic: str, payload: dict) -> None:
        if self._client and self._connected:
            self._client.publish(topic, json.dumps(payload))
        else:
            logger.warning("MQTT not connected - dropping publish to %s", topic)
