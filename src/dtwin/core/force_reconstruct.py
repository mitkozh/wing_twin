"""
Force reconstruction module for digital twin.

Implements the core force reconstruction algorithm using the
Moore-Penrose pseudoinverse of the strain sensitivity matrix.

Note: The strain unit conversion requires verification against actual
 Ansys FEA export format. The SSA states Ansys exports strain in meters
 (m), but if strain is already dimensionless (m/m), the 1e-6 scale factor
 introduces a systematic error. Current implementation assumes input is in
 micro-strain and converts to meters for compatibility with Ansys-exported matrices.
"""

import numpy as np

STRAIN_METER_SCALE = 1e-6


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
        Input strain is converted from micro-strain to meters using STRAIN_METER_SCALE.
        This requires verification against actual Ansys export units.
    """
    strain_vector = np.asarray(strain_vector, dtype=np.float64).ravel()
    # Convert micro-strain to meters (Ansys export unit)
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