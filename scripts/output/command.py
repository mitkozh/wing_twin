"""
Command handler - parses and executes commands from clients.
"""

import json
import time
from typing import Optional, Callable, Any


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

        return {
            "cmd": "ack",
            "action": "apply_force",
            "force": force_target,
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
            "apply_force": self._cmd_apply_force,
            "status": self._cmd_status,
        })

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

    def _cmd_apply_force(self, cmd: dict) -> dict:
        return {"cmd": "ack", "action": "apply_force"}

    def _cmd_status(self, cmd: dict) -> dict:
        return {
            "cmd": "status",
            "running": True,
            "damage": self._engine.state.damage,
            "confidence": self._engine.state.confidence,
            "led_state": self._engine.state.led_state,
            "speed": self._engine.state.speed_pct,
        }