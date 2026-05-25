"""
MQTT handler - Receives sensor data from MQTT broker.
"""

import json
from typing import Optional
from collections import deque

import numpy as np

from ..settings import MqttConfig
from ..logger import get_logger
from .client import MqttClientBase

logger = get_logger(__name__)


class MqttHandler(MqttClientBase):
    """
    Handles MQTT connection and message processing for sensor data.
    """

    def __init__(self, config: Optional[MqttConfig] = None):
        super().__init__(config)
        self._strain_buffers: dict[str, deque] = {}
        self._num_gauges = 3

    @property
    def strain_buffers(self) -> dict[str, deque]:
        return self._strain_buffers

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
        """Parse incoming sensor messages."""
        try:
            payload = json.loads(msg.payload.decode())

            timestamp = payload.get("timestamp", 0)

            if "strain_vector" in payload:
                strain_vals = np.array(payload["strain_vector"], dtype=np.float64)
                self._num_gauges = len(strain_vals)
                key = "vector"
                if key not in self._strain_buffers:
                    self._strain_buffers[key] = deque(maxlen=1)
                self._strain_buffers[key].clear()
                self._strain_buffers[key].append((strain_vals.tolist(), timestamp))

            elif "strain" in payload:
                strain_val = float(payload["strain"])
                key = "primary"
                if key not in self._strain_buffers:
                    self._strain_buffers[key] = deque(maxlen=max(100, self._num_gauges))
                self._strain_buffers[key].append((strain_val, timestamp))

        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.error("Parse error: %s", e)
