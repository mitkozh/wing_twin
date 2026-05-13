"""
Force reconstruction module for digital twin.

Implements the core force reconstruction algorithm using the
Moore-Penrose pseudoinverse of the strain sensitivity matrix.
"""

import numpy as np

STRAIN_METER_SCALE = 1e-6  # Convert µε to meters


def solve_forces(H_inv: np.ndarray, strain_vector: np.ndarray) -> np.ndarray:
    """
    Reconstruct force vector from strain measurements.

    Uses the pseudoinverse relationship: F = H⁺ · ε

    Note: The H_inv matrix expects strain in METERS (from Ansys FEA export).
    If input strain is in µε (microstrain), it must be converted to meters
    by multiplying by 1e-6.

    Args:
        H_inv: Moore-Penrose pseudoinverse of strain sensitivity matrix.
               Shape: (n_forces, n_gauges)
        strain_vector: Measured strain vector from sensors (in µε).
                       Shape: (n_gauges,) or (n_gauges, 1)

    Returns:
        Reconstructed force vector. Shape: (n_forces,)
    """
    strain_vector = np.asarray(strain_vector, dtype=np.float64).ravel()
    # Convert µε to meters (Ansys export unit)
    strain_meters = strain_vector * STRAIN_METER_SCALE
    return H_inv @ strain_meters


def force_vector_info(F: np.ndarray) -> dict:
    """
    Get information about a force vector.

    Args:
        F: Force vector

    Returns:
        Dictionary with force vector statistics
    """
    return {
        "num_forces": F.size,
        "magnitudes": F.ravel().tolist(),
        "max_abs": float(np.abs(F).max()),
    }