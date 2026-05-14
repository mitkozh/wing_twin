"""
Wing Orchestrator - main digital twin orchestration logic.
"""

import json
import asyncio
import numpy as np
from dataclasses import dataclass, field
from typing import Optional, Any

from dtwin import (
    load_transfer_matrices,
    solve_forces,
    compute_stress_field,
    compute_deformation_field,
    accumulate_damage,
    decide_control,
)
from dtwin.core import FatigueState, check_maintenance_needed
from dtwin.core.fatigue import DAMAGE_SAFE, DAMAGE_WARNING
from dtwin.core.matrices import matrix_info

from ..config import Config, MqttConfig, WebSocketConfig
from .mqtt_handler import MqttHandler
from .websocket_server import WebSocketServer
from .command_handler import OrchestratorCommandHandler


@dataclass
class WingState:
    """Current state of the wing digital twin."""
    strain_vector: list = field(default_factory=list)
    forces: list = field(default_factory=list)
    stress_field: list = field(default_factory=list)
    deformation_field: list = field(default_factory=list)
    damage: float = 0.0
    confidence: float = 100.0
    speed_pct: int = 100
    led_state: str = "green"
    maintenance_alert: bool = False

    def for_unity(self) -> dict:
        return {
            "strain": float(np.mean(self.strain_vector)) if self.strain_vector else 0.0,
            "forces": [round(f, 4) for f in self.forces],
            "stress_field": [round(s, 2) for s in self.stress_field],
            "deformation_field": [round(u, 6) for u in self.deformation_field],
            "damage": round(self.damage, 4),
            "confidence": round(self.confidence, 2),
            "speed": self.speed_pct,
            "led_state": self.led_state,
            "maintenance_alert": self.maintenance_alert,
        }

    def for_esp32(self) -> dict:
        return {
            "servo": self.speed_pct,
            "led": self.led_state,
        }


class WingOrchestrator:
    """
    Main orchestrator for the bidirectional digital twin.
    Coordinates MQTT input, force reconstruction, fatigue analysis, and output.
    """

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.matrices: Optional[Any] = None
        self.num_gauges = 3
        self.running = True
        self.paused = False
        self.state = WingState()
        self.fatigue_state = FatigueState()
        self.all_cycles: list = []
        self.params = {
            "osc_amp": 50.0,
            "osc_freq": 0.5,
            "sample_rate": 10,
            "base_strain": 100.0,
        }

        self._mqtt = MqttHandler(self.config.mqtt)
        self._ws_server = WebSocketServer(self.config.websocket)
        self._command_handler = OrchestratorCommandHandler(self)

        self._ws_server.set_state_provider(self.state.for_unity)
        self._ws_server.set_command_handler(self._command_handler.handle)
        self._mqtt.set_message_callback(self._on_sensor_data)

    @property
    def mqtt_handler(self) -> MqttHandler:
        return self._mqtt

    @property
    def ws_server(self) -> WebSocketServer:
        return self._ws_server

    @property
    def command_handler(self) -> OrchestratorCommandHandler:
        return self._command_handler

    def load_matrices(self) -> None:
        """Load transfer matrices from disk."""
        self.matrices = load_transfer_matrices()
        self.num_gauges = self.matrices.H_inv.shape[1]
        print(f"[MATRICES] Loaded transfer matrices ({self.num_gauges} gauge channels)")
        for name, info in matrix_info(self.matrices).items():
            print(f"  {name}: {info}")

    def start(self) -> None:
        """Start the orchestrator."""
        print("=" * 60)
        print("  Wing Digital Twin - Orchestrator")
        print("=" * 60)
        print(f"  MQTT:   {self.config.mqtt.broker}:{self.config.mqtt.port}")
        print(f"  Topics: subscribe={self.config.mqtt.sensors_topic}  publish={self.config.mqtt.control_topic}")
        print(f"  Damage: SAFE<{DAMAGE_SAFE}  WARNING<{DAMAGE_WARNING}  CRITICAL>={DAMAGE_WARNING}")
        print(f"  Confidence: EMA filter, alert below 50% for 10 frames")
        print("=" * 60)

        self._mqtt.connect()

    def stop(self) -> None:
        """Stop the orchestrator."""
        self.running = False
        self._mqtt.disconnect()

    def _on_sensor_data(self) -> None:
        """Called when new sensor data arrives."""
        self.process_frame()

    def process_frame(self) -> None:
        """Process a single frame of sensor data."""
        if self.paused or len(self._mqtt.strain_buffers) == 0 or self.matrices is None:
            return

        primary_buffer = list(self._mqtt.strain_buffers.values())[0]
        if len(primary_buffer) < self.num_gauges:
            return

        strain_vec = np.array(list(primary_buffer)[-self.num_gauges:], dtype=np.float64).ravel()

        F = solve_forces(self.matrices.H_inv, strain_vec)
        stress = compute_stress_field(self.matrices.S, F)
        deformation = compute_deformation_field(self.matrices.U, F)

        self.state.strain_vector = strain_vec.tolist()
        self.state.forces = F.tolist()
        self.state.stress_field = stress.tolist()
        self.state.deformation_field = deformation.tolist()

        current_buffer = list(self._mqtt.strain_buffers.values())[0]
        _, new_cycles = accumulate_damage(current_buffer, self.fatigue_state)
        self.all_cycles.extend(new_cycles)
        self.state.damage = self.fatigue_state.damage
        self.state.confidence = self.fatigue_state.confidence
        self.state.maintenance_alert = check_maintenance_needed(self.fatigue_state)

        self.state.led_state, self.state.speed_pct = decide_control(
            self.state.damage, self.fatigue_state.confidence
        )

        print(
            f"[ORCH] D={self.state.damage:.4f} | {self.state.led_state.upper()} | "
            f"Vmax={self.state.speed_pct}% | Conf={self.state.confidence:.1f}% | "
            f"F={[round(f,2) for f in self.state.forces]}"
        )
        self.publish_control()

    def publish_control(self) -> None:
        """Publish control output to ESP32."""
        payload = self.state.for_esp32()
        self._mqtt.publish(self.config.mqtt.control_topic, payload)

    async def run_async(self) -> None:
        """Run the orchestrator with async WebSocket server."""
        self.start()

        try:
            ws_task = asyncio.create_task(self._ws_server.start())
            broadcast_task = asyncio.create_task(self._ws_server.broadcast_loop())

            await asyncio.gather(ws_task, broadcast_task)
        except KeyboardInterrupt:
            print("\n[ORCHESTRATOR] Shutting down...")
            self.stop()