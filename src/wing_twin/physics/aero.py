"""
Stepper motor physics - aerodynamic force model.
"""

import math
import os
from pathlib import Path
from typing import Optional

import numpy as np

from wing_twin.constants import (
    AIR_DENSITY, AIR_VISCOSITY, WING_AREA, CHORD,
    ASPECT_RATIO, OSWALD_E, MAX_STEPPER_STEPS,
)
from wing_twin.config.calibration import CalibrationConfig


_LUT_DIR = Path(
    os.environ.get(
        "WING_LUT_DIR",
        str(Path(__file__).resolve().parent.parent.parent.parent / "transfer_matrices" / "neuralfoil_lut"),
    )
)
_NF_MODEL: Optional["NeuralFoilModel"] = None


class NeuralFoilModel:
    def __init__(self, model_size: str = "xlarge"):
        stem = model_size
        self.alpha_mesh = np.load(_LUT_DIR / f"{stem}_alpha_mesh.npy")
        self.Re_mesh = np.load(_LUT_DIR / f"{stem}_Re_mesh.npy")
        self.CL_lut = np.load(_LUT_DIR / f"{stem}_CL_lut.npy")
        self.CD_lut = np.load(_LUT_DIR / f"{stem}_CD_lut.npy")

    def get_CL(self, alpha_deg: float, Re: float) -> float:
        return self._interp(alpha_deg, Re, self.CL_lut)

    def get_CD(self, alpha_deg: float, Re: float) -> float:
        return self._interp(alpha_deg, Re, self.CD_lut)

    def _interp(self, alpha: float, Re: float, Z: np.ndarray) -> float:
        ax = self.alpha_mesh
        rx = self.Re_mesh
        alpha = float(np.clip(alpha, ax[0], ax[-1]))
        Re = float(np.clip(Re, rx[0], rx[-1]))

        i = int(np.searchsorted(ax, alpha, side="right") - 1)
        i = max(0, min(i, len(ax) - 2))
        j = int(np.searchsorted(rx, Re, side="right") - 1)
        j = max(0, min(j, len(rx) - 2))

        fx = (alpha - ax[i]) / (ax[i + 1] - ax[i]) if ax[i + 1] > ax[i] else 0.0
        fy = (Re - rx[j]) / (rx[j + 1] - rx[j]) if rx[j + 1] > rx[j] else 0.0

        Z00 = Z[i, j]
        Z10 = Z[i + 1, j]
        Z01 = Z[i, j + 1]
        Z11 = Z[i + 1, j + 1]

        return float(
            Z00 * (1.0 - fx) * (1.0 - fy)
            + Z10 * fx * (1.0 - fy)
            + Z01 * (1.0 - fx) * fy
            + Z11 * fx * fy
        )


def init_neuralfoil(model_size: str = "xlarge") -> NeuralFoilModel:
    global _NF_MODEL
    _NF_MODEL = NeuralFoilModel(model_size=model_size)
    return _NF_MODEL


def _compute_CL_CD(
    angle_deg: float,
    airspeed_kmh: float,
    model: Optional[NeuralFoilModel] = None,
    calibration: Optional[CalibrationConfig] = None,
) -> tuple[float, float]:
    if model is None:
        model = _NF_MODEL

    V = airspeed_kmh / 3.6
    Re = AIR_DENSITY * V * CHORD / AIR_VISCOSITY

    if model is not None:
        CL = model.get_CL(angle_deg, Re)
        CD = model.get_CD(angle_deg, Re)
    else:
        alpha = math.radians(angle_deg)
        CL = 2 * math.pi / (1 + 2 / ASPECT_RATIO) * alpha
        CD = 0.015 + CL ** 2 / (math.pi * OSWALD_E * ASPECT_RATIO)

    return CL, CD


def compute_aero_forces(
    angle_deg: float,
    airspeed_kmh: float,
    model: Optional[NeuralFoilModel] = None,
    calibration: Optional[CalibrationConfig] = None,
) -> tuple[float, float, float, float]:
    CL, CD = _compute_CL_CD(angle_deg, airspeed_kmh, model)
    V = airspeed_kmh / 3.6
    q = 0.5 * AIR_DENSITY * V ** 2
    L = q * WING_AREA * CL
    D = q * WING_AREA * CD

    if calibration is not None:
        L += calibration.lift_bias
        D += calibration.drag_bias

    return L, D, CL, CD


def compute_aero_force(
    angle_deg: float,
    airspeed_kmh: float,
    model: Optional[NeuralFoilModel] = None,
    calibration: Optional[CalibrationConfig] = None,
) -> float:
    CL, CD = _compute_CL_CD(angle_deg, airspeed_kmh, model)
    V = airspeed_kmh / 3.6
    q = 0.5 * AIR_DENSITY * V ** 2
    L = q * WING_AREA * CL
    D = q * WING_AREA * CD

    if calibration is not None:
        L += calibration.lift_bias
        D += calibration.drag_bias
    
    alpha_rad = math.radians(angle_deg)
    return L * math.cos(alpha_rad) + D * math.sin(alpha_rad)


def force_to_steps(
    F_newtons: float,
    steps_per_newton: float = 204.0,
    max_steps: Optional[int] = None,
) -> int:
    if max_steps is None:
        max_steps = MAX_STEPPER_STEPS
    raw = int(round(abs(F_newtons) * steps_per_newton))
    return min(raw, max_steps)
