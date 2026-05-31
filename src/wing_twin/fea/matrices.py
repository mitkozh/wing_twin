"""
Transfer matrix loading and management for force reconstruction.

Transfer matrices are pre-computed from Ansys FEA with unit force (1 N):
- H: Strain sensitivity matrix (n_gauges x n_forces). Maps force -> raw strain.
- H_inv: Pseudoinverse of H (n_forces x n_gauges). Maps raw strain -> force (N).
- S: Stress field transfer matrix (n_nodes x n_forces). Maps force -> stress (Pa).
- U: Deformation field transfer matrix (n_nodes x n_forces). Maps force -> deformation (m).

All matrices are loaded raw from .npy files.
  - Strain: raw (dimensionless)
  - Force: Newtons (N)
  - Stress: Pascal (Pa) from S @ F; convert to MPa via /1e6 for fatigue
  - Deformation: meters (m)
"""

import numpy as np
from pathlib import Path
from typing import NamedTuple, Optional


class TransferMatrices(NamedTuple):
    """Container for transfer matrices from FEA."""
    H: np.ndarray
    H_inv: np.ndarray
    S: np.ndarray
    U: np.ndarray

    @property
    def n_forces(self) -> int:
        return self.H.shape[1]

    @property
    def n_gauges(self) -> int:
        return self.H.shape[0]

    @property
    def n_nodes(self) -> int:
        return self.S.shape[0]


def _find_project_root() -> Path:
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
    if matrix_dir is None:
        matrix_dir = DEFAULT_MATRIX_DIR

    matrix_dir = Path(matrix_dir)

    required_files = {
        "H": "H.npy",
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

    H = np.load(matrix_dir / "H.npy")
    H_inv = np.load(matrix_dir / "Inverse_H.npy")
    S = np.load(matrix_dir / "EquivalentStress.npy")
    U = np.load(matrix_dir / "TotalDeformation.npy")

    if validate:
        _validate_matrices(H, H_inv, S, U)

    return TransferMatrices(H=H, H_inv=H_inv, S=S, U=U)


def _validate_matrices(
    H: np.ndarray, H_inv: np.ndarray, S: np.ndarray, U: np.ndarray
) -> None:
    n_gauges_h, n_forces_h = H.shape
    n_forces_hi, n_gauges_hi = H_inv.shape
    n_nodes_s, n_forces_s = S.shape
    n_nodes_u, n_forces_u = U.shape

    errors = []

    if n_forces_h != n_forces_hi:
        errors.append(f"H forces ({n_forces_h}) != H_inv forces ({n_forces_hi})")
    if n_gauges_h != n_gauges_hi:
        errors.append(f"H gauges ({n_gauges_h}) != H_inv gauges ({n_gauges_hi})")
    if n_forces_s != n_forces_h:
        errors.append(f"S forces ({n_forces_s}) != H forces ({n_forces_h})")
    if n_forces_u != n_forces_h:
        errors.append(f"U forces ({n_forces_u}) != H forces ({n_forces_h})")
    if n_nodes_s != n_nodes_u:
        errors.append(f"S nodes ({n_nodes_s}) != U nodes ({n_nodes_u})")

    for m, name in [(H, "H"), (H_inv, "H_inv"), (S, "S"), (U, "U")]:
        if m.ndim != 2:
            errors.append(f"{name} should be 2D, got {m.ndim}D")

    if errors:
        raise ValueError(f"Matrix validation failed: {'; '.join(errors)}")
