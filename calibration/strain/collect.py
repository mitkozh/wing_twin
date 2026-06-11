"""
MQTT-based sensor data collection for strain gauge calibration.

Usage:
    python -m calibration.strain.collect \\
        --mqtt-host localhost --weights 0,100,200,500,1000 --duration 10

For each weight the script prompts you to hang it at the wing tip,
records N seconds of sensor data, and saves a CSV.
"""

from __future__ import annotations

import argparse
import csv
import json
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt

HERE = Path(__file__).resolve().parent.parent
SENSOR_TOPIC = "wing/sensors"

_sensor_topic = "wing/sensors"
_records: list[dict] = []
_recording = False
_stop_requested = False


def _on_message(client, userdata, msg):
    global _recording, _records
    if not _recording:
        return
    try:
        data = json.loads(msg.payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return
    data["_wall_t"] = time.time()
    _records.append(data)


def _signal_handler(sig, frame):
    global _stop_requested
    _stop_requested = True


def collect_for_weight(
    weight_g: float,
    duration_s: float,
    mqtt_host: str,
    mqtt_port: int,
    data_dir: Path,
):
    global _records, _recording, _stop_requested

    client = mqtt.Client()
    client.on_message = _on_message
    client.connect(mqtt_host, mqtt_port, 60)
    client.subscribe(SENSOR_TOPIC)
    client.loop_start()

    try:
        if weight_g == 0:
            print("\n=== Tare (no load) ===")
            input("Remove all loads from the wing. Press Enter when ready...")
        else:
            print(f"\n=== {weight_g:.0f} g at tip ===")
            input(f"Hang {weight_g:.0f} g at the wing tip. Press Enter when ready...")

        _records = []
        _recording = True
        _stop_requested = False
        signal.signal(signal.SIGINT, _signal_handler)

        t0 = time.time()
        while time.time() - t0 < duration_s:
            if _stop_requested:
                print("  [interrupted]")
                break
            time.sleep(0.05)
        _recording = False

        if not _records:
            print("  No sensor data received - is MQTT broker running?")
            return

        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        filename = data_dir / f"{ts}_{weight_g:.0f}g.csv"

        fieldnames = [
            "wall_t", "esp_ts", "stepper_position", "dummy_raw",
            *[f"raw_{i}" for i in range(9)],
            *[f"offset_{i}" for i in range(9)],
            *[f"saturated_{i}" for i in range(9)],
        ]
        with open(filename, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(fieldnames)
            for rec in _records:
                raw = rec.get("raw", [0] * 9)
                off = rec.get("offset", [0.0] * 9)
                sat = rec.get("saturated", [False] * 9)
                row = [
                    rec.get("_wall_t", 0),
                    rec.get("timestamp", 0),
                    rec.get("stepper_position", 0),
                    rec.get("dummy_raw", 0),
                ]
                row.extend(raw[:9])
                row.extend(off[:9])
                row.extend(sat[:9])
                w.writerow(row)

        print(f"  Saved {len(_records)} samples to {filename.name}")
    finally:
        client.loop_stop()
        client.disconnect()


def main():
    parser = argparse.ArgumentParser(description="Collect calibration sensor data")
    parser.add_argument("--mqtt-host", default="localhost", help="MQTT broker host")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument(
        "--weights",
        default="0,100,200,500,1000",
        help="Comma-separated list of weights in grams (first should be 0 = tare)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=10.0,
        help="Recording duration per weight in seconds",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Output directory for CSV files (default: calibration/strain/data)",
    )
    args = parser.parse_args()

    data_dir = args.data_dir or (HERE / "strain" / "data")
    data_dir.mkdir(parents=True, exist_ok=True)

    weights = [float(w.strip()) for w in args.weights.split(",")]
    if not weights:
        print("No weights specified")
        sys.exit(1)

    print(f"MQTT broker: {args.mqtt_host}:{args.mqtt_port}")
    print(f"Weights: {weights} g")
    print(f"Duration per weight: {args.duration} s")
    print(f"Output directory: {data_dir}")
    print()

    for w in weights:
        collect_for_weight(
            weight_g=w,
            duration_s=args.duration,
            mqtt_host=args.mqtt_host,
            mqtt_port=args.mqtt_port,
            data_dir=data_dir,
        )

    print("\n=== Collection complete ===")
    print(f"Data files in: {data_dir}/")
    print("Run: python -m calibration.strain.analyze")


if __name__ == "__main__":
    main()
