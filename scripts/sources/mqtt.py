"""
MQTT data source - Receives real sensor data from MQTT broker.
"""

from typing import Optional

import numpy as np

from ..types import DataSource, SensorReading
from ..settings import MqttConfig
from ..mqtt.handler import MqttHandler


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
        buffers = self._handler.strain_buffers
        if not buffers:
            return None

        if "vector" in buffers and buffers["vector"]:
            raw, ts = buffers["vector"].popleft()
            strain_vector = np.array(raw, dtype=np.float64)
            return SensorReading(
                strain=float(strain_vector[0]) if len(strain_vector) > 0 else 0.0,
                strain_vector=strain_vector,
                accel_z=0.0,
                timestamp=ts,
                gauge_id="vector"
            )

        if "primary" in buffers and buffers["primary"]:
            strain, ts = buffers["primary"].popleft()
            return SensorReading(
                strain=strain,
                strain_vector=None,
                accel_z=0.0,
                timestamp=ts,
                gauge_id="primary"
            )

        return None