"""
Calibration configuration for physical model parameters.

Values here are tuned per physical wing unit after experimental calibration
"""

from dataclasses import dataclass, field

from wing_twin.config.types import check_ge, check_gt


@dataclass
class CalibrationConfig:
    # ADC -> strain conversion
    #
    # Converts HX711 compensated ADC counts to unitless strain.
    # Calculation assumes:
    #   - Quarter-bridge: 1 active strain gauge + 3 completion resistors
    #   - HX711 gain = 128 (set by 25 SCK pulses in firmware)
    #   - Gauge factor GF = 2.0 (standard cheap metal foil)
    #   - V_excitation = AVDD (E+ tracks AVDD on typical HX711 modules)
    #
    #   \epsilon = ADC_count * 4 / (GAIN * 2^23 * GF)
    #     = ADC_count * 4 / (128 * 8_388_608 * 2.0)
    #     = ADC_count / 536_870_912
    #     \approx ADC_count * 1.8626e-9
    #
    # Re-calibrate empirically by applying a known strain and adjusting.
    adc_to_strain_scale: float = 1.862645149230957e-9

    # Per-gauge zero offsets and gain trims (applied BEFORE adc_to_strain_scale)
    sensor_zero_offsets: tuple[float, ...] = field(default_factory=tuple)
    sensor_gain_factors: tuple[float, ...] = field(default_factory=tuple)

    # Force reconstruction
    H_matrix_scale: float = 1.0

    # Stepper motor
    steps_per_newton: float = 204.0
    stepper_max_steps: int = 2720
    stepper_max_frequency: float = 1000.0  # Hz (max step rate)

    # Aerodynamic force biases (additive corrections)
    lift_bias: float = 0.0
    drag_bias: float = 0.0

    def __post_init__(self) -> None:
        check_ge(self.adc_to_strain_scale, "CalibrationConfig.adc_to_strain_scale", 0)
        check_ge(self.steps_per_newton, "CalibrationConfig.steps_per_newton", 0)
        check_gt(self.stepper_max_steps, "CalibrationConfig.stepper_max_steps", 0)
        check_gt(self.stepper_max_frequency, "CalibrationConfig.stepper_max_frequency", 0)
        check_gt(self.H_matrix_scale, "CalibrationConfig.H_matrix_scale", 0)
