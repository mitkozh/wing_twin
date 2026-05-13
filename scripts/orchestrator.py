"""
Wing Digital Twin - Python Orchestrator
Bidirectional digital twin using force reconstruction:
  1. Receive multi-gauge strain vector from MQTT
  2. Reconstruct force vector F = H⁺ · ε
  3. Compute stress field σ = S · F and deformation field u = U · F
  4. Accumulate fatigue damage via rainflow + Miner's Rule
  5. Compute confidence via EMA-filtered residuals (Level 2)
  6. Publish control to ESP32 via MQTT
  7. Broadcast full state to Unity via WebSocket
"""

import json
import argparse
import threading
import asyncio
import time
import numpy as np
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import paho.mqtt.client as mqtt
import websockets

from dtwin import (
    load_transfer_matrices,
    solve_forces,
    compute_stress_field,
    compute_deformation_field,
    accumulate_damage,
    decide_control,
)
from dtwin.core import FatigueState, check_maintenance_needed
from dtwin.core.actuator import ActuatorModel, apply_force_target
from dtwin.core.matrices import matrix_info
from dtwin.core.fatigue import DAMAGE_SAFE, DAMAGE_WARNING


MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_SENSORS_TOPIC = "wing/sensors"
MQTT_CONTROL_TOPIC = "wing/control"


@dataclass
class WingState:
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


