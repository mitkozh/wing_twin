"""
Wing Digital Twin - Sensor Data Simulator
Generates simulated multi-gauge strain data to test the force reconstruction pipeline.
"""

import json
import time
import random
import math
import argparse
from dataclasses import dataclass

import paho.mqtt.client as mqtt


SAMPLE_RATE = 10
BASE_STRAIN = 100.0
OSC_AMP = 50.0
OSC_FREQ = 0.5


@dataclass
class SimulatorState:
    time_elapsed: float = 0.0
    current_damage: float = 0.0
    speed_pct: int = 100
    matrices = None
    num_gauges: int = 1


def generate_strain_vector(state: SimulatorState) -> list:
    effective_amp = OSC_AMP * (state.speed_pct / 100.0)
    base = BASE_STRAIN + random.uniform(-5, 5)
    oscillation = effective_amp * math.sin(2 * math.pi * OSC_FREQ * state.time_elapsed)
    noise = random.gauss(0, 10)

    strain_vector = []
    for i in range(state.num_gauges):
        gauge_noise = noise + random.gauss(0, 5)
        phase_offset = i * 0.1
        strain_vector.append(base + oscillation * math.sin(phase_offset) + gauge_noise)
    return strain_vector


def generate_accel_z(state: SimulatorState) -> float:
    effective_amp = OSC_AMP * (state.speed_pct / 100.0)
    accel = -effective_amp * (2 * math.pi * OSC_FREQ) ** 2 * math.sin(2 * math.pi * OSC_FREQ * state.time_elapsed)
    return accel + random.gauss(0, 50)


def run_offline(state: SimulatorState):
    print("\n=== Offline Mode (no MQTT) ===")
    print(f"{'Time':<10} {'Strain':<12} {'AccelZ':<12} {'Damage':<10}")
    print("-" * 44)
    t = 0.0
    dmg = 0.0
    try:
        while True:
            strain_vec = generate_strain_vector(state)
            accel_z = generate_accel_z(state)
            print(f"{t:<10.1f} {strain_vec[0]:<12.2f} {accel_z:<12.0f} {dmg:<10.4f}")
            time.sleep(1 / SAMPLE_RATE)
            t += 1 / SAMPLE_RATE
            if dmg >= 1.0:
                print("\n=== Wing Failed! ===")
                break
    except KeyboardInterrupt:
        pass


def main():
    parser = argparse.ArgumentParser(description="Wing Digital Twin Sensor Simulator")
    parser.add_argument("--broker", default="localhost", help="MQTT broker address")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--offline", action="store_true", help="Run in offline mode without MQTT")
    args = parser.parse_args()

    state = SimulatorState()

    try:
        from dtwin.core.matrices import load_transfer_matrices
        state.matrices = load_transfer_matrices()
        state.num_gauges = state.matrices.H_inv.shape[1]
        print(f"[MATRICES] Loaded: {state.num_gauges} gauge channels")
    except Exception:
        pass

    print("=" * 60)
    print("  Wing Digital Twin - Sensor Simulator")
    print("=" * 60)
    print(f"  Sample rate: {SAMPLE_RATE} Hz")
    print(f"  Oscillation: {OSC_AMP} us @ {OSC_FREQ} Hz")
    print(f"  Gauges:      {state.num_gauges}")
    print("=" * 60)

    if args.offline:
        run_offline(state)
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
            state.speed_pct = int(payload.get("servo", 100))
            state.current_damage = float(payload.get("damage", state.current_damage))
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
            strain_vec = generate_strain_vector(state)
            accel_z = generate_accel_z(state)

            if len(strain_vec) == 1:
                payload = {
                    "strain": strain_vec[0],
                    "accel_z": int(accel_z),
                    "timestamp": int(state.time_elapsed * 1000),
                }
            else:
                payload = {
                    "strain_vector": strain_vec,
                    "accel_z": int(accel_z),
                    "timestamp": int(state.time_elapsed * 1000),
                }
            mqtt_client.publish(mqtt_publish, json.dumps(payload))

            if int(state.time_elapsed * SAMPLE_RATE) % 10 == 0:
                print(f"{state.time_elapsed:<10.1f} {strain_vec[0]:<12.2f} {accel_z:<12.0f} {state.current_damage:<10.4f}")

            time.sleep(1 / SAMPLE_RATE)
            state.time_elapsed += 1 / SAMPLE_RATE
    except KeyboardInterrupt:
        print("\n[SIM] Stopping...")
        mqtt_client.loop_stop()
        mqtt_client.disconnect()


if __name__ == "__main__":
    main()