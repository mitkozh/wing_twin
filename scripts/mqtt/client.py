"""
Shared MQTT client base class.
"""

import threading
from typing import Optional

import paho.mqtt.client as mqtt

from ..settings import MqttConfig
from ..logger import get_logger

logger = get_logger(__name__)


class MqttClientBase:
    """Shared MQTT connection lifecycle management."""

    def __init__(self, config: Optional[MqttConfig] = None):
        self.config = config or MqttConfig()
        self._client: Optional[mqtt.Client] = None
        self._connected = False

    def connect(self) -> bool:
        """Connect to MQTT broker."""
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

    def _register_callbacks(self) -> None:
        """Override to register additional MQTT callbacks."""
        pass

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

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc == 0:
            self._connected = True
            logger.info("Connected to %s", self.config.broker)
        else:
            logger.error("Connection failed: %s", rc)
