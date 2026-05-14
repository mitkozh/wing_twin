"""
MQTT publisher - publishes control commands to ESP32.
"""

import json
from typing import Optional

import paho.mqtt.client as mqtt

from ..config import MqttConfig


class MqttPublisher:
    """Publishes control output to ESP32 via MQTT."""

    def __init__(self, config: Optional[MqttConfig] = None):
        self.config = config or MqttConfig()
        self._client: Optional[mqtt.Client] = None
        self._connected = False

    def connect(self) -> bool:
        """Connect to MQTT broker."""
        self._client = mqtt.Client()
        self._client.on_connect = self._on_connect

        try:
            self._client.connect(self.config.broker, self.config.port, 60)
            self._thread = __import__('threading').Thread(target=self._loop, daemon=True)
            self._thread.start()
            return True
        except Exception as e:
            print(f"[MQTT] Connection failed: {e}")
            return False

    def _loop(self) -> None:
        """Run MQTT network loop."""
        if self._client:
            self._client.loop_forever()

    def disconnect(self) -> None:
        """Disconnect from broker."""
        if self._client:
            self._client.disconnect()

    def is_connected(self) -> bool:
        return self._connected

    def publish(self, topic: str, payload: dict) -> None:
        """Publish a message to a topic."""
        if self._client and self._connected:
            self._client.publish(topic, json.dumps(payload))

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc == 0:
            self._connected = True
            print(f"[MQTT] Connected to {self.config.broker}")
        else:
            print(f"[MQTT] Connection failed: {rc}")