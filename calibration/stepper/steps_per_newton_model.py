from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from calibration.stepper.mqtt_helpers import (
    load_stepper_calibration,
    update_stepper_calibration,
    MODEL_FILE,
)

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent


def load_u_matrix() -> np.ndarray | None:
    transfer_dir = PROJECT_ROOT / "transfer_matrices"
    u_path = transfer_dir / "TotalDeformation.npy"
    if not u_path.exists():
        return None
    U = np.load(u_path)
    if U.ndim != 2:
        return None
    return U.astype(np.float64)


def run(max_newtons: float | None = None, steps_per_mm: float | None = None) -> float | None:
    print("=" * 60)
    print("Steps-per-Newton (Model)")
    print("=" * 60)
    print()

    U = load_u_matrix()
    if U is None:
        print("  [ERROR] TotalDeformation.npy not found in transfer_matrices/")
        return None
    print(f"  Loaded U matrix: {U.shape}")

    tip_deformation_m_per_N = float(np.max(np.abs(U)))
    tip_deformation_mm_per_N = tip_deformation_m_per_N * 1000.0
    print(f"  Tip deformation:     {tip_deformation_m_per_N:.4e} m/N = {tip_deformation_mm_per_N:.4f} mm/N")

    if steps_per_mm is not None:
        spmm = steps_per_mm
        print(f"  Steps per mm:        {spmm:.2f} (from argument)")
    else:
        existing = load_stepper_calibration(HERE, MODEL_FILE)
        spmm = existing.get("steps_per_mm")
        if spmm is None:
            existing = load_stepper_calibration(HERE)
            spmm = existing.get("steps_per_mm")
        if spmm is None:
            print("  [ERROR] No steps_per_mm found. Run range_model first or pass --steps-per-mm.")
            return None
        print(f"  Steps per mm:        {spmm:.2f} (from calibration)")

    spn = spmm * tip_deformation_mm_per_N
    print()
    print(f"  steps_per_newton = {spmm:.2f} × {tip_deformation_mm_per_N:.4f}")
    print(f"                    = {spn:.4f}")
    print()

    update_stepper_calibration(HERE, {
        "version": 1,
        "calibrated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "calibrated_with": "Model-based: steps_per_mm × U_tip (FEA)",
        "steps_per_newton": round(spn, 4),
        "deformation_m_per_N": round(tip_deformation_m_per_N, 10),
        "tip_deformation_mm_per_N": round(tip_deformation_mm_per_N, 4),
        "steps_per_mm": round(spmm, 2),
    }, filename=MODEL_FILE)

    if max_newtons is not None:
        wing_limit = int(round(max_newtons * spn))
        existing_motor = load_stepper_calibration(HERE, MODEL_FILE)
        motor_max = existing_motor.get("stepper_motor_max_steps")
        if motor_max is not None and wing_limit > motor_max:
            wing_limit = motor_max
        update_stepper_calibration(HERE, {
            "stepper_wing_safe_limit": wing_limit,
            "max_newtons_calibrated": max_newtons,
        }, filename=MODEL_FILE)
        print(f"  Max force:            {max_newtons:.2f} N")
        print(f"  Wing safe limit:      {wing_limit} steps")
        print()

    print("  All values saved to stepper_calibration_model.json")
    return spn


def main():
    parser = argparse.ArgumentParser(
        description="Model-based steps-per-newton calibration (no hardware)"
    )
    parser.add_argument("--max-newtons", type=float, default=None, help="Max safe force in N")
    parser.add_argument("--steps-per-mm", type=float, default=None, help="Steps per mm (from range_model)")
    args = parser.parse_args()
    run(max_newtons=args.max_newtons, steps_per_mm=args.steps_per_mm)


if __name__ == "__main__":
    main()
