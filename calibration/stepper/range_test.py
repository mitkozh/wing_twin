"""
Stepper range calibration.

Calculates the motor's physical step limits from the mechanical setup.

Drive system: direct-drive winch - the motor shaft has a stepped drum
(16/26/40 mm diameters), and the fishing wire wraps directly around one
of the sections. No belt, no gears.

    Step angle            = 1.8°  (NEMA23)
    Full steps per rev    = 360° / 1.8° = 200
    Microstepped steps    = 200 x microstepping  (e.g. 200 x 8 = 1600)
    Wire per motor rev    = π x drum_diameter
    Steps per mm          = steps_per_rev / wire_per_rev
    Max steps             = travel_mm x steps_per_mm

Note: wire layers on the drum increase the effective diameter. The
calculation uses the bare drum diameter. If multiple layers build up,
the steps-per-mm will change. For best accuracy, use the empirical
method: command N steps and measure actual wire travel.

Usage:
    python -m calibration.stepper.range_test                     # interactive
    python -m calibration.stepper.range_test --microstep 8       # skip prompts
"""

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
)

HERE = Path(__file__).resolve().parent
STEP_ANGLE_DEG = 1.8                          # NEMA23 standard
FULL_STEPS_PER_REV = int(round(360 / STEP_ANGLE_DEG))  # 360 / 1.8 = 200


def _prompt_float(prompt: str, default: float | None = None) -> float:
    while True:
        raw = input(prompt).strip()
        if not raw and default is not None:
            return default
        try:
            return float(raw)
        except ValueError:
            print("  Please enter a number.")


def _prompt_int(prompt: str, default: int | None = None) -> int:
    while True:
        raw = input(prompt).strip()
        if not raw and default is not None:
            return default
        try:
            return int(raw)
        except ValueError:
            print("  Please enter an integer.")


def method_calculation(microstep: int) -> dict:
    print()
    print("  Drive system: direct-drive winch (stepped drum on motor shaft)")
    print()

    drum_d = _prompt_float("  Drum diameter - wire section (mm) [26.0]: ", 26.0)

    steps_per_rev = FULL_STEPS_PER_REV * microstep  # 200 × 8 = 1600
    wire_per_rev = 3.14159 * drum_d
    steps_per_mm = steps_per_rev / wire_per_rev

    print(f"    Steps per rev:     {steps_per_rev}")
    print(f"    Wire per rev:      {wire_per_rev:.2f} mm")
    print(f"    Steps per mm:      {steps_per_mm:.2f}")
    print()

    total_travel = _prompt_float("  Total linear travel (mm): ")

    max_steps = int(round(total_travel * steps_per_mm))

    print()
    print(f"  Max steps (one-way): {max_steps}")
    print()

    return {
        "method": "calculated",
        "drum_diameter_mm": drum_d,
        "microstepping": microstep,
        "steps_per_rev": steps_per_rev,
        "wire_per_rev_mm": round(wire_per_rev, 2),
        "steps_per_mm": round(steps_per_mm, 2),
        "linear_travel_mm": total_travel,
        "stepper_motor_max_steps": max_steps,
        "stepper_motor_min_steps": 0,
    }


def method_empirical(microstep: int, mqtt_host: str, mqtt_port: int) -> dict:
    print()
    print("  Empirical method: command N steps, measure wire travel")
    print()

    session = MqttSession(mqtt_host, mqtt_port)
    session.subscribe_sensors()
    print(f"  Connected to {mqtt_host}:{mqtt_port}")
    print()

    n_steps = _prompt_int("  How many steps to command? (e.g. 1000): ", 1000)

    print(f"\n  Commanding {n_steps} steps forward to {n_steps} ...")
    session.publish_control({"position": 0})
    time.sleep(1)

    input("  Mark the wire position, then press Enter...")

    session.publish_control({"position": n_steps})
    time.sleep(3)

    measured = _prompt_float("  How far did the wire move (mm)? ")

    print("  Returning to 0 ...")
    session.publish_control({"position": 0})
    time.sleep(1)
    session.disconnect()

    steps_per_mm = n_steps / measured if measured > 0 else 0
    print(f"\n  Steps per mm: {steps_per_mm:.2f} ({n_steps} steps / {measured} mm)")
    print()

    total_travel = _prompt_float("  Total linear travel (mm): ")

    max_steps = int(round(total_travel * steps_per_mm))
    print(f"\n  Max steps (one-way): {max_steps}")

    return {
        "method": "empirical",
        "empirical_steps_commanded": n_steps,
        "empirical_travel_mm": measured,
        "microstepping": microstep,
        "steps_per_mm": round(steps_per_mm, 2),
        "linear_travel_mm": total_travel,
        "stepper_motor_max_steps": max_steps,
        "stepper_motor_min_steps": 0,
    }


