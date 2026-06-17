from __future__ import annotations

import argparse

from .server import create_app


def run_dashboard() -> None:
    parser = argparse.ArgumentParser(description="Wing Twin live dashboard")
    parser.add_argument("--broker", default="131.155.209.40", help="MQTT broker address")
    parser.add_argument("--port", type=int, default=1884, help="MQTT broker port")
    parser.add_argument("--web-port", type=int, default=5050, help="Dashboard HTTP port")
    parser.add_argument("--host", default="0.0.0.0", help="Dashboard bind address")
    args = parser.parse_args()

    app = create_app(args.broker, args.port)
    print(f"[DASHBOARD] http://{args.host}:{args.web_port}  (MQTT {args.broker}:{args.port})")
    app.run(host=args.host, port=args.web_port, debug=False, use_reloader=False)


__all__ = ["create_app", "run_dashboard"]
