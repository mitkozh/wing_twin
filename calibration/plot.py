"""
Plot calibration data for visualization and verification.

Plots:
  - Strain calibration       (calibration/strain/data/       — from collect.py)
  - Steps-per-newton         (calibration/stepper/data/      — from steps_per_newton.py)
  - Range calibration params (calibration/stepper/data/      — from range_test.py)
  - Max frequency pass/fail  (calibration/stepper/data/      — from max_frequency.py)

Usage:
    python -m calibration.plot                          # plot all found data
    python -m calibration.plot --type strain            # only strain calibration
    python -m calibration.plot --csv <path>             # plot a specific CSV
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

try:
    import matplotlib
    matplotlib.use("TkAgg")
    import matplotlib.pyplot as plt
except ImportError:
    plt = None
    print("matplotlib not installed. Install it: pip install matplotlib")

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
STRAIN_DATA_DIR = HERE / "strain" / "data"
STEPPER_DATA_DIR = HERE / "stepper" / "data"
CALIB_DATA_PATH = HERE / "strain" / "calibration_data.json"

CHANNEL_NAMES = [
    "root_0", "root_45", "root_90",
    "middle_0", "middle_45", "middle_90",
    "tip_0", "tip_45", "tip_90",
]


def load_h_matrix() -> np.ndarray | None:
    h_path = PROJECT_ROOT / "transfer_matrices" / "H.npy"
    if h_path.exists():
        return np.load(h_path).astype(np.float64)
    return None


def load_calibration_data() -> dict | None:
    if CALIB_DATA_PATH.exists():
        with open(CALIB_DATA_PATH) as f:
            return json.load(f)
    return None


def find_csv_files() -> dict[str, list[Path]]:
    files: dict[str, list[Path]] = {
        "strain": [], "range": [], "frequency": [], "steps_per_newton": [],
    }
    if STRAIN_DATA_DIR.exists():
        for p in sorted(STRAIN_DATA_DIR.glob("*.csv")):
            files["strain"].append(p)
    if STEPPER_DATA_DIR.exists():
        for p in sorted(STEPPER_DATA_DIR.glob("*.csv")):
            stem = p.stem.lower()
            if stem.startswith("range_"):
                files["range"].append(p)
            elif stem.startswith("max_frequency") or stem.startswith("max_freq"):
                files["frequency"].append(p)
            elif stem.startswith("steps_") or "newton" in stem:
                files["steps_per_newton"].append(p)
    return files


# ─── Strain calibration plots ────────────────────────────────────────────────

def plot_strain_calibration(csv_paths: list[Path]) -> None:
    H = load_h_matrix()
    calib = load_calibration_data()

    all_data: dict[float, dict[int, float]] = {}
    weights_seen: set[float] = set()

    for fp in csv_paths:
        stem = fp.stem
        try:
            w = float(stem.split("_")[-1].replace("g", ""))
        except (ValueError, IndexError):
            continue
        weights_seen.add(w)
        with open(fp, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                for i in range(9):
                    raw = float(row.get(f"raw_{i}", 0))
                    off = float(row.get(f"offset_{i}", 0))
                    dummy = float(row.get("dummy_raw", 0))
                    val = raw - dummy - off
                    if w not in all_data:
                        all_data[w] = {}
                    if i not in all_data[w]:
                        all_data[w][i] = []
                    all_data[w][i].append(val)

    if not all_data:
        print("  No strain CSV data found")
        return

    averaged: dict[float, np.ndarray] = {}
    for w in sorted(all_data):
        arr = np.zeros(9)
        for i in range(9):
            vals = all_data[w].get(i, [0])
            arr[i] = np.mean(vals)
        averaged[w] = arr

    tare_w = 0.0 if 0.0 in averaged else min(averaged.keys())
    tare = averaged.get(tare_w, np.zeros(9))

    n_channels = 9
    fig, axes = plt.subplots(3, 3, figsize=(14, 10))
    fig.suptitle("Strain Calibration — Per-Channel ADC vs Weight", fontsize=14)

    for ch in range(n_channels):
        ax = axes[ch // 3][ch % 3]
        weights_g = sorted(w for w in averaged if w != tare_w)
        x_vals = [w - tare_w for w in weights_g]
        y_vals = [(averaged[w][ch] - tare[ch]) for w in weights_g]
        ax.scatter(x_vals, y_vals, color="royalblue", zorder=3)

        if len(x_vals) >= 2:
            X = np.array(x_vals, dtype=float)
            Y = np.array(y_vals, dtype=float)
            mask = np.abs(X) > 1e-12
            if mask.any():
                s = np.dot(X[mask], Y[mask]) / np.dot(X[mask], X[mask])
                fit_x = np.linspace(0, max(X), 100)
                fit_y = fit_x * s
                ax.plot(fit_x, fit_y, "r--", alpha=0.6, label=f"slope={s:.2e}")
                ax.legend(fontsize=7)

        ax.set_xlabel("Weight (g)", fontsize=8)
        ax.set_ylabel("Compensated ADC", fontsize=8)
        ax.set_title(f"CH{ch}: {CHANNEL_NAMES[ch]}", fontsize=9)
        ax.grid(True, alpha=0.3)

    plt.tight_layout()

    # Plot 2: Calibration scale factors bar chart
    if calib:
        scales = calib.get("per_channel_adc_to_strain_scale")
        if scales:
            fig2, ax2 = plt.subplots(figsize=(10, 4))
            fig2.suptitle("ADC → Strain Scale Factors (from calibration_data.json)", fontsize=12)
            colors = ["green" if s >= 0 else "red" for s in scales]
            ax2.bar(range(9), scales, color=colors, alpha=0.7)
            ax2.set_xticks(range(9))
            ax2.set_xticklabels(CHANNEL_NAMES, rotation=45, ha="right", fontsize=8)
            ax2.set_ylabel("Scale Factor (strain / ADC count)")
            ax2.axhline(0, color="black", linewidth=0.5)
            for i, s in enumerate(scales):
                ax2.text(i, s, f"{s:.2e}", ha="center", va="bottom" if s >= 0 else "top", fontsize=7)
            plt.tight_layout()

    # Plot 3: Force reconstruction quality
    if H is not None and calib and scales:
        fig3, ax3 = plt.subplots(figsize=(8, 5))
        fig3.suptitle("Force Reconstruction — Expected vs Measured Strain", fontsize=12)
        g = 9.81
        for ch in range(n_channels):
            if abs(float(H[ch, 0])) < 1e-12:
                continue
            weights_g = sorted(w for w in averaged if w != tare_w)
            expected = [H[ch, 0] * (w / 1000 * g) for w in weights_g]
            measured = [(averaged[w][ch] - tare[ch]) * scales[ch] for w in weights_g]
            ax3.scatter(expected, measured, s=15, alpha=0.6, label=CHANNEL_NAMES[ch])

        ax3.plot([0, max(ax3.get_xlim()[1], ax3.get_ylim()[1])],
                 [0, max(ax3.get_xlim()[1], ax3.get_ylim()[1])],
                 "k--", alpha=0.3, label="ideal")
        ax3.set_xlabel("Expected strain (from H·F)")
        ax3.set_ylabel("Measured strain (ADC × scale)")
        ax3.grid(True, alpha=0.3)
        ax3.legend(fontsize=7, ncol=3)
        plt.tight_layout()

    plt.show()


# ─── Stepper range test plots ────────────────────────────────────────────────

def plot_range_test(csv_paths: list[Path]) -> None:
    for fp in csv_paths:
        params: dict[str, str] = {}
        with open(fp, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                k = row.get("parameter", "")
                v = row.get("value", "")
                if k:
                    params[k] = v

        if not params:
            continue

        fig, ax = plt.subplots(figsize=(8, 4))
        fig.suptitle(f"Range Calibration: {fp.name}", fontsize=12)
        labels = list(params.keys())
        values = list(params.values())
        y_pos = range(len(labels))
        ax.barh(y_pos, [1] * len(labels), alpha=0)
        for i, (l, v) in enumerate(zip(labels, values)):
            ax.text(0, i, f"{l}: {v}", fontsize=9, va="center")
        ax.set_yticks([])
        ax.set_xticks([])
        ax.spines[:].set_visible(False)
        plt.tight_layout()
    plt.show()


# ─── Max frequency test plots ────────────────────────────────────────────────

def plot_frequency_test(csv_paths: list[Path]) -> None:
    for fp in csv_paths:
        speeds, passed = [], []
        with open(fp, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                s = row.get("speed")
                p = row.get("passed", "").strip().lower()
                if s:
                    speeds.append(int(s))
                    passed.append(p == "true")

        if not speeds:
            continue

        fig, ax = plt.subplots(figsize=(8, 4))
        fig.suptitle(f"Max Frequency Test: {fp.name}", fontsize=12)

        colors = ["green" if p else "red" for p in passed]
        ax.bar(range(len(speeds)), speeds, color=colors, alpha=0.7, width=0.6)
        ax.set_xticks(range(len(speeds)))
        ax.set_xticklabels([str(s) for s in speeds], rotation=45, fontsize=8)
        ax.set_xlabel("Speed step")
        ax.set_ylabel("Steps/s")
        ax.axhline(0, color="black", linewidth=0.5)
        from matplotlib.patches import Patch
        ax.legend(
            handles=[Patch(color="green", label="Pass"), Patch(color="red", label="Fail")],
            fontsize=8,
        )
        plt.tight_layout()
    plt.show()


# ─── Steps-per-newton plots ──────────────────────────────────────────────────

def plot_steps_per_newton(csv_paths: list[Path]) -> None:
    H = load_h_matrix()
    calib = load_calibration_data()

    for fp in csv_paths:
        stepper_cmds: dict[int, list[np.ndarray]] = {}
        with open(fp, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cmd = int(row["_stepper_cmd"])
                compensated = np.array([
                    float(row[f"raw_{i}"]) - float(row.get("dummy_raw", 0)) - float(row[f"offset_{i}"])
                    for i in range(9)
                ], dtype=np.float64)
                if cmd not in stepper_cmds:
                    stepper_cmds[cmd] = []
                stepper_cmds[cmd].append(compensated)

        if not stepper_cmds:
            continue

        for k in stepper_cmds:
            stepper_cmds[k] = np.mean(stepper_cmds[k], axis=0)

        tare_raw = stepper_cmds.pop(0, None)
        if tare_raw is None:
            print(f"  [skip] {fp.name}: no tare position (0) data")
            continue

        scales = None
        if calib:
            s = calib.get("per_channel_adc_to_strain_scale")
            if s and len(s) == 9:
                scales = np.array(s)

        forces = []
        positions = []
        per_channel_forces: dict[int, list[float]] = {i: [] for i in range(9)}

        for cmd in sorted(stepper_cmds):
            net_raw = stepper_cmds[cmd] - tare_raw
            if scales is not None and H is not None:
                strain = net_raw * scales
                ch_forces = []
                for ch in range(9):
                    h_val = float(H[ch, 0])
                    if abs(h_val) > 1e-12:
                        f_ch = strain[ch] / h_val
                        ch_forces.append(f_ch)
                        per_channel_forces[ch].append(f_ch)
                if ch_forces:
                    forces.append(np.median(ch_forces))
                    positions.append(cmd)
            else:
                forces.append(np.mean(np.abs(net_raw)))
                positions.append(cmd)

        if len(forces) < 2:
            continue

        forces_arr = np.array(forces)
        positions_arr = np.array(positions)

        m = np.dot(forces_arr, positions_arr) / np.dot(forces_arr, forces_arr)
        y_pred = forces_arr * m
        ss_res = np.sum((positions_arr - y_pred) ** 2)
        ss_tot = np.sum((positions_arr - np.mean(positions_arr)) ** 2)
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
        rmse = float(np.sqrt(ss_res / len(forces_arr)))

        fig, axes = plt.subplots(1, 3, figsize=(15, 5))
        fig.suptitle(f"Steps/Newton Calibration: {fp.name}  (result: {m:.2f} steps/N)", fontsize=12)

        axes[0].scatter(forces_arr, positions_arr, s=40, color="royalblue", zorder=3)
        fit_x = np.linspace(0, max(forces_arr) * 1.05, 100)
        fit_y = fit_x * m
        axes[0].plot(fit_x, fit_y, "r--", alpha=0.6, label=f"steps = {m:.2f}·F  (R²={r2:.3f})")
        axes[0].set_xlabel("Force (N)")
        axes[0].set_ylabel("Stepper Position (steps)")
        axes[0].set_title("Force vs Position")
        axes[0].legend(fontsize=8)
        axes[0].grid(True, alpha=0.3)

        residuals = positions_arr - y_pred
        axes[1].scatter(forces_arr, residuals, s=30, alpha=0.6, color="darkorange")
        axes[1].axhline(0, color="k", linewidth=0.5)
        axes[1].set_xlabel("Force (N)")
        axes[1].set_ylabel("Residual (steps)")
        axes[1].set_title(f"Residuals  (RMSE={rmse:.1f} steps)")
        axes[1].grid(True, alpha=0.3)

        if scales is not None and H is not None:
            axes[2].set_title("Per-Channel Force Estimates")
            for ch in range(9):
                ch_f = per_channel_forces.get(ch, [])
                ch_p = positions[:len(ch_f)]
                if ch_f and abs(H[ch, 0]) > 1e-12:
                    axes[2].scatter(ch_p, ch_f, s=10, alpha=0.5, label=CHANNEL_NAMES[ch])
            axes[2].set_xlabel("Stepper Position (steps)")
            axes[2].set_ylabel("Force (N)")
            axes[2].legend(fontsize=6, ncol=3)
            axes[2].grid(True, alpha=0.3)

        plt.tight_layout()
    plt.show()


# ─── Main ─────────────────────────────────────────────────────────────────────

def plot_all() -> None:
    files = find_csv_files()

    if files["strain"]:
        print(f"Plotting strain calibration ({len(files['strain'])} files)...")
        plot_strain_calibration(files["strain"])
    else:
        print("No strain calibration CSVs found (run calibration.strain.collect)")

    if files["range"]:
        print(f"Plotting range calibration ({len(files['range'])} files)...")
        plot_range_test(files["range"])

    if files["frequency"]:
        print(f"Plotting max frequency test ({len(files['frequency'])} files)...")
        plot_frequency_test(files["frequency"])

    if files["steps_per_newton"]:
        print(f"Plotting steps-per-newton ({len(files['steps_per_newton'])} files)...")
        plot_steps_per_newton(files["steps_per_newton"])
    else:
        print("No steps-per-newton CSVs found (run calibration.stepper.steps_per_newton)")

    if not any(files.values()):
        print("No CSV data files found anywhere.")
        print("Run calibration scripts first to generate data, e.g.:")
        print("  python -m calibration.strain.collect")
        print("  python -m calibration.stepper.steps_per_newton")


def main():
    if plt is None:
        print("matplotlib is required. Install it and try again.")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Plot calibration data")
    parser.add_argument("--type", choices=["strain", "stepper", "all"], default="all")
    parser.add_argument("--csv", type=Path, default=None, help="Plot a specific CSV file")
    args = parser.parse_args()

    if args.csv:
        path = Path(args.csv)
        if not path.exists():
            print(f"File not found: {path}")
            sys.exit(1)
        stem = path.stem.lower()
        if "range" in stem:
            plot_range_test([path])
        elif "frequency" in stem or "freq" in stem:
            plot_frequency_test([path])
        elif "steps" in stem or "newton" in stem:
            plot_steps_per_newton([path])
        else:
            plot_strain_calibration([path])
        return

    if args.type == "strain":
        files = find_csv_files()
        if files["strain"]:
            plot_strain_calibration(files["strain"])
        else:
            print("No strain CSV data found")
    elif args.type == "stepper":
        files = find_csv_files()
        if files["range"]:
            plot_range_test(files["range"])
        if files["frequency"]:
            plot_frequency_test(files["frequency"])
        if files["steps_per_newton"]:
            plot_steps_per_newton(files["steps_per_newton"])
        if not any(v for k, v in files.items() if k != "strain"):
            print("No stepper CSV data found")
    else:
        plot_all()


if __name__ == "__main__":
    main()
