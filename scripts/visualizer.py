"""
Wing Digital Twin - Visualization Generator
Produces static PNG figures for the simulation run:
  1. Strain time series
  2. Accumulated damage + state thresholds
  3. Rainflow histogram (cycle amplitudes)
  4. S-N curve with operating points
  5. Stress field heatmap
  6. Deformation field heatmap
"""

import numpy as np
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
OUTPUT_DIR = PROJECT_ROOT / "figures"
OUTPUT_DIR.mkdir(exist_ok=True)

try:
    from dtwin.core.fatigue import DAMAGE_SAFE, DAMAGE_WARNING
except ImportError:
    DAMAGE_SAFE = 0.3
    DAMAGE_WARNING = 0.8


def sn_cycles(amp: float) -> float:
    """
    Calculate cycles to failure from stress amplitude using S-N curve.
    
    Uses: log(N) = a - m*log(σ)
    With a=8, m=3 (from DEMO_SN_CURVE)
    """
    if amp <= 0:
        return float("inf")
    # S-N curve parameters (from DEMO_SN_CURVE)
    a = 8.0  # intercept
    m = 3.0  # slope
    
    # Calculate cycles to failure: N = 10^(a - m*log10(σ))
    log_n = a - m * np.log10(amp)
    n = 10 ** log_n
    
    return n


def _make_style():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.style.use("dark_background")
    matplotlib.rcParams.update({
        "font.family": "monospace",
        "axes.facecolor": "#1e1e2e",
        "figure.facecolor": "#111118",
        "axes.edgecolor": "#555566",
        "axes.labelcolor": "#cccccc",
        "xtick.color": "#aaaaaa",
        "ytick.color": "#aaaaaa",
        "grid.color": "#333344",
        "grid.linewidth": 0.5,
        "axes.titlesize": 11,
        "axes.labelsize": 9,
        "figure.dpi": 120,
    })
    return plt


def plot_strain_timeseries(strain_history, times, filename="01_strain_timeseries.png"):
    plt = _make_style()
    fig, ax = plt.subplots(figsize=(10, 4))

    # Ensure equal length arrays
    min_len = min(len(strain_history), len(times))
    if min_len == 0:
        ax.text(0.5, 0.5, "No data available", transform=ax.transAxes, ha="center")
        fig.tight_layout()
        path = OUTPUT_DIR / filename
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        return path

    times = np.array(times[:min_len])
    strain_history = np.array(strain_history[:min_len])

    ax.plot(times, strain_history, color="#7ab8f5", linewidth=0.6, alpha=0.8, label="Strain")

    window = max(1, len(strain_history) // 10)
    envelope = np.array([np.max(strain_history[max(0, i-window):i+1]) for i in range(len(strain_history))])
    ax.plot(times, envelope, color="#ff9966", linewidth=0.8, alpha=0.5, label="Peak envelope")

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Strain (microstrain)")
    ax.set_title("Wing Root Strain — Time Series")
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.3)
    ax.set_xlim(times[0], times[-1])

    textstr = f"mean={np.mean(strain_history):.1f} με  max={np.max(strain_history):.1f} με  std={np.std(strain_history):.1f} με"
    ax.text(0.02, 0.95, textstr, transform=ax.transAxes, fontsize=8,
            verticalalignment="top", color="#aaaaaa",
            bbox=dict(boxstyle="round", facecolor="#222233", alpha=0.8))

    fig.tight_layout()
    path = OUTPUT_DIR / filename
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"  [FIG] Saved {path}")
    return path


