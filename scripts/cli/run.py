"""
Wing Digital Twin Production Runner CLI Entry Point.

Uses real sensors via MQTT - connects to the physical wing system.
"""

import argparse
import asyncio
import signal
import time
from pathlib import Path
from typing import Optional

from dtwin.core.fatigue import FatigueState

from ..settings import PROJECT_ROOT, Config
from ..engine import DigitalTwinEngine, EngineConfig
from ..sources import MqttSource
from ..output import MqttPublisher, WebSocketBroadcaster, EngineCommandHandler
from ..analysis import (
    DataRecorder,
    save_fatigue_state,
    load_fatigue_state,
)
from ..viz import generate_figures_from_recording
from ..logger import get_logger

logger = get_logger(__name__)


async def run_production(
    config: Config,
    record: bool = False,
    record_figures: bool = False,
    resume_state: Optional[FatigueState] = None,
) -> Optional[Path]:
    """Run the digital twin with real sensor data."""
    engine_config = EngineConfig()
    engine = DigitalTwinEngine(engine_config, initial_fatigue_state=resume_state)

    logger.info("Loading transfer matrices...")
    try:
        engine.load_matrices()
        logger.info("Loaded successfully (%d gauge channels)", engine.num_gauges)
    except FileNotFoundError as e:
        logger.error("%s", e)
        logger.error("Cannot start without transfer matrices")
        raise

    mqtt_source = MqttSource(config.mqtt)
    engine.data_source = mqtt_source

    mqtt_publisher = MqttPublisher(config.mqtt)
    mqtt_publisher.connect()

    broadcaster = WebSocketBroadcaster(port=config.websocket.port)
    command_handler = EngineCommandHandler(engine)
    broadcaster.set_state_provider(engine.state.for_unity)

    recorder = None
    rec_dir = None
    stop_event = asyncio.Event()

    def _signal_handler():
        logger.info("Shutdown requested...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    if record or record_figures:
        from datetime import datetime
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        rec_dir = PROJECT_ROOT / "recordings" / f"run_{stamp}"
        scalar_int = 1 if record else 10
        recorder = DataRecorder(rec_dir, scalar_interval=scalar_int, field_interval=50)

    logger.info("=" * 60)
    logger.info("  Wing Digital Twin - Production Mode")
    logger.info("=" * 60)
    logger.info("  MQTT:   %s:%d", config.mqtt.broker, config.mqtt.port)
    logger.info("  Sensors topic: %s", config.mqtt.sensors_topic)
    logger.info("  Control topic: %s", config.mqtt.control_topic)
    if record:
        logger.info("  Recording: enabled -> recordings/")
    if record_figures:
        logger.info("  Figures:  enabled on exit")
    if resume_state is not None:
        logger.info("  Resuming from prior run (D=%.4f, %d cycles)", resume_state.damage, len(resume_state.cycles or []))
    logger.info("=" * 60)

    async def process_loop():
        while not stop_event.is_set():
            if engine.step():
                if recorder is not None:
                    recorder.record_frame(engine)

            mqtt_publisher.publish(config.mqtt.control_topic, engine.state.for_esp32())
            await asyncio.sleep(0.05)
            await broadcaster.broadcast()

    ws_task = asyncio.create_task(broadcaster.start())
    process_task = asyncio.create_task(process_loop())

    try:
        await asyncio.gather(ws_task, process_task, stop_event.wait())
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down...")
    finally:
        stop_event.set()
        process_task.cancel()
        ws_task.cancel()
        try:
            await process_task
        except asyncio.CancelledError:
            pass
        try:
            await ws_task
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0.1)

        if recorder is not None:
            recorder.finalize()
            save_fatigue_state(engine.fatigue_state, rec_dir)
            logger.info("Recording finalized")

        return rec_dir


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
    parser = argparse.ArgumentParser(description="Wing Digital Twin Production Runner")
    parser.add_argument("--broker", default="localhost", help="MQTT broker address")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--record", action="store_true", help="Record data to HDF5 during run")
    parser.add_argument("--figures", action="store_true", help="Generate PNG figures on shutdown")
    parser.add_argument("--figures-only", action="store_true", help="Regenerate figures from saved data")
    parser.add_argument("--data-dir", type=str, default=None, help="Data directory for --figures-only (default: most recent recording)")
    parser.add_argument("--resume", type=str, default=None, help="Resume from prior run directory (loads fatigue_state.json)")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory for figures (default: figures/)")
    args = parser.parse_args()

    config = Config()
    config.mqtt.broker = args.broker
    config.mqtt.port = args.port

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

    rec_dir = asyncio.run(
        run_production(config, record=args.record, record_figures=args.figures, resume_state=resume_state)
    )

    if args.figures and rec_dir is not None:
        generate_figures_from_recording(rec_dir, output_dir)


if __name__ == "__main__":
    main()
