"""
Flight dynamics - handles acceleration-limited motion toward target states.
"""

import math


class FlightDynamics:
    """Acceleration-limited angle and speed dynamics.

    Smoothly ramps actual angle/speed toward desired targets
    with configurable acceleration limits (so the physical wing
    isn't subjected to sudden step changes).
    """

    def __init__(self, max_angle_rate: float = 15.0, max_speed_rate: float = 60.0):
        self.max_angle_rate = max_angle_rate
        self.max_speed_rate = max_speed_rate
        self._angle_rate: float = 0.0
        self._speed_rate: float = 0.0
        self.prev_angle_of_attack: float = 0.0

    def update(self, state, dt: float) -> None:
        """Smoothly move actual angle/speed toward targets."""
        state.control.angle_of_attack, self._angle_rate = self._accel_towards(
            state.control.angle_of_attack,
            self._angle_rate,
            state.control.target_angle_of_attack,
            self.max_angle_rate,
            dt,
        )
        state.control.airspeed, self._speed_rate = self._accel_towards(
            state.control.airspeed,
            self._speed_rate,
            state.control.target_airspeed,
            self.max_speed_rate,
            dt,
        )

    def d_alpha_dt(self, current_angle: float, sample_rate: float) -> float:
        """Rate of change of angle of attack (deg/s)."""
        rate = (current_angle - self.prev_angle_of_attack) * sample_rate
        self.prev_angle_of_attack = current_angle
        return rate

    @property
    def angle_rate(self) -> float:
        return self._angle_rate

    @property
    def speed_rate(self) -> float:
        return self._speed_rate

    def to_dict(self) -> dict:
        return {
            "angle_rate": self._angle_rate,
            "speed_rate": self._speed_rate,
            "prev_angle_of_attack": self.prev_angle_of_attack,
        }

    def from_dict(self, data: dict) -> None:
        self._angle_rate = data.get("angle_rate", 0.0)
        self._speed_rate = data.get("speed_rate", 0.0)
        self.prev_angle_of_attack = data.get("prev_angle_of_attack", 0.0)

    def reset(self) -> None:
        self._angle_rate = 0.0
        self._speed_rate = 0.0
        self.prev_angle_of_attack = 0.0

    @staticmethod
    def _accel_towards(
        pos: float, vel: float, target: float, accel: float, dt: float
    ) -> tuple[float, float]:
        """Move `pos` towards `target` with acceleration-limited velocity.
        Returns (new_pos, new_vel).
        """
        error = target - pos
        if abs(error) < 1e-6 and abs(vel) < 1e-6:
            return target, 0.0

        braking_dist = (vel * vel) / (2 * accel) if abs(vel) > 0.0 else 0.0

        if abs(error) <= braking_dist:
            vel -= math.copysign(accel * dt, vel)
        else:
            vel += math.copysign(accel * dt, error)

        if vel * error < 0:
            vel = 0.0

        pos += vel * dt

        if (pos - target) * error > 0.0:
            pos = target

        return pos, vel