def plot_damage_progress(damage_history, times, filename="02_damage_progress.png"):
    plt = _make_style()
    fig, ax = plt.subplots(figsize=(10, 4))

    # Ensure equal length arrays
    min_len = min(len(damage_history), len(times))
    if min_len == 0:
        ax.text(0.5, 0.5, "No data available", transform=ax.transAxes, ha="center")
        fig.tight_layout()
        path = OUTPUT_DIR / filename
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        return path

    times = np.array(times[:min_len])
    damage_history = np.array(damage_history[:min_len])

    ax.fill_between(times, 0, DAMAGE_SAFE, alpha=0.15, color="#22cc66", label="SAFE")
    ax.fill_between(times, DAMAGE_SAFE, DAMAGE_WARNING, alpha=0.15, color="#ccaa22", label="WARNING")
    ax.fill_between(times, DAMAGE_WARNING, 1.0, alpha=0.15, color="#cc3322", label="CRITICAL")

    ax.axhline(DAMAGE_SAFE, color="#ccaa22", linestyle="--", linewidth=1, alpha=0.8)
    ax.axhline(DAMAGE_WARNING, color="#cc3322", linestyle="--", linewidth=1, alpha=0.8)

    ax.plot(times, damage_history, color="#66ddff", linewidth=2, label="Accumulated damage D")

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Damage D")
    ax.set_title("Fatigue Damage Accumulation — Miner's Rule")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)
    ax.set_xlim(times[0], times[-1])
    ax.set_ylim(0, 1.05)

    final_d = damage_history[-1]
    if final_d >= DAMAGE_WARNING:
        status, color = "CRITICAL", "#ff4444"
    elif final_d >= DAMAGE_SAFE:
        status, color = "WARNING", "#ffcc22"
    else:
        status, color = "SAFE", "#44ff88"

    ax.text(0.98, 0.05, f"Final D = {final_d:.4f} ({status})", transform=ax.transAxes,
            fontsize=10, ha="right", va="bottom", color=color, fontweight="bold",
            bbox=dict(boxstyle="round", facecolor="#222233", alpha=0.8))

    fig.tight_layout()
    path = OUTPUT_DIR / filename
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"  [FIG] Saved {path}")
    return path


def _cycles_to_histogram_data(cycles):
    if not cycles:
        return np.array([]), np.array([])
    if isinstance(cycles[0], (list, tuple, np.ndarray)) and len(cycles[0]) == 2:
        ranges_arr = np.array([c[0] for c in cycles])
        counts_arr = np.array([c[1] for c in cycles])
        unique_ranges, _ = np.unique(ranges_arr, return_counts=True)
        total_counts = np.zeros_like(unique_ranges)
        for r, c in zip(ranges_arr, counts_arr):
            idx = np.searchsorted(unique_ranges, r)
            total_counts[idx] += c
        return unique_ranges, total_counts
    rngs = np.asarray(cycles)
    if rngs.ndim == 2 and rngs.shape[1] == 3:
        return rngs[:, 1], rngs[:, 2]
    return np.asarray(cycles), np.ones(len(cycles))


def plot_rainflow_histogram(cycles, filename="03_rainflow_histogram.png"):
    plt = _make_style()
    rngs, cnts = _cycles_to_histogram_data(cycles)
    fig, ax = plt.subplots(figsize=(10, 4))

    if len(rngs) > 0:
        total_cycles = float(np.sum(cnts))
        
        if len(rngs) > 1:
            min_spacing = np.min(np.diff(np.sort(rngs)))
            bar_width = min(0.8, min_spacing * 0.9)
        else:
            bar_width = 0.8
        
        ax.bar(rngs, cnts, width=bar_width, color="#aa88ff", alpha=0.8, edgecolor="#ffffff44")
        ax.set_xlabel("Stress Range (MPa)")
        ax.set_ylabel("Cycle Count")
        ax.set_title(f"Rainflow Cycle Histogram  ({len(rngs)} bins, {total_cycles:.1f} total cycles)")
    else:
        ax.text(0.5, 0.5, "No cycles extracted", transform=ax.transAxes, ha="center", va="center")
        ax.set_title("Rainflow Cycle Histogram")

    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    path = OUTPUT_DIR / filename
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"  [FIG] Saved {path}")
    return path


