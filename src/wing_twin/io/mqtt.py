"""
MQTT module - transport, data source, stepper monitor, and publisher.
"""

import json
import time
import threading
from collections import deque
from typing import Callable, Optional

import numpy as np
import paho.mqtt.client as mqtt

from wing_twin.config import MqttConfig
from wing_twin.io.protocol import (
    LedCommand,
    SENSOR_COMMAND_TOPIC,
    SENSOR_DATA_TOPIC,
    STEPPER_COMMAND_TOPIC,
    STEPPER_STATUS_TOPIC,
    SensorPayload,
    StepperEnableCommand,
    StepperPositionCommand,
    StepperResetCommand,
    StepperStatusPayload,
    TareCommand,
)
from wing_twin.io.logger import get_logger
from wing_twin.types import DataSource, SensorReading, StepperState

logger = get_logger(__name__)


class MqttConnection:
    """Manages a single MQTT connection lifecycle."""

    def __init__(self, config: MqttConfig, client_id: str = ""):
        self._config = config
        self._client = mqtt.Client(client_id=client_id)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._listeners: dict[str, list[Callable[[str, bytes], None]]] = {}
        self._connected = False

    def connect(self) -> bool:
        try:
            self._client.connect(self._config.broker, self._config.port, 60)
            self._thread = threading.Thread(
                target=self._client.loop_forever, daemon=True,
            )
            self._thread.start()
            return True
        except Exception as e:
            logger.error("MQTT connection failed: %s", e)
            return False

    def disconnect(self) -> None:
        if self._client:
            self._client.disconnect()

    def set_last_will(self, topic: str, payload: dict) -> None:
        self._client.will_set(topic, json.dumps(payload), qos=1)

    def subscribe(
        self, topic: str, callback: Callable[[str, bytes], None]
    ) -> None:
        if topic not in self._listeners:
            self._listeners[topic] = []
            if self._connected:
                self._client.subscribe(topic)
        self._listeners[topic].append(callback)

    def publish(self, topic: str, payload: str) -> None:
        if self._connected:
            self._client.publish(topic, payload, qos=1)
        else:
            logger.warning("MQTT not connected - dropping publish to %s", topic)

    @property
    def is_connected(self) -> bool:
        return self._connected

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc == 0:
            self._connected = True
            logger.info("Connected to %s", self._config.broker)
            for topic in self._listeners:
                client.subscribe(topic)
        else:
            logger.error("Connection failed: %s", rc)

    def _on_message(self, client, userdata, msg) -> None:
        callbacks = self._listeners.get(msg.topic, [])
        for cb in callbacks:
            try:
                cb(msg.topic, msg.payload)
            except Exception as e:
                logger.error("MQTT callback error on %s: %s", msg.topic, e)



class MqttSensorSource(DataSource):
    """Receives ESP32 sensor data via MQTT."""

    def __init__(self, connection: MqttConnection):
        self._connection = connection
        self._buffer: deque = deque(maxlen=1)
        self._last_seen: float = 0.0
        self._home_offset: Optional[int] = None

    def connect(self) -> bool:
        self._connection.subscribe(SENSOR_DATA_TOPIC, self._on_message)
        return True

    def disconnect(self) -> None:
        pass

    def is_connected(self) -> bool:
        return self._connection.is_connected

    def read(self) -> Optional[SensorReading]:
        if not self._buffer:
            return None
        raw_vals, offset_vals, dummy_raw, saturated, ts = self._buffer.popleft()
        return SensorReading(
            raw_values=raw_vals,
            offset_values=offset_vals,
            dummy_raw=dummy_raw,
            saturated_flags=saturated,
            accel_z=0.0,
            timestamp=ts,
            gauge_id="esp32_raw",
        )

    def peek_latest(self) -> Optional[SensorReading]:
        """Non-destructive read of the latest sensor value.

        Calibration code needs to peek at sensor data without
        consuming it from the buffer, so the engine's next
        ``step()`` call still has data to process.
        """
        if not self._buffer:
            return None
        raw_vals, offset_vals, dummy_raw, saturated, ts = self._buffer[-1]
        return SensorReading(
            raw_values=raw_vals,
            offset_values=offset_vals,
            dummy_raw=dummy_raw,
            saturated_flags=saturated,
            accel_z=0.0,
            timestamp=ts,
            gauge_id="esp32_raw",
        )

    @property
    def home_offset(self) -> Optional[int]:
        """Latest ``home_offset`` reported by the sensor ESP32."""
        return self._home_offset

    @property
    def last_seen(self) -> float:
        """``time.monotonic()`` stamp of the most recent sensor message."""
        return self._last_seen

    def is_device_connected(self, timeout_s: float = 5.0) -> bool:
        return (time.monotonic() - self._last_seen) < timeout_s

    def _on_message(self, topic: str, payload: bytes) -> None:
        try:
            sensor = SensorPayload.from_json(payload)
            raw_vals = np.array(sensor.raw, dtype=np.int64)
            offset_vals = np.array(sensor.offset, dtype=np.float64)

            self._buffer.clear()
            self._buffer.append(
                (raw_vals, offset_vals, sensor.dummy_raw, sensor.saturated, sensor.timestamp)
            )

            self._last_seen = time.monotonic()
            self._home_offset = sensor.home_offset
        except Exception as e:
            logger.error("Sensor parse error: %s", e)


class MqttStepperMonitor:
    """Monitors ESP32 stepper status via MQTT."""

    def __init__(self, connection: MqttConnection):
        self._connection = connection
        self._state = StepperState()
        self._connection.subscribe(STEPPER_STATUS_TOPIC, self._on_message)

    @property
    def state(self) -> StepperState:
        return self._state

    def is_connected(self, timeout_s: float = 5.0) -> bool:
        return (time.monotonic() - self._state.last_seen) < timeout_s

    def _on_message(self, topic: str, payload: bytes) -> None:
        try:
            status = StepperStatusPayload.from_json(payload)
            self._state = StepperState(
                position=status.position,
                target=status.target,
                enabled=status.enabled,
                moving=status.moving,
                mid_move=status.mid_move,
                last_seen=time.monotonic(),
            )
        except Exception as e:
            logger.error("Stepper parse error: %s", e)



class MqttCommandPublisher:
    """Publishes typed commands to ESP32 devices via MQTT.

    Uses its own MqttConnection with a Last Will so that
    commands are sent on graceful or abrupt shutdown.
    """

    def __init__(self, connection: MqttConnection):
        self._connection = connection

    def publish_stepper_position(self, position: int) -> None:
        self._connection.publish(
            STEPPER_COMMAND_TOPIC, StepperPositionCommand(position).to_json(),
        )

    def publish_led_command(self, colors: list[str]) -> None:
        self._connection.publish(
            SENSOR_COMMAND_TOPIC, LedCommand(colors).to_json(),
        )

    def publish_tare(self) -> None:
        self._connection.publish(
            SENSOR_COMMAND_TOPIC, TareCommand().to_json(),
        )

    def publish_stepper_reset(self, position: int = 0) -> None:
        self._connection.publish(
            STEPPER_COMMAND_TOPIC, StepperResetCommand(position).to_json(),
        )

    def publish_stepper_enable(self, enabled: bool = True) -> None:
        self._connection.publish(
            STEPPER_COMMAND_TOPIC, StepperEnableCommand(enabled).to_json(),
        )

    def publish_raw(self, topic: str, payload: dict) -> None:
        self._connection.publish(topic, json.dumps(payload))

    @property
    def is_connected(self) -> bool:
        return self._connection.is_connected
