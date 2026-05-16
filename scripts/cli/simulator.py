"""
Wing Digital Twin Sensor Simulator CLI Entry Point.
"""

import argparse
import json
import time

import paho.mqtt.client as mqtt

from scripts.config import SimulationConfig
from scripts.sources import SimulatorSource


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
        print(f"[MATRICES] Loaded: {simulator.state.num_gauges} gauge channels")
    except Exception:
        pass

    print("=" * 60)
    print("  Wing Digital Twin - Sensor Simulator")
    print("=" * 60)
    print(f"  Sample rate:  {config.sample_rate} Hz")
    print(f"  Oscillation: {config.osc_amp} us @ {config.osc_freq} Hz")
    print(f"  Gauges:      {simulator.state.num_gauges}")
    print("=" * 60)

    if args.offline:
        simulator.run_offline()
        return

    mqtt_client = mqtt.Client()
    mqtt_publish = "wing/sensors"
    mqtt_subscribe = "wing/control"

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            print(f"[SIM] Connected to MQTT broker")
        else:
            print(f"[SIM] MQTT connection failed: {rc}")

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
        print(f"[SIM] Cannot connect to MQTT: {e}")
        print("Use --offline to run without MQTT")
        return

    mqtt_client.loop_start()

    print(f"\n{'Time':<10} {'Strain[0]':<12} {'AccelZ':<12} {'Damage':<10}")
    print("-" * 50)

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
                print(f"{simulator.state.time_elapsed:<10.1f} {strain_val:<12.2f} {reading.accel_z:<12.0f} {simulator.state.current_damage:<10.4f}")

            time.sleep(1 / config.sample_rate)
    except KeyboardInterrupt:
        print("\n[SIM] Stopping...")
        mqtt_client.loop_stop()
        mqtt_client.disconnect()


if __name__ == "__main__":
    main()