"""
Wing Digital Twin Real Run CLI Entry Point.

Uses real sensors via MQTT - connects to the physical wing system.
"""

import argparse
import asyncio
from pathlib import Path
from typing import Optional

from ._lifecycle import cancel_task, finalize_recorder, publish_final_zero, setup_recorder, setup_signal_handler

from wing_twin.config import PROJECT_ROOT, Config
from wing_twin.engine.engine import DigitalTwinEngine
from wing_twin.config import EngineConfig
from wing_twin.engine.state import EngineSnapshot
from wing_twin.io.mqtt import MqttSource, MqttPublisher
from wing_twin.io.websocket import WebSocketBroadcaster, EngineCommandHandler
from wing_twin.recorder.recorder import load_engine_snapshot
from wing_twin.viz.generator import generate_figures_from_recording
from wing_twin.io.logger import get_logger

logger = get_logger(__name__)


async def run_production(
    config: Config,
    record: bool = False,
    record_figures: bool = False,
    resume_snapshot: Optional[EngineSnapshot] = None,
) -> Optional[Path]:
    engine_config = EngineConfig()
    engine = DigitalTwinEngine(
        engine_config,
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

    mqtt_source = MqttSource(config.mqtt)
    engine.data_source = mqtt_source

    mqtt_publisher = MqttPublisher(config.mqtt)
    mqtt_publisher.connect()

    broadcaster = WebSocketBroadcaster(port=config.websocket.port)
    command_handler = EngineCommandHandler(engine)
    broadcaster.set_command_handler(command_handler)
    broadcaster.set_state_provider(engine.state.for_unity)

    recorder, rec_dir = setup_recorder(record, record_figures)
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    setup_signal_handler(loop, stop_event)

    async def process_loop():
        while not stop_event.is_set():
            try:
                stepped = engine.step()
            except Exception as e:
                logger.error("Engine step failed: %s", e)
                stepped = False

            reported = mqtt_source.handler.latest_esp32_stepper
            if reported is not None:
                engine.state.esp32_reported_position = reported
            offset = mqtt_source.handler.latest_esp32_home_offset
            if offset is not None:
                engine.state.esp32_reported_home_offset = offset

            if stepped and recorder is not None:
                try:
                    recorder.record_frame(engine)
                except Exception as e:
                    logger.error("Recording failed: %s", e)

            loop.run_in_executor(
                None, mqtt_publisher.publish,
                config.mqtt.control_topic, engine.state.for_esp32(),
            )
            await asyncio.sleep(0.05)
            await broadcaster.broadcast()

    ws_task = asyncio.create_task(broadcaster.start())
    process_task = asyncio.create_task(process_loop())

    try:
        await stop_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down...")
    finally:
        stop_event.set()
        await cancel_task(process_task)
        await cancel_task(ws_task)
        await asyncio.sleep(0.1)

        publish_final_zero(mqtt_publisher, config, engine)
        await asyncio.sleep(0.05)
        mqtt_publisher.disconnect()

        finalize_recorder(recorder, engine, rec_dir)
        if recorder is not None:
            logger.info("Recording finalized")

        return rec_dir


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
    parser = argparse.ArgumentParser(description="Wing Digital Twin Real Run")
    parser.add_argument("--broker", default="localhost", help="MQTT broker address")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--record", action="store_true", help="Record data to HDF5 during run")
    parser.add_argument("--figures", nargs="?", const=True, default=False, help="Generate PNG figures (optional: output directory)")
    parser.add_argument("--figures-only", nargs="?", const=True, default=False, help="Regenerate figures from saved data (optional: data directory)")
    parser.add_argument("--resume", type=str, default=None, help="Resume from prior run directory")
    args = parser.parse_args()

    config = Config()
    config.mqtt.broker = args.broker
    config.mqtt.port = args.port

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
    logger.info("  Wing Digital Twin - Real Run Mode")
    logger.info("=" * 60)
    logger.info("  MQTT:   %s:%d", config.mqtt.broker, config.mqtt.port)
    logger.info("  Sensors topic: %s", config.mqtt.sensors_topic)
    logger.info("  Control topic: %s", config.mqtt.control_topic)
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

    rec_dir = asyncio.run(
        run_production(
            config,
            record=args.record,
            record_figures=bool(args.figures),
            resume_snapshot=resume_snapshot,
        )
    )

    if args.figures and rec_dir is not None:
        generate_figures_from_recording(rec_dir, output_dir)


if __name__ == "__main__":
    main()
