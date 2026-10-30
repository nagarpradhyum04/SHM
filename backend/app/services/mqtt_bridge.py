"""MQTT → ingestion bridge for ESP32 sensor nodes.

Topics (prefix configurable, default ``bridge``):

* ``<prefix>/<device_id>/accel``  – batch of MPU6050 samples
    {"token": "...", "seq0": 1200, "t0_ms": 1761700000123, "rate_hz": 100,
     "ax": [...], "ay": [...], "az": [...], "gx": [...], "gy": [...], "gz": [...],   # g, deg/s
     "temp_c": 31.2, "fw": "node-0.2.0"}
  ``t0_ms`` is the UTC epoch time of sample 0 (from NTP); sample i is at t0 + i/rate.
  The HTTP shape {"token": ..., "readings": [{seq, ts, ax, ay, az, ...}]} is also accepted.
* ``<prefix>/<device_id>/env``    – {"token", "seq", "t_ms", "temp_c", "rh", "sensor": "DHT22"}
* ``<prefix>/<device_id>/status`` – {"token", "fw", "rssi", "uptime_s", "ip", "mpu_ok", "env_ok"}

Every message is authenticated with the per-device ingestion token (same as the HTTP API) and
validated by the same ingestion code, so MQTT and HTTP data are indistinguishable downstream
(source = "real"). Payloads flagged ``"simulated": true`` are refused: simulated data is never
stored as real. Messages that cannot be used are kept in a small diagnostics buffer shown in
Settings so wiring/firmware problems are visible.
"""
from __future__ import annotations

import json
import logging
import threading
from collections import deque
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Device
from app.services import environment, ingestion
from app.services.events import broadcaster
from app.timeutil import utcnow

log = logging.getLogger(__name__)
MAX_SAMPLES = 2000


class Diagnostics:
    def __init__(self, size: int = 60):
        self.messages: deque = deque(maxlen=size)
        self.counts = {"received": 0, "accepted": 0, "rejected": 0}
        self.lock = threading.Lock()

    def record(self, topic: str, size: int, outcome: str, detail: str, device_id: str | None = None):
        with self.lock:
            self.counts["received"] += 1
            self.counts["accepted" if outcome == "accepted" else "rejected"] += 1
            self.messages.appendleft({"ts": utcnow().isoformat(), "topic": topic, "bytes": size, "device_id": device_id,
                                      "outcome": outcome, "detail": detail[:300]})

    def snapshot(self) -> dict:
        with self.lock:
            return {"counts": dict(self.counts), "recent": list(self.messages)}


diagnostics = Diagnostics()


def _accel_readings(p: dict) -> list[dict]:
    if isinstance(p.get("readings"), list):
        return p["readings"]
    ax, ay, az = p.get("ax"), p.get("ay"), p.get("az")
    if not (isinstance(ax, list) and isinstance(ay, list) and isinstance(az, list)) or not (len(ax) == len(ay) == len(az)):
        raise ValueError("accel payload needs equal-length arrays ax, ay, az (or a 'readings' list)")
    if len(ax) > MAX_SAMPLES:
        raise ValueError(f"too many samples in one message (max {MAX_SAMPLES})")
    seq0 = p.get("seq0")
    if seq0 is None:
        raise ValueError("accel payload needs seq0 (sequence number of the first sample)")
    rate = float(p.get("rate_hz") or 0)
    t0 = p.get("t0_ms")
    if t0 is not None and rate <= 0:
        raise ValueError("rate_hz must be > 0 when t0_ms is given")
    g = {k: p.get(k) if isinstance(p.get(k), list) and len(p.get(k)) == len(ax) else None for k in ("gx", "gy", "gz")}
    out = []
    for i in range(len(ax)):
        r = {"seq": int(seq0) + i, "ax": ax[i], "ay": ay[i], "az": az[i]}
        if t0 is not None:
            r["ts"] = datetime.fromtimestamp(float(t0) / 1000.0 + i / rate, tz=timezone.utc)
        for k, arr in g.items():
            if arr is not None:
                r[k] = arr[i]
        if p.get("temp_c") is not None:
            r["temperature_c"] = p["temp_c"]
        out.append(r)
    return out