def plot_sn_curve(cycles, filename="04_sn_curve.png"):
    plt = _make_style()
    fig, ax = plt.subplots(figsize=(10, 5))

    # Generate S-N curve line using the same formula as damage calculation
    # N = 10^(a - m*log10(σ)) → σ = 10^((a - log10(N))/m)
    n_points = np.logspace(3, 10, 100)  # N from 1e3 to 1e10
    a, m = 8.0, 3.0
    stress_curve = 10 ** ((a - np.log10(n_points)) / m)

    ax.plot(n_points, stress_curve, color="#ffaa44", linewidth=2.5, 
            label="S-N curve (demo)")

    ax.axhline(80, color="#22cc66", linestyle=":", linewidth=1, alpha=0.7, label="Endurance limit (80 MPa)")

    rngs, cnts = _cycles_to_histogram_data(cycles)

    if len(rngs) > 0:
        op_amplitudes = rngs
        op_cycles = np.array([sn_cycles(a) for a in op_amplitudes])
        valid = (op_cycles < 1e12) & (op_cycles > 1e0)
        if valid.sum() > 0:
            sc = ax.scatter(op_cycles[valid], op_amplitudes[valid], c=cnts[valid], cmap="plasma",
                           s=100, zorder=5, alpha=0.9, edgecolors="white", linewidths=0.5)
            plt.colorbar(sc, ax=ax, label="Cycle count", shrink=0.7)

    ax.set_xscale("log")
    ax.set_xlabel("Cycles to Failure N")
    ax.set_ylabel("Stress Amplitude (MPa)")
    ax.set_title("S-N Curve with Simulation Operating Points")
    ax.legend(loc="upper right")
    ax.grid(True, which="both", alpha=0.3)
    ax.set_xlim(1e3, 1e10)
    ax.set_ylim(0, 100)

    fig.tight_layout()
    path = OUTPUT_DIR / filename
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"  [FIG] Saved {path}")
    return path


def plot_stress_field(stress_field_history, filename="05_stress_field.png"):
    plt = _make_style()
    if not stress_field_history:
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.text(0.5, 0.5, "No stress field data available", transform=ax.transAxes, ha="center")
        ax.set_title("Stress Field")
    else:
        latest = np.array(stress_field_history[-1])
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(latest, color="#ff6666", linewidth=1.5, label="Equivalent stress (MPa)")
        ax.fill_between(np.arange(len(latest)), latest, alpha=0.3, color="#ff6666")
        ax.set_xlabel("Node index")
        ax.set_ylabel("Stress (MPa)")
        ax.set_title(f"Equivalent Stress Field — {len(latest)} nodes")
        ax.grid(True, alpha=0.3)
        ax.text(0.02, 0.95, f"max={latest.max():.2f} MPa  mean={latest.mean():.2f} MPa",
                transform=ax.transAxes, fontsize=8, va="top", color="#aaaaaa",
                bbox=dict(boxstyle="round", facecolor="#222233", alpha=0.8))
    fig.tight_layout()
    path = OUTPUT_DIR / filename
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"  [FIG] Saved {path}")
    return path


def plot_deformation_field(deformation_field_history, filename="06_deformation_field.png"):
    plt = _make_style()
    if not deformation_field_history:
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.text(0.5, 0.5, "No deformation field data available", transform=ax.transAxes, ha="center")
        ax.set_title("Deformation Field")
    else:
        latest = np.array(deformation_field_history[-1])
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(latest, color="#66ffaa", linewidth=1.5, label="Total deformation (m)")
        ax.fill_between(np.arange(len(latest)), latest, alpha=0.3, color="#66ffaa")
        ax.set_xlabel("Node index")
        ax.set_ylabel("Deformation (m)")
        ax.set_title(f"Total Deformation Field — {len(latest)} nodes")
        ax.grid(True, alpha=0.3)
        ax.text(0.02, 0.95, f"max={latest.max():.6f} m  mean={latest.mean():.6f} m",
                transform=ax.transAxes, fontsize=8, va="top", color="#aaaaaa",
                bbox=dict(boxstyle="round", facecolor="#222233", alpha=0.8))
    fig.tight_layout()
    path = OUTPUT_DIR / filename
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"  [FIG] Saved {path}")
    return path


def generate_all(strain_history, times, damage_history, cycles, force_history, stress_field_history, deformation_field_history):
    print("\n" + "=" * 50)
    print("  Generating Figures...")
    print("=" * 50)
    plot_strain_timeseries(strain_history, times)
    plot_damage_progress(damage_history, times)
    plot_rainflow_histogram(cycles)
    plot_sn_curve(cycles)
    plot_stress_field(stress_field_history)
    plot_deformation_field(deformation_field_history)
    print("=" * 50)
    print(f"  Figures saved to: {OUTPUT_DIR}/")
    print("=" * 50)