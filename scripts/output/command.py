"""
Command handler - parses and executes commands from clients.
"""

import json
import time
from typing import Optional, Callable, Any
from ..sources.base import SensorReading
from dtwin.core.stepper_physics import compute_aero_force, force_to_steps
import numpy as np


class CommandHandler:
    """Handles commands received from WebSocket clients."""

    def __init__(self):
        self._handlers: dict[str, Callable] = {}
        self._register_default_handlers()

    def _register_default_handlers(self) -> None:
        """Register built-in command handlers."""
        self._handlers = {
            "ping": self._handle_ping,
            "play": self._handle_play,
            "pause": self._handle_pause,
            "reset": self._handle_reset,
            "set_param": self._handle_set_param,
            "set_steps": self._handle_set_steps,
            "set_flight_state": self._handle_set_flight_state,
            "status": self._handle_status,
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
        else:
            return {"cmd": "error", "message": f"Unknown command: {command}"}

    def _handle_ping(self, cmd: dict) -> dict:
        return {"cmd": "pong", "time": time.time()}

    def _handle_play(self, cmd: dict) -> dict:
        return {"cmd": "ack", "action": "play"}

    def _handle_pause(self, cmd: dict) -> dict:
        return {"cmd": "ack", "action": "pause"}

    def _handle_reset(self, cmd: dict) -> dict:
        target = cmd.get("target", "damage")
        return {"cmd": "ack", "action": "reset", "target": target}

    def _handle_set_param(self, cmd: dict) -> dict:
        key = cmd.get("key")
        value = cmd.get("value")
        if key and value is not None:
            return {"cmd": "ack", "action": "set_param", "key": key, "value": value}
        return {"cmd": "error", "message": "Missing 'key' or 'value'"}

    def _handle_set_steps(self, cmd: dict) -> dict:
        steps = cmd.get("steps")
        if steps is None:
            return {"cmd": "error", "message": "Missing 'steps'"}
        return {
            "cmd": "ack",
            "action": "set_steps",
            "steps": steps,
        }

    def _handle_set_flight_state(self, cmd: dict) -> dict:
        angle = cmd.get("angle")
        speed = cmd.get("speed")
        if angle is None and speed is None:
            return {"cmd": "error", "message": "Missing 'angle' and/or 'speed'"}
        return {
            "cmd": "ack",
            "action": "set_flight_state",
            "angle": angle,
            "speed": speed,
        }

    def _handle_status(self, cmd: dict) -> dict:
        return {"cmd": "status", "running": True}


class EngineCommandHandler(CommandHandler):
    """
    Extended command handler that can control the digital twin engine.
    """

    def __init__(self, engine: Any):
        super().__init__()
        self._engine = engine
        self._register_engine_handlers()

    def _register_engine_handlers(self) -> None:
        self._handlers.update({
            "play": self._cmd_play,
            "pause": self._cmd_pause,
            "reset": self._cmd_reset,
            "set_param": self._cmd_set_param,
            "set_steps": self._cmd_set_steps,
            "set_flight_state": self._cmd_set_flight_state,
            "status": self._cmd_status,
        })

    def _apply_stepper_state(self, steps: int, angle: float, speed: float) -> None:
        self._engine.state.stepper_position = steps
        self._engine.state.angle_of_attack = angle
        self._engine.state.airspeed = speed

    def _ref_speed(self) -> float:
        return self._engine.config.reference_speed

    def _steps_per_newton(self) -> float:
        return self._engine.config.steps_per_newton

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
        speed = cmd.get("speed", float(self._engine.state.airspeed))
        self._engine.state.stepper_position = steps
        self._engine.state.airspeed = speed
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
        current = self._engine.state
        angle = float(angle) if angle is not None else current.angle_of_attack
        speed = float(speed) if speed is not None else current.airspeed
        F = compute_aero_force(angle, speed)
        steps = force_to_steps(F, self._steps_per_newton())
        self._apply_stepper_state(steps, angle, speed)
        return {
            "cmd": "ack",
            "action": "set_flight_state",
            "angle": angle,
            "speed": speed,
            "steps": steps,
        }

    def _cmd_status(self, cmd: dict) -> dict:
        return {
            "cmd": "status",
            "running": True,
            "damage": self._engine.state.damage,
            "confidence": self._engine.state.confidence,
            "led_state": self._engine.state.led_state,
            "speed": self._engine.state.speed_pct,
        }
