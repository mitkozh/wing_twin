from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from calibration.stepper.mqtt_helpers import (
    MqttSession,
    update_stepper_calibration,
    EMPIRICAL_FILE,
)

HERE = Path(__file__).resolve().parent


def run(mqtt_host: str, mqtt_port: int, microstep: int) -> None:
    print("=" * 60)
    print("Stepper Range (Empirical)")
    print("=" * 60)
    print()

    session = MqttSession(mqtt_host, mqtt_port)
    session.subscribe_sensors()
    print(f"  Connected to {mqtt_host}:{mqtt_port}")
    print()

    n_steps = int(input("  How many steps to command? (e.g. 1000): ") or 1000)

    print(f"\n  Commanding {n_steps} steps forward to {n_steps} ...")
    session.publish_control({"position": 0})
    time.sleep(1)

    input("  Mark the wire position, then press Enter...")

    session.publish_control({"position": n_steps})
    time.sleep(3)

    measured = float(input("  How far did the wire move (mm)? "))

    print("  Returning to 0 ...")
    session.publish_control({"position": 0})
    time.sleep(1)
    session.disconnect()

    steps_per_mm = n_steps / measured if measured > 0 else 0
    print(f"\n  Steps per mm: {steps_per_mm:.2f} ({n_steps} steps / {measured} mm)")
    print()

    total_travel = float(input("  Total linear travel (mm): "))

    max_steps = int(round(total_travel * steps_per_mm))
    print(f"\n  Max steps (one-way): {max_steps}")

    result = {
        "method": "empirical",
        "empirical_steps_commanded": n_steps,
        "empirical_travel_mm": measured,
        "microstepping": microstep,
        "steps_per_mm": round(steps_per_mm, 2),
        "linear_travel_mm": total_travel,
        "stepper_motor_max_steps": max_steps,
        "stepper_motor_min_steps": 0,
    }

    update_stepper_calibration(HERE, {
        "version": 1,
        "calibrated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **result,
    }, filename=EMPIRICAL_FILE)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    csv_path = HERE / "data" / f"range_empirical_{ts}.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["parameter", "value"])
        for k, v in result.items():
            w.writerow([k, v])
    print(f"  CSV saved to {csv_path}")
    print()
    print("  Make sure to update the firmware hardware limit:")
    print(f"    STEPPER_ABSOLUTE_MAX_POSITION  {max_steps}")
    print("    STEPPER_MIN_POSITION          0")
    print("  in esp32_stepper/src/config.h and reflash the ESP32.")


def main():
    parser = argparse.ArgumentParser(
        description="Empirical stepper range calibration (needs hardware)"
    )
    parser.add_argument("--mqtt-host", default="131.155.209.40")
    parser.add_argument("--mqtt-port", type=int, default=1884)
    parser.add_argument("--microstep", type=int, default=8, help="Microstepping (1, 2, 4, 8, 16, 32)")
    args = parser.parse_args()

    if args.microstep not in (1, 2, 4, 8, 16, 32):
        print("  Microstepping must be 1, 2, 4, 8, 16, or 32")
        return

    run(args.mqtt_host, args.mqtt_port, args.microstep)


if __name__ == "__main__":
    main()
