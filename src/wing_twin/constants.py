"""
Shared physical constants for Wing Digital Twin.

All modules should import from here rather than duplicating values.
"""

# Air properties (ISA sea level)
AIR_DENSITY: float = 1.225       # kg/m^3
AIR_VISCOSITY: float = 1.789e-5  # Pa*s

# Prototype wing geometry
WING_AREA: float = 0.012375   # m^2
CHORD: float = 0.0491         # m
ASPECT_RATIO: float = 7.27
OSWALD_E: float = 0.85

# Actuator limits
MAX_STEPPER_STEPS: int = 2720
