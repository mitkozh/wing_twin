"""
Force reconstruction: F = H_inv @ epsilon.
"""

import numpy as np


def solve_forces(H_inv: np.ndarray, strain_vector: np.ndarray) -> np.ndarray:
    strain_vector = np.asarray(strain_vector, dtype=np.float64).ravel()
    return H_inv @ strain_vector
