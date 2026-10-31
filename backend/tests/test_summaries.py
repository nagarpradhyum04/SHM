"""Device-computed summaries, using payloads copied from a real ESP32 + MPU6050 + DHT11 serial log."""
import json
from datetime import timedelta

import pytest

from app.timeutil import utcnow

API = "/api/v1"
CALM = {"vib": 0.0055, "peak": 0.0124, "level": "CALM", "tilt": 29.42, "temp": 29.5, "hum": 51.0, "mpu": True, "dht": True, "simulated": False}
SEVERE = {"vib": 0.3428, "peak": 0.9771, "level": "SEVERE", "tilt": 24.52, "temp": 29.5, "hum": 51.0, "mpu": True, "dht": True, "simulated": False}


def _node(client, topic="bridge/sensors", token_required=False):
    client.post(f"{API}/assets", json={"id": "SB", "name": "Smart bridge"})
    client.post(f"{API}/assets/SB/components", json={"id": "SB-DECK", "name": "Deck", "component_type": "deck_segment"})
    r = client.post(f"{API}/devices", json={"id": "NODE-01", "device_type": "sensor_node", "name": "ESP32", "asset_id": "SB", "component_id": "SB-DECK"})
    token = r.json()["ingestion_token"]
    r = client.patch(f"{API}/devices/NODE-01", json={"config": {"mqtt_topic": topic, "mqtt_token_required": token_required, "env_sensor": "DHT11"}})
    assert r.status_code == 200, r.text
    return token


def _handle(topic, payload):
    from app.db import get_database
    from app.services.mqtt_bridge import handle_message

    db = get_database().session()
    try:
        return handle_message(db, topic, json.dumps(payload).encode())
    finally:
        db.close()


def test_user_firmware_payload_on_bound_topic(client):
    assert "bind this topic" in _handle("bridge/sensors", CALM)["detail"]  # not bound yet → explained
    _node(client)
    t0 = utcnow() - timedelta(seconds=10)
    for i in range(6):  # 3 s of 0.5 s summaries with device timestamps
        r = _handle("bridge/sensors", {**CALM, "t_ms": (t0 + timedelta(seconds=0.5 * i)).timestamp() * 1000})
        assert r["outcome"] == "accepted", r
    s = client.get(f"{API}/sensors/NODE-01/summaries").json()
    assert len(s) == 6 and s[-1]["vib_rms_g"] == 0.0055 and s[-1]["tilt_deg"] == 29.42 and s[-1]["device_level"] == "CALM"
    env = client.get(f"{API}/sensors/NODE-01/environment").json()
    assert len(env["series"]) == 2 and env["latest"]["sensor_model"] == "DHT11"  # DHT stored at most every 2 s
    dev = client.get(f"{API}/devices/NODE-01").json()
    assert dev["connection"]["status"] == "online" and dev["config"]["last_status"]["format"] == "summary"
    assert "simulated" in _handle("bridge/sensors", {**CALM, "simulated": True})["detail"]
    assert "outside" in _handle("bridge/sensors", {**CALM, "vib": -1})["detail"]


def test_bound_topic_can_require_a_token(client):
    token = _node(client, token_required=True)
    assert _handle("bridge/sensors", CALM)["outcome"] == "rejected"
    assert _handle("bridge/sensors", {**CALM, "token": token})["outcome"] == "accepted"
    assert _handle("bridge/NODE-01/summary", {**CALM, "token": token})["outcome"] == "accepted"
    assert _handle("bridge/NODE-01/summary", CALM)["outcome"] == "rejected"  # device topic always needs the token
    # a topic can only be bound to one device
    client.post(f"{API}/devices", json={"id": "NODE-02", "device_type": "sensor_node", "name": "x", "asset_id": "SB"})
    assert client.patch(f"{API}/devices/NODE-02", json={"config": {"mqtt_topic": "bridge/sensors"}}).status_code == 409


def test_windows_limits_and_tilt_from_summaries(client):
    _node(client)
    client.put(f"{API}/settings/vibration", json={"value": {"abs_rms_dyn_limit_g": 0.03, "tilt_change_limit_deg": 2.0}})
    start = (utcnow() - timedelta(minutes=4)).replace(second=0, microsecond=0)
    for w, payload in enumerate([CALM, CALM, SEVERE]):
        for i in range(120):
            _handle("bridge/sensors", {**payload, "t_ms": (start + timedelta(seconds=60 * w + 0.5 * i)).timestamp() * 1000})
    from app.db import get_database
    from app.models import Device
    from app.services import summaries

    db = get_database().session()
    feats = summaries.process_device(db, db.get(Device, "NODE-01"), "real", start + timedelta(minutes=3))
    db.commit()
    db.close()
    assert len(feats) == 3 and all(f.feature_version == "vib-summary-v1" for f in feats)
    assert feats[0].rms_dyn == pytest.approx(0.0055) and feats[0].sample_count == 120 and feats[0].data_quality == "ok"
    assert feats[2].rms_dyn == pytest.approx(0.3428) and feats[2].peak_dyn == pytest.approx(0.9771)
    alerts = {a["rule_type"]: a for a in client.get(f"{API}/alerts", params={"asset_id": "SB"}).json()}
    assert "vibration_threshold" in alerts and "tilt_change" in alerts
    assert "29.42" in alerts["tilt_change"]["message"] and "mount" in alerts["tilt_change"]["message"]
    f = client.get(f"{API}/sensors/NODE-01/features").json()
    assert f[-1]["tilt_mean_deg"] == pytest.approx(24.52) and f[-1]["mean_x"] is None
    r = client.post(f"{API}/devices/NODE-01/tilt-reference", params={"value": 24.5}).json()
    assert r["tilt_reference_deg"] == 24.5


def test_fatigue_explains_summary_only_sensor(client):
    _node(client)
    _handle("bridge/sensors", CALM)
    client.put(f"{API}/rul/config/SB-DECK", json={"value": {"stress_per_g_mpa": 500, "detail_category_mpa": 71}})
    r = client.post(f"{API}/rul/estimate", json={"asset_id": "SB", "component_id": "SB-DECK"}).json()
    assert r["status"] == "unavailable" and "summaries" in r["message"] and "raw" in r["message"]
