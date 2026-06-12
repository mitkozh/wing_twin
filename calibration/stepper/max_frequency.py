"""
Manual stepper max-frequency test.


    1. The stepper moves back-and-forth at increasing step rates
    2. At each speed, you observe (listen for stall buzz, watch wire)
    3. Press   [p]   if the move was clean (pass)
    4. Press   [f]   if the motor stalled or skipped steps (fail)
    5. The last passing speed is saved as stepper_max_frequency

You can also note the voltage at the driver supply (VMD) when stalling
occurs, to find the practical voltage limit.

Usage:
    python -m calibration.stepper.max_frequency --mqtt-host localhost

Options:
    --start 100       Starting speed in steps/sec (default: 100)
    --end 2000        Ending speed in steps/sec (default: 2000)
    --step 100        Speed increment per cycle (default: 100)
    --move 1000       Move distance in steps per half-cycle (default: 1000)
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


def run_manual(
    mqtt_host: str,
    mqtt_port: int,
    start_speed: int,
    end_speed: int,
    step: int,
    move_distance: int,
) -> None:
    print("=" * 60)
    print("Manual Max Frequency Test")
    print("=" * 60)
    print()
    print("The stepper will move back-and-forth at increasing speeds.")
    print()
    print("  At each speed, watch and listen for stall:")
    print("    - Clean pass: press  p")
    print("    - Stall / skipped steps: press  f")
    print("  Or press  q  to quit early.")
    print()
    print("You can also note the supply voltage (VMD) when stalling")
    print("to identify the practical voltage limit of your setup.")
    print()

    input("Press Enter when ready...")
    print()

    session = MqttSession(mqtt_host, mqtt_port)
    session.subscribe_sensors()
    print(f"Connected to {mqtt_host}:{mqtt_port}")

    session.publish_control({"acceleration": 2000.0})
    time.sleep(0.2)

    print()
    print(f"  Start:  {start_speed} steps/s")
    print(f"  End:    {end_speed} steps/s")
    print(f"  Step:   {step} steps/s")
    print(f"  Move:   {move_distance} steps per half-cycle")
    print(f"  Accel:  2000 steps/s² (overridden for test)")
    print()

    last_pass = None
    results: list[dict] = []

    speed = start_speed
    while speed <= end_speed:
        print(f"\n--- Speed: {speed} steps/s ---")

        session.publish_control({"speed": float(speed)})
        time.sleep(0.2)

        for direction, cmd_pos in [("Forward", move_distance), ("Back", 0)]:
            print(f"  {direction} to {cmd_pos} ...", end=" ")
            sys.stdout.flush()
            session.publish_control({"position": cmd_pos})
            time.sleep(1.5)

            if speed == start_speed and direction == "Forward":
                actual = session.latest_stepper_pos
                print(f"pos={actual}")
            else:
                print("done")

        while True:
            key = input("  Result (p/f/q): ").strip().lower()
            if key in ("p",):
                print(f"  -> PASS at {speed} steps/s")
                last_pass = speed
                results.append({"speed": speed, "passed": True})
                break
            elif key in ("f",):
                print(f"  -> FAIL at {speed} steps/s")
                results.append({"speed": speed, "passed": False})
                break
            elif key in ("q",):
                print("  Quitting early.")
                results.append({"speed": speed, "passed": False, "quit": True})
                break
            else:
                print("  Press p (pass), f (fail), or q (quit)")

        if key == "q":
            break

        speed += step

    # Return to zero
    print("\n  Returning to 0 ...")
    session.publish_control({"position": 0})
    time.sleep(1)
    session.disconnect()

    # Results
    print()
    print("=" * 60)
    print("Results")
    print("=" * 60)
    print()

    passes = [r for r in results if r.get("passed")]
    fails = [r for r in results if not r.get("passed")]

    for r in results:
        label = "PASS" if r.get("passed") else "FAIL"
        print(f"  {label:4s}  {r['speed']} steps/s")

    print()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    csv_path = HERE / "data" / f"max_frequency_{ts}.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["speed", "passed"])
        for r in results:
            w.writerow([r["speed"], r.get("passed", False)])
    print(f"  CSV saved to {csv_path}")

    if last_pass is not None:
        recommended = last_pass
        print(f"  Last passing speed:  {last_pass} steps/s")
        print(f"  Recommended max frequency:  {recommended} steps/s")
        print()

        update_stepper_calibration(HERE, {
            "version": 1,
            "calibrated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "stepper_max_frequency": float(recommended),
        })

        print("  Saved to stepper_calibration.json")
        print()
        print("  Update firmware config.h:")
        print(f"    #define STEPPER_MAX_SPEED  {recommended}.0f")
        print("  and reflash the ESP32.")
    else:
        print("  No passing speeds recorded - try a lower start speed.")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Manual stepper max-frequency test"
    )
    parser.add_argument("--mqtt-host", default="localhost")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--start", type=int, default=100, help="Start speed (steps/s)")
    parser.add_argument("--end", type=int, default=2000, help="End speed (steps/s)")
    parser.add_argument("--step", type=int, default=100, help="Speed increment (steps/s)")
    parser.add_argument(
        "--move", type=int, default=1000,
        help="Move distance per half-cycle (steps)",
    )
    args = parser.parse_args()

    run_manual(
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
        start_speed=args.start,
        end_speed=args.end,
        step=args.step,
        move_distance=args.move,
    )


if __name__ == "__main__":
    main()
