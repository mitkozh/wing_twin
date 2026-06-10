import threading
from dataclasses import dataclass
from typing import Optional

import numpy as np

from wing_twin.config import SimulationConfig
from wing_twin.config.calibration import CalibrationConfig
from wing_twin.types import DataSource, SensorReading
from wing_twin.fea.matrices import TransferMatrices
from wing_twin.physics.aero import compute_aero_force, NeuralFoilModel
from wing_twin.physics.wind import WindModel, apparent_wind


@dataclass
class SimulatorState:
    time_elapsed: float = 0.0
    num_gauges: int = 1
    airspeed: float = 0.0
    angle_of_attack: float = 0.0


class SimulatorSource(DataSource):

    def __init__(
        self,
        config: Optional[SimulationConfig] = None,
        aero_model: Optional[NeuralFoilModel] = None,
        wind_model: Optional[WindModel] = None,
        calibration: Optional[CalibrationConfig] = None,
    ):
        self.config = config or SimulationConfig()
        self._state = SimulatorState()
        self._running = False
        self._lock = threading.Lock()
        self._matrices: Optional[TransferMatrices] = None
        self._aero_model: Optional[NeuralFoilModel] = aero_model
        self._wind: Optional[WindModel] = wind_model
        self._calibration: Optional[CalibrationConfig] = calibration

    def set_airspeed(self, airspeed: float) -> None:
        with self._lock:
            self._state.airspeed = max(0.0, airspeed)

    def set_angle_of_attack(self, angle_deg: float) -> None:
        with self._lock:
            self._state.angle_of_attack = angle_deg

    def set_num_gauges(self, num: int) -> None:
        with self._lock:
            self._state.num_gauges = num

    def set_matrices(self, matrices: TransferMatrices) -> None:
        with self._lock:
            self._matrices = matrices
            self._state.num_gauges = matrices.n_gauges

    def set_aero_model(self, model: NeuralFoilModel) -> None:
        self._aero_model = model

    def set_wind_model(self, wind_model: WindModel) -> None:
        self._wind = wind_model

    def set_calibration(self, calibration: CalibrationConfig) -> None:
        self._calibration = calibration

    def connect(self) -> bool:
        if self._matrices is None:
            raise RuntimeError("TransferMatrices required before connecting")
        self._running = True
        return True

    def disconnect(self) -> None:
        self._running = False

    def is_connected(self) -> bool:
        return self._running

    def _generate_force(
        self, t: float, dt: float, airspeed: float, angle_deg: float
    ) -> float:
        u_w, w_w = 0.0, 0.0
        if self._wind is not None:
            u_w, w_w = self._wind.sample(t, dt=dt)

        v_eff, alpha_eff = apparent_wind(airspeed, angle_deg, u_w, w_w)
        return compute_aero_force(
            alpha_eff, v_eff,
            model=self._aero_model,
            calibration=self._calibration,
        )

    def _read(
        self, t: float, dt: float, airspeed: float, angle_deg: float
    ) -> tuple[np.ndarray, float]:
        base_force = self._generate_force(t, dt, airspeed, angle_deg)
        F = np.full(self._matrices.n_forces, base_force, dtype=np.float64)
        strain_raw = (self._matrices.H @ F).flatten()
        noise = np.random.normal(0, self.config.strain_noise_std, size=strain_raw.shape)
        strain_vector = strain_raw + noise
        accel_z = -strain_raw[0] * self.config.accel_scale + np.random.normal(0, self.config.accel_noise)
        return strain_vector, accel_z

    def read(self) -> Optional[SensorReading]:
        with self._lock:
            t = self._state.time_elapsed
            airspeed = self._state.airspeed
            angle_deg = self._state.angle_of_attack

        dt = 1.0 / self.config.sample_rate
        strain_vector, accel_z = self._read(t, dt, airspeed, angle_deg)

        with self._lock:
            self._state.time_elapsed += dt

        return SensorReading(
            strain_vector=strain_vector,
            accel_z=accel_z,
            timestamp=int(t * 1000),
            gauge_id="simulator",
        )
