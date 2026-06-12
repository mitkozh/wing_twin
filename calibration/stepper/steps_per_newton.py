"""
Steps-per-newton calibration for the stepper motor.

Determines the relationship between stepper position (steps) and
the equivalent aerodynamic force (Newtons) on the wing.

How it works:
    1. Tare strain gauges at stepper position 0 (no load).
    2. Command the stepper through a range of positions.
    3. At each position, record strain from the gauges.
    4. Convert strain -> force using the per-channel strain calibration
       (from calibration/strain/calibration_data.json) and the FEA H matrix.
    5. Linear regression: stepper_position = steps_per_newton x force.
    6. Prompt for max Newtons the wing should experience -> calculate
       stepper_wing_safe_limit = max_newtons x steps_per_newton.
    7. Save to stepper_calibration.json (auto-loaded by the engine).

Prerequisites:
    - Strain calibration must exist at calibration/strain/calibration_data.json
      (run `python -m calibration.strain.collect` and `python -m calibration.strain.analyze`)
    - Wing must be attached to the stepper
    - ESP32 must be powered and connected to MQTT
    - Mosquitto broker must be running on port 1883

Usage:
    python -m calibration.stepper.steps_per_newton --mqtt-host localhost
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from calibration.stepper.mqtt_helpers import (
    MqttSession,
    load_stepper_calibration,
    update_stepper_calibration,
)

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent

G = 9.81

STEPPER_POSITIONS = [0, 200, 400, 600, 800, 1000, 1200, 1400, 1600, 1800, 2000, 2200, 2400, 2600, 2720]

CHANNEL_NAMES = [
    "root_0", "root_45", "root_90",
    "middle_0", "middle_45", "middle_90",
    "tip_0", "tip_45", "tip_90",
]


def load_strain_calibration() -> np.ndarray | None:
    """Load per-channel ADC-to-strain scale from calibration file."""
    calib_path = HERE.parent / "strain" / "calibration_data.json"
    if not calib_path.exists():
        return None
    with open(calib_path) as f:
        data = json.load(f)
    raw = data.get("per_channel_adc_to_strain_scale")
    if raw is None or len(raw) != 9:
        return None
    return np.array(raw, dtype=np.float64)


def load_h_matrix() -> np.ndarray | None:
    """Load FEA H matrix (relates tip force to per-channel strain)."""
    transfer_dir = PROJECT_ROOT / "transfer_matrices"
    h_path = transfer_dir / "H.npy"
    if not h_path.exists():
        return None
    H = np.load(h_path)
    if H.shape != (9, 1):
        return None
    return H.astype(np.float64)


def collect_stepper_sweep(session: MqttSession, positions, duration_s, data_dir):
    """Command stepper to each position and record strain at each."""
    print("\n" + "=" * 60)
    print("Stepper Sweep - measure strain at each position")
    print("=" * 60)
    print("No weights needed. The strain gauges + FEA H matrix will")
    print("provide the force reference.")
    print()

    all_records = []

    for pos in positions:
        print(f"\n--- Stepper position {pos} ---")
        print(f"  Moving stepper to {pos}...")
        session.publish_control({"position": pos})
        time.sleep(0.5)

        samples = session.collect_samples(duration_s)
        if not samples:
            print("  No data received - skipping")
            continue
        for s in samples:
            s["_stepper_cmd"] = pos
        all_records.extend(samples)
        actual = samples[-1].get("stepper_position", "?")
        print(f"  Collected {len(samples)} samples (actual pos: {actual})")

    print("\n  Returning stepper to 0...")
    session.publish_control({"position": 0})

    return all_records


def analyze(results_csv: Path, data_dir: Path) -> float | None:
    """Analyze collected data: strain -> force -> regress steps vs force."""
    print("\n" + "=" * 60)
    print("Analysis")
    print("=" * 60)
    print()

    # Load calibration data
    per_channel_scale = load_strain_calibration()
    if per_channel_scale is None:
        print("  [ERROR] No strain calibration found at calibration/strain/calibration_data.json")
        print("  Run: python -m calibration.strain.collect  then  python -m calibration.strain.analyze")
        return None
    print(f"  Loaded strain calibration ({len(per_channel_scale)} channels)")

    H = load_h_matrix()
    if H is None:
        print("  [ERROR] FEA H matrix not found at transfer_matrices/H.npy")
        return None
    print(f"  Loaded FEA H matrix, shape {H.shape}")

    # Load CSV
    stepper_data: dict[int, list[np.ndarray]] = {}
    tare_raw: np.ndarray | None = None

    with open(results_csv, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cmd = int(row["_stepper_cmd"])
            compensated = np.array([
                float(row[f"raw_{i}"]) - float(row["dummy_raw"]) - float(row[f"offset_{i}"])
                for i in range(9)
            ], dtype=np.float64)
            if cmd not in stepper_data:
                stepper_data[cmd] = []
            stepper_data[cmd].append(compensated)

    for k in stepper_data:
        stepper_data[k] = np.mean(stepper_data[k], axis=0)

    if 0 not in stepper_data:
        print("  [ERROR] No tare (position 0) data found")
        return None
    tare_raw = stepper_data.pop(0)

    print(f"\n  Stepper positions analyzed: {sorted(stepper_data.keys())}")
    print()

    # Convert strain to force for each stepper position
    #   strain = ADC_raw * per_channel_scale  (per channel)
    #   force at tip = strain / H             (FEA relationship)
    # We use the channel with the strongest signal

    forces: list[float] = []
    positions: list[int] = []

    for cmd in sorted(stepper_data.keys()):
        net_raw = stepper_data[cmd] - tare_raw
        strain = net_raw * per_channel_scale       # per-channel strain

        # Infer force from each channel using FEA: F = strain / H
        # Avoid division by zero (dead channel)
        channel_forces = []
        for ch in range(9):
            h_val = float(H[ch, 0])
            if abs(h_val) > 1e-12:
                channel_forces.append(strain[ch] / h_val)

        if not channel_forces:
            print(f"  Stepper {cmd:5d}: no valid channels for force inference - skipping")
            continue

        # Use median force across channels (robust to outliers)
        F_median = float(np.median(channel_forces))
        F_iqr = float(np.percentile(channel_forces, 75) - np.percentile(channel_forces, 25))

        forces.append(F_median)
        positions.append(cmd)

        # Show contributing channels
        ch_str = ", ".join(
            f"{CHANNEL_NAMES[ch]}:{strain[ch]/h_val:.4f} N"
            for ch in range(9)
            if abs(float(H[ch, 0])) > 1e-12
        )
        print(f"  Stepper {cmd:5d} ->  F = {F_median:7.4f} N  (IQR={F_iqr:.4f})  [{ch_str}]")

    if len(forces) < 2:
        print("\n  [ERROR] Need at least 2 valid stepper positions for regression")
        return None

    x_vals = np.array(forces, dtype=np.float64)
    y_vals = np.array(positions, dtype=np.float64)

    # Constrained through origin: y = m * x
    m = float(np.dot(x_vals, y_vals) / np.dot(x_vals, x_vals))
    y_pred = x_vals * m
    ss_res = np.sum((y_vals - y_pred) ** 2)
    ss_tot = np.sum((y_vals - np.mean(y_vals)) ** 2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    rmse = float(np.sqrt(ss_res / len(x_vals)))

    print()
    print("=" * 60)
    print("Calibration Result")
    print("=" * 60)
    print(f"  steps_per_newton = {m:.4f}")
    print(f"  R²  = {r2:.4f}")
    print(f"  RMSE = {rmse:.2f} steps")
    print(f"  Data points: {len(forces)}")
    print()
    print(f"  Regression line: steps = {m:.4f} × force (N)")

    # Save steps_per_newton
    update_stepper_calibration(HERE, {
        "version": 1,
        "calibrated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "steps_per_newton": round(m, 4),
        "r_squared": round(r2, 4),
        "rmse_steps": round(rmse, 2),
        "data_points": len(forces),
        "force_step_pairs": [(round(f, 4), int(s)) for f, s in zip(forces, positions)],
    })
    print("\n  steps_per_newton saved to stepper_calibration.json")
    print()

    return m


def main():
    parser = argparse.ArgumentParser(
        description="Steps-per-newton calibration (no weights needed)"
    )
    parser.add_argument("--mqtt-host", default="localhost", help="MQTT broker host")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument(
        "--positions",
        default="0,200,400,600,800,1000,1200,1400,1600,1800,2000,2200,2400,2600,2720",
        help="Comma-separated stepper positions to test (first should be 0 = tare)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=5.0,
        help="Recording duration per position in seconds",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=HERE / "data",
        help="Output directory for CSV files",
    )
    parser.add_argument(
        "--max-newtons",
        type=float,
        default=None,
        help="Max Newtons the wing should experience (prompted if not set)",
    )
    parser.add_argument(
        "--analyze-only",
        type=Path,
        default=None,
        help="Skip collection, analyze existing CSV at this path",
    )
    args = parser.parse_args()

    positions = [int(p.strip()) for p in args.positions.split(",")]

    data_dir = args.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    results_csv = data_dir / f"steps_per_newton_{ts}.csv"

    if args.analyze_only:
        results_csv = args.analyze_only
    else:
        print("=" * 60)
        print("Steps-per-Newton Calibration")
        print("=" * 60)
        print()
        print("Prerequisites:")
        print("  1. Strain calibration must exist (calibration/strain/calibration_data.json)")
        print("  2. Wing must be attached to the stepper")
        print("  3. ESP32 must be powered and connected to MQTT")
        print("  4. Stepper should start at position 0")
        print()
        print("No weights are needed. The strain gauges + FEA H matrix")
        print("provide the force reference.")
        print()
        input("Press Enter when ready...")

        session = MqttSession(args.mqtt_host, args.mqtt_port)
        session.subscribe_sensors()
        print(f"Connected to {args.mqtt_host}:{args.mqtt_port}")

        records = collect_stepper_sweep(session, positions, args.duration, data_dir)

        if not records:
            print("No data collected - aborting.")
            session.disconnect()
            return

        fieldnames = [
            "_stepper_cmd",
            "_wall_t", "timestamp", "stepper_position", "dummy_raw",
            *[f"raw_{i}" for i in range(9)],
            *[f"offset_{i}" for i in range(9)],
            *[f"saturated_{i}" for i in range(9)],
        ]
        with open(results_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(fieldnames)
            for rec in records:
                raw = rec.get("raw", [0] * 9)
                off = rec.get("offset", [0.0] * 9)
                sat = rec.get("saturated", [False] * 9)
                row = [
                    rec.get("_stepper_cmd", ""),
                    rec.get("_wall_t", 0),
                    rec.get("timestamp", 0),
                    rec.get("stepper_position", 0),
                    rec.get("dummy_raw", 0),
                ]
                row.extend(raw[:9])
                row.extend(off[:9])
                row.extend(sat[:9])
                w.writerow(row)

        print(f"\nAll data saved to {results_csv}")
        session.disconnect()

    spn = analyze(results_csv, data_dir)
    if spn is None:
        return

    # Wing safe limit
    print()
    print("=" * 60)
    print("Wing Safe Limit")
    print("=" * 60)
    print()
    print(f"  Calibrated steps_per_newton = {spn:.4f}")
    print()
    print("  The wing safe limit is the maximum stepper position")
    print("  allowed to prevent wing damage.")
    print(f"  wing_limit = max_newtons × {spn:.4f}")
    print()

    if args.max_newtons is not None:
        max_n = args.max_newtons
    else:
        max_n_input = input("  Enter max Newtons for wing (default 5.0): ")
        max_n = float(max_n_input) if max_n_input.strip() else 5.0

    wing_limit = int(round(max_n * spn))

    # Clamp to motor max if known
    existing = load_stepper_calibration(HERE)
    motor_max = existing.get("stepper_motor_max_steps")
    if motor_max is not None:
        if wing_limit > motor_max:
            print(f"\n Calculated limit ({wing_limit}) exceeds motor max ({motor_max}) - clamping")
            wing_limit = motor_max
    else:
        print("\n  Motor max not yet calibrated (run range_test first)")
        print(f"     Wing limit set to {wing_limit} - verify manually")

    print(f"\n  Max force:          {max_n:.2f} N")
    print(f"  Steps per Newton:   {spn:.4f}")
    print(f"  Wing safe limit:    {wing_limit} steps")
    print()

    update_stepper_calibration(HERE, {
        "stepper_wing_safe_limit": wing_limit,
        "max_newtons_calibrated": max_n,
    })
    print()
    print("  All stepper calibration values saved.")
    print("  Restart the engine to pick up the new values.")


if __name__ == "__main__":
    main()
