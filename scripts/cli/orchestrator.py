#!/usr/bin/env python3
"""
Wing Digital Twin Orchestrator CLI Entry Point.
"""

import argparse
import asyncio

from scripts.config import Config
from scripts.orchestration import WingOrchestrator


def main():
    parser = argparse.ArgumentParser(description="Wing Digital Twin Orchestrator")
    parser.add_argument("--broker", default="localhost", help="MQTT broker address")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    args = parser.parse_args()

    config = Config()
    config.mqtt.broker = args.broker
    config.mqtt.port = args.port

    orchestrator = WingOrchestrator(config)

    try:
        orchestrator.load_matrices()
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        print("[ERROR] Cannot start without transfer matrices in transfer_matrices/")
        return

    asyncio.run(orchestrator.run_async())


if __name__ == "__main__":
    main()