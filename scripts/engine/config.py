"""
Engine configuration.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FatigueConfig:
    min_buffer_size: int = 50
    strain_buffer_size: int = 3000
    strain_to_stress: float = 70_000.0  # Pa/ue
    critical_stress_threshold: float = 50.0  # MPa
    critical_node_percentile: float = 90.0
    rainflow_range_bin_width: float = 2.0  # MPa
    buffer_size: int = 500
    max_critical_nodes: int = 100
    node_buffer_size: int = 500
    overlap_size: int = 20
    material: str = "demo"  # "demo", "aluminum", "steel"
    ema_alpha: float = 0.1
    confidence_threshold: float = 50.0
    confidence_frames_threshold: int = 10
    damage_safe: float = 0.3
    damage_warning: float = 0.8


@dataclass
class EngineConfig:
    """Configuration for the digital twin engine."""
    sample_rate: int = 10
    seed: Optional[int] = None
    matrix_dir: Optional[str] = None
    fatigue: FatigueConfig = field(default_factory=FatigueConfig)