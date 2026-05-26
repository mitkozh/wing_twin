"""
Shared asyncio lifecycle utilities for CLI runners.
"""

import asyncio
import signal
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..settings import PROJECT_ROOT
from ..analysis import DataRecorder, save_fatigue_state
from ..logger import get_logger

logger = get_logger(__name__)


def setup_signal_handler(loop: asyncio.AbstractEventLoop, stop_event: asyncio.Event) -> None:
    """Register SIGINT/SIGTERM (Unix) or SIGINT/SIGBREAK (Windows)."""
    def _on_signal():
        logger.info("Shutdown requested...")
        stop_event.set()

    try:
        loop.add_signal_handler(signal.SIGINT, _on_signal)
        loop.add_signal_handler(signal.SIGTERM, _on_signal)
    except NotImplementedError:
        _setup_win32_fallback(loop, _on_signal)


def _setup_win32_fallback(loop, on_signal):
    """Windows: register signals via signal.signal, deliver to the event loop."""
    for sig in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGBREAK", None)):
        if sig is None:
            continue
        try:
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(on_signal))
        except (ValueError, OSError):
            pass


async def cancel_task(task: Optional[asyncio.Task]) -> None:
    """Cancel an asyncio task and wait for cancellation to complete."""
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def setup_recorder(
    record: bool,
    record_figures: bool,
) -> tuple[Optional[DataRecorder], Optional[Path]]:
    """Create a DataRecorder if recording is requested.

    Returns (recorder, recording_dir) on success, or (None, None) if recording
    was not requested or if setup failed.
    """
    if not record and not record_figures:
        return None, None

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    rec_dir = PROJECT_ROOT / "recordings" / f"run_{stamp}"

    try:
        rec_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error("Cannot create recording directory %s: %s", rec_dir, exc)
        return None, None

    scalar_int = 1 if record else 10
    try:
        recorder = DataRecorder(rec_dir, scalar_interval=scalar_int, field_interval=50)
    except Exception as exc:
        logger.error("Failed to initialise recorder at %s: %s", rec_dir, exc)
        return None, None

    return recorder, rec_dir


def finalize_recorder(recorder: Optional[DataRecorder], engine, rec_dir: Optional[Path]) -> None:
    """Flush recordings and persist fatigue state.

    This is safe to call even if the recorder is None or if finalization
    encounters an error — failures are logged but never propagated.
    """
    if recorder is None:
        return

    try:
        recorder.finalize()
    except Exception as exc:
        logger.error("Recorder finalization failed: %s", exc)

    try:
        save_fatigue_state(engine.fatigue_state, rec_dir)
    except Exception as exc:
        logger.error("Failed to save fatigue state: %s", exc)
