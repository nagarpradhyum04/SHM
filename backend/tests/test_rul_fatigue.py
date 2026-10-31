import math
from collections import Counter
from datetime import timedelta

import numpy as np
import pytest

from app.services.fatigue import SECONDS_PER_YEAR, rainflow, reversals, sn_cycles_to_failure
from app.timeutil import utcnow

API = "/api/v1"


def test_rainflow_matches_astm_e1049_example():
    # ASTM E1049-85 Fig. 6 example: expected ranges 3:0.5, 4:1.5, 6:0.5, 8:1.0, 9:0.5
    cycles = rainflow([-2, 1, -3, 5, -1, 3, -4, 4, -2])
    got = Counter()
    for r, n in cycles:
        got[r] += n
    assert dict(got) == {3: 0.5, 4: 1.5, 6: 0.5, 8: 1.0, 9: 0.5}


def test_reversals_with_noise_gate():
    x = [0, 0.001, 0, 1, 0.999, 1.0005, -1, -0.9995, 0.5]
    assert list(reversals(x, gate=0.01)) == [0, 1.0005, -1, 0.5]


def test_en1993_sn_curve():
    assert sn_cycles_to_failure(80, 80) == pytest.approx(2e6)
    d = (2 / 5) ** (1 / 3) * 80
    assert sn_cycles_to_failure(d, 80) == pytest.approx(5e6, rel=1e-6)
    assert sn_cycles_to_failure((5 / 100) ** (1 / 5) * d * 0.99, 80) == math.inf  # below cut-off
    assert sn_cycles_to_failure(100, 80, gamma=1.35) < sn_cycles_to_failure(100, 80)


def _node_with_sine(client, source="real", amp=0.05, freq=2.0, minutes=12):
    client.post(f"{API}/assets", json={"id": "FAT", "name": "fatigue"})
    client.post(f"{API}/assets/FAT/components", json={"id": "FAT-G1", "name": "Girder 1", "component_type": "girder"})
    r = client.post(f"{API}/devices", json={"id": "N1", "device_type": "sensor_node", "name": "n", "asset_id": "FAT", "component_id": "FAT-G1",
                                            "data_source": source, "sample_rate_hz": 100})
    token = r.json()["ingestion_token"]
    start = utcnow() - timedelta(minutes=minutes + 1)
    n = minutes * 60 * 100
    t = np.arange(n) / 100
    az = 1 + amp * np.sin(2 * np.pi * freq * t)
    if source == "real":
        for i in range(0, n, 2000):
            rows = [{"seq": int(k), "ts": (start + timedelta(seconds=float(t[k]))).isoformat(), "ax": 0, "ay": 0, "az": float(az[k])}
                    for k in range(i, min(i + 2000, n))]
            assert client.post(f"{API}/ingest/readings", json={"device_id": "N1", "readings": rows}, headers={"X-Device-Token": token}).status_code == 202
    return n / 100, freq


def test_fatigue_estimate_matches_hand_calculation(client):
    duration, freq = _node_with_sine(client)
    # missing inputs → explicit unavailable state
    r = client.post(f"{API}/rul/estimate", json={"asset_id": "FAT", "component_id": "FAT-G1"}).json()
    assert r["status"] == "unavailable" and r["estimate"] is None and "stress-per-g" in r["message"]
    assert client.put(f"{API}/rul/config/FAT-G1", json={"value": {"axis": "w"}}).status_code == 422
    cfg = {"stress_per_g_mpa": 1000, "detail_category_mpa": 80, "gamma_mf": 1.0, "factor_uncertainty_pct": 10, "factor_source": "test"}
    assert client.put(f"{API}/rul/config/FAT-G1", json={"value": cfg}).status_code == 200
    r = client.post(f"{API}/rul/estimate", json={"asset_id": "FAT", "component_id": "FAT-G1"}).json()
    assert r["status"] == "estimated" and r["validation_status"] == "unvalidated_engineering_estimate" and r["data_source"] == "real"
    # 0.05 g amplitude → 0.1 g range → 100 MPa; N = 2e6·(80/100)^3; 2 cycles/s → life = N / (2·year)
    expected = 2e6 * (80 / 100) ** 3 / (freq * SECONDS_PER_YEAR)
    assert r["estimate"] == pytest.approx(expected, rel=0.02)
    assert r["interval_low"] < r["estimate"] < r["interval_high"]
    d = r["details"]
    assert d["max_stress_range_mpa"] == pytest.approx(100, rel=0.01) and d["sn_curve"]["standard"] == "EN 1993-1-9"
    assert d["cycles_counted"] == pytest.approx(duration * freq, rel=0.02)
    # prior damage halves the remaining life
    client.put(f"{API}/rul/config/FAT-G1", json={"value": {"prior_damage": 0.5}})
    r2 = client.post(f"{API}/rul/estimate", json={"asset_id": "FAT", "component_id": "FAT-G1"}).json()
    assert r2["estimate"] == pytest.approx(r["estimate"] / 2, rel=1e-6)
    # small loading below the cut-off → no damaging cycles, not an invented number
    client.put(f"{API}/rul/config/FAT-G1", json={"value": {"stress_per_g_mpa": 100, "prior_damage": 0}})
    r3 = client.post(f"{API}/rul/estimate", json={"asset_id": "FAT", "component_id": "FAT-G1"}).json()
    assert r3["status"] == "no_damaging_cycles" and r3["estimate"] is None
    assert len(client.get(f"{API}/rul/results", params={"component_id": "FAT-G1"}).json()) == 4


