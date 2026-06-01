"""
Life prediction for digital twin.

Tracks damage-per-kilometer and remaining flight distance
based on accumulated fatigue damage across flights.
"""

from dataclasses import dataclass, asdict
import math


@dataclass
class LifePredictionState:
    ema_damage_per_km: float = 0.0
    ema_km_per_flight: float = 0.0
    total_damage: float = 0.0
    total_km_flown: float = 0.0
    total_flights: int = 0
    alpha: float = 0.3
    initial_remaining_km: float = 500.0

    @property
    def remaining_km(self) -> float:
        if self.ema_damage_per_km <= 0:
            return self.initial_remaining_km
        return max(0.0, (1.0 - self.total_damage) / self.ema_damage_per_km)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "LifePredictionState":
        state = LifePredictionState()
        for key, value in data.items():
            if hasattr(state, key) and key != "remaining_km":
                if key == "total_flights":
                    setattr(state, key, int(value))
                else:
                    setattr(state, key, value)
        return state

    def update_after_flight(self, damage_delta: float, km_delta: float) -> None:
        if km_delta > 0 and damage_delta > 0:
            damage_per_km = damage_delta / km_delta

            if self.ema_damage_per_km <= 0:
                self.ema_damage_per_km = damage_per_km
            else:
                self.ema_damage_per_km = (
                    damage_per_km * self.alpha
                    + self.ema_damage_per_km * (1.0 - self.alpha)
                )

            if self.ema_km_per_flight <= 0:
                self.ema_km_per_flight = km_delta
            else:
                self.ema_km_per_flight = (
                    km_delta * self.alpha
                    + self.ema_km_per_flight * (1.0 - self.alpha)
                )

        self.total_damage += damage_delta
        self.total_km_flown += km_delta
        self.total_flights += 1

    def pre_flight_check(self, planned_km: float) -> dict:
        safe = planned_km <= self.remaining_km
        warning = ""
        if not safe:
            if self.ema_damage_per_km <= 0:
                warning = "No flight history yet. Cannot assess risk for the planned distance."
            else:
                warning = (
                    f"Estimated remaining flight distance ({self.remaining_km:.1f} km) "
                    f"is too low for the planned {planned_km:.1f} km. "
                    "Flying the plane is not advised."
                )
        return {
            "safe": safe,
            "remaining_km": self.remaining_km,
            "planned_km": planned_km,
            "warning": warning,
        }
