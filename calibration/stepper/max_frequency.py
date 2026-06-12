"""
Stepper max-frequency test.

Measures the maximum reliable step rate the stepper can achieve
with the current ESP32 firmware configuration (STEPPER_MAX_SPEED,
STEPPER_ACCELERATION).

Procedure:
    1. Disconnect the stepper from the wing (no mechanical load).
    2. Command rapid back-and-forth moves over a large distance
       (allowing the stepper to reach a constant-speed region).
    3. Record actual positions from MQTT and compute achieved
       step rate from the position-vs-time slope.
    4. Detect step loss and report the max reliable frequency.
    5. Output recommended values for configuration updates.

Usage:
    python -m calibration.stepper.max_frequency --mqtt-host localhost
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from calibration.stepper.mqtt_helpers import (
    MqttSession,
    update_stepper_calibration,
)

HERE = Path(__file__).resolve().parent

# Current ESP32 config values
CONFIG_MAX_SPEED = 1000.0      # steps/sec  (STEPPER_MAX_SPEED)
CONFIG_ACCEL = 600.0           # steps/sec² (STEPPER_ACCELERATION)
CONFIG_MAX_POS = 2720          # STEPPER_MAX_POSITION

# Test parameters
MOVE_DISTANCE = 2000           # steps per half-cycle (must exceed acceleration ramp)
NUM_CYCLES = 10                # number of back-and-forth cycles
SETTLE_S = 0.5                 # settle time before data recording


def estimate_max_frequency_from_profile(
    positions: list[float],
    times: list[float],
) -> dict:
    positions = np.array(positions, dtype=np.float64)
    times = np.array(times, dtype=np.float64)

    if len(positions) < 5:
        return {"error": "too few samples"}

    # Sort by time
    idx = np.argsort(times)
    positions = positions[idx]
    times = times[idx]

    # Remove duplicates
    _, unique_idx = np.unique(times, return_index=True)
    positions = positions[unique_idx]
    times = times[unique_idx]

    if len(positions) < 5:
        return {"error": "too few unique samples"}

    # Compute velocities
    dt = np.diff(times)
    dp = np.diff(positions)
    vel = dp / dt

    # Filter out invalid velocity spikes (position noise, MQTT jitter)
    valid = np.abs(vel) < CONFIG_MAX_SPEED * 1.5
    vel = vel[valid]
    dt = dt[valid]
    dp = dp[valid]

    if len(vel) < 3:
        return {"error": "too few valid velocity samples"}

    # Find constant-speed region: velocities near the max
    max_vel_idx = int(np.argmax(np.abs(vel)))
    max_vel = float(vel[max_vel_idx])

    # Determine reliable speed: 90th percentile of absolute velocity
    abs_vel = np.abs(vel)
    p90 = float(np.percentile(abs_vel, 90))
    p95 = float(np.percentile(abs_vel, 95))
    mean_max = float(np.mean(abs_vel[abs_vel > p90])) if np.any(abs_vel > p90) else 0.0

    return {
        "max_measured_speed": round(max_vel, 1),
        "p90_speed": round(p90, 1),
        "p95_speed": round(p95, 1),
        "mean_top10_speed": round(mean_max, 1),
        "n_valid_samples": len(vel),
    }


def run_test(
    mqtt_host: str,
    mqtt_port: int,
    data_dir: Path,
) -> None:
    print("=" * 60)
    print("Stepper Max Frequency Test")
    print("=" * 60)
    print()
    print("Before proceeding:")
    print("  1. Disconnect the stepper from the wing (no mechanical load).")
    print("  2. Make sure the ESP32 is powered and connected to MQTT.")
    print("  3. The stepper should be enabled and at position 0.")
    print()
    print(f"Current ESP32 config:")
    print(f"  STEPPER_MAX_SPEED      = {CONFIG_MAX_SPEED} steps/sec")
    print(f"  STEPPER_ACCELERATION   = {CONFIG_ACCEL} steps/sec²")
    print(f"  STEPPER_MAX_POSITION   = {CONFIG_MAX_POS}")
    print(f"  Move distance per cycle = {MOVE_DISTANCE} steps")
    print(f"  Number of cycles        = {NUM_CYCLES}")
    print()
    input("Press Enter when ready...")
    print()

    session = MqttSession(mqtt_host, mqtt_port)
    session.subscribe_sensors()
    print(f"Connected to {mqtt_host}:{mqtt_port}")
    print()

    all_records: list[dict] = []

    for cycle in range(NUM_CYCLES):
        forward_pos = MOVE_DISTANCE if cycle % 2 == 0 else 0
        direction = "FORWARD" if forward_pos > 0 else "BACKWARD"

        print(f"  Cycle {cycle + 1}/{NUM_CYCLES}: {direction} to {forward_pos}...", end=" ")
        sys.stdout.flush()

        session.publish_control({"position": forward_pos})
        samples = session.collect_samples(SETTLE_S * 2)
        for s in samples:
            s["_cmd_position"] = forward_pos
            s["_cycle"] = cycle

        if samples:
            actual = samples[-1].get("stepper_position", "?")
            print(f"actual {actual} ({len(samples)} samples)")
        else:
            print("no response")

        all_records.extend(samples)

    print("\n  Returning stepper to 0...")
    session.publish_control({"position": 0})

    if not all_records:
        print("No data recorded.")
        session.disconnect()
        return

    # Save raw data
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = data_dir / f"max_frequency_{ts}.csv"
    filename.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["_wall_t", "_cycle", "_cmd_position", "timestamp", "stepper_position"]
    with open(filename, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(fieldnames)
        for rec in all_records:
            w.writerow([
                rec.get("_wall_t", ""),
                rec.get("_cycle", ""),
                rec.get("_cmd_position", ""),
                rec.get("timestamp", ""),
                rec.get("stepper_position", ""),
            ])
    print(f"\nRaw data saved to {filename}")
    print()

    # Extract positions and wall times
    positions = np.array([r.get("stepper_position", 0) for r in all_records], dtype=float)
    wall_times = np.array([r.get("_wall_t", 0) for r in all_records], dtype=float)

    result = estimate_max_frequency_from_profile(positions, wall_times)

    print("=" * 60)
    print("Results")
    print("=" * 60)
    print()

    if "error" in result:
        print(f"  Analysis error: {result['error']}")
    else:
        print(f"  Max measured speed:  {result['max_measured_speed']:7.1f} steps/sec")
        print(f"  P90 speed:           {result['p90_speed']:7.1f} steps/sec")
        print(f"  P95 speed:           {result['p95_speed']:7.1f} steps/sec")
        print(f"  Mean top-10% speed:  {result['mean_top10_speed']:7.1f} steps/sec")
        print(f"  Valid samples:       {result['n_valid_samples']}")
        print()

        p95 = result["p95_speed"]
        if p95 >= CONFIG_MAX_SPEED * 0.95:
            print(f"  Stepper reliably achieves {CONFIG_MAX_SPEED} steps/sec")
            recommended = CONFIG_MAX_SPEED
        elif p95 >= CONFIG_MAX_SPEED * 0.8:
            print(f"  Stepper nearly achieves {CONFIG_MAX_SPEED} steps/sec (p95={p95:.0f})")
            recommended = p95
        else:
            print(f"  Stepper struggles at {CONFIG_MAX_SPEED} steps/sec (p95={p95:.0f})")
            recommended = p95

        print()
        print(f"  Recommended STEPPER_MAX_SPEED: {recommended:.0f} steps/sec")
        print()

    # Save to shared stepper calibration file
    if "error" not in result:
        update_stepper_calibration(HERE, {
            "version": 1,
            "calibrated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "stepper_max_frequency": float(recommended),
            "stepper_max_frequency_measured": float(p95),
        })

    # Output config recommendations
    print()
    print("-" * 60)
    print("Configuration Update Guide")
    print("-" * 60)
    print()
    print("Update ESP32 firmware (esp32/src/config.h):")
    if "error" not in result:
        print(f"  #define STEPPER_MAX_SPEED    {recommended:.0f}f   // steps/sec (calibrated)")
    print()
    print("Update Python config (src/wing_twin/config/calibration.py):")
    if "error" not in result:
        print(f"  stepper_max_frequency: float = {recommended:.0f}.0  # Hz (calibrated max step rate)")
    print()
    print(f"Test data saved to: {filename}")

    session.disconnect()


def main():
    parser = argparse.ArgumentParser(description="Stepper max-frequency test")
    parser.add_argument("--mqtt-host", default="localhost", help="MQTT broker host")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker port")
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
        data_dir=args.data_dir,
    )


if __name__ == "__main__":
    main()
