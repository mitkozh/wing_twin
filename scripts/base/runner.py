"""
Abstract base class for all runner scripts.
"""

from abc import ABC, abstractmethod
from typing import TypeVar, Generic
import threading
import signal
import sys

T = TypeVar("T")


class Runner(ABC, Generic[T]):
    """
    Base class for script runners.
    Provides common lifecycle management and signal handling.
    """

    def __init__(self):
        self._running = False
        self._paused = False
        self._threads: list[threading.Thread] = []
        self._setup_signal_handlers()

    def _setup_signal_handlers(self):
        """Set up signal handlers for graceful shutdown."""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        print("\n[RUNNER] Received shutdown signal")
        self.stop()

    @property
    def running(self) -> bool:
        return self._running

    @property
    def paused(self) -> bool:
        return self._paused

    @paused.setter
    def paused(self, value: bool):
        self._paused = value

    @abstractmethod
    def setup(self) -> T:
        """Initialize resources. Returns configuration/state."""
        pass

    @abstractmethod
    def run_loop(self, state: T) -> None:
        """Main execution loop."""
        pass

    @abstractmethod
    def cleanup(self, state: T) -> None:
        """Release resources."""
        pass

    def start(self) -> None:
        """Start the runner."""
        self._running = True
        print(f"[{self.__class__.__name__}] Starting...")

    def stop(self) -> None:
        """Stop the runner."""
        self._running = False
        for thread in self._threads:
            if thread.is_alive():
                thread.join(timeout=2.0)
        print(f"[{self.__class__.__name__}] Stopped")

    def pause(self) -> None:
        """Pause execution."""
        self._paused = True

    def resume(self) -> None:
        """Resume execution."""
        self._paused = False

    def add_thread(self, thread: threading.Thread) -> None:
        """Add a background thread to manage."""
        self._threads.append(thread)
        thread.daemon = True