import math
from datetime import timedelta

import numpy as np
import pytest

from app.timeutil import utcnow

API = "/api/v1"


def _register(client, aid, did="ACC-R1", source="real", rate=10):
    r = client.post(f"{API}/devices", json={"id": did, "device_type": "accelerometer", "name": did, "asset_id": aid,
                                            "component_id": f"{aid}-C1", "data_source": source, "sample_rate_hz": rate})
    assert r.status_code == 201, r.text
    return r.json()["ingestion_token"]


def _readings(n, start, seq0=0, rate=10, amp=0.01):
    return [{"seq": seq0 + i, "ts": (start + timedelta(seconds=i / rate)).isoformat(), "ax": 0.0, "ay": 0.0,
             "az": 1.0 + amp * math.sin(2 * math.pi * 1.0 * i / rate)} for i in range(n)]


def test_ingestion_auth_and_validation(client, make_asset):
    aid = make_asset()
    token = _register(client, aid)
    body = {"device_id": "ACC-R1", "readings": _readings(20, utcnow() - timedelta(seconds=30))}
    assert client.post(f"{API}/ingest/readings", json=body).status_code == 401
    assert client.post(f"{API}/ingest/readings", json=body, headers={"X-Device-Token": "wrong"}).status_code == 401
    r = client.post(f"{API}/ingest/readings", json=body, headers={"X-Device-Token": token}).json()
    assert r["accepted"] == 20 and r["source"] == "real"
    # duplicate sequences rejected; malformed / out-of-range rejected with reasons
    bad = body["readings"][:5] + [{"seq": 100, "ax": "x", "ay": 0, "az": 1}, {"seq": 101, "ax": 50, "ay": 0, "az": 1},
                                   {"seq": 102, "ts": (utcnow() + timedelta(days=1)).isoformat(), "ax": 0, "ay": 0, "az": 1},
                                   {"seq": 103, "ax": 0, "ay": 0, "az": 1}]
    r = client.post(f"{API}/ingest/readings", json={"device_id": "ACC-R1", "readings": bad}, headers={"X-Device-Token": token}).json()
    assert r["accepted"] == 1 and r["duplicates"] == 5 and len(r["errors"]) == 4
    latest = client.get(f"{API}/sensors/ACC-R1/latest").json()
    assert latest["reading"]["seq"] == 103 and latest["reading"]["quality"] == "suspect"  # server-substituted timestamp
    assert client.get(f"{API}/alerts", params={"rule_type": "data_validation_failure"}).json()
    assert client.post(f"{API}/ingest/readings", json={"device_id": "ACC-R1", "readings": []}, headers={"X-Device-Token": token}).status_code == 422


def test_token_rotation(client, make_asset):
    aid = make_asset()
    old = _register(client, aid)
    new = client.post(f"{API}/devices/ACC-R1/rotate-token").json()["ingestion_token"]
    body = {"device_id": "ACC-R1", "readings": _readings(2, utcnow())}
    assert client.post(f"{API}/ingest/readings", json=body, headers={"X-Device-Token": old}).status_code == 401
    assert client.post(f"{API}/ingest/readings", json=body, headers={"X-Device-Token": new}).status_code == 202


def test_simulated_and_real_never_mix(client, make_asset):
    aid = make_asset()
    token = _register(client, aid, "ACC-SIM", "simulated")
    assert token is None
    r = client.post(f"{API}/ingest/readings", json={"device_id": "ACC-SIM", "readings": _readings(2, utcnow())},
                    headers={"X-Device-Token": "anything"})
    assert r.status_code == 401  # simulated devices have no token
    gen = client.post(f"{API}/simulation/generate", json={"device_id": "ACC-SIM", "minutes": 2}).json()
    assert gen["source"] == "simulated" and gen["generated"] > 0
    rows = client.get(f"{API}/sensors/ACC-SIM/readings", params={"limit": 50}).json()
    assert rows and all(r["source"] == "simulated" for r in rows)
    st = client.get(f"{API}/devices/ACC-SIM/status").json()
    assert st["is_simulated"] and not st["physically_connected"] and st["status"].startswith("simulated")
    # real device cannot be simulated
    _register(client, aid, "ACC-REAL")
    assert client.post(f"{API}/simulation/generate", json={"device_id": "ACC-REAL", "minutes": 1}).status_code == 400
    assert client.get(f"{API}/sensors/ACC-SIM/readings", params={"source": "real"}).json() == []


def test_ingest_into_simulated_device_rejected_at_service_level(db):
    from app.models import Asset, Device
    from app.services.ingestion import ingest

    db.add(Asset(id="A", name="a"))
    dev = Device(id="S", device_type="accelerometer", name="s", asset_id="A", data_source="simulated")
    db.add(dev)
    db.flush()
    with pytest.raises(ValueError):
        ingest(db, dev, [{"seq": 1, "ax": 0, "ay": 0, "az": 1}], "real")
    with pytest.raises(ValueError):
        ingest(db, dev, [{"seq": 1, "ax": 0, "ay": 0, "az": 1}], "simulated")


def test_csv_upload_is_labelled_uploaded(client, make_asset):
    aid = make_asset()
    _register(client, aid)
    t = utcnow() - timedelta(hours=1)
    csv = "seq,ts,ax,ay,az\n" + "\n".join(f"{i},{(t + timedelta(seconds=i / 10)).isoformat()},0,0,1.0" for i in range(30))
    r = client.post(f"{API}/sensors/ACC-R1/upload", files={"file": ("h.csv", csv.encode(), "text/csv")}).json()
    assert r["accepted"] == 30 and r["source"] == "uploaded"
    assert client.post(f"{API}/sensors/ACC-R1/upload", files={"file": ("h.csv", b"a,b\n1,2", "text/csv")}).status_code == 400
    latest = client.get(f"{API}/sensors/ACC-R1/latest").json()
    assert latest["data_source"] == "uploaded"
    # uploaded history does not mark the device as seen/connected
    assert client.get(f"{API}/devices/ACC-R1/status").json()["status"] == "never_connected"


