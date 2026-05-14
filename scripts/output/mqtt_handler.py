"""
MQTT handler - Receives sensor data from MQTT broker.
"""

import json
import threading
from typing import Callable, Optional
from collections import deque

import numpy as np
import paho.mqtt.client as mqtt

from ..config import MqttConfig


class MqttHandler:
    """
    Handles MQTT connection and message processing for sensor data.
    """

    def __init__(self, config: Optional[MqttConfig] = None):
        self.config = config or MqttConfig()
        self._client: Optional[mqtt.Client] = None
        self._connected = False
        self._strain_buffers: dict[str, deque] = {}
        self._num_gauges = 3
        self._message_callback: Optional[Callable] = None

    @property
    def strain_buffers(self) -> dict[str, deque]:
        return self._strain_buffers

    @property
    def num_gauges(self) -> int:
        return self._num_gauges

    @num_gauges.setter
    def num_gauges(self, value: int):
        self._num_gauges = value

    def set_message_callback(self, callback: Callable) -> None:
        """Set callback for processed sensor data."""
        self._message_callback = callback

    def connect(self) -> bool:
        """Connect to MQTT broker."""
        self._client = mqtt.Client()
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

        try:
            self._client.connect(self.config.broker, self.config.port, 60)
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
            return True
        except Exception as e:
            print(f"[MQTT] Connection failed: {e}")
            return False

    def _loop(self) -> None:
        """Run MQTT network loop."""
        self._client.loop_forever()

    def disconnect(self) -> None:
        """Disconnect from broker."""
        if self._client:
            self._client.disconnect()

    def publish(self, topic: str, payload: dict) -> None:
        """Publish a message to a topic."""
        if self._client and self._connected:
            self._client.publish(topic, json.dumps(payload))

    def is_connected(self) -> bool:
        return self._connected

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc == 0:
            self._connected = True
            print(f"[MQTT] Connected to {self.config.broker}")
            client.subscribe(self.config.sensors_topic)
            client.subscribe(self.config.control_topic)
        else:
            print(f"[MQTT] Connection failed: {rc}")

    def _on_message(self, client, userdata, msg) -> None:
        """Parse incoming sensor messages."""
        try:
            payload = json.loads(msg.payload.decode())

            if "strain" in payload:
                strain_val = float(payload["strain"])
                key = "primary"
                if key not in self._strain_buffers:
                    self._strain_buffers[key] = deque(maxlen=max(100, self._num_gauges))
                self._strain_buffers[key].append(strain_val)

            elif "strain_vector" in payload:
                strain_vals = np.array(payload["strain_vector"], dtype=np.float64)
                self._num_gauges = len(strain_vals)
                key = "vector"
                if key not in self._strain_buffers:
                    self._strain_buffers[key] = deque(maxlen=1)
                self._strain_buffers[key].clear()
                self._strain_buffers[key].append(strain_vals.tolist())

            if self._message_callback:
                self._message_callback()

        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            print(f"[MQTT] Parse error: {e}")