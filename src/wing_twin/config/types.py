"""
Base types and validation helpers for configuration.
"""

from typing import Any, Protocol


class SupportsValidation(Protocol):
    def validate(self) -> None: ...


def check_gt(value: Any, field: str, limit: float) -> None:
    if not (value > limit):
        raise ValueError(f"{field} must be > {limit}, got {value}")


def check_ge(value: Any, field: str, limit: float) -> None:
    if not (value >= limit):
        raise ValueError(f"{field} must be >= {limit}, got {value}")


def check_range(value: Any, field: str, lo: float, hi: float) -> None:
    if not (lo <= value <= hi):
        raise ValueError(f"{field} must be in [{lo}, {hi}], got {value}")


def check_in(value: Any, field: str, choices: tuple[Any, ...]) -> None:
    if value not in choices:
        raise ValueError(f"{field} must be one of {choices}, got {value}")
