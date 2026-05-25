"""
Command handler - parses and executes commands from WebSocket clients.
"""

import json
import time
from typing import Optional, Callable, Any


class EngineCommandHandler:
    """Parses JSON commands from Unity and acts on the digital twin engine."""

    def __init__(self, engine: Any):
        self._engine = engine
        self._handlers: dict[str, Callable] = {
            "ping": self._cmd_ping,
            "play": self._cmd_play,
            "pause": self._cmd_pause,
            "reset": self._cmd_reset,
            "set_param": self._cmd_set_param,
            "set_steps": self._cmd_set_steps,
            "set_flight_state": self._cmd_set_flight_state,
            "set_heatmap_mode": self._cmd_set_heatmap_mode,
            "status": self._cmd_status,
        }

    def register_handler(self, command: str, handler: Callable) -> None:
        """Register a custom command handler."""
        self._handlers[command] = handler

    def handle(self, message: str) -> Optional[dict]:
        """Parse and execute a command. Returns response dict."""
        try:
            cmd = json.loads(message)
        except json.JSONDecodeError:
            return {"cmd": "error", "message": "Invalid JSON"}

        command = cmd.get("cmd")
        if command is None:
            return {"cmd": "error", "message": "Missing 'cmd' field"}

        handler = self._handlers.get(command)
        if handler:
            return handler(cmd)
        return {"cmd": "error", "message": f"Unknown command: {command}"}

    def _cmd_ping(self, cmd: dict) -> dict:
        return {"cmd": "pong", "time": time.time()}

    def _cmd_play(self, cmd: dict) -> dict:
        return {"cmd": "ack", "action": "play"}

    def _cmd_pause(self, cmd: dict) -> dict:
        return {"cmd": "ack", "action": "pause"}

    def _cmd_reset(self, cmd: dict) -> dict:
        target = cmd.get("target", "damage")
        self._engine.reset(target)
        return {"cmd": "ack", "action": "reset", "target": target}

    def _cmd_set_param(self, cmd: dict) -> dict:
        return {"cmd": "ack", "action": "set_param"}

    def _cmd_set_steps(self, cmd: dict) -> dict:
        steps = cmd.get("steps")
        if steps is None:
            return {"cmd": "error", "message": "Missing 'steps'"}
        steps = int(steps)
        speed = cmd.get("speed", float(self._engine.state.target_airspeed))
        self._engine.state.stepper_position = steps
        self._engine.state.target_airspeed = speed
        return {
            "cmd": "ack",
            "action": "set_steps",
            "steps": steps,
            "speed": speed,
        }

    def _cmd_set_flight_state(self, cmd: dict) -> dict:
        angle = cmd.get("angle")
        speed = cmd.get("speed")
        if angle is None and speed is None:
            return {"cmd": "error", "message": "Missing 'angle' and/or 'speed'"}
        state = self._engine.state
        if angle is not None:
            state.target_angle_of_attack = float(angle)
        if speed is not None:
            state.target_airspeed = float(speed)
        return {
            "cmd": "ack",
            "action": "set_flight_state",
            "target_angle": state.target_angle_of_attack,
            "target_speed": state.target_airspeed,
        }

    def _cmd_set_heatmap_mode(self, cmd: dict) -> dict:
        mode = cmd.get("mode", "damage")
        if mode not in ("stress", "damage"):
            return {"cmd": "error", "message": f"Invalid mode: {mode}. Use 'stress' or 'damage'"}
        self._engine.state.heatmap_mode = mode
        return {"cmd": "ack", "action": "set_heatmap_mode", "mode": mode}

    def _cmd_status(self, cmd: dict) -> dict:
        return {
            "cmd": "status",
            "running": True,
            "damage": self._engine.state.damage,
            "confidence": self._engine.state.confidence,
            "led_state": self._engine.state.led_state,
            "speed": self._engine.state.speed_pct,
        }
