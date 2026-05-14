"""
WebSocket server - broadcasts state to Unity clients.
"""

import asyncio
import json
from typing import Optional, Set, Callable
import websockets
from websockets.server import WebSocketServerProtocol

from ..config import WebSocketConfig


class WebSocketServer:
    """
    Manages WebSocket connections and broadcasts state to Unity.
    """

    def __init__(self, config: Optional[WebSocketConfig] = None):
        self.config = config or WebSocketConfig()
        self._clients: Set[WebSocketServerProtocol] = set()
        self._state_provider: Optional[Callable] = None
        self._command_handler: Optional[Callable[[str], Optional[dict]]] = None
        self._running = False

    def set_state_provider(self, provider: Callable) -> None:
        """Set callback that returns current state dict."""
        self._state_provider = provider

    def set_command_handler(self, handler: Callable[[str], Optional[dict]]) -> None:
        """Set callback to handle commands from clients."""
        self._command_handler = handler

    @property
    def connected_clients(self) -> Set[WebSocketServerProtocol]:
        """Return set of connected clients."""
        return self._clients

    async def start(self) -> None:
        """Start the WebSocket server."""
        self._running = True
        async with websockets.serve(self._handler, self.config.host, self.config.port):
            print(f"[WEBSOCKET] Server running on ws://:{self.config.port}")
            await asyncio.Future()

    async def stop(self) -> None:
        """Stop the server."""
        self._running = False
        for client in list(self._clients):
            await client.close()

    async def broadcast_loop(self) -> None:
        """Periodically broadcast state to all connected clients."""
        while self._running:
            if self._clients and self._state_provider:
                state = self._state_provider()
                msg = json.dumps(state)
                await asyncio.gather(
                    *[client.send(msg) for client in self._clients],
                    return_exceptions=True
                )
            await asyncio.sleep(0.1)

    async def _handler(self, ws: WebSocketServerProtocol, path: str) -> None:
        """Handle a single WebSocket client connection."""
        self._clients.add(ws)
        print(f"[WEBSOCKET] Client connected ({len(self._clients)} total)")

        try:
            if self._state_provider:
                await ws.send(json.dumps(self._state_provider()))

            async for msg in ws:
                if self._command_handler:
                    response = self._command_handler(msg)
                    if response:
                        await ws.send(json.dumps(response))
        except websockets.ConnectionClosed:
            pass
        finally:
            self._clients.discard(ws)
            print(f"[WEBSOCKET] Client disconnected")

    @property
    def client_count(self) -> int:
        return len(self._clients)