"""
Regression analysis for strain gauge calibration.

Loads collected sensor CSV files and the FEA H matrix,
performs per-channel linear regression, and saves the
calibration data file.

Usage:
    python -m calibration_regression.analyze --data-dir calibration_regression/data
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent


def _find_project_root() -> Path:
    current = HERE
    for parent in [current] + list(current.parents):
        if (parent / "pyproject.toml").exists():
            return parent
    return current.parent


G = 9.81  # gravitational acceleration, m/s²

CHANNEL_NAMES = [
    "root_0", "root_45", "root_90",
    "middle_0", "middle_45", "middle_90",
    "tip_0", "tip_45", "tip_90",
]


def load_h_matrix(transfer_dir: Path) -> np.ndarray:
    H = np.load(transfer_dir / "H.npy")
    if H.shape != (9, 1):
        raise ValueError(f"Expected H shape (9, 1), got {H.shape}")
    # Convert float32 → float64 for precision
    return H.astype(np.float64)


def load_data_files(data_dir: Path) -> dict[float, np.ndarray]:
    """Load CSV files, return {weight_g: averaged_compensated_raw[9]}."""
    csv_files = sorted(data_dir.glob("*_*g.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {data_dir}")

    results: dict[float, np.ndarray] = {}
    for fp in csv_files:
        stem = fp.stem
        # Parse weight from filename like "20260610T120000Z_500g"
        try:
            weight_part = stem.split("_")[-1]
            weight_g = float(weight_part.replace("g", ""))
        except (ValueError, IndexError):
            print(f"  [skip] cannot parse weight from {fp.name}")
            continue

        records: list[np.ndarray] = []
        with open(fp, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                compensated = np.array([
                    float(row[f"raw_{i}"]) - float(row["dummy_raw"]) - float(row[f"offset_{i}"])
                    for i in range(9)
                ], dtype=np.float64)
                saturated = [row.get(f"saturated_{i}", "False").strip().lower() == "true" for i in range(9)]
                # Zero out saturated channels
                for i in range(9):
                    if saturated[i]:
                        compensated[i] = 0.0
                records.append(compensated)

        if not records:
            print(f"  [skip] {fp.name} has no valid records")
            continue

        averaged = np.mean(records, axis=0)
        results[weight_g] = averaged
        n = len(records)
        nonzero = np.count_nonzero(averaged)
        print(f"  {fp.name}: {n} samples, {nonzero}/9 channels active")

    return results


def compute_scale_factors(
    weight_data: dict[float, np.ndarray],
    H: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Per-channel linear regression.

    For each channel i:
      compensated_raw[w] * scale_i = sigma_expected[w,i] = H[i,0] * (w * g)

    Least-squares:
      scale_i = Sigma(H[i,0] * w * g * compensated_raw[w,i]) / Sigma(compensated_raw[w,i]^2)
    """
    weights_g = sorted(weight_data.keys())
    n_channels = 9

    # Remove tare from all readings
    if 0.0 in weight_data:
        tare_raw = weight_data[0.0]
    else:
        print("  [WARN] no tare (0g) data found — using first weight as baseline")
        tare_raw = weight_data[weights_g[0]]

    scale = np.zeros(n_channels, dtype=np.float64)
    r2 = np.zeros(n_channels, dtype=np.float64)
    rmse = np.zeros(n_channels, dtype=np.float64)

    for ch in range(n_channels):
        x_vals: list[float] = []
        y_vals: list[float] = []

        for w_g in weights_g:
            if w_g == 0.0:
                continue  # tare is subtracted, not a data point
            comp_raw = weight_data[w_g][ch] - tare_raw[ch]
            h_val = float(H[ch, 0])
            w_n = w_g / 1000.0 * G  # grams → Newtons
            expected_strain = h_val * w_n

            if abs(comp_raw) < 1e-9:
                continue  # saturated or dead channel

            x_vals.append(comp_raw)
            y_vals.append(expected_strain)

        if not x_vals:
            print(f"  [WARN] channel {ch} ({CHANNEL_NAMES[ch]}): no valid data points, scale=0")
            scale[ch] = 0.0
            r2[ch] = 0.0
            rmse[ch] = float("inf")
            continue

        x = np.array(x_vals, dtype=np.float64)
        y = np.array(y_vals, dtype=np.float64)

        # Constrained through origin: y = x * scale
        s = np.dot(x, y) / np.dot(x, x) if np.dot(x, x) > 0 else 0.0
        scale[ch] = s

        y_pred = x * s
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r2[ch] = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
        rmse[ch] = np.sqrt(ss_res / len(x)) if len(x) > 0 else float("inf")

        qual = "good" if r2[ch] > 0.9 else "weak" if r2[ch] > 0.5 else "poor"
        print(f"  {CHANNEL_NAMES[ch]:>12}: scale={s:.6e}  R²={r2[ch]:.4f}  RMSE={rmse[ch]:.4e}  [{qual}]")

    print()
    n_good = np.sum(r2 > 0.9)
    n_weak = np.sum((r2 > 0.5) & (r2 <= 0.9))
    n_poor = np.sum(r2 <= 0.5)
    print(f"  Summary: {n_good} good, {n_weak} weak, {n_poor} poor channels")
    return scale, r2, rmse


def save_calibration(scale: np.ndarray, weights_used: list[float]):
    calib_path = HERE / "calibration_data.json"

    calib_data = {
        "version": 1,
        "calibrated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "calibrated_with": f"Weights (g): {weights_used}, hung at wing tip, using FEA H matrix",
        "per_channel_adc_to_strain_scale": [float(round(s, 22)) for s in scale],
    }

    with open(calib_path, "w") as f:
        json.dump(calib_data, f, indent=4)

    print(f"\n  Calibration saved → {calib_path}")
    print("  Copy the per_channel_adc_to_strain_scale values for reference:")
    print(f"    scale = {calib_data['per_channel_adc_to_strain_scale']}")


def main():
    parser = argparse.ArgumentParser(description="Analyze calibration data")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=HERE / "data",
        help="Directory with collected CSV files",
    )
    parser.add_argument(
        "--transfer-matrices",
        type=Path,
        default=None,
        help="Path to transfer_matrices directory (default: project root/transfer_matrices)",
    )
    args = parser.parse_args()

    if args.transfer_matrices is None:
        transfer_dir = _find_project_root() / "transfer_matrices"
    else:
        transfer_dir = args.transfer_matrices

    if not (transfer_dir / "H.npy").exists():
        print(f"FEA matrix H.npy not found in {transfer_dir}")
        print("Transfer matrices required for expected strain computation.")
        return

    print("Loading H matrix...")
    H = load_h_matrix(transfer_dir)
    print(f"  H shape: {H.shape}")

    print("\nLoading data files...")
    weight_data = load_data_files(args.data_dir)

    if not weight_data:
        print("No data loaded — aborting.")
        return

    print(f"\nLoaded {len(weight_data)} weight conditions:")
    for w_g in sorted(weight_data):
        print(f"  {w_g:.0f} g")

    print("\nPer-channel regression...")
    scale, r2, rmse = compute_scale_factors(weight_data, H)

    save_calibration(scale, sorted(weight_data.keys()))

    print("\nDone. Restart the engine to pick up the new calibration.")
    print("To verify: check the dashboard strain bars move proportionally to applied load.")


if __name__ == "__main__":
    main()
