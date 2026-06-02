"""
Wind simulation configuration."""

from dataclasses import dataclass


@dataclass
class WindConfig:
    # See Desmos: https://www.desmos.com/calculator/tt9d5etwya

    enabled: bool = True
    amplification: float = 1 # l

    base_freq_hz: float = 0.4 # u
    mid_freq_hz: float = 1.9 # a
    high_freq_hz: float = 3 # c

    mid_sharpness: int = 3 # b
    high_sharpness: int = 23 # d

    base_power: float = 1 # h
    mid_power: float = 1 # j
    high_power: float = 1 # f
