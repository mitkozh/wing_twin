"""
Field computation module for digital twin.

Computes stress and deformation fields from force vectors
using pre-computed transfer matrices from FEA.
"""

import numpy as np


def compute_stress_field(S: np.ndarray, F: np.ndarray) -> np.ndarray:
    """
    Compute stress field from force vector using transfer matrix.

    Uses: σ = S · F

    Args:
        S: Stress field transfer matrix. Shape: (n_nodes, n_forces)
        F: Force vector. Shape: (n_forces,)

    Returns:
        Stress field values at each node. Shape: (n_nodes,)
    """
    F = np.asarray(F, dtype=np.float64).ravel()
    S = np.asarray(S, dtype=np.float64)
    if S.ndim == 2:
        return S @ F
    return S * F


def compute_deformation_field(U: np.ndarray, F: np.ndarray) -> np.ndarray:
    """
    Compute deformation field from force vector using transfer matrix.

    Uses: u = U · F

    Args:
        U: Deformation field transfer matrix. Shape: (n_nodes, n_forces)
        F: Force vector. Shape: (n_forces,)

    Returns:
        Deformation values at each node. Shape: (n_nodes,)
    """
    F = np.asarray(F, dtype=np.float64).ravel()
    U = np.asarray(U, dtype=np.float64)
    if U.ndim == 2:
        return U @ F
    return U * F


def field_summary(stress: np.ndarray, deformation: np.ndarray) -> dict:
    """
    Get summary statistics for stress and deformation fields.

    Args:
        stress: Stress field array
        deformation: Deformation field array

    Returns:
        Dictionary with field statistics
    """
    return {
        "num_nodes": stress.size,
        "stress_max": float(np.abs(stress).max()),
        "stress_mean": float(np.mean(stress)),
        "deformation_max": float(np.abs(deformation).max()),
        "deformation_mean": float(np.mean(deformation)),
    }