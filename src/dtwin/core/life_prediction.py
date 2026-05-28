"""
Life prediction for digital twin

Calculates cycles left till the full damage based on damage and cycle rate.

"""

from dataclasses import dataclass, asdict
import math


@dataclass
class LifePredictionState:
    ema_damage_per_cycle: float = 0.0
    ema_cycles_per_run: float = 0.0
    last_damage: float = 0.0
    last_total_cycles: float = 0.0

    # Higher alpha = more preference to newest run.
    # Lower alpha = more memory of older runs.
    alpha: float = 0.3

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "LifePredictionState":
        return LifePredictionState(**data)

    def update_after_run_predictions(
        self,
        current_damage: float,
        total_cycles: float,
    ) -> dict:
        damage_delta = current_damage - self.last_damage
        cycles_delta = total_cycles - self.last_total_cycles

        if cycles_delta > 0 and damage_delta > 0:
            damage_per_cycle = damage_delta / cycles_delta

            if self.ema_damage_per_cycle <= 0:
                self.ema_damage_per_cycle = damage_per_cycle
            else:
                self.ema_damage_per_cycle = (
                    damage_per_cycle * self.alpha
                    + self.ema_damage_per_cycle * (1.0 - self.alpha)
                )

            if self.ema_cycles_per_run <= 0:
                self.ema_cycles_per_run = cycles_delta
            else:
                self.ema_cycles_per_run = (
                    cycles_delta * self.alpha
                    + self.ema_cycles_per_run * (1.0 - self.alpha)
                )

        self.last_damage = current_damage
        self.last_total_cycles = total_cycles

        if self.ema_damage_per_cycle <= 0:
            cycles_remaining = math.inf
        else:
            cycles_remaining = max(
                0.0,
                (1.0 - current_damage) / self.ema_damage_per_cycle
            )

        flight_allowed = cycles_remaining >= self.ema_cycles_per_run

        warning = ""
        if not flight_allowed:
            warning = (
                "Estimated fatigue life is too low to allow for the next flight. "
                "Starting the plane is not advised."
            )

        return {
            "cycles_remaining": cycles_remaining,
            "ema_damage_per_cycle": self.ema_damage_per_cycle,
            "ema_cycles_per_run": self.ema_cycles_per_run,
            "flight_allowed": flight_allowed,
            "prediction_warning": warning,
        }
