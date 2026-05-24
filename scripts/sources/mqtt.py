"""
MQTT data source - Receives real sensor data from MQTT broker.
"""

from typing import Optional

import numpy as np

from .base import DataSource, SensorReading
from ..config import MqttConfig
from ..output.mqtt_handler import MqttHandler


class MqttSource(DataSource):
    """
    Data source that receives strain data from MQTT broker.
    """

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
        """Get latest reading from MQTT buffer."""
        if not self._handler.strain_buffers:
            return None

        buffers = list(self._handler.strain_buffers.values())
        if not buffers:
            return None

        buffer = buffers[0]
        if not buffer:
            return None

        if isinstance(buffer[0], list):
            strain_vector = np.array(buffer.popleft(), dtype=np.float64)
            return SensorReading(
                strain=float(strain_vector[0]) if len(strain_vector) > 0 else 0.0,
                strain_vector=strain_vector,
                accel_z=0.0,
                timestamp=0,
                gauge_id="vector"
            )
        else:
            strain = float(buffer.popleft())
            return SensorReading(
                strain=strain,
                strain_vector=None,
                accel_z=0.0,
                timestamp=0,
                gauge_id="primary"
            )