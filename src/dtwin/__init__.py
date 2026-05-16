"""
Digital Twin - Real-time wing fatigue monitoring system.
"""

from .core import (
    load_transfer_matrices,
    solve_forces,
    compute_stress_field,
    compute_deformation_field,
    accumulate_damage,
    decide_control,
)

__version__ = "1.0.0"
__all__ = [
    "load_transfer_matrices",
    "solve_forces",
    "compute_stress_field",
    "compute_deformation_field",
    "accumulate_damage",
    "decide_control",
]