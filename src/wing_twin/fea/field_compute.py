"""
Field computation: stress = S @ F, deformation = U @ F.
"""

import numpy as np


def compute_stress_field(S: np.ndarray, F: np.ndarray) -> np.ndarray:
    F = np.asarray(F, dtype=np.float64).ravel()
    S_mat = np.asarray(S, dtype=np.float64)
    if S_mat.ndim == 2:
        return S_mat @ F
    return S_mat * F


def compute_deformation_field(U: np.ndarray, F: np.ndarray) -> np.ndarray:
    F = np.asarray(F, dtype=np.float64).ravel()
    U_mat = np.asarray(U, dtype=np.float64)
    if U_mat.ndim == 2:
        return U_mat @ F
    return U_mat * F
