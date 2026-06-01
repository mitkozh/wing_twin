"""
Wing Digital Twin Sensor Simulator CLI Entry Point.
"""

import argparse
import json
import time

from wing_twin.config import SimulationConfig, MqttConfig
from wing_twin.io.simulator import SimulatorSource
from wing_twin.io.mqtt import MqttClientBase
from wing_twin.io.logger import get_logger
from wing_twin.fea.matrices import load_transfer_matrices

logger = get_logger(__name__)


class SimulatorMqttClient(MqttClientBase):
    """MQTT client for the sensor simulator."""

    def __init__(self, simulator, config=None):
        super().__init__(config)
        self._simulator = simulator
        self._sensors_topic = self.config.sensors_topic
        self._control_topic = self.config.control_topic

    def _register_callbacks(self):
        self._client.on_message = self._on_control

    def _on_connect(self, client, userdata, flags, rc):
        super()._on_connect(client, userdata, flags, rc)
        if rc == 0:
            client.subscribe(self._control_topic)

    def _on_control(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            if "position" in payload:
                self._simulator.state.airspeed = float(payload.get("speed", self._simulator.state.airspeed))
            elif "servo" in payload:
                self._simulator.set_airspeed(float(payload.get("speed", 0)))
        except Exception:
            pass

    def publish_sensor(self, payload: dict) -> None:
        if self._client and self._connected:
            self._client.publish(self._sensors_topic, json.dumps(payload))


def main():
    parser = argparse.ArgumentParser(description="Wing Digital Twin Sensor Simulator")
    parser.add_argument("--broker", default="localhost", help="MQTT broker address")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    args = parser.parse_args()

    sim_config = SimulationConfig()
    mqtt_config = MqttConfig(broker=args.broker, port=args.port)

    simulator = SimulatorSource(sim_config)
    matrices = load_transfer_matrices()
    simulator.set_matrices(matrices)
    logger.info("Loaded: %d gauge channels", simulator.state.num_gauges)

    logger.info("=" * 60)
    logger.info("  Wing Digital Twin - Sensor Simulator")
    logger.info("=" * 60)
    logger.info("  Sample rate:  %d Hz", sim_config.sample_rate)
    logger.info("  MQTT:        %s:%d", mqtt_config.broker, mqtt_config.port)
    logger.info("  Publish:     %s", mqtt_config.sensors_topic)
    logger.info("  Subscribe:   %s", mqtt_config.control_topic)
    logger.info("=" * 60)

    mqtt_client = SimulatorMqttClient(simulator, mqtt_config)
    if not mqtt_client.connect():
        return

    logger.info("%-10s %-12s %-12s", "Time", "Strain[0]", "AccelZ")
    logger.info("-" * 40)

    try:
        while True:
            reading = simulator.read()

            if reading.strain_vector is not None:
                payload = {
                    "strain_vector": reading.strain_vector.tolist(),
                    "accel_z": int(reading.accel_z),
                    "timestamp": reading.timestamp,
                }
            else:
                payload = {
                    "strain": reading.strain,
                    "accel_z": int(reading.accel_z),
                    "timestamp": reading.timestamp,
                }
            mqtt_client.publish_sensor(payload)

            if int(simulator.state.time_elapsed * sim_config.sample_rate) % 10 == 0:
                strain_val = reading.strain if reading.strain_vector is None else reading.strain_vector[0]
                logger.info("%-10.1f %-12.2f %-12.0f", simulator.state.time_elapsed, strain_val, reading.accel_z)

            time.sleep(1 / sim_config.sample_rate)
    except KeyboardInterrupt:
        logger.info("Stopping...")
        mqtt_client.disconnect()


if __name__ == "__main__":
    main()
