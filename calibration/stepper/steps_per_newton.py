from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from wing_twin.fea.field_compute import compute_force_from_deformation

from calibration.stepper.mqtt_helpers import (
    MqttSession,
    load_stepper_calibration,
    update_stepper_calibration,
    EMPIRICAL_FILE,
)

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent

STEPPER_POSITIONS = [0, 200, 400, 600, 800, 1000, 1200, 1400, 1600, 1800, 2000, 2200, 2400, 2600, 2720]

CHANNEL_NAMES = [
    "root_0", "root_45", "root_90",
    "middle_0", "middle_45", "middle_90",
    "tip_0", "tip_45", "tip_90",
]


def load_strain_calibration() -> np.ndarray | None:
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
    transfer_dir = PROJECT_ROOT / "transfer_matrices"
    h_path = transfer_dir / "H.npy"
    if not h_path.exists():
        return None
    H = np.load(h_path)
    if H.shape != (9, 1):
        return None
    return H.astype(np.float64)


def load_u_matrix() -> np.ndarray | None:
    transfer_dir = PROJECT_ROOT / "transfer_matrices"
    u_path = transfer_dir / "TotalDeformation.npy"
    if not u_path.exists():
        return None
    U = np.load(u_path)
    if U.ndim != 2:
        return None
    return U.astype(np.float64)


def collect_stepper_sweep(session: MqttSession, positions, duration_s, data_dir):
    print("\n" + "=" * 60)
    print("Stepper Sweep - measure strain at each position")
    print("=" * 60)
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


def analyze(results_csv: Path, data_dir: Path, use_deformation: bool = False) -> float | None:
    print("\n" + "=" * 60)
    print("Analysis")
    print("=" * 60)
    print()

    per_channel_scale = load_strain_calibration()
    if per_channel_scale is None:
        print("  [ERROR] No strain calibration at calibration/strain/calibration_data.json")
        print("  Run: python -m calibration.strain.collect  then  python -m calibration.strain.analyze")
        return None
    print(f"  Loaded strain calibration ({len(per_channel_scale)} channels)")

    H = load_h_matrix()
    if H is None:
        print("  [ERROR] H.npy not found in transfer_matrices/")
        return None
    print(f"  Loaded H matrix: {H.shape}")

    U = None
    H_inv = None
    if use_deformation:
        U = load_u_matrix()
        if U is None:
            print("  [ERROR] TotalDeformation.npy not found")
            return None
        print(f"  Loaded U matrix: {U.shape} (deformation-based force)")
        h_inv_path = PROJECT_ROOT / "transfer_matrices" / "Inverse_H.npy"
        if h_inv_path.exists():
            H_inv = np.load(h_inv_path).astype(np.float64)
            print(f"  Loaded H_inv matrix: {H_inv.shape}")
        else:
            print("  [ERROR] Inverse_H.npy not found (needed for deformation method)")
            return None

    stepper_data: dict[int, list[np.ndarray]] = {}
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

    forces: list[float] = []
    positions: list[int] = []

    for cmd in sorted(stepper_data.keys()):
        net_raw = stepper_data[cmd] - tare_raw
        strain = net_raw * per_channel_scale

        if use_deformation:
            F_strain = H_inv @ strain
            deformation = U @ F_strain
            F_def = compute_force_from_deformation(U, deformation)
            F_val = float(F_def[0])
            ch_str = f"deformation: {F_val:.4f} N"
        else:
            channel_forces = []
            for ch in range(9):
                h_val = float(H[ch, 0])
                if abs(h_val) > 1e-12:
                    channel_forces.append(strain[ch] / h_val)
            if not channel_forces:
                print(f"  Stepper {cmd:5d}: no valid channels - skipping")
                continue
            F_val = float(np.median(channel_forces))
            ch_str = ", ".join(
                f"{CHANNEL_NAMES[ch]}:{strain[ch]/h_val:.4f} N"
                for ch in range(9)
                if abs(float(H[ch, 0])) > 1e-12
            )

        forces.append(F_val)
        positions.append(cmd)
        print(f"  Stepper {cmd:5d} ->  F = {F_val:7.4f} N  [{ch_str}]")

    if len(forces) < 2:
        print("\n  [ERROR] Need at least 2 valid stepper positions for regression")
        return None

    x_vals = np.array(forces, dtype=np.float64)
    y_vals = np.array(positions, dtype=np.float64)

    m = float(np.dot(x_vals, y_vals) / np.dot(x_vals, x_vals))
    y_pred = x_vals * m
    ss_res = np.sum((y_vals - y_pred) ** 2)
    ss_tot = np.sum((y_vals - np.mean(y_vals)) ** 2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    rmse = float(np.sqrt(ss_res / len(x_vals)))

    method_label = "Deformation" if use_deformation else "Strain"
    print()
    print("=" * 60)
    print(f"Calibration Result ({method_label})")
    print("=" * 60)
    print(f"  steps_per_newton = {m:.4f}")
    print(f"  R²  = {r2:.4f}")
    print(f"  RMSE = {rmse:.2f} steps")
    print(f"  Data points: {len(forces)}")
    print(f"  Regression: steps = {m:.4f} × force (N)")

    update_stepper_calibration(HERE, {
        "version": 1,
        "calibrated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "steps_per_newton": round(m, 4),
        "r_squared": round(r2, 4),
        "rmse_steps": round(rmse, 2),
        "data_points": len(forces),
        "force_step_pairs": [(round(f, 4), int(s)) for f, s in zip(forces, positions)],
    }, filename=EMPIRICAL_FILE)

    return m


def main():
    parser = argparse.ArgumentParser(
        description="Empirical steps-per-newton calibration (needs hardware)"
    )
    parser.add_argument("--mqtt-host", default="localhost")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--max-newtons", type=float, default=None)
    parser.add_argument("--use-deformation", action="store_true")
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--data-dir", type=Path, default=HERE / "data")
    parser.add_argument(
        "--positions",
        default="0,200,400,600,800,1000,1200,1400,1600,1800,2000,2200,2400,2600,2720",
    )
    parser.add_argument("--analyze-only", type=Path, default=None)
    parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompts")
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
        print("Steps-per-Newton (Empirical)")
        print("=" * 60)
        print()
        print("Prerequisites:")
        print("  1. Strain calibration must exist (calibration/strain/calibration_data.json)")
        print("  2. Wing attached to stepper, ESP32 powered, MQTT connected")
        print()
        if not args.yes:
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
            "_stepper_cmd", "_wall_t", "timestamp", "stepper_position", "dummy_raw",
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

    spn = analyze(results_csv, data_dir, use_deformation=args.use_deformation)
    if spn is None:
        return

    if args.max_newtons is not None:
        max_n = args.max_newtons
        wing_limit = int(round(max_n * spn))
        existing = load_stepper_calibration(HERE, EMPIRICAL_FILE)
        motor_max = existing.get("stepper_motor_max_steps")
        if motor_max is not None and wing_limit > motor_max:
            wing_limit = motor_max
        update_stepper_calibration(HERE, {
            "stepper_wing_safe_limit": wing_limit,
            "max_newtons_calibrated": max_n,
        }, filename=EMPIRICAL_FILE)
        print(f"\n  Max force:          {max_n:.2f} N")
        print(f"  Steps per Newton:   {spn:.4f}")
        print(f"  Wing safe limit:    {wing_limit} steps")
        print()
    else:
        print("\n  Pass --max-newtons to compute the safe wing limit.")
        print()

    print("  All values saved to stepper_calibration_empirical.json")
    print("  Restart the engine to pick up the new values.")


if __name__ == "__main__":
    main()
