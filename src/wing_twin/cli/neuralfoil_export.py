"""
CLI entry point to pre-compute NeuralFoil lookup tables.
"""

import argparse
import math
import os
from pathlib import Path

import neuralfoil as nf
import numpy as np

from wing_twin.constants import (
    ASPECT_RATIO, OSWALD_E,
)


_LUT_DIR = Path(
    os.environ.get(
        "WING_LUT_DIR",
        str(Path(__file__).resolve().parent.parent.parent.parent / "transfer_matrices" / "neuralfoil_lut"),
    )
)


def _naca_0002_coords(n_pts: int = 200) -> np.ndarray:
    t = 0.02
    beta = np.linspace(0, math.pi, n_pts)
    x_cos = 0.5 * (1.0 - np.cos(beta))
    y = (
        t
        / 0.2
        * (
            0.2969 * np.sqrt(x_cos)
            - 0.1260 * x_cos
            - 0.3516 * x_cos ** 2
            + 0.2843 * x_cos ** 3
            - 0.1015 * x_cos ** 4
        )
    )
    x = np.concatenate([x_cos[::-1], x_cos[1:]])
    y = np.concatenate([y[::-1], -y[1:]])
    return np.column_stack([x, y])


def _lifting_line_correction(
    alpha_3d_mesh: np.ndarray,
    Re_mesh: np.ndarray,
    cl_2d_raw: np.ndarray,
    cd_2d_raw: np.ndarray,
    alpha_2d_mesh: np.ndarray,
    AR: float,
    e: float,
) -> tuple[np.ndarray, np.ndarray]:
    n_alpha = len(alpha_3d_mesh)
    n_Re = len(Re_mesh)
    CL = np.empty((n_alpha, n_Re), dtype=np.float64)
    CD = np.empty((n_alpha, n_Re), dtype=np.float64)
    rad_per_deg = math.pi / 180.0

    for j in range(n_Re):
        cl_slice = cl_2d_raw[:, j]
        cd_slice = cd_2d_raw[:, j]
        for i in range(n_alpha):
            a3 = alpha_3d_mesh[i]
            CL_val = 0.0
            for _ in range(40):
                alpha_i = CL_val / (math.pi * AR)
                a2 = float(np.clip(a3 - alpha_i / rad_per_deg, alpha_2d_mesh[0], alpha_2d_mesh[-1]))
                cl_new = float(np.interp(a2, alpha_2d_mesh, cl_slice))
                CL_val = 0.5 * CL_val + 0.5 * cl_new
                if abs(cl_new - CL_val) < 1e-6:
                    break
            cd = float(np.interp(a2, alpha_2d_mesh, cd_slice))
            CD_val = cd + CL_val ** 2 / (math.pi * AR * e)
            CL[i, j] = CL_val
            CD[i, j] = CD_val

    return CL, CD


def main():
    parser = argparse.ArgumentParser(description="Pre-compute NeuralFoil lookup tables")
    parser.add_argument(
        "--model-size",
        default="xlarge",
        choices=["large", "xlarge", "xxxlarge"],
        help="NeuralFoil model size",
    )
    args = parser.parse_args()

    _LUT_DIR.mkdir(parents=True, exist_ok=True)

    coords = _naca_0002_coords()

    alpha_2d_mesh = np.arange(-18.0, 18.5, 0.5)
    alpha_3d_mesh = np.arange(-15.0, 15.5, 0.5)
    Re_mesh = np.arange(30_000, 205_000, 10_000, dtype=np.float64)

    AA, RR = np.meshgrid(alpha_2d_mesh, Re_mesh, indexing="ij")
    raw = nf.get_aero_from_coordinates(
        coordinates=coords,
        alpha=AA.ravel(),
        Re=RR.ravel(),
        model_size=args.model_size,
    )

    cl_2d_raw = np.asarray(raw["CL"]).reshape(len(alpha_2d_mesh), len(Re_mesh))
    cd_2d_raw = np.asarray(raw["CD"]).reshape(len(alpha_2d_mesh), len(Re_mesh))

    CL, CD = _lifting_line_correction(
        alpha_3d_mesh, Re_mesh, cl_2d_raw, cd_2d_raw, alpha_2d_mesh, ASPECT_RATIO, OSWALD_E
    )

    stem = args.model_size
    np.save(_LUT_DIR / f"{stem}_alpha_mesh.npy", alpha_3d_mesh)
    np.save(_LUT_DIR / f"{stem}_Re_mesh.npy", Re_mesh)
    np.save(_LUT_DIR / f"{stem}_CL_lut.npy", CL)
    np.save(_LUT_DIR / f"{stem}_CD_lut.npy", CD)

    print(
        f"NeuralFoil LUT saved to {_LUT_DIR}/ ({stem}, "
        f"{len(alpha_3d_mesh)}x{len(Re_mesh)} cells)"
    )


if __name__ == "__main__":
    main()
