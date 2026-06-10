"""
Calibration configuration for physical model parameters.

Values here are tuned per physical wing unit after experimental calibration
"""

from dataclasses import dataclass

from wing_twin.config.types import check_ge, check_gt


@dataclass
class CalibrationConfig:
    # ADC -> unitless strain conversion.
    #
    # ESP32 firmware publishes strain_vector = (raw - dummy - tare_offset) * scale
    # with scale = 1.0 (stored in ESP32 calibration file after tare).
    # This constant converts those firmware strain values (in ADC count space)
    # to unitless strain.
    #
    #   \epsilon = ADC_count * 4 / (GAIN * 2^23 * GF)
    #     = ADC_count * 4 / (128 * 8_388_608 * 2.0)
    #     = ADC_count / 536_870_912
    #     \approx ADC_count * 1.8626e-9
    #
    adc_to_strain_scale: float = 1.862645149230957e-9

    # Force reconstruction
    H_matrix_scale: float = 1.0

    # Stepper motor
    steps_per_newton: float = 204.0
    stepper_max_steps: int = 2720
    stepper_max_frequency: float = 1000.0  # Hz (max step rate)

    # Aerodynamic force biases (additive corrections)
    lift_bias: float = 0.0
    drag_bias: float = 0.0

    strain_saturation_threshold: float = 0.003

    # Channel names matching ESP32 firmware ordering (9 active gauges)
    channel_names: tuple[str, ...] = (
        "root_0", "root_45", "root_90",
        "middle_0", "middle_45", "middle_90",
        "tip_0", "tip_45", "tip_90",
    )

    def __post_init__(self) -> None:
        check_ge(self.adc_to_strain_scale, "CalibrationConfig.adc_to_strain_scale", 0)
        check_ge(self.steps_per_newton, "CalibrationConfig.steps_per_newton", 0)
        check_gt(self.stepper_max_steps, "CalibrationConfig.stepper_max_steps", 0)
        check_gt(self.stepper_max_frequency, "CalibrationConfig.stepper_max_frequency", 0)
        check_gt(self.H_matrix_scale, "CalibrationConfig.H_matrix_scale", 0)
