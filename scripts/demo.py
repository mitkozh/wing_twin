"""
Wing Digital Twin - Full Stack Demo + Figure Generator
Runs the complete force-reconstruction simulation, records all data, generates PNG figures.
Usage:
    python demo.py                     # Live demo only
    python demo.py --duration 120     # 120-second run
    python demo.py --duration 120 --figures   # Run + generate figures
    python demo.py --figures-only     # Load last run + regenerate figures
"""

import argparse
import asyncio
import threading
import time
import json
import math
import os
import numpy as np
import websockets
from collections import deque
from pathlib import Path
from dataclasses import dataclass, field

from dtwin import (
    load_transfer_matrices,
    solve_forces,
    compute_stress_field,
    compute_deformation_field,
    accumulate_damage,
    decide_control,
)
from dtwin.core import FatigueState
from dtwin.core.fatigue import STRAIN_BUFFER_SIZE, set_random_seed


SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
OUTPUT_DIR = PROJECT_ROOT / "figures"
OUTPUT_DIR.mkdir(exist_ok=True)

SAMPLE_RATE = 10
OSC_AMP = 50.0
OSC_FREQ = 0.5


@dataclass
class SimulationState:
    running: bool = True
    sensor_queue: deque = field(default_factory=lambda: deque(maxlen=100))
    control_queue: deque = field(default_factory=lambda: deque(maxlen=10))
    strain_buffer: deque = field(default_factory=lambda: deque(maxlen=STRAIN_BUFFER_SIZE))
    current_damage: float = 0.0
    current_speed_pct: int = 100
    led_state: str = "green"
    fatigue_state: FatigueState = field(default_factory=FatigueState)
    matrices = None
    num_gauges: int = 3
    record_strain: bool = True
    strain_history: list = field(default_factory=list)
    force_history: list = field(default_factory=list)
    stress_field_history: list = field(default_factory=list)
    deformation_field_history: list = field(default_factory=list)
    damage_history: list = field(default_factory=list)
    times_history: list = field(default_factory=list)
    cycle_history: list = field(default_factory=list)


def generate_strain(t: float, speed_pct: int) -> float:
    effective_amp = OSC_AMP * (speed_pct / 100.0)
    base = 100.0 + np.random.uniform(-5, 5)
    osc = effective_amp * math.sin(2 * math.pi * OSC_FREQ * t)
    noise = np.random.normal(0, 10)
    return base + osc + noise


def simulator_thread(state: SimulationState):
    t = 0.0
    dt = 1.0 / SAMPLE_RATE
    print("[SIM] Simulator started")
    while state.running:
        strain = generate_strain(t, state.current_speed_pct)
        state.sensor_queue.append({
            "strain": round(strain, 2),
            "accel_z": round(
                -state.current_speed_pct / 100.0 * OSC_AMP * (2 * math.pi * OSC_FREQ) ** 2
                * math.sin(2 * math.pi * OSC_FREQ * t) + np.random.normal(0, 50),
                1,
            ),
            "timestamp": int(t * 1000),
        })
        time.sleep(dt)
        t += dt


def orchestrator_thread(state: SimulationState):
    print("[ORCH] Orchestrator started")
    while state.running:
        samples_processed = 0
        while state.sensor_queue:
            data = state.sensor_queue.popleft()
            state.strain_buffer.append(data["strain"])
            if state.record_strain:
                state.strain_history.append(data["strain"])
            samples_processed += 1

        if samples_processed > 0 and len(state.strain_buffer) >= state.num_gauges:
            current_time = (len(state.strain_history) - 1) / SAMPLE_RATE
            arr = np.array(list(state.strain_buffer)[-state.num_gauges:], dtype=np.float64).ravel()

            if state.matrices is not None:
                F = solve_forces(state.matrices.H_inv, arr)
                stress = compute_stress_field(state.matrices.S, F)
                deformation = compute_deformation_field(state.matrices.U, F)
                state.force_history.append(F.tolist())
                state.stress_field_history.append(stress.tolist())
                state.deformation_field_history.append(deformation.tolist())
            else:
                state.force_history.append([0.0])
                state.stress_field_history.append([0.0])
                state.deformation_field_history.append([0.0])

            damage_inc, new_cycles = accumulate_damage(state.strain_buffer, state.fatigue_state)
            state.cycle_history.extend(new_cycles)
            state.current_damage = state.fatigue_state.damage

            state.led_state, state.current_speed_pct = decide_control(
                state.current_damage, state.fatigue_state.confidence
            )

            state.damage_history.append(state.fatigue_state.damage)
            state.times_history.append(current_time)
            state.control_queue.append({
                "servo": state.current_speed_pct,
                "led": state.led_state,
                "damage": state.current_damage,
                "speed": state.current_speed_pct,
            })

        time.sleep(0.05)


def display_thread(state: SimulationState):
    print("\n" + "=" * 60)
    print("  Wing Digital Twin — Live Dashboard")
    print("=" * 60)
    tick = 0
    while state.running:
        tick += 1
        bar_len = 30
        filled = int(state.current_damage * bar_len)
        bar = "#" * filled + "-" * (bar_len - filled)
        state_sym = {"green": "GREEN", "yellow": "YELLOW", "red": "RED"}.get(state.led_state, "UNKNOWN")
        print(f"[{tick:4d}s] |{bar}| {state.current_damage*100:5.1f}%  {state_sym:7s}  Vmax={state.current_speed_pct:3d}%")
        time.sleep(1)


