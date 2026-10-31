"""MQTT connection check: reproduces the Windows 'two brokers' and 'localhost-only' situations with real Mosquitto brokers."""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

from app.services.mqtt_diag import diagnose, local_ipv4

pytestmark = pytest.mark.skipif(shutil.which("mosquitto") is None or not local_ipv4(), reason="needs mosquitto and a non-loopback IPv4")
LAN = local_ipv4()[0] if local_ipv4() else None


def _port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _broker(tmp: Path, name: str, listen: str, port: int) -> subprocess.Popen:
    conf = tmp / f"{name}.conf"
    conf.write_text(f"listener {port} {listen}\nallow_anonymous true\n")
    p = subprocess.Popen(["mosquitto", "-c", str(conf)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            socket.create_connection((listen if listen != "0.0.0.0" else "127.0.0.1", port), timeout=0.2).close()
            return p
        except OSError:
            time.sleep(0.1)
    p.terminate()
    pytest.fail(f"broker {name} did not start")


class _Esp32:
    """Publishes the user's summary payload to bridge/sensors every 0.3 s."""

    def __init__(self, host: str, port: int, topic: str = "bridge/sensors"):
        import paho.mqtt.client as mqtt

        self.c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="esp32-sim")
        self.c.connect(host, port)
        self.c.loop_start()
        self.stop = threading.Event()
        self.t = threading.Thread(target=self._run, args=(topic,), daemon=True)
        self.t.start()

    def _run(self, topic):
        while not self.stop.is_set():
            self.c.publish(topic, json.dumps({"vib": 0.005, "peak": 0.01, "level": "CALM", "tilt": 29.4, "temp": 29.5, "hum": 51,
                                              "mpu": True, "dht": True, "simulated": False}))
            time.sleep(0.3)

    def close(self):
        self.stop.set()
        self.t.join()
        self.c.loop_stop()
        self.c.disconnect()


def test_two_brokers_points_to_the_one_with_the_device(tmp_path):
    port = _port()
    service = _broker(tmp_path, "service", "127.0.0.1", port)   # Windows Mosquitto service: localhost only
    own = _broker(tmp_path, "own", LAN, port)                   # broker the user started for the ESP32
    esp = _Esp32(LAN, port)
    try:
        r = diagnose("127.0.0.1", port, "bridge", listen_s=1.5)
    finally:
        esp.close()
        service.terminate()
        own.terminate()
    assert r["status"] == "other_broker", r
    assert r["suggest_host"] == LAN
    lan = next(b for b in r["brokers"] if b["host"] == LAN)
    assert lan["topics"][0]["topic"] == "bridge/sensors" and '"vib"' in lan["topics"][0]["sample"]
    assert next(b for b in r["brokers"] if b["host"] == "127.0.0.1")["same_broker_as"] == []


def test_localhost_only_broker(tmp_path):
    port = _port()
    service = _broker(tmp_path, "service", "127.0.0.1", port)
    try:
        r = diagnose("127.0.0.1", port, "bridge", listen_s=1)
    finally:
        service.terminate()
    assert r["status"] == "localhost_only", r
    assert "0.0.0.0" in r["fix"]


def test_network_broker_same_as_backend(tmp_path):
    port = _port()
    b = _broker(tmp_path, "net", "0.0.0.0", port)
    try:
        silent = diagnose("127.0.0.1", port, "bridge", listen_s=1)
        esp = _Esp32(LAN, port)
        try:
            ok = diagnose("127.0.0.1", port, "bridge", listen_s=1.5)
        finally:
            esp.close()
        esp = _Esp32(LAN, port, topic="sensors")
        try:
            wrong = diagnose("127.0.0.1", port, "bridge", listen_s=1.5)
        finally:
            esp.close()
    finally:
        b.terminate()
    assert silent["status"] == "silent", silent
    assert LAN in next(x for x in silent["brokers"] if x["host"] == "127.0.0.1")["same_broker_as"]
    assert ok["status"] == "ok", ok
    assert wrong["status"] == "wrong_topic" and "bridge/" in wrong["fix"]


def test_no_broker():
    r = diagnose("127.0.0.1", _port(), "bridge", listen_s=1)
    assert r["status"] == "no_broker"


def test_use_broker_endpoint_switches_and_persists(client):
    r = client.put("/api/v1/mqtt/broker", json={"host": "192.0.2.77"})
    assert r.status_code == 200 and r.json()["host"] == "192.0.2.77"
    assert client.get("/api/v1/mqtt/status").json()["broker"].startswith("192.0.2.77:")
    assert client.put("/api/v1/mqtt/broker", json={"host": "bad host!"}).status_code == 422
    r = client.put("/api/v1/mqtt/broker", json={"host": None})
    assert r.json()["host_overridden"] is False
