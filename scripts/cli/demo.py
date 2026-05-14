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

from dtwin.core.fatigue import DAMAGE_SAFE, DAMAGE_WARNING

from pathlib import Path

from ..config import PROJECT_ROOT
from ..analysis import DataExporter, DataLoader
from ..viz import VisualizationGenerator
from ..engine import DigitalTwinEngine, EngineConfig
from ..sources import SimulatorSource
from ..output import WebSocketBroadcaster


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
    record: bool = True
) -> tuple[DigitalTwinEngine, HistoryState]:
    """Run demo with WebSocket broadcasting."""
    config = EngineConfig(seed=seed)
    engine = DigitalTwinEngine(config)

    print("[MATRICES] Loading transfer matrices...")
    try:
        engine.load_matrices()
        print(f"[MATRICES] Loaded successfully ({engine.num_gauges} gauge channels)")
    except FileNotFoundError as e:
        print(f"[MATRICES] {e}")
        print("[MATRICES] Running without transfer matrices")

    simulator = SimulatorSource()
    engine.data_source = simulator

    history = HistoryState()
    running = [True]  # Use list for mutability across threads
    start_time = time.time()

    broadcaster = WebSocketBroadcaster()

    def state_provider():
        return engine.state.for_unity()

    broadcaster.set_state_provider(state_provider)

    display_task = asyncio.create_task(broadcaster.start())

    async def process_loop():
        while running[0]:
            if engine.step():
                if record:
                    history.strain_history.append(
                        engine.state.strain_vector[0] if engine.state.strain_vector else 0.0
                    )
                    history.force_history.append(engine.state.forces.copy())
                    history.stress_field_history.append(engine.state.stress_field.copy())
                    history.deformation_field_history.append(engine.state.deformation_field.copy())
                    history.damage_history.append(engine.state.damage)
                    history.times_history.append(time.time() - start_time)
                    history.cycle_history.extend(engine.cycles)
                    engine.clear_cycles()
            await asyncio.sleep(0.05)
            if broadcaster.connected_clients > 0:
                await broadcaster.broadcast()

    process_task = asyncio.create_task(process_loop())
    display_thread = threading.Thread(target=_display_thread, args=(engine, running), daemon=True)
    display_thread.start()

    try:
        await asyncio.sleep(duration_s)
    except KeyboardInterrupt:
        pass

    running[0] = False
    await asyncio.sleep(0.5)

    print(f"\n[SIM] Recorded {len(history.strain_history)} samples over {duration_s}s")

    return engine, history


def _display_thread(engine, running_ref):
    """Thread that displays live dashboard."""
    print("\n" + "=" * 60)
    print("  Wing Digital Twin — Live Dashboard")
    print("=" * 60)
    tick = 0
    while running_ref[0]:
        tick += 1
        bar_len = 30
        filled = int(engine.state.damage * bar_len)
        bar = "#" * filled + "-" * (bar_len - filled)
        state_sym = {"green": "GREEN", "yellow": "YELLOW", "red": "RED"}.get(engine.state.led_state, "UNKNOWN")
        print(f"[{tick:4d}s] |{bar}| {engine.state.damage*100:5.1f}%  {state_sym:7s}  Vmax={engine.state.speed_pct:3d}%")
        time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description="Wing Digital Twin Demo")
    parser.add_argument("--duration", type=int, default=30, help="Simulation duration in seconds")
    parser.add_argument("--figures", action="store_true", help="Generate PNG figures after simulation")
    parser.add_argument("--figures-only", action="store_true", help="Regenerate figures from last saved data")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducible results")
    args = parser.parse_args()

    if args.seed is not None:
        print(f"[SEED] Random seed set to {args.seed}")

    print("=" * 60)
    print("  Wing Digital Twin — Full Stack Demo")
    print("=" * 60)
    print(f"  Sample rate:  10 Hz")
    print(f"  Thresholds:   SAFE<{DAMAGE_SAFE}  WARN<{DAMAGE_WARNING}  CRIT>={DAMAGE_WARNING}")
    print("=" * 60)

    if args.figures_only:
        loader = DataLoader(PROJECT_ROOT / "figures")
        strain, times, damage, forces, stress_fields, deformations, cycles = loader.load_tuple()
        if strain:
            generator = VisualizationGenerator(PROJECT_ROOT / "figures")
            generator.generate(strain, times, damage, cycles or [], stress_fields, deformations)
        return

    engine, history = asyncio.run(run_demo_async(args.duration, args.seed, record=True))

    if args.figures and history.strain_history:
        exporter = DataExporter(PROJECT_ROOT / "figures")
        exporter.save(
            history.strain_history,
            history.times_history,
            history.damage_history,
            history.cycle_history,
            history.force_history,
            history.stress_field_history,
            history.deformation_field_history,
        )
        generator = VisualizationGenerator(PROJECT_ROOT / "figures")
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