def verify(
    result: dict,
    mqtt_host: str,
    mqtt_port: int,
) -> None:
    max_steps = result["stepper_motor_max_steps"]
    print()
    print("  Verification: the stepper will move to the calculated limits.")
    print("  Watch the mechanism and confirm it stops before binding.")
    print()

    session = MqttSession(mqtt_host, mqtt_port)
    session.subscribe_sensors()

    print(f"  Moving to MAX ({max_steps:+d}) ...", end=" ")
    sys.stdout.flush()
    session.publish_control({"position": max_steps})
    time.sleep(3)
    ok = input("  Safe? (y/n): ").strip().lower()
    if ok != "y":
        print("  Aborting. Re-measure and try again.")
        session.disconnect()
        return

    print("  Returning to 0 ...")
    session.publish_control({"position": 0})
    time.sleep(1)
    session.disconnect()
    print("  Verification passed.")
    print()


def run(
    mqtt_host: str,
    mqtt_port: int,
    microstep: int | None,
    method: str | None,
    verify_flag: bool,
) -> None:
    print("=" * 60)
    print("Stepper Range Calibration")
    print("=" * 60)
    print()

    if microstep is None:
        microstep = _prompt_int(
            "  Microstepping (1, 2, 4, 8, 16, 32) [8]: ", 8
        )
        while microstep not in (1, 2, 4, 8, 16, 32):
            microstep = _prompt_int("  Must be 1, 2, 4, 8, 16, or 32: ")

    print()

    if method is None:
        print("  Choose method:")
        print("    [c]  Calculate from drum diameter + travel")
        print("    [e]  Empirical: command N steps, measure travel")
        choice = input("  Method (c/e) [c]: ").strip().lower() or "c"
        method = "calculate" if choice == "c" else "empirical"

    if method == "calculate":
        result = method_calculation(microstep)
    else:
        if not mqtt_host:
            print("  MQTT host required for empirical method.")
            return
        result = method_empirical(microstep, mqtt_host, mqtt_port)

    if verify_flag and mqtt_host:
        verify(result, mqtt_host, mqtt_port)

    update_stepper_calibration(HERE, {
        "version": 1,
        "calibrated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **result,
    })

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    csv_path = HERE / "data" / f"range_calib_{ts}.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["parameter", "value"])
        for k, v in result.items():
            w.writerow([k, v])
    print(f"  CSV saved to {csv_path}")
    print()
    print("  Make sure to update the firmware limit:")
    print(f"    STEPPER_MAX_POSITION  {result['stepper_motor_max_steps']}")
    print(f"    STEPPER_MIN_POSITION  0")
    print("  in esp32_stepper/src/config.h and reflash the ESP32.")
    print()
    print("  Next steps:")
    print("    python -m calibration.stepper.max_frequency")
    print("    python -m calibration.stepper.steps_per_newton")


def main():
    parser = argparse.ArgumentParser(
        description="Stepper range calibration"
    )
    parser.add_argument("--mqtt-host", default="localhost")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument(
        "--microstep", type=int, default=None,
        help="Microstepping setting (1, 2, 4, 8, 16, 32)",
    )
    parser.add_argument(
        "--method", choices=["calculate", "empirical"], default=None,
    )
    parser.add_argument(
        "--verify", action="store_true",
        help="Move motor to calculated limits to confirm they are safe",
    )
    args = parser.parse_args()

    run(
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
        microstep=args.microstep,
        method=args.method,
        verify_flag=args.verify,
    )


if __name__ == "__main__":
    main()