def test_stale_and_offline_status(db):
    from app.models import Asset, Device
    from app.services.alert_engine import evaluate_device_status
    from app.services.device_status import connection_status
    from app.models import Alert

    db.add(Asset(id="A", name="a"))
    now = utcnow()
    devs = {
        "fresh": Device(id="fresh", device_type="accelerometer", name="f", asset_id="A", last_seen_at=now - timedelta(seconds=10)),
        "stale": Device(id="stale", device_type="accelerometer", name="s", asset_id="A", last_seen_at=now - timedelta(seconds=300)),
        "off": Device(id="off", device_type="accelerometer", name="o", asset_id="A", last_seen_at=now - timedelta(hours=2)),
        "never": Device(id="never", device_type="accelerometer", name="n", asset_id="A"),
        "sim": Device(id="sim", device_type="accelerometer", name="x", asset_id="A", data_source="simulated", last_seen_at=now - timedelta(hours=2)),
    }
    db.add_all(devs.values())
    db.flush()
    got = {k: connection_status(db, d, now)["status"] for k, d in devs.items()}
    assert got == {"fresh": "online", "stale": "stale", "off": "offline", "never": "never_connected", "sim": "simulated_idle"}
    evaluate_device_status(db, now)
    rules = {(a.device_id, a.rule_type) for a in db.query(Alert).all()}
    assert rules == {("stale", "stale_data"), ("off", "sensor_offline")}  # nothing for simulated/never-connected
    evaluate_device_status(db, now)
    assert db.query(Alert).count() == 2  # deduplicated


def test_feature_calculations_known_signal():
    from app.services.vibration import compute_features

    n, rate, amp = 600, 10, 0.02
    t = np.arange(n) / rate
    az = 1.0 + amp * np.sin(2 * np.pi * 2.5 * t)  # 2.5 Hz at 10 Hz sampling hits the peaks exactly
    f = compute_features(np.zeros(n), np.zeros(n), az, np.arange(n))
    assert f["sample_count"] == 600 and f["duplicate_count"] == 0 and f["gap_count"] == 0
    assert f["mean_z"] == pytest.approx(1.0, abs=1e-6)
    assert f["rms_dyn"] == pytest.approx(amp / math.sqrt(2), rel=1e-3)
    assert f["peak_dyn"] == pytest.approx(amp, rel=1e-3)
    assert f["std_z"] == pytest.approx(amp / math.sqrt(2), rel=1e-3)
    assert f["rms_z"] == pytest.approx(math.sqrt(1 + amp ** 2 / 2), rel=1e-6)
    seqs = list(range(300)) + list(range(298, 400)) + list(range(420, 618))  # 2 duplicates, one gap
    g = compute_features(np.zeros(600), np.zeros(600), az, seqs)
    assert g["duplicate_count"] == 2 and g["gap_count"] == 1


def test_missing_data_window_not_evaluated_and_baseline_anomaly(db):
    from app.models import Asset, Device, VibrationFeature
    from app.services import vibration
    from app.services.ingestion import ingest

    db.add(Asset(id="A", name="a"))
    dev = Device(id="D", device_type="accelerometer", name="d", asset_id="A", sample_rate_hz=10, data_source="real")
    db.add(dev)
    db.flush()
    start = (utcnow() - timedelta(minutes=30)).replace(second=0, microsecond=0)
    rng = np.random.default_rng(0)
    readings = []
    for w in range(14):
        n = 600 if w != 3 else 200  # window 3 is incomplete (missing data)
        amp = 0.01 if w < 12 else 0.08  # last two windows are much stronger
        for i in range(n):
            k = w * 600 + i
            readings.append({"seq": k, "ts": (start + timedelta(seconds=k / 10)).isoformat(), "ax": 0, "ay": 0,
                             "az": 1 + amp * math.sin(2 * math.pi * 1.3 * k / 10) + rng.normal(0, 0.001)})
    for i in range(0, len(readings), 2000):
        ingest(db, dev, readings[i : i + 2000], "real")
    feats = vibration.process_device(db, dev, "real", start + timedelta(minutes=12))
    assert len(feats) == 12
    w3 = feats[3]
    assert w3.data_quality == "incomplete" and w3.missing_ratio == pytest.approx(2 / 3, abs=0.01)
    assert w3.anomaly_reasons == ["not_evaluated:incomplete_window"]
    assert feats[0].anomaly_reasons == ["not_evaluated:no_baseline"]
    b = vibration.create_baseline(db, dev, "real", start, start + timedelta(minutes=12))
    assert b.version == 1 and b.n_windows == 11  # incomplete window excluded
    later = vibration.process_device(db, dev, "real", start + timedelta(minutes=14))
    assert len(later) == 2 and all(f.anomaly for f in later)
    assert later[0].baseline_id == b.id and later[0].thresholds["rule_version"] == "vib-anomaly-v1"
    assert later[0].feature_version == "vib-features-v1" and later[0].baseline_ratio > 4
    with pytest.raises(ValueError):
        vibration.create_baseline(db, dev, "simulated", start, start + timedelta(minutes=12))
    assert db.query(VibrationFeature).count() == 14
