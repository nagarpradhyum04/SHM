import json
import shutil
import socket
import subprocess
import time
from datetime import timedelta

import numpy as np
import pytest

from app.timeutil import utcnow

API = "/api/v1"


def _node(client, aid, did="NODE-1", source="real"):
    r = client.post(f"{API}/devices", json={"id": did, "device_type": "sensor_node", "name": "ESP32 node", "asset_id": aid,
                                            "component_id": f"{aid}-C1", "data_source": source, "sample_rate_hz": 100})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["device"]["capabilities"] == ["acceleration", "temperature", "humidity"]
    return body["ingestion_token"]


def _accel_payload(token, seq0=0, n=50, t0=None, **extra):
    t0 = t0 or utcnow() - timedelta(seconds=5)
    return {"token": token, "seq0": seq0, "t0_ms": t0.timestamp() * 1000, "rate_hz": 100, "ax": [0.0] * n, "ay": [0.0] * n,
            "az": [1.0 + 0.01 * np.sin(i) for i in range(n)], "temp_c": 30.5, "fw": "node-0.2.0", **extra}


def test_mqtt_handler_accel_env_status(client, make_asset):
    from app.db import get_database
    from app.services.mqtt_bridge import handle_message

    aid = make_asset()
    token = _node(client, aid)
    db = get_database().session()
    t0 = utcnow() - timedelta(seconds=10)
    r = handle_message(db, "bridge/NODE-1/accel", json.dumps(_accel_payload(token, t0=t0)).encode())
    assert r["outcome"] == "accepted" and r["detail"].startswith("50 accepted")
    rows = client.get(f"{API}/sensors/NODE-1/readings", params={"limit": 100}).json()
    assert len(rows) == 50 and rows[0]["source"] == "real" and rows[0]["quality"] == "ok"
    assert rows[1]["ts"] > rows[0]["ts"]  # timestamps advance by 1/rate
    # duplicates are rejected, bad token / unknown topic / simulated flag are refused
    assert handle_message(db, "bridge/NODE-1/accel", json.dumps(_accel_payload(token, t0=t0)).encode())["outcome"] == "rejected"
    assert "token" in handle_message(db, "bridge/NODE-1/accel", json.dumps(_accel_payload("bad", seq0=100)).encode())["detail"]
    assert "Unrecognised topic" in handle_message(db, "bridge/sensors", b'{"vib":0.01,"simulated":true}')["detail"]
    assert "simulated" in handle_message(db, "bridge/NODE-1/accel", json.dumps(_accel_payload(token, seq0=200, simulated=True)).encode())["detail"]
    assert "Invalid JSON" in handle_message(db, "bridge/NODE-1/env", b"{nope")["detail"]
    r = handle_message(db, "bridge/NODE-1/env", json.dumps({"token": token, "seq": 1, "t_ms": utcnow().timestamp() * 1000 - 1000,
                                                             "temp_c": 24.0, "rh": 60.0, "sensor": "DHT22"}).encode())
    assert r["outcome"] == "accepted"
    assert handle_message(db, "bridge/NODE-1/env", json.dumps({"token": token, "seq": 2, "temp_c": 24.0, "rh": 140}).encode())["outcome"] == "rejected"
    r = handle_message(db, "bridge/NODE-1/status", json.dumps({"token": token, "fw": "node-0.2.0", "rssi": -61, "mpu_ok": True}).encode())
    assert r["outcome"] == "accepted"
    db.close()
    dev = client.get(f"{API}/devices/NODE-1").json()
    assert dev["config"]["last_status"]["rssi"] == -61 and dev["firmware_version"] == "node-0.2.0"
    assert dev["connection"]["status"] == "online" and dev["connection"]["physically_connected"]
    env = client.get(f"{API}/sensors/NODE-1/environment").json()
    assert env["latest"]["temperature_c"] == 24.0 and env["latest"]["sensor_model"] == "DHT22"
    assert 15.5 < env["latest"]["dew_point_c"] < 16.5  # Magnus: 24 °C / 60 % RH ≈ 15.8 °C


def test_simulated_device_cannot_receive_mqtt_real_data(client, make_asset):
    from app.db import get_database
    from app.services.mqtt_bridge import handle_message

    aid = make_asset()
    _node(client, aid, "SIM-NODE", "simulated")
    db = get_database().session()
    r = handle_message(db, "bridge/SIM-NODE/accel", json.dumps(_accel_payload("x")).encode())
    assert r["outcome"] == "rejected"
    db.close()


