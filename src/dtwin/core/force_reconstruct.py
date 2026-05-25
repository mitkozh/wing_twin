"""
Force reconstruction module for digital twin.

Implements force reconstruction using the Moore-Penrose pseudoinverse
of the strain sensitivity matrix: F = H^+ * epsilon

Units:
  - Input strain: raw (dimensionless)
  - H_inv matrix: raw strain -> force (N)
  - Output force: Newtons (N)
"""

import numpy as np


def solve_forces(H_inv: np.ndarray, strain_vector: np.ndarray) -> np.ndarray:
    """
    Reconstruct force vector from strain measurements.

    F = H_inv @ epsilon

    Args:
        H_inv: Pseudoinverse of strain sensitivity matrix.
               Shape: (n_forces, n_gauges). Expects raw strain input.
        strain_vector: Measured strain (dimensionless).
                       Shape: (n_gauges,) or (n_gauges, 1)

    Returns:
        Reconstructed force vector in Newtons. Shape: (n_forces,)
    """
    strain_vector = np.asarray(strain_vector, dtype=np.float64).ravel()
    return H_inv @ strain_vector
