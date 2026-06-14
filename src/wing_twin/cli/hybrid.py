"""
Wing Digital Twin - Hybrid Run CLI Entry Point.

Uses simulated aero and strain while driving
physical hardware (stepper motor, LEDs) via MQTT.
"""

import argparse
import asyncio
import json
import threading
from pathlib import Path
from typing import Optional

from wing_twin.config import (
    EngineConfig,
    MqttConfig,
    PROJECT_ROOT,
    SimulationConfig,
)
from wing_twin.engine.engine import DigitalTwinEngine
from wing_twin.io.logger import get_logger
from wing_twin.io.mqtt import (
    MqttCommandPublisher,
    MqttConnection,
    MqttStepperMonitor,
)
from wing_twin.io.protocol import STEPPER_COMMAND_TOPIC
from wing_twin.io.simulator import SimulatorSource
from wing_twin.io.websocket import WebSocketBroadcaster, EngineCommandHandler
from wing_twin.viz.generator import generate_figures_from_recording

from ._lifecycle import (
    cancel_task,
    finalize_recorder,
    publish_final_zero,
    setup_recorder,
    setup_signal_handler,
)

logger = get_logger(__name__)


class SimulatorMqttBridge:

    def __init__(self, engine: DigitalTwinEngine, config: Optional[MqttConfig] = None):
        self._config = config or MqttConfig()
        self._connection = MqttConnection(self._config)
        self._engine = engine
        self._control_topic = self._config.control_topic
        self._cmd_handler = EngineCommandHandler(engine)

    def connect(self) -> bool:
        self._connection.subscribe(self._control_topic, self._on_control)
        return self._connection.connect()

    def disconnect(self) -> None:
        self._connection.disconnect()

    def _on_control(self, topic: str, payload: bytes) -> None:
        self._cmd_handler.handle(payload.decode())

    def publish_engine_state(self, engine: DigitalTwinEngine) -> None:
        if not self._connection.is_connected:
            return

        state = engine.state
        msg: dict = {
            "timestamp": int(state.for_unity().get("timestamp", 0)),
            "strain_vector": state.structural.strain_vector,
            "accel_z": 0.0,
            "stepper_position": state.stepper.stepper_position,
            "damage": round(state.damage.damage, 4),
            "confidence": round(state.damage.confidence, 2),
            "flight_phase": state.flight.flight_phase,
            "altitude": round(state.flight.altitude, 2),
            "airspeed": round(state.control.airspeed, 2),
            "angle_of_attack": round(state.control.angle_of_attack, 2),
        }

        try:
            self._connection.publish(self._config.sensors_topic, json.dumps(msg))
        except Exception:
            pass


def _display_loop(engine: DigitalTwinEngine, stop_event: asyncio.Event) -> None:
    import time as _time

    while not stop_event.is_set():
        s = engine.state
        phase = s.flight.flight_phase.upper()
        logger.info(
            "  [%s]  dmg=%.2f%%  conf=%.1f%%  alt=%.1fm  km=%.3f  speed=%.0f  aoa=%.1f  step=%d",
            phase,
            s.damage.damage * 100.0,
            s.damage.confidence,
            s.flight.altitude,
            s.flight.km_this_flight,
            s.control.airspeed,
            s.control.angle_of_attack,
            s.stepper.stepper_position,
        )
        _time.sleep(1.0)