class Orchestrator:
    def __init__(self, mqtt_broker: str = MQTT_BROKER, mqtt_port: int = MQTT_PORT):
        self.matrices: Optional[object] = None
        self.num_gauges = 3
        self.running = True
        self.paused = False
        self.state = WingState()
        self.fatigue_state = FatigueState()
        self.strain_buffers: dict[str, deque] = {}
        self.connected_unity_clients: set = set()
        self.all_cycles: list = []
        self.mqtt_broker = mqtt_broker
        self.mqtt_port = mqtt_port
        self.mqtt_client = mqtt.Client()

        self.params = {
            "osc_amp": 50.0,
            "osc_freq": 0.5,
            "sample_rate": 10,
            "base_strain": 100.0,
        }

        self.actuator = ActuatorModel()
        self.target_force = 0.0
        self.target_force_active = False

    def process_frame(self):
        if self.paused or len(self.strain_buffers) == 0 or self.matrices is None:
            return

        primary_buffer = list(self.strain_buffers.values())[0]
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

        current_buffer = list(self.strain_buffers.values())[0]
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

    def on_mqtt_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print(f"[MQTT] Connected to {self.mqtt_broker}")
            client.subscribe(MQTT_SENSORS_TOPIC)
        else:
            print(f"[MQTT] Connection failed: {rc}")

    def on_mqtt_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            if "strain" in payload:
                strain_val = float(payload["strain"])
                key = "primary"
                if key not in self.strain_buffers:
                    self.strain_buffers[key] = deque(maxlen=max(100, self.num_gauges))
                self.strain_buffers[key].append(strain_val)
            elif "strain_vector" in payload:
                strain_vals = np.array(payload["strain_vector"], dtype=np.float64)
                self.num_gauges = len(strain_vals)
                key = "vector"
                if key not in self.strain_buffers:
                    self.strain_buffers[key] = deque(maxlen=1)
                self.strain_buffers[key].clear()
                self.strain_buffers[key].append(strain_vals.tolist())
            else:
                return

            if len(self.strain_buffers.get("primary", [])) >= max(100, self.num_gauges):
                self.process_frame()
            elif len(self.strain_buffers.get("vector", [])) >= 1:
                self.process_frame()
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            print(f"[MQTT] Parse error: {e}")

    def publish_control(self):
        payload = json.dumps(self.state.for_esp32())
        self.mqtt_client.publish(MQTT_CONTROL_TOPIC, payload)

    async def websocket_handler(self, ws: websockets.WebSocketServerProtocol, path: str):
        self.connected_unity_clients.add(ws)
        print(f"[WEBSOCKET] Unity client connected ({len(self.connected_unity_clients)} total)")
        try:
            await ws.send(json.dumps(self.state.for_unity()))
            async for msg in ws:
                response = self.handle_command(msg)
                if response:
                    await ws.send(json.dumps(response))
        except websockets.ConnectionClosed:
            pass
        finally:
            self.connected_unity_clients.discard(ws)
            print(f"[WEBSOCKET] Unity client disconnected")

    def handle_command(self, msg: str) -> Optional[dict]:
        try:
            cmd = json.loads(msg)
        except json.JSONDecodeError:
            return {"cmd": "error", "message": "Invalid JSON"}

        command = cmd.get("cmd")
        if command is None:
            return {"cmd": "error", "message": "Missing 'cmd' field"}

        if command == "ping":
            return {"cmd": "pong", "time": time.time()}

        elif command == "play":
            self.paused = False
            print("[CMD] Simulation resumed")
            return {"cmd": "ack", "action": "play"}

        elif command == "pause":
            self.paused = True
            print("[CMD] Simulation paused")
            return {"cmd": "ack", "action": "pause"}

        elif command == "reset":
            target = cmd.get("target", "damage")
            if target == "damage":
                self.fatigue_state.damage = 0.0
                self.state.damage = 0.0
            elif target == "strain":
                self.strain_buffers.clear()
            elif target == "all":
                self.fatigue_state.damage = 0.0
                self.state.damage = 0.0
                self.strain_buffers.clear()
            print(f"[CMD] Reset {target}")
            return {"cmd": "ack", "action": "reset", "target": target}

        elif command == "set_param":
            key = cmd.get("key")
            value = cmd.get("value")
            if key and value is not None:
                if key in self.params:
                    try:
                        self.params[key] = float(value)
                        print(f"[CMD] Set {key} = {self.params[key]}")
                        return {"cmd": "ack", "action": "set_param", "key": key, "value": self.params[key]}
                    except (TypeError, ValueError):
                        return {"cmd": "error", "message": f"Invalid value for {key}"}
                else:
                    return {"cmd": "error", "message": f"Unknown parameter: {key}"}
            return {"cmd": "error", "message": "Missing 'key' or 'value'"}

        elif command == "apply_force":
            force_target = cmd.get("force")
            if force_target is None:
                return {"cmd": "error", "message": "Missing 'force' value"}
            try:
                force_target = float(force_target)
            except (TypeError, ValueError):
                return {"cmd": "error", "message": "Force must be a number"}
            
            pwm, speed_pct = apply_force_target(force_target)
            self.state.speed_pct = speed_pct
            
            payload = json.dumps({"servo": speed_pct, "led": self.state.led_state})
            self.mqtt_client.publish(MQTT_CONTROL_TOPIC, payload)
            
            print(f"[CMD] Apply force: {force_target}N -> {speed_pct}% speed ({pwm}us PWM)")
            return {"cmd": "ack", "action": "apply_force", "force": force_target, "speed_pct": speed_pct, "pwm_us": pwm}

        elif command == "status":
            return {
                "cmd": "status",
                "running": not self.paused,
                "damage": self.state.damage,
                "confidence": self.state.confidence,
                "led_state": self.state.led_state,
                "speed": self.state.speed_pct,
                "params": self.params,
            }

        else:
            return {"cmd": "error", "message": f"Unknown command: {command}"}

    async def broadcast_state(self):
        while self.running:
            if self.connected_unity_clients:
                msg = json.dumps(self.state.for_unity())
                await asyncio.gather(*[ws.send(msg) for ws in self.connected_unity_clients])
            await asyncio.sleep(0.1)

    async def ws_main(self):
        async with websockets.serve(self.websocket_handler, "", 8765):
            print("[WEBSOCKET] Server running on ws://:8765")
            await asyncio.Future()

    def mqtt_thread(self):
        self.mqtt_client.on_connect = self.on_mqtt_connect
        self.mqtt_client.on_message = self.on_mqtt_message
        try:
            self.mqtt_client.connect(self.mqtt_broker, self.mqtt_port, 60)
            self.mqtt_client.loop_forever()
        except Exception as e:
            print(f"[MQTT] {e}")

    async def run(self):
        print("=" * 60)
        print("  Wing Digital Twin - Orchestrator")
        print("=" * 60)

        try:
            self.matrices = load_transfer_matrices()
            self.num_gauges = self.matrices.H_inv.shape[1]
            print(f"[MATRICES] Loaded transfer matrices ({self.num_gauges} gauge channels)")
            for name, info in matrix_info(self.matrices).items():
                print(f"  {name}: {info}")
        except FileNotFoundError as e:
            print(f"[ERROR] {e}")
            print("[ERROR] Cannot start without transfer matrices in transfer_matrices/")
            return

        print(f"  MQTT:   {self.mqtt_broker}:{self.mqtt_port}")
        print(f"  Topics:  subscribe={MQTT_SENSORS_TOPIC}  publish={MQTT_CONTROL_TOPIC}")
        print(f"  Damage: SAFE<{DAMAGE_SAFE}  WARNING<{DAMAGE_WARNING}  CRITICAL>={DAMAGE_WARNING}")
        print(f"  Confidence: EMA filter, alert below 50% for 10 frames")
        print("=" * 60)

        t = threading.Thread(target=self.mqtt_thread, daemon=True)
        t.start()

        try:
            await asyncio.gather(self.ws_main(), self.broadcast_state())
        except KeyboardInterrupt:
            self.running = False
            print("\n[ORCHESTRATOR] Shutting down...")
            self.mqtt_client.disconnect()


def main():
    parser = argparse.ArgumentParser(description="Wing Digital Twin Orchestrator")
    parser.add_argument("--broker", default=MQTT_BROKER, help="MQTT broker address")
    parser.add_argument("--port", type=int, default=MQTT_PORT, help="MQTT broker port")
    args = parser.parse_args()

    orchestrator = Orchestrator(mqtt_broker=args.broker, mqtt_port=args.port)
    asyncio.run(orchestrator.run())


if __name__ == "__main__":
    main()