"""
WebSocket broadcaster - sends state to Unity clients.
"""

import asyncio
import json
from typing import Callable, Optional, Set

import websockets
from websockets import WebSocketServerProtocol


class WebSocketBroadcaster:
    """WebSocket server that broadcasts engine state to Unity."""

    def __init__(self, host: str = "localhost", port: int = 8765):
        self.host = host
        self.port = port
        self._clients: Set[WebSocketServerProtocol] = set()
        self._state_provider: Optional[Callable[[], dict]] = None
        self._running = False

    def set_state_provider(self, provider: Callable[[], dict]) -> None:
        """Set callback that returns current state dict."""
        self._state_provider = provider

    @property
    def connected_clients(self) -> int:
        return len(self._clients)

    async def start(self) -> None:
        """Start the WebSocket server."""
        self._running = True

        async def handler(ws: WebSocketServerProtocol) -> None:
            """Handle WebSocket client connection (websockets 16+ API)."""
            self._clients.add(ws)
            print(f"[WS] Client connected ({len(self._clients)} total)")

            try:
                if self._state_provider:
                    await ws.send(json.dumps(self._state_provider()))

                async for _ in ws:
                    pass
            except Exception as e:
                print(f"[WS] Client error: {e}")
            finally:
                self._clients.discard(ws)
                print(f"[WS] Client disconnected ({len(self._clients)} total)")

        async with websockets.serve(handler, self.host, self.port):
            print(f"[WS] WebSocket server running on ws://{self.host}:{self.port}")
            await asyncio.Future()

    async def stop(self) -> None:
        """Stop the server."""
        self._running = False
        for client in list(self._clients):
            await client.close()

    async def broadcast(self) -> None:
        """Broadcast current state to all connected clients."""
        if not self._clients or not self._state_provider:
            return

        state = self._state_provider()
        msg = json.dumps(state)

        await asyncio.gather(
            *[client.send(msg) for client in self._clients],
            return_exceptions=True
        )