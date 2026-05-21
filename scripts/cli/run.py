"""
Wing Digital Twin Production Runner CLI Entry Point.

Uses real sensors via MQTT - connects to the physical wing system.
"""

import argparse
import asyncio

from scripts.config import Config
from scripts.engine import DigitalTwinEngine, EngineConfig
from scripts.sources import MqttSource
from scripts.output import WebSocketBroadcaster, EngineCommandHandler
from scripts.logger import get_logger

logger = get_logger(__name__)


async def run_production(config: Config):
    """Run the digital twin with real sensor data."""
    engine_config = EngineConfig()
    engine = DigitalTwinEngine(engine_config)

    logger.info("Loading transfer matrices...")
    try:
        engine.load_matrices()
        logger.info("Loaded successfully (%d gauge channels)", engine.num_gauges)
    except FileNotFoundError as e:
        logger.error("%s", e)
        logger.error("Cannot start without transfer matrices")
        return

    mqtt_source = MqttSource(config.mqtt)
    engine.data_source = mqtt_source

    broadcaster = WebSocketBroadcaster(port=config.websocket.port)
    command_handler = EngineCommandHandler(engine)
    broadcaster.set_state_provider(engine.state.for_unity)

    logger.info("=" * 60)
    logger.info("  Wing Digital Twin - Production Mode")
    logger.info("=" * 60)
    logger.info("  MQTT:   %s:%d", config.mqtt.broker, config.mqtt.port)
    logger.info("  Topics: %s", config.mqtt.sensors_topic)
    logger.info("=" * 60)

    async def process_loop():
        while True:
            engine.step()
            await asyncio.sleep(0.05)
            await broadcaster.broadcast()

    ws_task = asyncio.create_task(broadcaster.start())
    process_task = asyncio.create_task(process_loop())

    try:
        await asyncio.gather(ws_task, process_task)
    except KeyboardInterrupt:
        logger.info("Shutting down...")


def main():
    parser = argparse.ArgumentParser(description="Wing Digital Twin Production Runner")
    parser.add_argument("--broker", default="localhost", help="MQTT broker address")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    args = parser.parse_args()

    config = Config()
    config.mqtt.broker = args.broker
    config.mqtt.port = args.port

    asyncio.run(run_production(config))


if __name__ == "__main__":
    main()