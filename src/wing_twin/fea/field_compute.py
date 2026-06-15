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


def compute_force_from_deformation(U: np.ndarray, deformation: np.ndarray) -> np.ndarray:
    deformation = np.asarray(deformation, dtype=np.float64).ravel()
    U_mat = np.asarray(U, dtype=np.float64)
    if U_mat.ndim == 2:
        U_pinv = np.linalg.pinv(U_mat)
        return (U_pinv @ deformation).ravel()
    if deformation.ndim == 0:
        return np.array([deformation / U_mat]) if U_mat != 0 else np.zeros(1)
    return deformation / U_mat