def handle_message(db: Session, topic: str, raw: bytes, prefix: str | None = None) -> dict:
    """Process one MQTT message. Returns {"outcome": accepted|rejected, "detail", "device_id"}. Commits on success."""
    prefix = (prefix or get_settings().mqtt_topic_prefix).strip("/")
    parts = topic.strip("/").split("/")
    if len(parts) != 3 or parts[0] != prefix or parts[2] not in ("accel", "env", "status"):
        return {"outcome": "rejected", "device_id": None,
                "detail": f"Unrecognised topic. Expected {prefix}/<device_id>/accel|env|status (see docs/hardware-integration.md)."}
    device_id, kind = parts[1], parts[2]
    try:
        p = json.loads(raw.decode("utf-8"))
        if not isinstance(p, dict):
            raise ValueError("payload must be a JSON object")
    except (UnicodeDecodeError, ValueError) as exc:
        return {"outcome": "rejected", "device_id": device_id, "detail": f"Invalid JSON: {exc}"}
    dev = db.get(Device, device_id)
    if dev is None or not ingestion.authenticate(dev, p.get("token")):
        return {"outcome": "rejected", "device_id": device_id, "detail": "Unknown device or invalid token (register the device and copy its token into the firmware)."}
    if p.get("simulated") is True:
        return {"outcome": "rejected", "device_id": device_id, "detail": "Payload is flagged simulated; simulated values are never stored as real data."}
    if dev.operational_status == "decommissioned":
        return {"outcome": "rejected", "device_id": device_id, "detail": "Device is decommissioned."}
    try:
        if kind == "status":
            cfg = dict(dev.config or {})
            cfg["last_status"] = {k: p.get(k) for k in ("fw", "rssi", "uptime_s", "ip", "mpu_ok", "env_ok", "free_heap") if k in p}
            cfg["last_status"]["received_at"] = utcnow().isoformat()
            cfg["transport"] = "mqtt"
            dev.config = cfg
            if p.get("fw"):
                dev.firmware_version = str(p["fw"])[:60]
            db.commit()
            broadcaster.publish("devices", {"asset_id": dev.asset_id})
            return {"outcome": "accepted", "device_id": device_id, "detail": "status updated"}
        if dev.device_type == "camera":
            raise ValueError("camera devices do not publish sensor readings")
        if kind == "accel":
            res = ingestion.ingest(db, dev, _accel_readings(p), "real")
        else:
            res = environment.ingest(db, dev, [p], "real")
        if p.get("fw"):
            dev.firmware_version = str(p["fw"])[:60]
        db.commit()
    except ValueError as exc:
        db.rollback()
        return {"outcome": "rejected", "device_id": device_id, "detail": str(exc)}
    detail = f"{res['accepted']} accepted, {res['rejected']} rejected" + (f": {'; '.join(res['errors'][:3])}" if res["errors"] else "")
    return {"outcome": "accepted" if res["accepted"] else "rejected", "device_id": device_id, "detail": detail}


class MqttBridge:
    def __init__(self):
        self.client = None
        self.state = "disabled"
        self.last_error: str | None = None
        self.connected_since: datetime | None = None

    def start(self) -> None:
        s = get_settings()
        if not s.mqtt_enabled:
            self.state = "disabled"
            return
        import paho.mqtt.client as mqtt

        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=s.mqtt_client_id, clean_session=True)
        if s.mqtt_username:
            c.username_pw_set(s.mqtt_username, s.mqtt_password)
        c.reconnect_delay_set(min_delay=1, max_delay=30)
        c.on_connect = self._on_connect
        c.on_disconnect = self._on_disconnect
        c.on_message = self._on_message
        self.client = c
        self.state = "connecting"
        try:
            c.connect_async(s.mqtt_host, s.mqtt_port, keepalive=30)
            c.loop_start()
        except Exception as exc:  # noqa: BLE001
            self.state, self.last_error = "error", str(exc)

    def stop(self) -> None:
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            self.state, self.last_error = "error", f"broker refused connection: {reason_code}"
            return
        prefix = get_settings().mqtt_topic_prefix.strip("/")
        client.subscribe(f"{prefix}/#", qos=0)
        self.state, self.last_error, self.connected_since = "connected", None, utcnow()
        log.info("MQTT connected, subscribed to %s/#", prefix)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.state = "reconnecting"
        self.last_error = f"disconnected: {reason_code}"

    def _on_message(self, client, userdata, msg):
        from app.db import get_database

        db = get_database().session()
        try:
            r = handle_message(db, msg.topic, msg.payload)
        except Exception as exc:  # noqa: BLE001 - keep the network thread alive
            db.rollback()
            log.exception("MQTT message handling failed")
            r = {"outcome": "rejected", "device_id": None, "detail": f"server error: {exc}"}
        finally:
            db.close()
        diagnostics.record(msg.topic, len(msg.payload), r["outcome"], r["detail"], r.get("device_id"))

    def status(self) -> dict:
        s = get_settings()
        return {"enabled": s.mqtt_enabled, "state": self.state, "broker": f"{s.mqtt_host}:{s.mqtt_port}",
                "topic": f"{s.mqtt_topic_prefix.strip('/')}/<device_id>/accel|env|status", "last_error": self.last_error,
                "connected_since": self.connected_since.isoformat() if self.connected_since else None,
                "auth": "username/password" if s.mqtt_username else "anonymous broker (protect it on shared networks)",
                **diagnostics.snapshot()}


bridge = MqttBridge()

__all__ = ["bridge", "handle_message", "diagnostics"]
