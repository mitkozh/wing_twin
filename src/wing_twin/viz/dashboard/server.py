"""
Flask web dashboard for wing twin — live monitoring + stepper control,
with historical data buffer and CSV export.
"""

from __future__ import annotations

import csv
import io
import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import paho.mqtt.client as mqtt

HERE = Path(__file__).parent
STATIC = HERE / "static"

_MAX_RECORDS = 43200  # 6 hours @ 2 Hz

CHANNEL_NAMES = [
    "root_0", "root_45", "root_90",
    "middle_0", "middle_45", "middle_90",
    "tip_0", "tip_45", "tip_90",
]


@dataclass
class DashboardState:
    raw: list[int] = field(default_factory=lambda: [0] * 10)
    offset: list[float] = field(default_factory=lambda: [0.0] * 9)
    dummy_raw: int = 0
    stepper_position: int = 0
    stepper_enabled: bool = True
    home_offset: int = 0
    saturated: list[bool] = field(default_factory=lambda: [False] * 9)
    mqtt_connected: bool = False
    timestamp: int = 0
    record_count: int = 0
    last_tare_time: float = 0.0       # wall-clock seconds when offset last changed
    last_tare_esp_ts: int = 0         # ESP millis when offset last changed


_state = DashboardState()
_mqtt_client: Optional[mqtt.Client] = None
_sensor_topic = "wing/sensors"
_control_topic = "wing/control"
_stepper_topic = "wing/stepper/command"

_buf: deque = deque(maxlen=_MAX_RECORDS)
_buf_lock = threading.Lock()

# Track previous offset to detect tare
_prev_offset: list[float] | None = None


def _on_connect(client, userdata, flags, rc):
    client.subscribe(_sensor_topic)
    _state.mqtt_connected = True


def _on_disconnect(client, userdata, rc):
    _state.mqtt_connected = False


def _on_message(client, userdata, msg):
    global _prev_offset
    try:
        data = json.loads(msg.payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return

    now = time.time()
    _state.raw = data.get("raw", _state.raw)
    _state.dummy_raw = data.get("dummy_raw", _state.dummy_raw)
    _state.stepper_position = data.get("stepper_position", _state.stepper_position)
    _state.home_offset = data.get("home_offset", _state.home_offset)
    _state.saturated = data.get("saturated", _state.saturated)
    _state.timestamp = data.get("timestamp", _state.timestamp)

    # Track offset changes to detect tare events
    offset_raw = data.get("offset")
    if offset_raw is not None and isinstance(offset_raw, list) and len(offset_raw) == 9:
        offset_float = [float(v) for v in offset_raw]
        if _prev_offset is not None and offset_float != _prev_offset:
            _state.last_tare_time = now
            _state.last_tare_esp_ts = _state.timestamp
        _state.offset = offset_float
        _prev_offset = offset_float

    record = {
        "t": now,
        "esp_ts": _state.timestamp,
        "raw": list(_state.raw),
        "offset": list(_state.offset),
        "stepper_pos": _state.stepper_position,
        "dummy_raw": _state.dummy_raw,
        "saturated": list(_state.saturated),
    }
    with _buf_lock:
        _buf.append(record)
        _state.record_count = len(_buf)


class _MqttThread(threading.Thread):
    def __init__(self, broker: str, port: int):
        super().__init__(daemon=True)
        global _mqtt_client
        _mqtt_client = mqtt.Client()
        _mqtt_client.on_connect = _on_connect
        _mqtt_client.on_disconnect = _on_disconnect
        _mqtt_client.on_message = _on_message
        self._broker = broker
        self._port = port

    def run(self):
        try:
            _mqtt_client.connect(self._broker, self._port, 60)
            _mqtt_client.loop_forever()
        except Exception:
            pass


def create_app(broker: str = "localhost", port: int = 1883):
    """Build and return the Flask WSGI app."""
    from flask import Flask, jsonify, request, send_from_directory

    app = Flask(__name__, static_folder=str(STATIC))

    _MqttThread(broker, port).start()

    @app.route("/")
    def index():
        return send_from_directory(str(STATIC), "index.html")

    @app.route("/static/<path:filename>")
    def static_files(filename):
        return send_from_directory(str(STATIC), filename)

    @app.route("/api/state")
    def api_state():
        return jsonify(
            {
                "raw": _state.raw,
                "offset": _state.offset,
                "dummy_raw": _state.dummy_raw,
                "stepper_position": _state.stepper_position,
                "stepper_enabled": _state.stepper_enabled,
                "home_offset": _state.home_offset,
                "saturated": _state.saturated,
                "mqtt_connected": _state.mqtt_connected,
                "timestamp": _state.timestamp,
                "record_count": _state.record_count,
                "last_tare_time": _state.last_tare_time,
                "last_tare_esp_ts": _state.last_tare_esp_ts,
            }
        )

    @app.route("/api/control", methods=["POST"])
    def api_control():
        data = request.get_json(force=True)
        if data is None:
            return jsonify({"ok": False, "error": "no payload"}), 400
        # Track stepper enable locally
        if "stepper_enable" in data:
            _state.stepper_enabled = bool(data["stepper_enable"])
        c = _mqtt_client
        if c is None or not c.is_connected():
            return jsonify({"ok": False, "error": "MQTT not connected"}), 503
        # Route stepper commands to wing/stepper/command, others to wing/control
        # calibrate stays on wing/control (main ESP orchestrates it over MQTT)
        stepper_keys = {"position", "stepper_enable", "reset_position"}
        if stepper_keys & data.keys():
            topic = _stepper_topic
        else:
            topic = _control_topic
        payload = json.dumps(data)
        c.publish(topic, payload, qos=1)
        return jsonify({"ok": True})

    @app.route("/api/export.csv")
    def api_export_csv():
        start_s = request.args.get("start", type=float)
        end_s = request.args.get("end", type=float)

        with _buf_lock:
            records = list(_buf)

        if start_s is not None:
            records = [r for r in records if r["t"] >= start_s]
        if end_s is not None:
            records = [r for r in records if r["t"] <= end_s]

        out = io.StringIO()
        w = csv.writer(out)

        header = ["timestamp_utc", "esp_millis", "stepper_position", "dummy_raw"]
        for ch in CHANNEL_NAMES:
            header.append(f"raw_{ch}")
        for ch in CHANNEL_NAMES:
            header.append(f"offset_{ch}")
        for ch in CHANNEL_NAMES:
            header.append(f"saturated_{ch}")
        w.writerow(header)

        for r in records:
            row = [
                f"{r['t']:.3f}",
                r["esp_ts"],
                r["stepper_pos"],
                r["dummy_raw"],
            ]
            row.extend(r["raw"][:9])
            row.extend(r["offset"][:9])
            row.extend(r["saturated"][:9])
            w.writerow(row)

        csv_bytes = out.getvalue().encode("utf-8")
        from flask import Response
        return Response(
            csv_bytes,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=wing_strain_export.csv"},
        )

    return app


def run_dashboard(broker: str = "localhost", port: int = 1883,
                  host: str = "0.0.0.0", web_port: int = 5050) -> None:
    app = create_app(broker, port)
    print(f"[DASHBOARD] http://{host}:{web_port}")
    app.run(host=host, port=web_port, debug=False, use_reloader=False)
