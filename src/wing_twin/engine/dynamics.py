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

    def __init__(self, angle_accel: float = 15.0, speed_accel: float = 60.0):
        self.angle_accel = angle_accel
        self.speed_accel = speed_accel
        self._angle_velocity: float = 0.0
        self._speed_velocity: float = 0.0
        self.prev_angle_of_attack: float = 0.0

    def update(self, state, dt: float) -> None:
        """Smoothly move actual angle/speed toward targets."""
        state.angle_of_attack, self._angle_velocity = self._accel_towards(
            state.angle_of_attack,
            self._angle_velocity,
            state.target_angle_of_attack,
            self.angle_accel,
            dt,
        )
        state.airspeed, self._speed_velocity = self._accel_towards(
            state.airspeed,
            self._speed_velocity,
            state.target_airspeed,
            self.speed_accel,
            dt,
        )

    def d_alpha_dt(self, current_angle: float, sample_rate: float) -> float:
        """Rate of change of angle of attack (deg/s)."""
        rate = (current_angle - self.prev_angle_of_attack) * sample_rate
        self.prev_angle_of_attack = current_angle
        return rate

    @property
    def angle_velocity(self) -> float:
        return self._angle_velocity

    @property
    def speed_velocity(self) -> float:
        return self._speed_velocity

    def to_dict(self) -> dict:
        return {
            "angle_velocity": self._angle_velocity,
            "speed_velocity": self._speed_velocity,
            "prev_angle_of_attack": self.prev_angle_of_attack,
        }

    def from_dict(self, data: dict) -> None:
        self._angle_velocity = data.get("angle_velocity", 0.0)
        self._speed_velocity = data.get("speed_velocity", 0.0)
        self.prev_angle_of_attack = data.get("prev_angle_of_attack", 0.0)

    def reset(self) -> None:
        self._angle_velocity = 0.0
        self._speed_velocity = 0.0
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
