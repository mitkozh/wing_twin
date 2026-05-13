"""
Force reconstruction module for digital twin.

Implements the core force reconstruction algorithm using the
Moore-Penrose pseudoinverse of the strain sensitivity matrix.

Note: Strain is dimensionless (ratio, no units). Input values in
 micro-strain (1e-6) are converted to dimensionless by multiplying by 1e-6.
"""

import numpy as np

STRAIN_SCALE_FACTOR = 1e-6  # Convert micro-strain to dimensionless (m/m)


def solve_forces(H_inv: np.ndarray, strain_vector: np.ndarray) -> np.ndarray:
    """
    Reconstruct force vector from strain measurements.

    Uses the pseudoinverse relationship: F = H^+ * epsilon

    Args:
        H_inv: Moore-Penrose pseudoinverse of strain sensitivity matrix.
               Shape: (n_forces, n_gauges)
        strain_vector: Measured strain vector from sensors (in micro-strain).
                       Shape: (n_gauges,) or (n_gauges, 1)

    Returns:
        Reconstructed force vector. Shape: (n_forces,)

    Note:
        Input strain is converted from micro-strain to dimensionless (m/m)
        by multiplying by STRAIN_SCALE_FACTOR.
    """
    strain_vector = np.asarray(strain_vector, dtype=np.float64).ravel()
    strain_dimensionless = strain_vector * STRAIN_SCALE_FACTOR
    return H_inv @ strain_dimensionless


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