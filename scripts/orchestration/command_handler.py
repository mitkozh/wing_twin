"""
Command handler - parses and executes commands from WebSocket clients.
"""

import json
import time
from typing import Optional, Callable, Any

from dtwin.core.actuator import apply_force_target


class CommandHandler:
    """
    Handles commands received from WebSocket clients.
    """

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
            "apply_force": self._handle_apply_force,
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

    def _handle_apply_force(self, cmd: dict) -> dict:
        force_target = cmd.get("force")
        if force_target is None:
            return {"cmd": "error", "message": "Missing 'force' value"}

        try:
            force_target = float(force_target)
        except (TypeError, ValueError):
            return {"cmd": "error", "message": "Force must be a number"}

        pwm, speed_pct = apply_force_target(force_target)
        return {
            "cmd": "ack",
            "action": "apply_force",
            "force": force_target,
            "speed_pct": speed_pct,
            "pwm_us": pwm
        }

    def _handle_status(self, cmd: dict) -> dict:
        return {"cmd": "status", "running": True}


class OrchestratorCommandHandler(CommandHandler):
    """
    Extended command handler for orchestrator-specific commands.
    """

    def __init__(self, orchestrator: Any):
        super().__init__()
        self._orchestrator = orchestrator
        self._register_orchestrator_handlers()

    def _register_orchestrator_handlers(self) -> None:
        self._handlers.update({
            "play": self._cmd_play,
            "pause": self._cmd_pause,
            "reset": self._cmd_reset,
            "set_param": self._cmd_set_param,
            "apply_force": self._cmd_apply_force,
            "status": self._cmd_status,
        })

    def _cmd_play(self, cmd: dict) -> dict:
        self._orchestrator.paused = False
        print("[CMD] Simulation resumed")
        return {"cmd": "ack", "action": "play"}

    def _cmd_pause(self, cmd: dict) -> dict:
        self._orchestrator.paused = True
        print("[CMD] Simulation paused")
        return {"cmd": "ack", "action": "pause"}

    def _cmd_reset(self, cmd: dict) -> dict:
        target = cmd.get("target", "damage")
        if target == "damage":
            self._orchestrator.fatigue_state.damage = 0.0
            self._orchestrator.state.damage = 0.0
        elif target == "strain":
            self._orchestrator._mqtt.strain_buffers.clear()
        elif target == "all":
            self._orchestrator.fatigue_state.damage = 0.0
            self._orchestrator.state.damage = 0.0
            self._orchestrator._mqtt.strain_buffers.clear()
        print(f"[CMD] Reset {target}")
        return {"cmd": "ack", "action": "reset", "target": target}

    def _cmd_set_param(self, cmd: dict) -> dict:
        key = cmd.get("key")
        value = cmd.get("value")
        if key and value is not None:
            if key in self._orchestrator.params:
                try:
                    self._orchestrator.params[key] = float(value)
                    print(f"[CMD] Set {key} = {self._orchestrator.params[key]}")
                    return {"cmd": "ack", "action": "set_param", "key": key, "value": self._orchestrator.params[key]}
                except (TypeError, ValueError):
                    return {"cmd": "error", "message": f"Invalid value for {key}"}
            else:
                return {"cmd": "error", "message": f"Unknown parameter: {key}"}
        return {"cmd": "error", "message": "Missing 'key' or 'value'"}

    def _cmd_status(self, cmd: dict) -> dict:
        return {
            "cmd": "status",
            "running": not self._orchestrator.paused,
            "damage": self._orchestrator.state.damage,
            "confidence": self._orchestrator.state.confidence,
            "led_state": self._orchestrator.state.led_state,
            "speed": self._orchestrator.state.speed_pct,
            "params": self._orchestrator.params,
        }

    def _cmd_apply_force(self, cmd: dict) -> dict:
        force_target = cmd.get("force")
        if force_target is None:
            return {"cmd": "error", "message": "Missing 'force' value"}

        try:
            force_target = float(force_target)
        except (TypeError, ValueError):
            return {"cmd": "error", "message": "Force must be a number"}

        pwm, speed_pct = apply_force_target(force_target)
        self._orchestrator.state.speed_pct = speed_pct

        self._orchestrator.publish_control()

        return {
            "cmd": "ack",
            "action": "apply_force",
            "force": force_target,
            "speed_pct": speed_pct,
            "pwm_us": pwm
        }