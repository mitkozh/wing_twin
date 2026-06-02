"""
WebSocket broadcaster and command handler.
"""

import asyncio
import json
import time
from typing import Any, Callable, Optional, Set

import websockets
from websockets import WebSocketServerProtocol

from wing_twin.io.logger import get_logger

logger = get_logger(__name__)


class WebSocketBroadcaster:
    """WebSocket server that broadcasts engine state to Unity."""

    def __init__(self, host: str = "localhost", port: int = 8765):
        self.host = host
        self.port = port
        self._clients: Set[WebSocketServerProtocol] = set()
        self._state_provider: Optional[Callable[[], dict]] = None
        self._command_handler: Optional[Any] = None
        self._running = False

    def set_state_provider(self, provider: Callable[[], dict]) -> None:
        self._state_provider = provider

    def set_command_handler(self, handler: Any) -> None:
        self._command_handler = handler

    @property
    def connected_clients(self) -> int:
        return len(self._clients)

    async def start(self) -> None:
        self._running = True

        async def handler(ws: WebSocketServerProtocol) -> None:
            self._clients.add(ws)
            logger.info("Client connected (%d total)", len(self._clients))
            try:
                if self._state_provider:
                    await ws.send(json.dumps(self._state_provider()))
                async for message in ws:
                    if self._command_handler:
                        response = self._command_handler.handle(message)
                        if response:
                            await ws.send(json.dumps(response))
            except Exception as e:
                logger.error("Client error: %s", e)
            finally:
                self._clients.discard(ws)
                logger.info("Client disconnected (%d total)", len(self._clients))

        async with websockets.serve(handler, self.host, self.port):
            logger.info("WebSocket server running on ws://%s:%d", self.host, self.port)
            await asyncio.Future()

    async def stop(self) -> None:
        self._running = False
        for client in list(self._clients):
            await client.close()

    async def broadcast(self) -> None:
        if not self._clients or not self._state_provider:
            return
        try:
            state = self._state_provider()
            msg = json.dumps(state)
        except Exception as e:
            logger.error("State provider error: %s", e)
            return

        disconnected = []
        for client in list(self._clients):
            try:
                await client.send(msg)
            except Exception as e:
                logger.error("Broadcast error: %s", e)
                disconnected.append(client)

        for client in disconnected:
            self._clients.discard(client)


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
            "set_maintenance_assist": self._cmd_set_maintenance_assist,
            "status": self._cmd_status,
            "dismiss_notification": self._cmd_dismiss_notification,
            "plan_flight": self._cmd_plan_flight,
            "takeoff": self._cmd_takeoff,
            "land": self._cmd_land,
        }

    def register_handler(self, command: str, handler: Callable) -> None:
        self._handlers[command] = handler

    def handle(self, message: str) -> Optional[dict]:
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
        # Only allow setting flight state during active flight
        if self._engine.flight_phase.value != "in_flight":
            return {"cmd": "ack", "action": "set_flight_state", "ignored": "not in flight"}

        angle = cmd.get("angle")
        speed = cmd.get("speed")

        if angle is None and speed is None:
            return {"cmd": "error", "message": "Missing 'angle' and/or 'speed'"}

        state = self._engine.state

        if angle is not None:
            state.desired_angle_of_attack = float(angle)

        if speed is not None:
            state.desired_airspeed = float(speed)

        return {
            "cmd": "ack",
            "action": "set_flight_state",
            "desired_angle": state.desired_angle_of_attack,
            "desired_speed": state.desired_airspeed,
        }

    def _cmd_plan_flight(self, cmd: dict) -> dict:
        planned_km = cmd.get("planned_km")
        if planned_km is None:
            return {"cmd": "error", "message": "Missing 'planned_km'"}
        planned_km = float(planned_km)
        result = self._engine.life_prediction_state.pre_flight_check(planned_km)
        self._engine.state.planned_km = planned_km
        self._engine.state.pre_flight_safe = result["safe"]
        self._engine.state.pre_flight_warning = result["warning"]
        return {
            "cmd": "plan_flight_result",
            "safe": result["safe"],
            "remaining_km": result["remaining_km"],
            "planned_km": result["planned_km"],
            "warning": result["warning"],
        }

    def _cmd_takeoff(self, cmd: dict) -> dict:
        phase = self._engine.flight_phase.value
        if phase != "on_ground":
            return {"cmd": "error", "message": f"Cannot take off during '{phase}'"}
        if not self._engine.state.flight_allowed:
            return {"cmd": "error", "message": "Flight not allowed - fatigue life too low"}
        ok = self._engine.request_takeoff()
        if not ok:
            return {"cmd": "error", "message": "Takeoff rejected"}
        return {"cmd": "ack", "action": "takeoff", "phase": "taking_off"}

    def _cmd_land(self, cmd: dict) -> dict:
        phase = self._engine.flight_phase.value
        if phase != "in_flight":
            return {"cmd": "error", "message": f"Cannot land during '{phase}'"}
        ok = self._engine.request_landing()
        if not ok:
            return {"cmd": "error", "message": "Landing rejected"}
        return {"cmd": "ack", "action": "land", "phase": "landing"}

    def _cmd_set_heatmap_mode(self, cmd: dict) -> dict:
        mode = cmd.get("mode", "damage")
        if mode not in ("stress", "damage"):
            return {"cmd": "error", "message": f"Invalid mode: {mode}. Use 'stress' or 'damage'"}
        self._engine.state.heatmap_mode = mode
        return {"cmd": "ack", "action": "set_heatmap_mode", "mode": mode}

    def _cmd_set_maintenance_assist(self, cmd: dict) -> dict:
        enabled = cmd.get("enabled", True)
        self._engine.state.maintenance_assist = bool(enabled)
        return {"cmd": "ack", "action": "set_maintenance_assist", "enabled": bool(enabled)}

    def _cmd_dismiss_notification(self, cmd: dict) -> dict:
        nid = cmd.get("notification_id")
        if not nid:
            return {"cmd": "error", "message": "Missing 'notification_id'"}
        self._engine.state.dismiss_notification(nid)
        return {"cmd": "ack", "action": "dismiss_notification", "notification_id": nid}

    def _cmd_status(self, cmd: dict) -> dict:
        return {
            "cmd": "status",
            "running": True,
            "damage": self._engine.state.damage,
            "confidence": self._engine.state.confidence,
            "led_state": self._engine.state.led_state,
        }
