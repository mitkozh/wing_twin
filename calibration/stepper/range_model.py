from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from calibration.stepper.mqtt_helpers import (
    update_stepper_calibration,
    MODEL_FILE,
)

HERE = Path(__file__).resolve().parent
STEP_ANGLE_DEG = 1.8
FULL_STEPS_PER_REV = int(round(360 / STEP_ANGLE_DEG))


def run(drum_diameter: float, travel: float, microstep: int = 8) -> dict:
    steps_per_rev = FULL_STEPS_PER_REV * microstep
    wire_per_rev = 3.14159 * drum_diameter
    steps_per_mm = steps_per_rev / wire_per_rev
    max_steps = int(round(travel * steps_per_mm))

    print("=" * 60)
    print("Stepper Range (Model)")
    print("=" * 60)
    print()
    print(f"  Drum diameter:             {drum_diameter} mm")
    print(f"  Microstepping:             {microstep}")
    print(f"  Steps per rev:             {steps_per_rev}")
    print(f"  Wire per rev:              {wire_per_rev:.2f} mm")
    print(f"  Steps per mm:              {steps_per_mm:.2f}")
    print(f"  Total linear travel:       {travel} mm")
    print(f"  Max steps (one-way):       {max_steps}")
    print()

    result = {
        "method": "model",
        "drum_diameter_mm": drum_diameter,
        "microstepping": microstep,
        "steps_per_rev": steps_per_rev,
        "wire_per_rev_mm": round(wire_per_rev, 2),
        "steps_per_mm": round(steps_per_mm, 2),
        "linear_travel_mm": travel,
        "stepper_motor_max_steps": max_steps,
        "stepper_motor_min_steps": 0,
    }

    update_stepper_calibration(HERE, {
        "version": 1,
        "calibrated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **result,
    }, filename=MODEL_FILE)

    print(f"  To update firmware, set STEPPER_ABSOLUTE_MAX_POSITION = {max_steps}")
    print("  in esp32_stepper/src/config.h and reflash the ESP32.")
    print()

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Model-based stepper range calibration (no hardware)"
    )
    parser.add_argument("--drum-diameter", type=float, default=26.0, help="Drum diameter in mm")
    parser.add_argument("--travel", type=float, default=140.0, help="Total linear travel in mm")
    parser.add_argument("--microstep", type=int, default=8, help="Microstepping (1, 2, 4, 8, 16, 32)")
    args = parser.parse_args()
    run(args.drum_diameter, args.travel, args.microstep)


if __name__ == "__main__":
    main()
