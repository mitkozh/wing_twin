"""
Wing Digital Twin Demo CLI Entry Point.
"""

import argparse
import asyncio
import signal
import threading
import time
from typing import Optional

from dtwin.core.fatigue import FatigueConfig, FatigueState

from pathlib import Path

from ..settings import PROJECT_ROOT, SimulationConfig
from ..analysis import (
    DataRecorder,
    save_fatigue_state,
    load_fatigue_state,
)
from ..viz import generate_figures_from_recording
from ..engine import DigitalTwinEngine, EngineConfig
from ..sources import SimulatorSource
from ..output import WebSocketBroadcaster, EngineCommandHandler
from ..logger import get_logger

logger = get_logger(__name__)


async def run_demo_async(
    duration_s: int,
    seed: Optional[int] = None,
    record: bool = False,
    record_figures: bool = False,
    headless: bool = False,
    resume_state: Optional[FatigueState] = None,
) -> tuple[DigitalTwinEngine, Optional[Path]]:
    """Run demo with optional WebSocket broadcasting.

    Returns:
        Tuple of (engine, recording_dir_or_None)
    """
    config = EngineConfig(seed=seed)
    engine = DigitalTwinEngine(config, initial_fatigue_state=resume_state)

    logger.info("Loading transfer matrices...")
    engine.load_matrices()
    logger.info("Loaded successfully (%d gauge channels)", engine.num_gauges)

    sim_config = SimulationConfig()
    simulator = SimulatorSource(sim_config)
    simulator.set_matrices(engine.matrices)
    engine.data_source = simulator

    stop_event = asyncio.Event()

    def _signal_handler():
        logger.info("Shutdown requested...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    recorder = None
    rec_dir = None

    if not headless:
        broadcaster = WebSocketBroadcaster()
        command_handler = EngineCommandHandler(engine)

        def state_provider():
            return engine.state.for_unity()

        broadcaster.set_state_provider(state_provider)
        broadcaster.set_command_handler(command_handler)

    if record or record_figures:
        from datetime import datetime
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        rec_dir = PROJECT_ROOT / "recordings" / f"run_{stamp}"
        scalar_int = 1 if record else 10
        recorder = DataRecorder(rec_dir, scalar_interval=scalar_int, field_interval=50)

    async def process_loop():
        while not stop_event.is_set():
            if engine.step():
                if recorder is not None:
                    recorder.record_frame(engine)

            if not headless and broadcaster is not None and broadcaster._clients:
                await broadcaster.broadcast()

            await asyncio.sleep(1.0 / sim_config.sample_rate)

    process_task = asyncio.create_task(process_loop())

    if not headless:
        broadcaster_task = asyncio.create_task(broadcaster.start())
        display_thread = threading.Thread(target=_display_thread, args=(engine, stop_event), daemon=True)
        display_thread.start()

    try:
        if duration_s > 0:
            await asyncio.wait_for(stop_event.wait(), timeout=duration_s)
        else:
            await stop_event.wait()
    except asyncio.TimeoutError:
        pass

    stop_event.set()

    process_task.cancel()
    try:
        await process_task
    except asyncio.CancelledError:
        pass

    if not headless:
        broadcaster_task.cancel()
        try:
            await broadcaster_task
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0.1)

    if recorder is not None:
        recorder.finalize()
        save_fatigue_state(engine.fatigue_state, rec_dir)

    return engine, rec_dir


def _display_thread(engine, stop_event):
    """Thread that displays live dashboard."""
    logger.info("\n" + "=" * 60)
    logger.info("  Wing Digital Twin Live Dashboard")
    logger.info("=" * 60)
    tick = 0
    while not stop_event.is_set():
        tick += 1
        bar_len = 30
        filled = int(engine.state.damage * bar_len)
        bar = "#" * filled + "-" * (bar_len - filled)
        state_sym = {"green": "GREEN", "yellow": "YELLOW", "red": "RED"}.get(engine.state.led_state, "UNKNOWN")
        logger.info("[%4ds] |%s| %5.1f%%  %7s  Vmax=%3d%%", tick, bar, engine.state.damage*100, state_sym, engine.state.speed_pct)
        time.sleep(1)


def _resolve_data_dir(hint: Optional[str] = None) -> Optional[Path]:
    """Resolve data directory for figures-only mode."""
    if hint:
        return Path(hint)
    rec_dir = PROJECT_ROOT / "recordings"
    if rec_dir.exists():
        dirs = sorted(rec_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        if dirs:
            return dirs[0]
    return None


def main():
    parser = argparse.ArgumentParser(description="Wing Digital Twin Demo")
    parser.add_argument("--duration", type=int, default=30, help="Simulation duration in seconds (use 0 for infinite)")
    parser.add_argument("--run", action="store_true", help="Run indefinitely until Ctrl+C")
    parser.add_argument("--headless", action="store_true", help="Run without WebSocket or dashboard")
    parser.add_argument("--figures", action="store_true", help="Generate PNG figures after simulation")
    parser.add_argument("--figures-only", action="store_true", help="Regenerate figures from saved data")
    parser.add_argument("--record", action="store_true", help="Record data to HDF5 during run")
    parser.add_argument("--resume", type=str, default=None, help="Resume from prior run directory (loads fatigue_state.json)")
    parser.add_argument("--data-dir", type=str, default=None, help="Data directory for --figures-only (default: most recent recording)")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory for figures (default: figures/)")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducible results")
    args = parser.parse_args()

    if args.run:
        args.duration = 0

    if args.seed is not None:
        logger.info("Random seed set to %d", args.seed)

    output_dir = Path(args.output_dir) if args.output_dir else PROJECT_ROOT / "figures"
    output_dir.mkdir(exist_ok=True)

    if getattr(args, 'figures_only', False):
        data_dir = _resolve_data_dir(args.data_dir)
        if data_dir:
            generate_figures_from_recording(data_dir, output_dir)
        else:
            logger.warning("No saved data found")
        return

    resume_state = None
    if args.resume:
        resume_state = load_fatigue_state(Path(args.resume))

    mode = "Headless" if args.headless else "Full Stack"
    logger.info("=" * 60)
    logger.info("  Wing Digital Twin Demo (%s)", mode)
    logger.info("=" * 60)
    fatigue_config = FatigueConfig()
    logger.info("  Sample rate:  %d Hz", SimulationConfig().sample_rate)
    logger.info("  Thresholds:   SAFE<%s  WARN<%s  CRIT>=%s", fatigue_config.damage_warning, fatigue_config.damage_critical, fatigue_config.damage_critical)
    if args.record:
        logger.info("  Recording: enabled -> recordings/")
    if args.figures:
        logger.info("  Figures:  enabled on exit")
    if resume_state is not None:
        logger.info("  Resuming from prior run (D=%.4f, %d cycles)", resume_state.damage, len(resume_state.cycles or []))
    logger.info("=" * 60)

    engine, rec_dir = asyncio.run(
        run_demo_async(
            args.duration, args.seed,
            record=args.record,
            record_figures=args.figures,
            headless=args.headless,
            resume_state=resume_state,
        )
    )

    if args.figures and rec_dir is not None:
        generate_figures_from_recording(rec_dir, output_dir)


if __name__ == "__main__":
    main()
