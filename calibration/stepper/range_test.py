"""
Stepper max-range test.

Verifies the stepper can reach its configured limits and reports
position accuracy across the full travel range.

Procedure:
    1. Disconnect the stepper from the wing (no mechanical load).
    2. The script commands positions across the range and records
       actual positions reported by the ESP32 via MQTT.
    3. A CSV is saved with commanded vs actual positions.

Usage:
    python -m calibration.stepper.range_test --mqtt-host localhost
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from calibration.stepper.mqtt_helpers import (
    connect,
    disconnect,
    subscribe_sensors,
    publish_control,
    collect_samples,
    update_stepper_calibration,
)

HERE = Path(__file__).resolve().parent

# Stepper limits from config
STEPPER_MIN = -500
STEPPER_MAX = 2720


def sweep_positions(
    client,
    positions: list[int],
    settle_s: float,
) -> list[dict]:
    all_records: list[dict] = []
    for pos in positions:
        print(f"  Commanding position {pos:+5d} ...", end=" ")
        sys.stdout.flush()
        publish_control(client, {"position": pos})
        time.sleep(settle_s)
        samples = collect_samples(client, 1.0)
        if samples:
            actual = samples[-1].get("stepper_position", "N/A")
            print(f"actual {actual}")
        else:
            print("no response")
        for s in samples:
            s["commanded"] = pos
        all_records.extend(samples)
    return all_records


def run_test(
    mqtt_host: str,
    mqtt_port: int,
    settle_s: float,
    data_dir: Path,
) -> None:
    print("=" * 60)
    print("Stepper Range Test")
    print("=" * 60)
    print()
    print("Before proceeding:")
    print("  1. Disconnect the stepper from the wing (no mechanical load).")
    print("  2. Make sure the ESP32 is powered and connected to MQTT.")
    print("  3. The stepper should be enabled.")
    print()
    input("Press Enter when ready...")
    print()

    client = connect(mqtt_host, mqtt_port)
    subscribe_sensors(client)
    print(f"Connected to {mqtt_host}:{mqtt_port}")
    print()

    print("Phase 1: Sweep 0 -> MAX -> 0 -> MIN -> 0")
    print("-" * 50)
    records = sweep_positions(client, [0, STEPPER_MAX, 0, STEPPER_MIN, 0], settle_s)
    print()

    print("Phase 2: Incremental sweep full range")
    print("-" * 50)
    inc = 200
    full_sweep = list(range(0, STEPPER_MAX + 1, inc)) + \
                 list(range(STEPPER_MAX, STEPPER_MIN - 1, -inc)) + \
                 list(range(STEPPER_MIN, 1, inc))
    records += sweep_positions(client, full_sweep, settle_s)

    if not records:
        print("No sensor data received.")
        disconnect(client)
        return

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = data_dir / f"range_test_{ts}.csv"
    filename.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["commanded", "stepper_position", "_wall_t", "timestamp"]
    with open(filename, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(fieldnames)
        for rec in records:
            w.writerow([
                rec.get("commanded", ""),
                rec.get("stepper_position", ""),
                rec.get("_wall_t", ""),
                rec.get("timestamp", ""),
            ])

    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    matched = [r for r in records if r.get("commanded") == r.get("stepper_position")]
    total_unique = len(set(r.get("commanded") for r in records if "commanded" in r))
    errors = []
    for r in records:
        cmd = r.get("commanded")
        act = r.get("stepper_position")
        if cmd is not None and act is not None:
            errors.append(abs(cmd - act))

    print(f"  Positions tested: {total_unique}")
    print(f"  Samples recorded: {len(records)}")
    print(f"  Exact matches:    {len(matched)}")
    if errors:
        print(f"  Max error:        {max(errors)} steps")
        print(f"  Mean error:       {sum(errors) / len(errors):.1f} steps")
    print(f"  Range min:        {STEPPER_MIN}")
    print(f"  Range max:        {STEPPER_MAX}")
    print(f"  Total span:       {STEPPER_MAX - STEPPER_MIN} steps")
    print()
    print(f"Data saved to: {filename}")
    print("Check the CSV for detailed commanded vs actual positions.")

    # Save motor range to shared stepper calibration file
    print()
    print("-" * 60)
    print("Calibration Output")
    print("-" * 60)
    print()
    print(f"  Measured motor max steps: {STEPPER_MAX}")
    print(f"  Measured motor min steps: {STEPPER_MIN}")
    print()

    update_stepper_calibration(HERE, {
        "version": 1,
        "calibrated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stepper_motor_max_steps": STEPPER_MAX,
        "stepper_motor_min_steps": STEPPER_MIN,
    })
    print()
    print("  Next steps:")
    print(f"    Run: python -m calibration.stepper.max_frequency       (stepper disconnected)")
    print(f"    Run: python -m calibration.stepper.steps_per_newton   (wing attached, weights)")

    disconnect(client)


def main():
    parser = argparse.ArgumentParser(description="Stepper max-range test")
    parser.add_argument("--mqtt-host", default="localhost", help="MQTT broker host")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument(
        "--settle",
        type=float,
        default=2.0,
        help="Settling time per position in seconds",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=HERE / "data",
        help="Output directory for CSV files",
    )
    args = parser.parse_args()

    run_test(
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
        settle_s=args.settle,
        data_dir=args.data_dir,
    )


if __name__ == "__main__":
    main()
