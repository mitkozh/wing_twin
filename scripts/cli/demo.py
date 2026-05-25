"""
Wing Digital Twin Demo CLI Entry Point.
"""

import argparse
import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from dtwin.core.fatigue import FatigueConfig

from pathlib import Path

from ..settings import PROJECT_ROOT, SimulationConfig
from ..analysis import DataExporter, DataLoader
from ..viz import VisualizationGenerator
from ..engine import DigitalTwinEngine, EngineConfig
from ..sources import SimulatorSource
from ..output import WebSocketBroadcaster, EngineCommandHandler
from ..logger import get_logger

logger = get_logger(__name__)


@dataclass
class HistoryState:
    """Tracks history for visualization and export."""
    strain_history: list = field(default_factory=list)
    force_history: list = field(default_factory=list)
    stress_field_history: list = field(default_factory=list)
    deformation_field_history: list = field(default_factory=list)
    damage_history: list = field(default_factory=list)
    times_history: list = field(default_factory=list)
    cycle_history: list = field(default_factory=list)


async def run_demo_async(
    duration_s: int,
    seed: Optional[int] = None,
    record: bool = True,
    record_figures: bool = False,
    headless: bool = False,
) -> tuple[DigitalTwinEngine, HistoryState]:
    """Run demo with optional WebSocket broadcasting."""
    config = EngineConfig(seed=seed)
    engine = DigitalTwinEngine(config)

    logger.info("Loading transfer matrices...")
    engine.load_matrices()
    logger.info("Loaded successfully (%d gauge channels)", engine.num_gauges)

    sim_config = SimulationConfig()
    simulator = SimulatorSource(sim_config)
    simulator.set_matrices(engine.matrices)
    engine.data_source = simulator

    history = HistoryState()
    running = [True]
    start_time = time.time()

    if not headless:
        broadcaster = WebSocketBroadcaster()
        command_handler = EngineCommandHandler(engine)

        def state_provider():
            return engine.state.for_unity()

        broadcaster.set_state_provider(state_provider)
        broadcaster.set_command_handler(command_handler)

        display_task = asyncio.create_task(broadcaster.start())
    else:
        broadcaster = None

    async def process_loop():
        record_interval = 10
        frame_count = 0
        while running[0]:
            if engine.step():
                frame_count += 1
                if record and frame_count % record_interval == 0:
                    history.strain_history.append(
                        engine.state.strain_vector[0] if engine.state.strain_vector else 0.0
                    )
                    history.damage_history.append(engine.state.damage)
                    history.times_history.append(time.time() - start_time)
                    history.cycle_history.extend(engine.cycles)
                    if record_figures:
                        history.force_history.append(list(engine.state.forces))
                        history.stress_field_history.append(list(engine.state.stress_field))
                        history.deformation_field_history.append(list(engine.state.deformation_field))
                    engine.clear_cycles()

            if not headless and broadcaster is not None and broadcaster._clients:
                await broadcaster.broadcast()

            await asyncio.sleep(1.0 / sim_config.sample_rate)

    process_task = asyncio.create_task(process_loop())

    if not headless:
        display_thread = threading.Thread(target=_display_thread, args=(engine, running), daemon=True)
        display_thread.start()

    if duration_s > 0:
        try:
            await asyncio.sleep(duration_s)
        except KeyboardInterrupt:
            pass
    else:
        try:
            while running[0]:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass

    running[0] = False
    await asyncio.sleep(0.5)

    if duration_s > 0:
        logger.info("Recorded %d samples over %ds", len(history.strain_history), duration_s)

    return engine, history


def _display_thread(engine, running_ref):
    """Thread that displays live dashboard."""
    logger.info("\n" + "=" * 60)
    logger.info("  Wing Digital Twin Live Dashboard")
    logger.info("=" * 60)
    tick = 0
    while running_ref[0]:
        tick += 1
        bar_len = 30
        filled = int(engine.state.damage * bar_len)
        bar = "#" * filled + "-" * (bar_len - filled)
        state_sym = {"green": "GREEN", "yellow": "YELLOW", "red": "RED"}.get(engine.state.led_state, "UNKNOWN")
        logger.info("[%4ds] |%s| %5.1f%%  %7s  Vmax=%3d%%", tick, bar, engine.state.damage*100, state_sym, engine.state.speed_pct)
        time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description="Wing Digital Twin Demo")
    parser.add_argument("--duration", type=int, default=30, help="Simulation duration in seconds (use 0 for infinite)")
    parser.add_argument("--run", action="store_true", help="Run indefinitely until Ctrl+C")
    parser.add_argument("--headless", action="store_true", help="Run without WebSocket or dashboard")
    parser.add_argument("--figures", action="store_true", help="Generate PNG figures after simulation")
    parser.add_argument("--figures-only", action="store_true", help="Regenerate figures from saved data")
    parser.add_argument("--data-dir", type=str, default=None, help="Data directory for --figures-only (default: figures/)")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory for figures (default: figures/)")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducible results")
    args = parser.parse_args()

    if args.run:
        args.duration = 0

    if args.seed is not None:
        logger.info("Random seed set to %d", args.seed)

    data_dir = Path(args.data_dir) if args.data_dir else PROJECT_ROOT / "figures"
    output_dir = Path(args.output_dir) if args.output_dir else data_dir

    if args.figures_only:
        loader = DataLoader(data_dir)
        strain, times, damage, forces, stress_fields, deformations, cycles = loader.load_tuple()
        if strain:
            generator = VisualizationGenerator(output_dir)
            generator.generate(strain, times, damage, cycles or [], stress_fields, deformations)
        else:
            logger.warning("No saved data found in %s", data_dir)
        return

    mode = "Headless" if args.headless else "Full Stack"
    logger.info("=" * 60)
    logger.info("  Wing Digital Twin Demo (%s)", mode)
    logger.info("=" * 60)
    fatigue_config = FatigueConfig()
    logger.info("  Sample rate:  %d Hz", SimulationConfig().sample_rate)
    logger.info("  Thresholds:   SAFE<%s  WARN<%s  CRIT>=%s", fatigue_config.damage_warning, fatigue_config.damage_critical, fatigue_config.damage_critical)
    logger.info("=" * 60)

    engine, history = asyncio.run(
        run_demo_async(args.duration, args.seed, record=True, record_figures=args.figures, headless=args.headless)
    )

    if args.figures and history.strain_history:
        exporter = DataExporter(data_dir)
        exporter.save(
            history.strain_history,
            history.times_history,
            history.damage_history,
            history.cycle_history,
            history.force_history,
            history.stress_field_history,
            history.deformation_field_history,
        )
        generator = VisualizationGenerator(output_dir)
        generator.generate(
            history.strain_history,
            history.times_history,
            history.damage_history,
            history.cycle_history,
            history.stress_field_history,
            history.deformation_field_history,
        )


if __name__ == "__main__":
    main()