async def websocket_server(state: SimulationState):
    connected_clients = set()

    async def handler(ws):
        connected_clients.add(ws)
        print(f"[WS] Client connected ({len(connected_clients)} total)")
        try:
            await ws.send(json.dumps({
                "strain": 0.0, "forces": [], "stress_field": [], 
                "deformation_field": [], "damage": 0.0, "speed": 100, "led_state": "green"
            }))
            async for _ in ws:
                pass
        except Exception:
            pass
        finally:
            connected_clients.discard(ws)

    async with websockets.serve(handler, "localhost", 8765):
        print("[WS]  WebSocket server running on ws://localhost:8765")
        print("[WS]  Clients can connect and receive: {strain, forces, stress_field, deformation_field, damage, speed, led_state}")
        while state.running:
            if connected_clients and state.control_queue:
                latest = state.control_queue[-1]
                msg = {
                    "strain": float(np.mean(state.strain_history[-100:])) if state.strain_history else 0.0,
                    "forces": state.force_history[-1] if state.force_history else [0.0],
                    "stress_field": state.stress_field_history[-1][:5] if state.stress_field_history else [],
                    "deformation_field": state.deformation_field_history[-1][:5] if state.deformation_field_history else [],
                    "damage": round(latest["damage"], 4),
                    "speed": latest["speed"],
                    "led_state": latest["led"],
                }
                await asyncio.gather(*[ws.send(json.dumps(msg)) for ws in connected_clients], return_exceptions=True)
            await asyncio.sleep(0.1)


def websocket_thread_wrapper(state: SimulationState):
    asyncio.run(websocket_server(state))


def run_simulation(duration_s: int, state: SimulationState):
    state.running = True
    state.strain_history = []
    state.force_history = []
    state.stress_field_history = []
    state.deformation_field_history = []
    state.damage_history = []
    state.times_history = []
    state.cycle_history = []
    state.fatigue_state = FatigueState()
    state.sensor_queue.clear()
    state.control_queue.clear()
    state.strain_buffer.clear()

    print("[MATRICES] Loading transfer matrices...")
    try:
        state.matrices = load_transfer_matrices()
        state.num_gauges = state.matrices.H_inv.shape[1]
        print(f"[MATRICES] Loaded successfully ({state.num_gauges} gauge channels)")
    except FileNotFoundError as e:
        print(f"[MATRICES] {e}")
        print("[MATRICES] Running without transfer matrices (forces/fields will be zero)")

    t1 = threading.Thread(target=simulator_thread, args=(state,), daemon=True)
    t2 = threading.Thread(target=orchestrator_thread, args=(state,), daemon=True)
    t3 = threading.Thread(target=websocket_thread_wrapper, args=(state,), daemon=True)
    t4 = threading.Thread(target=display_thread, args=(state,), daemon=True)
    for t in [t1, t2, t3, t4]:
        t.start()

    try:
        time.sleep(duration_s)
    except KeyboardInterrupt:
        pass

    state.running = False
    time.sleep(0.5)

    n = min(len(state.strain_history), len(state.damage_history), len(state.times_history))
    print(f"\n[SIM] Recorded {len(state.strain_history)} samples over {duration_s}s")
    print(f"       (truncating to {n} synchronized points for figures)")


def save_data(state: SimulationState):
    path = OUTPUT_DIR / "sim_data.json"
    with open(path, "w") as f:
        json.dump({
            "strain": state.strain_history,
            "forces": state.force_history,
            "stress_field": state.stress_field_history,
            "deformation_field": state.deformation_field_history,
            "damage": state.damage_history,
            "times": state.times_history,
            "cycles": state.cycle_history,
        }, f)
    print(f"  [DATA] Saved to {path}")


def load_data():
    path = OUTPUT_DIR / "sim_data.json"
    if not path.exists():
        print(f"  [DATA] No saved data at {path}")
        return None, None, None, None, None, None, None
    with open(path) as f:
        d = json.load(f)
    print(f"  [DATA] Loaded {len(d['strain'])} samples")
    return d["strain"], d["times"], d["damage"], d.get("forces"), d.get("stress_field"), d.get("deformation_field"), d.get("cycles", [])


def main():
    from dtwin.core.fatigue import DAMAGE_SAFE, DAMAGE_WARNING

    parser = argparse.ArgumentParser(description="Wing Digital Twin Demo")
    parser.add_argument("--duration", type=int, default=30, help="Simulation duration in seconds")
    parser.add_argument("--figures", action="store_true", help="Generate PNG figures after simulation")
    parser.add_argument("--figures-only", action="store_true", help="Regenerate figures from last saved data")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducible results")
    args = parser.parse_args()

    if args.seed is not None:
        set_random_seed(args.seed)
        print(f"[SEED] Random seed set to {args.seed}")

    print("=" * 60)
    print("  Wing Digital Twin — Full Stack Demo")
    print("=" * 60)
    print(f"  Sample rate:  {SAMPLE_RATE} Hz")
    print(f"  Thresholds:   SAFE<{DAMAGE_SAFE}  WARN<{DAMAGE_WARNING}  CRIT>={DAMAGE_WARNING}")
    print("=" * 60)

    if args.figures_only:
        from visualizer import generate_all
        strain, times, damage, forces, stress_fields, deformations, cycles = load_data()
        if strain:
            generate_all(strain, times, damage, cycles or [], forces, stress_fields, deformations)
        return

    state = SimulationState()
    run_simulation(args.duration, state)

    if args.figures and state.strain_history:
        from visualizer import generate_all
        save_data(state)
        generate_all(state.strain_history, state.times_history, state.damage_history, state.cycle_history, state.force_history, state.stress_field_history, state.deformation_field_history)


if __name__ == "__main__":
    main()