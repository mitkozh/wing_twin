"""
Wing Digital Twin Demo CLI Entry Point.
"""

import argparse
import asyncio
import threading
from typing import Optional

from pathlib import Path

from wing_twin.config import FatigueConfig

from ._lifecycle import cancel_task, finalize_recorder, setup_recorder, setup_signal_handler

from wing_twin.config import PROJECT_ROOT, SimulationConfig
from wing_twin.recorder.recorder import load_engine_snapshot
from wing_twin.viz.generator import generate_figures_from_recording
from wing_twin.engine.engine import DigitalTwinEngine
from wing_twin.config import EngineConfig
from wing_twin.engine.state import EngineSnapshot
from wing_twin.io.simulator import SimulatorSource
from wing_twin.io.websocket import WebSocketBroadcaster, EngineCommandHandler
from wing_twin.io.logger import get_logger

logger = get_logger(__name__)


async def run_demo_async(
    duration_s: int,
    seed: Optional[int] = None,
    record: bool = False,
    record_figures: bool = False,
    auto_takeoff: bool = False,
    resume_snapshot: Optional[EngineSnapshot] = None,
) -> tuple[DigitalTwinEngine, Optional[Path]]:
    config = EngineConfig(seed=seed)
    engine = DigitalTwinEngine(
        config,
        engine_snapshot=resume_snapshot,
    )

    logger.info("Loading transfer matrices...")
    try:
        engine.load_matrices()
        logger.info("Loaded successfully (%d gauge channels)", engine.num_gauges)
    except FileNotFoundError as e:
        logger.error("%s", e)
        logger.error("Cannot start without transfer matrices")
        raise

    sim_config = SimulationConfig()
    simulator = SimulatorSource(sim_config)
    simulator.set_matrices(engine.matrices)
    engine.data_source = simulator

    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    setup_signal_handler(loop, stop_event)

    recorder, rec_dir = setup_recorder(record, record_figures)

    broadcaster = WebSocketBroadcaster()
    command_handler = EngineCommandHandler(engine)

    def state_provider():
        return engine.state.for_unity()

    broadcaster.set_state_provider(state_provider)
    broadcaster.set_command_handler(command_handler)

    async def process_loop():
        takeoff_done = False
        while not stop_event.is_set():
            if auto_takeoff and not takeoff_done and engine.flight_phase.value == "on_ground":
                engine.request_takeoff()
                takeoff_done = True
                logger.info("Auto-takeoff initiated")

            if auto_takeoff and engine.flight_phase.value == "landing" and duration_s <= 0:
                if engine.state.altitude < 0.5:
                    stop_event.set()
                    break

            try:
                stepped = engine.step()
            except Exception as e:
                logger.error("Engine step failed: %s", e)
                stepped = False

            if stepped and recorder is not None:
                try:
                    recorder.record_frame(engine)
                except Exception as e:
                    logger.error("Recording failed: %s", e)

            if broadcaster._clients:
                await broadcaster.broadcast()

            await asyncio.sleep(1.0 / sim_config.sample_rate)

    process_task = asyncio.create_task(process_loop())

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
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down...")
    finally:
        stop_event.set()
        await cancel_task(process_task)
        await cancel_task(broadcaster_task)
        await asyncio.sleep(0.1)

        finalize_recorder(recorder, engine, rec_dir)
        if recorder is not None:
            logger.info("Recording finalized")

    return engine, rec_dir


def _display_thread(engine, stop_event):
    logger.info("\n" + "=" * 60)
    logger.info("  Wing Digital Twin Live Dashboard")
    logger.info("=" * 60)
    tick = 0
    while not stop_event.is_set():
        tick += 1
        bar_len = 30
        filled = int(engine.state.damage * bar_len)
        bar = "#" * filled + "-" * (bar_len - filled)
        phase = engine.state.flight_phase.upper()
        alt = engine.state.altitude
        km = engine.state.km_this_flight
        logger.info("[%4ds] |%s| %5.1f%%  [%s]  alt=%.1fm  km=%.3f",
                    tick, bar, engine.state.damage*100,
                    phase, alt, km)
        import time
        time.sleep(1)


def _resolve_data_dir(hint: Optional[str] = None) -> Optional[Path]:
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
    parser.add_argument("--auto-takeoff", action="store_true", help="Automatically take off on start (for testing)")
    parser.add_argument("--figures", nargs="?", const=True, default=False, help="Generate PNG figures (optional: output directory)")
    parser.add_argument("--figures-only", nargs="?", const=True, default=False, help="Regenerate figures from saved data (optional: data directory)")
    parser.add_argument("--record", action="store_true", help="Record data to HDF5 during run")
    parser.add_argument("--resume", type=str, default=None, help="Resume from prior run directory")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducible results")
    args = parser.parse_args()

    if args.run:
        args.duration = 0

    if args.seed is not None:
        logger.info("Random seed set to %d", args.seed)

    output_dir = Path(args.figures) if isinstance(args.figures, str) else PROJECT_ROOT / "figures"
    output_dir.mkdir(exist_ok=True)

    if args.figures_only:
        data_dir = _resolve_data_dir(args.figures_only if isinstance(args.figures_only, str) else None)
        if data_dir:
            generate_figures_from_recording(data_dir, output_dir)
        else:
            logger.warning("No saved data found")
        return

    resume_snapshot = None
    if args.resume:
        resume_snapshot = load_engine_snapshot(Path(args.resume))

    logger.info("=" * 60)
    logger.info("  Wing Digital Twin Demo")
    logger.info("=" * 60)
    fatigue_config = FatigueConfig()
    logger.info("  Sample rate:  %d Hz", SimulationConfig().sample_rate)
    logger.info("  Thresholds:   SAFE<%s  WARN<%s  CRIT>=%s", fatigue_config.damage_warning, fatigue_config.damage_critical, fatigue_config.damage_critical)
    if args.auto_takeoff:
        logger.info("  Auto-takeoff: enabled (simulates complete flight cycle)")
    if args.record:
        logger.info("  Recording: enabled -> recordings/")
    if args.figures:
        logger.info("  Figures:  enabled on exit")
    if resume_snapshot is not None:
        dmg = (resume_snapshot.fatigue or {}).get("damage", 0.0)
        n_cyc = len((resume_snapshot.fatigue or {}).get("cycles", []))
        n_flt = (resume_snapshot.life or {}).get("total_flights", 0)
        total_km = (resume_snapshot.life or {}).get("total_km_flown", 0.0)
        logger.info("  Resuming from prior run (D=%.4f, %d cycles, %d flights, %.1f km)", dmg, n_cyc, n_flt, total_km)
        km_resume = (resume_snapshot.flight or {}).get("km_this_flight", 0.0)
        if km_resume > 0:
            logger.info("  Aborted flight recovered (%.3f km)", km_resume)
    logger.info("=" * 60)

    engine, rec_dir = asyncio.run(
        run_demo_async(
            args.duration, args.seed,
            record=args.record,
            record_figures=bool(args.figures),
            auto_takeoff=args.auto_takeoff,
            resume_snapshot=resume_snapshot,
        )
    )

    if args.figures and rec_dir is not None:
        generate_figures_from_recording(rec_dir, output_dir)


if __name__ == "__main__":
    main()
