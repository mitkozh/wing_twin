"""
Field computation module for digital twin.

Computes stress and deformation fields from force vectors
using pre-computed transfer matrices from FEA.

For S matrix, stress per Newton (Pa/N). Multiply by F(N) to get stress (Pa).
For U matrix, deformation per Newton (m/N). Multiply by F(N) to get deformation (m).
"""

import numpy as np


def compute_stress_field(S: np.ndarray, F: np.ndarray) -> np.ndarray:
    """
    Compute stress field from force vector.

    sigma = S @ F

    Args:
        S: Stress transfer matrix. Shape: (n_nodes, n_forces). Units: Pa/N.
        F: Force vector in Newtons. Shape: (n_forces,)

    Returns:
        Stress field in Pascals. Shape: (n_nodes,)
    """
    F = np.asarray(F, dtype=np.float64).ravel()
    S = np.asarray(S, dtype=np.float64)
    if S.ndim == 2:
        return S @ F
    return S * F


def compute_deformation_field(U: np.ndarray, F: np.ndarray) -> np.ndarray:
    """
    Compute deformation field from force vector.

    u = U @ F

    Args:
        U: Deformation transfer matrix. Shape: (n_nodes, n_forces). Units: m/N.
        F: Force vector in Newtons. Shape: (n_forces,)

    Returns:
        Deformation field in meters. Shape: (n_nodes,)
    """
    F = np.asarray(F, dtype=np.float64).ravel()
    U = np.asarray(U, dtype=np.float64)
    if U.ndim == 2:
        return U @ F
    return U * F


def field_summary(stress: np.ndarray, deformation: np.ndarray) -> dict:
    """Get summary statistics for stress and deformation fields."""
    return {
        "num_nodes": stress.size,
        "stress_max_pa": float(np.abs(stress).max()),
        "stress_max_mpa": float(np.abs(stress).max() / 1e6),
        "stress_mean_pa": float(np.mean(stress)),
        "deformation_max_m": float(np.abs(deformation).max()),
        "deformation_mean_m": float(np.mean(deformation)),
    }
