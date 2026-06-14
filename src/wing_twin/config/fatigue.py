"""
Fatigue configuration - moved from fatigue/fatigue.py to the centralized config package.
"""

from dataclasses import dataclass

from wing_twin.config.types import check_gt, check_ge, check_range


@dataclass
class FatigueConfig:
    min_buffer_size: int = 50
    rainflow_range_bin_width: float = 2.0
    critical_stress_threshold: float = 50.0
    critical_node_percentile: float = 90.0
    max_critical_nodes: int = 200
    node_buffer_size: int = 500
    confidence_threshold: float = 50.0
    confidence_frames_threshold: int = 50
    low_load_threshold: float = 1e-5

    # EMA smoothing for the confidence residual (0.0 = no smoothing, 1.0 = no history)
    ema_alpha: float = 0.1

    # S-curve half-saturation point for per-channel model-fit confidence.
    # Higher values make the model more forgiving of residual errors.
    s_curve_threshold: float = 0.30

    # Blending weights for the 3-component confidence score.
    # Must sum to 1.0; higher model_weight prioritises per-channel fit.
    confidence_weight_model: float = 0.60
    confidence_weight_group: float = 0.20
    confidence_weight_force: float = 0.20

    # When True, low-confidence channels do NOT trigger re-imputation.
    disable_confidence_imputation: bool = False

    damage_warning: float = 0.3
    damage_critical: float = 0.8
    material: str = "demo"
    initial_remaining_km: float = 500.0

    def __post_init__(self) -> None:
        check_gt(self.min_buffer_size, "FatigueConfig.min_buffer_size", 0)
        check_gt(self.rainflow_range_bin_width, "FatigueConfig.rainflow_range_bin_width", 0)
        check_ge(self.critical_stress_threshold, "FatigueConfig.critical_stress_threshold", 0)
        check_range(self.critical_node_percentile, "FatigueConfig.critical_node_percentile", 0, 100)
        check_gt(self.max_critical_nodes, "FatigueConfig.max_critical_nodes", 0)
        check_gt(self.node_buffer_size, "FatigueConfig.node_buffer_size", 0)
        check_range(self.confidence_threshold, "FatigueConfig.confidence_threshold", 0, 100)
        check_ge(self.confidence_frames_threshold, "FatigueConfig.confidence_frames_threshold", 0)
        check_gt(self.low_load_threshold, "FatigueConfig.low_load_threshold", 0)
        check_range(self.ema_alpha, "FatigueConfig.ema_alpha", 0, 1)
        check_gt(self.s_curve_threshold, "FatigueConfig.s_curve_threshold", 0)
        for name, val in [
            ("confidence_weight_model", self.confidence_weight_model),
            ("confidence_weight_group", self.confidence_weight_group),
            ("confidence_weight_force", self.confidence_weight_force),
        ]:
            check_range(val, f"FatigueConfig.{name}", 0, 1)
        total_w = (
            self.confidence_weight_model
            + self.confidence_weight_group
            + self.confidence_weight_force
        )
        if abs(total_w - 1.0) > 1e-6:
            raise ValueError(
                f"FatigueConfig confidence weights must sum to 1.0, got {total_w}"
            )
        check_range(self.damage_warning, "FatigueConfig.damage_warning", 0, 1)
        check_range(self.damage_critical, "FatigueConfig.damage_critical", 0, 1)
        if not (self.damage_warning < self.damage_critical):
            raise ValueError(
                f"FatigueConfig.damage_warning ({self.damage_warning}) must be "
                f"< damage_critical ({self.damage_critical})"
            )
        check_ge(self.initial_remaining_km, "FatigueConfig.initial_remaining_km", 0)