def test_fatigue_on_simulated_data_is_demonstration_only(client):
    client.post(f"{API}/assets", json={"id": "FAT", "name": "fatigue"})
    client.post(f"{API}/assets/FAT/components", json={"id": "FAT-G1", "name": "Girder 1", "component_type": "girder"})
    client.post(f"{API}/devices", json={"id": "S1", "device_type": "accelerometer", "name": "s", "asset_id": "FAT", "component_id": "FAT-G1",
                                        "data_source": "simulated", "sample_rate_hz": 10})
    client.post(f"{API}/simulation/generate", json={"device_id": "S1", "minutes": 15})
    client.put(f"{API}/rul/config/FAT-G1", json={"value": {"stress_per_g_mpa": 3000, "detail_category_mpa": 36, "source": "simulated", "noise_gate_g": 0.0}})
    r = client.post(f"{API}/rul/estimate", json={"asset_id": "FAT", "component_id": "FAT-G1"}).json()
    assert r["validation_status"] == "demonstration_only" and r["data_source"] == "simulated"
    if r["status"] == "estimated":
        assert r["message"].startswith("DEMONSTRATION ONLY")


def test_too_little_data_is_unavailable(client):
    _node_with_sine(client, minutes=3)
    client.put(f"{API}/rul/config/FAT-G1", json={"value": {"stress_per_g_mpa": 1000, "detail_category_mpa": 80}})
    r = client.post(f"{API}/rul/estimate", json={"asset_id": "FAT", "component_id": "FAT-G1"}).json()
    assert r["status"] == "unavailable" and "at least 10 min" in r["message"]


def test_device_delete_keeps_history(client):
    from tests.test_cameras import _camera, _frame

    cam, token = _camera(client)
    _frame(client, cam, token, 20, store="always")
    prev = client.get(f"{API}/devices/{cam}/delete-preview").json()
    assert prev["kept"]["inspections"] == 1
    assert client.delete(f"{API}/devices/{cam}", params={"actor": "eng"}).status_code == 200
    assert client.get(f"{API}/devices/{cam}").status_code == 404
    insp = client.get(f"{API}/inspections", params={"asset_id": "CAMA"}).json()
    assert len(insp) == 1 and insp[0]["device_id"] is None
    assert any(e["event_type"] == "device_deleted" for e in client.get(f"{API}/events").json())


def test_api_index_and_root_redirect(client):
    r = client.get(f"{API}")
    assert r.status_code == 200 and r.json()["documentation"] == "/docs"
    assert client.get(f"{API}/").status_code == 200
    assert client.get("/", follow_redirects=False).headers["location"] == "/docs"


def test_model_upload_installs_and_validates(client, tmp_path):
    from tests.conftest import build_test_onnx_model

    d = build_test_onnx_model(tmp_path / "m")
    bad = client.post(f"{API}/models/upload", files={"onnx_file": ("model.onnx", b"garbage", "application/octet-stream"),
                                                     "card_file": ("model_card.json", (d / "model_card.json").read_bytes(), "application/json")})
    assert bad.status_code == 422 and "could not be loaded" in bad.json()["detail"]
    assert client.get(f"{API}/system/status").json()["models"]["available"] is False
    ok = client.post(f"{API}/models/upload", files={"onnx_file": ("model.onnx", (d / "model.onnx").read_bytes(), "application/octet-stream"),
                                                    "card_file": ("model_card.json", (d / "model_card.json").read_bytes(), "application/json")})
    assert ok.status_code == 201 and ok.json()["installed"] == "test-classifier"
    assert client.get(f"{API}/system/status").json()["models"]["available"] is True
    assert client.get(f"{API}/models").json()[0]["is_active"] is True