def test_environment_thresholds_need_consecutive_samples(client, make_asset):
    aid = make_asset()
    token = _node(client, aid)
    client.put(f"{API}/settings/environment", json={"value": {"humidity_max_pct": 85, "consecutive_samples": 3}})
    h = {"X-Device-Token": token}
    now = utcnow()
    mk = lambda i, rh: {"seq": i, "ts": (now - timedelta(seconds=60 - i)).isoformat(), "temp_c": 20, "rh": rh}  # noqa: E731
    client.post(f"{API}/ingest/environment", json={"device_id": "NODE-1", "readings": [mk(1, 90), mk(2, 90), mk(3, 70)]}, headers=h)
    assert not client.get(f"{API}/alerts", params={"rule_type": "environment_threshold"}).json()
    r = client.post(f"{API}/ingest/environment", json={"device_id": "NODE-1", "readings": [mk(4, 91), mk(5, 92), mk(6, 93)]}, headers=h)
    assert r.json()["accepted"] == 3
    alerts = client.get(f"{API}/alerts", params={"rule_type": "environment_threshold"}).json()
    assert len(alerts) == 1 and "does not indicate a crack" in alerts[0]["message"]
    agg = client.get(f"{API}/sensors/NODE-1/environment", params={"bucket_s": 3600}).json()["series"]
    assert sum(b["n"] for b in agg) == 6 and agg[0]["rh_max"] == 93


def test_absolute_vibration_limit_without_baseline(db):
    from app.models import Alert, Asset, Device
    from app.services import alert_engine, vibration
    from app.services.ingestion import ingest
    from app.services.settings_store import get_setting, set_setting

    db.add(Asset(id="A", name="a"))
    dev = Device(id="N", device_type="sensor_node", name="n", asset_id="A", sample_rate_hz=10, data_source="real")
    db.add(dev)
    db.flush()
    set_setting(db, "vibration", {**get_setting(db, "vibration"), "abs_rms_dyn_limit_g": 0.02})
    start = (utcnow() - timedelta(minutes=5)).replace(second=0, microsecond=0)
    readings = []
    for w, amp in enumerate((0.005, 0.08)):
        for i in range(600):
            k = w * 600 + i
            readings.append({"seq": k, "ts": (start + timedelta(seconds=k / 10)).isoformat(), "ax": 0, "ay": 0,
                             "az": 1 + amp * np.sin(2 * np.pi * 1.3 * k / 10)})
    ingest(db, dev, readings, "real")
    feats = vibration.process_device(db, dev, "real", start + timedelta(minutes=2), on_anomaly=alert_engine.on_feature_anomaly)
    assert feats[0].anomaly is False and feats[0].anomaly_reasons == ["not_evaluated:no_baseline"]
    assert feats[1].anomaly and feats[1].anomaly_reasons == ["rms_dyn_above_absolute_limit"]
    rules = [a.rule_type for a in db.query(Alert).all()]
    assert rules == ["vibration_threshold"]


@pytest.mark.skipif(shutil.which("mosquitto") is None, reason="mosquitto broker not installed")
def test_mqtt_end_to_end_with_real_broker(env, monkeypatch):
    """Publishes through a real Mosquitto broker into the running backend's MQTT bridge."""
    import paho.mqtt.client as mqtt
    from fastapi.testclient import TestClient

    from app.config import get_settings

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    conf = env / "mosq.conf"
    conf.write_text(f"listener {port} 127.0.0.1\nallow_anonymous true\n")
    broker = subprocess.Popen(["mosquitto", "-c", str(conf)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(0.5)
        s = get_settings()
        monkeypatch.setattr(s, "mqtt_enabled", True)
        monkeypatch.setattr(s, "mqtt_port", port)
        from app.main import create_app

        with TestClient(create_app()) as client:
            client.post(f"{API}/assets", json={"id": "MQ", "name": "m"})
            client.post(f"{API}/assets/MQ/components", json={"id": "MQ-C1", "name": "c", "component_type": "deck_segment"})
            token = _node(client, "MQ")
            for _ in range(50):
                if client.get(f"{API}/mqtt/status").json()["state"] == "connected":
                    break
                time.sleep(0.1)
            pub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            pub.connect("127.0.0.1", port)
            pub.loop_start()
            pub.publish("bridge/NODE-1/accel", json.dumps(_accel_payload(token, n=100)), qos=1).wait_for_publish()
            pub.publish("bridge/NODE-1/env", json.dumps({"token": token, "temp_c": 22.5, "rh": 55}), qos=1).wait_for_publish()
            for _ in range(50):
                if client.get(f"{API}/mqtt/status").json()["counts"]["accepted"] >= 2:
                    break
                time.sleep(0.1)
            pub.loop_stop()
            st = client.get(f"{API}/mqtt/status").json()
            assert st["state"] == "connected" and st["counts"]["accepted"] >= 2, st
            assert len(client.get(f"{API}/sensors/NODE-1/readings", params={"limit": 500}).json()) == 100
            assert client.get(f"{API}/sensors/NODE-1/environment").json()["latest"]["humidity_pct"] == 55
    finally:
        broker.terminate()
        broker.wait(5)
        from app.services.mqtt_bridge import diagnostics

        diagnostics.counts.update({"received": 0, "accepted": 0, "rejected": 0})
