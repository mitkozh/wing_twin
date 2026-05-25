"""
MQTT publisher - publishes control commands to ESP32.
"""

import json

from ..logger import get_logger
from ..mqtt.client import MqttClientBase

logger = get_logger(__name__)


class MqttPublisher(MqttClientBase):
    """Publishes control output to ESP32 via MQTT."""

    def publish(self, topic: str, payload: dict) -> None:
        """Publish a message to a topic."""
        if self._client and self._connected:
            self._client.publish(topic, json.dumps(payload))
