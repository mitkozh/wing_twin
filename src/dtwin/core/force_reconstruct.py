"""
Force reconstruction module for digital twin.

Implements force reconstruction using the Moore-Penrose pseudoinverse
of the strain sensitivity matrix: F = H^+ * epsilon

Units:
  - Input strain: microstrain (ue)
  - H_inv matrix: raw strain -> force (N)
  - Conversion: raw_strain = microstrain * 1e-6
  - Output force: Newtons (N)
"""

import numpy as np

STRAIN_TO_RAW = 1e-6  # Convert microstrain (ue) to dimensionless raw strain


def solve_forces(H_inv: np.ndarray, strain_vector: np.ndarray) -> np.ndarray:
    """
    Reconstruct force vector from strain measurements.

    F = H_inv @ (strain_ue * 1e-6)

    Args:
        H_inv: Pseudoinverse of strain sensitivity matrix.
               Shape: (n_forces, n_gauges). Expects raw strain input.
        strain_vector: Measured strain in microstrain (ue).
                       Shape: (n_gauges,) or (n_gauges, 1)

    Returns:
        Reconstructed force vector in Newtons. Shape: (n_forces,)
    """
    strain_vector = np.asarray(strain_vector, dtype=np.float64).ravel()
    strain_raw = strain_vector * STRAIN_TO_RAW
    return H_inv @ strain_raw


def force_vector_info(F: np.ndarray) -> dict:
    """Get information about a force vector."""
    return {
        "num_forces": F.size,
        "magnitudes": F.ravel().tolist(),
        "max_abs": float(np.abs(F).max()),
    }
