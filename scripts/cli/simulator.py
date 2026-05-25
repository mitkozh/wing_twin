"""
Wing Digital Twin Sensor Simulator CLI Entry Point.
"""

import argparse
import json
import time

import paho.mqtt.client as mqtt

from scripts.settings import SimulationConfig
from scripts.sources import SimulatorSource
from scripts.logger import get_logger

logger = get_logger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Wing Digital Twin Sensor Simulator")
    parser.add_argument("--broker", default="localhost", help="MQTT broker address")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    args = parser.parse_args()

    from dtwin.core.matrices import load_transfer_matrices

    config = SimulationConfig()
    simulator = SimulatorSource(config)
    matrices = load_transfer_matrices()
    simulator.set_matrices(matrices)
    logger.info("Loaded: %d gauge channels", simulator.state.num_gauges)

    logger.info("=" * 60)
    logger.info("  Wing Digital Twin - Sensor Simulator")
    logger.info("=" * 60)
    logger.info("  Sample rate:  %d Hz", config.sample_rate)
    logger.info("=" * 60)

    mqtt_client = mqtt.Client()
    mqtt_publish = "wing/sensors"
    mqtt_subscribe = "wing/control"

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            logger.info("Connected to MQTT broker")
        else:
            logger.error("MQTT connection failed: %s", rc)

    def on_control(client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            if "position" in payload:
                steps = int(payload["position"])
                simulator.state.airspeed = float(payload.get("speed", simulator.state.airspeed))
            elif "servo" in payload:
                simulator.set_speed(int(payload["servo"]))
        except Exception:
            pass

    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_control

    try:
        mqtt_client.connect(args.broker, args.port, 60)
        mqtt_client.subscribe(mqtt_subscribe)
    except Exception as e:
        logger.error("Cannot connect to MQTT: %s", e)
        return

    mqtt_client.loop_start()

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
            mqtt_client.publish(mqtt_publish, json.dumps(payload))

            if int(simulator.state.time_elapsed * config.sample_rate) % 10 == 0:
                strain_val = reading.strain if reading.strain_vector is None else reading.strain_vector[0]
                logger.info("%-10.1f %-12.2f %-12.0f", simulator.state.time_elapsed, strain_val, reading.accel_z)

            time.sleep(1 / config.sample_rate)
    except KeyboardInterrupt:
        logger.info("Stopping...")
        mqtt_client.loop_stop()
        mqtt_client.disconnect()


if __name__ == "__main__":
    main()