async def run_simulator(
    mqtt_config: MqttConfig,
    auto_takeoff: bool = False,
    seed: Optional[int] = None,
    enable_ws: bool = False,
    record: bool = False,
    record_figures: bool = False,
    publish_sensors: bool = False,
) -> Optional[Path]:
    config = EngineConfig(seed=seed)
    engine = DigitalTwinEngine(config)

    logger.info("Loading transfer matrices...")
    try:
        engine.load_matrices()
        logger.info("Loaded successfully (%d gauge channels)", engine.num_gauges)
    except FileNotFoundError as e:
        logger.error("%s", e)
        raise

    sim_config = SimulationConfig()
    simulator = SimulatorSource(sim_config, wind_model=engine.wind_model)
    simulator.set_matrices(engine.matrices)
    engine.data_source = simulator

    sub_conn = MqttConnection(mqtt_config, client_id="wing-twin-hybrid-sub")
    sub_conn.connect()

    pub_conn = MqttConnection(mqtt_config, client_id="wing-twin-hybrid-pub")
    pub_conn.set_last_will(STEPPER_COMMAND_TOPIC, {"position": 0})
    pub_conn.connect()

    stepper_monitor = MqttStepperMonitor(sub_conn)
    publisher = MqttCommandPublisher(pub_conn)

    mqtt_bridge = SimulatorMqttBridge(engine, mqtt_config)
    if mqtt_bridge.connect():
        logger.info("MQTT control bridge connected to %s:%d", mqtt_config.broker, mqtt_config.port)
    else:
        logger.warning("MQTT control bridge connection failed")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    setup_signal_handler(loop, stop_event)

    broadcaster: Optional[WebSocketBroadcaster] = None
    if enable_ws:
        broadcaster = WebSocketBroadcaster()
        command_handler = EngineCommandHandler(engine)
        broadcaster.set_state_provider(engine.state.for_unity)
        broadcaster.set_command_handler(command_handler)

    recorder, rec_dir = setup_recorder(record, record_figures)

    display_thread = threading.Thread(
        target=_display_loop, args=(engine, stop_event), daemon=True
    )
    display_thread.start()

    takeoff_done = False

    async def process_loop() -> None:
        nonlocal takeoff_done
        while not stop_event.is_set():
            if auto_takeoff and not takeoff_done and engine.flight_phase.value == "on_ground":
                engine.request_takeoff()
                takeoff_done = True
                logger.info("Auto-takeoff initiated")

            try:
                stepped = engine.step()
            except Exception as e:
                logger.error("Engine step failed: %s", e)
                stepped = False

            engine.state.stepper.esp32_reported_position = stepper_monitor.state.position

            if stepped and recorder is not None:
                try:
                    recorder.record_frame(engine)
                except Exception as e:
                    logger.error("Recording failed: %s", e)

            loop.run_in_executor(
                None, publisher.publish_stepper_position,
                engine.state.stepper.stepper_position,
            )
            loop.run_in_executor(
                None, publisher.publish_led_command,
                engine.state.compute_led_colors(),
            )

            if publish_sensors:
                mqtt_bridge.publish_engine_state(engine)

            if broadcaster and broadcaster._clients:
                await broadcaster.broadcast()

            await asyncio.sleep(1.0 / sim_config.sample_rate)

    process_task = asyncio.create_task(process_loop())

    ws_task: Optional[asyncio.Task] = None
    if broadcaster:
        ws_task = asyncio.create_task(broadcaster.start())

    try:
        await stop_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down...")
    finally:
        stop_event.set()
        await cancel_task(process_task)
        if ws_task:
            await cancel_task(ws_task)
        await asyncio.sleep(0.1)

        publish_final_zero(publisher, engine)
        await asyncio.sleep(0.05)
        mqtt_bridge.disconnect()
        pub_conn.disconnect()
        sub_conn.disconnect()

        finalize_recorder(recorder, engine, rec_dir)
        if recorder is not None:
            logger.info("Recording finalized")

    return rec_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Wing Digital Twin - Hybrid Run (simulated aero/strain, physical stepper/LEDs)"
    )
    parser.add_argument("--broker", default="localhost", help="MQTT broker address")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument(
        "--auto-takeoff", action="store_true",
        help="Automatically take off on start (simulates a full flight cycle)",
    )
    parser.add_argument(
        "--record", action="store_true",
        help="Record data to HDF5 during run",
    )
    parser.add_argument(
        "--figures", nargs="?", const=True, default=False,
        help="Generate PNG figures on exit (optional: output directory)",
    )
    parser.add_argument(
        "--publish-sensors", action="store_true",
        help="Publish synthetic sensor data to MQTT sensors topic (for dashboard testing)",
    )
    parser.add_argument(
        "--ws", action="store_true",
        help="Enable WebSocket server for Unity visualization",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Random seed for reproducible results",
    )
    args = parser.parse_args()

    mqtt_config = MqttConfig(broker=args.broker, port=args.port)

    logger.info("=" * 60)
    logger.info("  Wing Digital Twin - Hybrid Run")
    logger.info("=" * 60)
    logger.info("  MQTT:        %s:%d", mqtt_config.broker, mqtt_config.port)
    logger.info("  Stepper:     %s", "wing/stepper/command")
    logger.info("  LEDs:        %s", "wing/sensor/command")
    if args.auto_takeoff:
        logger.info("  Auto-takeoff: enabled")
    if args.record:
        logger.info("  Recording:    enabled -> recordings/")
    if args.figures:
        logger.info("  Figures:      enabled on exit")
    if args.publish_sensors:
        logger.info("  Sensor bridge: enabled -> %s", mqtt_config.sensors_topic)
    if args.ws:
        logger.info("  WebSocket:    enabled (ws://localhost:8765)")
    if args.seed is not None:
        logger.info("  Random seed:  %d", args.seed)
    logger.info("=" * 60)

    output_dir = Path(args.figures) if isinstance(args.figures, str) else PROJECT_ROOT / "figures"
    output_dir.mkdir(exist_ok=True)

    try:
        rec_dir = asyncio.run(
            run_simulator(
                mqtt_config,
                auto_takeoff=args.auto_takeoff,
                seed=args.seed,
                enable_ws=args.ws,
                record=args.record,
                record_figures=bool(args.figures),
                publish_sensors=args.publish_sensors,
            )
        )

        if args.figures and rec_dir is not None:
            generate_figures_from_recording(rec_dir, output_dir)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
