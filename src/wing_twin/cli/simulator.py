import argparse
import asyncio
import json
import threading
from typing import Optional

from wing_twin.config import (
    EngineConfig,
    MqttConfig,
    SimulationConfig,
)
from wing_twin.engine.engine import DigitalTwinEngine
from wing_twin.io.logger import get_logger
from wing_twin.io.mqtt import MqttClientBase, MqttPublisher
from wing_twin.io.simulator import SimulatorSource
from wing_twin.io.websocket import WebSocketBroadcaster, EngineCommandHandler

from ._lifecycle import cancel_task, setup_signal_handler

logger = get_logger(__name__)


class SimulatorMqttBridge(MqttClientBase):

    def __init__(self, engine: DigitalTwinEngine, config: Optional[MqttConfig] = None):
        super().__init__(config)
        self._engine = engine
        self._sensors_topic = self.config.sensors_topic
        self._control_topic = self.config.control_topic

    def _register_callbacks(self) -> None:
        self._client.on_message = self._on_control

    def _on_connect(self, client, userdata, flags, rc) -> None:
        super()._on_connect(client, userdata, flags, rc)
        if rc == 0:
            client.subscribe(self._control_topic)

    def _on_control(self, client, userdata, msg) -> None:
        try:
            payload = json.loads(msg.payload.decode())
        except json.JSONDecodeError:
            return

        cmd = payload.get("cmd", "")
        engine = self._engine

        if cmd == "set_steps":
            steps = payload.get("steps")
            if steps is not None:
                engine.state.stepper_position = int(steps)
                speed = payload.get("speed", engine.state.target_airspeed)
                engine.state.target_airspeed = speed

        elif cmd == "set_flight_state":
            if engine.flight_phase.value == "in_flight":
                angle = payload.get("angle")
                speed = payload.get("speed")
                if angle is not None:
                    engine.state.desired_angle_of_attack = float(angle)
                if speed is not None:
                    engine.state.desired_airspeed = float(speed)

        elif cmd == "takeoff":
            engine.request_takeoff()

        elif cmd == "land":
            engine.request_landing()

        elif cmd == "set_heatmap_mode":
            mode = payload.get("mode", "damage")
            if mode in ("stress", "damage"):
                engine.state.heatmap_mode = mode

        elif cmd == "set_maintenance_assist":
            engine.state.maintenance_assist = bool(payload.get("enabled", True))

    def publish_engine_state(self, engine: DigitalTwinEngine) -> None:
        if not self._client or not self._connected:
            return

        state = engine.state
        msg: dict = {
            "timestamp": int(state.for_unity().get("timestamp", 0)),
            "strain_vector": state.strain_vector,
            "accel_z": 0.0,
            "stepper_position": state.stepper_position,
            "damage": round(state.damage, 4),
            "confidence": round(state.confidence, 2),
            "flight_phase": state.flight_phase,
            "altitude": round(state.altitude, 2),
            "airspeed": round(state.airspeed, 2),
            "angle_of_attack": round(state.angle_of_attack, 2),
        }

        try:
            self._client.publish(self._sensors_topic, json.dumps(msg))
        except Exception:
            pass


def _display_loop(engine: DigitalTwinEngine, stop_event: asyncio.Event) -> None:
    import time as _time

    while not stop_event.is_set():
        s = engine.state
        phase = s.flight_phase.upper()
        logger.info(
            "  [%s]  dmg=%.2f%%  conf=%.1f%%  alt=%.1fm  km=%.3f  speed=%.0f  aoa=%.1f",
            phase,
            s.damage * 100.0,
            s.confidence,
            s.altitude,
            s.km_this_flight,
            s.airspeed,
            s.angle_of_attack,
        )
        _time.sleep(1.0)


async def run_simulator(
    mqtt_config: MqttConfig,
    auto_takeoff: bool = False,
    seed: Optional[int] = None,
    enable_ws: bool = False,
) -> None:
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
    simulator = SimulatorSource(sim_config, wind_model=engine._wind)
    simulator.set_matrices(engine.matrices)
    engine.data_source = simulator

    mqtt_bridge = SimulatorMqttBridge(engine, mqtt_config)
    if not mqtt_bridge.connect():
        logger.warning("MQTT connection failed – running without MQTT bridge")
    else:
        logger.info("MQTT bridge connected to %s:%d", mqtt_config.broker, mqtt_config.port)

    mqtt_publisher = MqttPublisher(mqtt_config)
    mqtt_publisher.connect()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    setup_signal_handler(loop, stop_event)

    broadcaster: Optional[WebSocketBroadcaster] = None
    if enable_ws:
        broadcaster = WebSocketBroadcaster()
        command_handler = EngineCommandHandler(engine)
        broadcaster.set_state_provider(engine.state.for_unity)
        broadcaster.set_command_handler(command_handler)

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

            mqtt_bridge.publish_engine_state(engine)

            loop.run_in_executor(
                None,
                mqtt_publisher.publish,
                mqtt_config.control_topic,
                engine.state.for_esp32(),
            )

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
        mqtt_bridge.disconnect()
        mqtt_publisher.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Wing Digital Twin - Headless Sensor Simulator with MQTT bridge"
    )
    parser.add_argument("--broker", default="localhost", help="MQTT broker address")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument(
        "--auto-takeoff", action="store_true",
        help="Automatically take off on start (simulates a full flight cycle)",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Random seed for reproducible results",
    )
    parser.add_argument(
        "--ws", action="store_true",
        help="Enable WebSocket server for Unity visualization",
    )
    args = parser.parse_args()

    mqtt_config = MqttConfig(broker=args.broker, port=args.port)

    logger.info("=" * 60)
    logger.info("  Wing Digital Twin - Sensor Simulator")
    logger.info("=" * 60)
    logger.info("  MQTT:        %s:%d", mqtt_config.broker, mqtt_config.port)
    logger.info("  Publish:     %s", mqtt_config.sensors_topic)
    logger.info("  Subscribe:   %s", mqtt_config.control_topic)
    if args.auto_takeoff:
        logger.info("  Auto-takeoff: enabled")
    if args.ws:
        logger.info("  WebSocket:   enabled (ws://localhost:8765)")
    if args.seed is not None:
        logger.info("  Random seed: %d", args.seed)
    logger.info("=" * 60)

    try:
        asyncio.run(
            run_simulator(
                mqtt_config,
                auto_takeoff=args.auto_takeoff,
                seed=args.seed,
                enable_ws=args.ws,
            )
        )
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
