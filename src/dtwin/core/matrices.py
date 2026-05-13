"""
Transfer matrix loading and management for force reconstruction.

Transfer matrices are pre-computed from Ansys FEA:
- H_inv: Strain sensitivity matrix pseudoinverse (force reconstruction)
- S: Stress field transfer matrix
- U: Deformation field transfer matrix
"""

import numpy as np
from pathlib import Path
from typing import NamedTuple, Optional


class TransferMatrices(NamedTuple):
    """Container for transfer matrices from FEA."""
    H_inv: np.ndarray  # Shape: (n_forces, n_gauges)
    S: np.ndarray      # Shape: (n_nodes, n_forces)
    U: np.ndarray      # Shape: (n_nodes, n_forces)


def _find_project_root() -> Path:
    """Find project root by looking for marker files."""
    current = Path(__file__).resolve()
    for parent in [current.parent] + list(current.parents):
        if (parent / "pyproject.toml").exists() or (parent / "transfer_matrices").exists():
            return parent
    return current.parent.parent.parent


DEFAULT_MATRIX_DIR = _find_project_root() / "transfer_matrices"


def load_transfer_matrices(
    matrix_dir: Optional[str | Path] = None,
    validate: bool = True,
) -> TransferMatrices:
    """
    Load transfer matrices from .npy files.

    Args:
        matrix_dir: Path to directory containing matrix files.
                   Defaults to project_root/transfer_matrices
        validate: If True, validate matrix shapes and dimensions

    Returns:
        TransferMatrices namedtuple

    Raises:
        FileNotFoundError: If required matrix files are missing
        ValueError: If matrix validation fails
    """
    if matrix_dir is None:
        matrix_dir = DEFAULT_MATRIX_DIR

    matrix_dir = Path(matrix_dir)

    required_files = {
        "Inverse_H": "Inverse_H.npy",
        "EquivalentStress": "EquivalentStress.npy",
        "TotalDeformation": "TotalDeformation.npy",
    }

    missing = []
    for name, filename in required_files.items():
        filepath = matrix_dir / filename
        if not filepath.exists():
            missing.append(f"'{name}' ({filepath})")

    if missing:
        raise FileNotFoundError(
            f"Transfer matrices not found: {', '.join(missing)}. "
            f"Ensure matrix files exist in {matrix_dir}"
        )

    H_inv = np.load(matrix_dir / "Inverse_H.npy")
    S = np.load(matrix_dir / "EquivalentStress.npy")
    U = np.load(matrix_dir / "TotalDeformation.npy")

    if validate:
        _validate_matrices(H_inv, S, U)

    return TransferMatrices(H_inv=H_inv, S=S, U=U)


def _validate_matrices(H_inv: np.ndarray, S: np.ndarray, U: np.ndarray) -> None:
    """
    Validate that matrix dimensions are compatible.

    Args:
        H_inv: Strain sensitivity matrix pseudoinverse
        S: Stress field matrix
        U: Deformation field matrix

    Raises:
        ValueError: If matrices have incompatible dimensions
    """
    n_forces = H_inv.shape[0]
    n_gauges = H_inv.shape[1]
    n_nodes_s = S.shape[0]
    n_nodes_u = U.shape[0]
    n_forces_s = S.shape[1]
    n_forces_u = U.shape[1]

    errors = []

    if n_forces_s != n_forces:
        errors.append(f"S matrix force dimension ({n_forces_s}) != H_inv ({n_forces})")

    if n_forces_u != n_forces:
        errors.append(f"U matrix force dimension ({n_forces_u}) != H_inv ({n_forces})")

    if n_nodes_s != n_nodes_u:
        errors.append(f"S and U have different node counts: {n_nodes_s} vs {n_nodes_u}")

    if H_inv.ndim != 2:
        errors.append(f"H_inv should be 2D, got {H_inv.ndim}D")

    if S.ndim != 2:
        errors.append(f"S should be 2D, got {S.ndim}D")

    if U.ndim != 2:
        errors.append(f"U should be 2D, got {U.ndim}D")

    if errors:
        raise ValueError(f"Matrix validation failed: {'; '.join(errors)}")


def matrix_info(matrices: TransferMatrices) -> dict:
    """
    Get human-readable information about transfer matrices.

    Args:
        matrices: TransferMatrices instance

    Returns:
        Dictionary with matrix shapes and descriptions
    """
    return {
        "H_inv": f"{matrices.H_inv.shape} (strain→force)",
        "S": f"{matrices.S.shape} (force→stress field)",
        "U": f"{matrices.U.shape} (force→deformation field)",
    }