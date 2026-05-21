"""
Wing Digital Twin Sensor Simulator CLI Entry Point.
"""

import argparse
import json
import time

import paho.mqtt.client as mqtt

from scripts.config import SimulationConfig
from scripts.sources import SimulatorSource
from scripts.logger import get_logger

logger = get_logger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Wing Digital Twin Sensor Simulator")
    parser.add_argument("--broker", default="localhost", help="MQTT broker address")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--offline", action="store_true", help="Run in offline mode without MQTT")
    args = parser.parse_args()

    config = SimulationConfig()
    simulator = SimulatorSource(config)

    try:
        from dtwin.core.matrices import load_transfer_matrices
        matrices = load_transfer_matrices()
        simulator.set_matrices(matrices)
        logger.info("Loaded: %d gauge channels", simulator.state.num_gauges)
    except Exception:
        pass

    logger.info("=" * 60)
    logger.info("  Wing Digital Twin - Sensor Simulator")
    logger.info("=" * 60)
    logger.info("  Sample rate:  %d Hz", config.sample_rate)
    logger.info("  Oscillation: %d us @ %d Hz", config.osc_amp, config.osc_freq)
    logger.info("  Gauges:      %d", simulator.state.num_gauges)
    logger.info("=" * 60)

    if args.offline:
        simulator.run_offline()
        return

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
            simulator.set_speed(int(payload.get("servo", 100)))
            simulator.set_damage(float(payload.get("damage", 0.0)))
        except Exception:
            pass

    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_control
    mqtt_client.subscribe(mqtt_subscribe)

    try:
        mqtt_client.connect(args.broker, args.port, 60)
    except Exception as e:
        logger.error("Cannot connect to MQTT: %s", e)
        logger.info("Use --offline to run without MQTT")
        return

    mqtt_client.loop_start()

    logger.info("%-10s %-12s %-12s %-10s", "Time", "Strain[0]", "AccelZ", "Damage")
    logger.info("-" * 50)

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
                logger.info("%-10.1f %-12.2f %-12.0f %-10.4f", simulator.state.time_elapsed, strain_val, reading.accel_z, simulator.state.current_damage)

            time.sleep(1 / config.sample_rate)
    except KeyboardInterrupt:
        logger.info("Stopping...")
        mqtt_client.loop_stop()
        mqtt_client.disconnect()


if __name__ == "__main__":
    main()