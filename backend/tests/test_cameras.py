import io
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from tests.conftest import build_test_onnx_model

API = "/api/v1"
BACKEND = Path(__file__).resolve().parent.parent


def _jpg(value: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (128, 96), (value, value, value)).save(buf, format="JPEG")
    return buf.getvalue()


def _camera(client, aid="CAMA", source="real"):
    client.post(f"{API}/assets", json={"id": aid, "name": "a"})
    client.post(f"{API}/assets/{aid}/components", json={"id": f"{aid}-C", "name": "c", "component_type": "deck_segment"})
    r = client.post(f"{API}/devices", json={"id": f"{aid}-CAM", "device_type": "camera", "name": "webcam", "asset_id": aid,
                                            "component_id": f"{aid}-C", "data_source": source, "fov_deg": 50, "resolution_w": 1280, "resolution_h": 720})
    assert r.status_code == 201, r.text
    return f"{aid}-CAM", r.json()["ingestion_token"]


def _frame(client, cam, token, value, store="on_finding"):
    return client.post(f"{API}/cameras/{cam}/frames", data={"store": store}, files={"file": ("f.jpg", _jpg(value), "image/jpeg")},
                       headers={"X-Device-Token": token})


def test_frames_without_model_store_only_reference_snapshots(client):
    cam, token = _camera(client)
    assert _frame(client, cam, "bad", 20).status_code == 401
    r = _frame(client, cam, token, 20).json()
    assert r["model_status"] == "model_unavailable" and r["stored"] is False and r["detections"] == []
    r = _frame(client, cam, token, 20, store="always").json()
    assert r["stored"] and r["inspection"]["status"] == "model_unavailable" and r["inspection"]["data_source"] == "real"
    dev = client.get(f"{API}/devices/{cam}").json()
    assert dev["connection"]["status"] == "online"


def test_findings_clip_suppression_and_heartbeat(env):
    build_test_onnx_model(env / "models" / "t")
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as client:
        cam, token = _camera(client)
        assert _frame(client, cam, token, 240).json()["stored"] is False  # bright frame: test model says no crack
        r = _frame(client, cam, token, 15).json()
        assert r["stored"] and r["request_clip"] and r["defects"][0]["detection_source"] == "ai_model"
        insp = r["inspection"]["id"]
        again = _frame(client, cam, token, 15).json()
        assert again["stored"] is False and again["suppressed_by"] == r["defects"][0]["id"]
        # clip upload: format checks + storage + exposure through defect detail
        bad = client.post(f"{API}/inspections/{insp}/clip", files={"file": ("c.webm", b"not a video", "video/webm")}, headers={"X-Device-Token": token})
        assert bad.status_code == 422
        path = env / "c.webm"
        vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"VP80"), 10, (160, 120))
        for i in range(20):
            vw.write(np.full((120, 160, 3), i * 10, np.uint8))
        vw.release()
        c = client.post(f"{API}/inspections/{insp}/clip", data={"duration_s": "2"}, files={"file": ("c.webm", path.read_bytes(), "video/webm")},
                        headers={"X-Device-Token": token})
        assert c.status_code == 201 and c.json()["content_type"] == "video/webm"
        detail = client.get(f"{API}/defects/{r['defects'][0]['id']}").json()
        assert len(detail["clips"]) == 1
        f = client.get(detail["clips"][0]["url"])
        assert f.status_code == 200 and f.content[:4] == b"\x1a\x45\xdf\xa3"
        hb = client.post(f"{API}/devices/{cam}/heartbeat", json={"stream_url": "http://127.0.0.1:8081/stream", "info": {"fps": 10}},
                         headers={"X-Device-Token": token})
        assert hb.status_code == 200
        assert client.get(f"{API}/devices/{cam}").json()["stream_url"] == "http://127.0.0.1:8081/stream"


def test_simulated_camera_cannot_submit_frames(client):
    cam, _ = _camera(client, "SIMC", "simulated")
    assert _frame(client, cam, "x", 20).status_code == 401  # simulated devices have no token


def test_camera_agent_end_to_end(tmp_path):
    """Real uvicorn backend + edge/camera_agent.py reading a synthetic video file."""
    build_test_onnx_model(tmp_path / "models" / "t")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    env = {**os.environ, "SS_DATABASE_URL": f"sqlite:///{tmp_path / 'db.sqlite'}", "SS_STORAGE_DIR": str(tmp_path / "s"),
           "SS_MODEL_DIR": str(tmp_path / "models"), "SS_SEED_DEMO_DATA": "false", "SS_BACKGROUND_ENABLED": "false", "SS_MQTT_ENABLED": "false"}
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)], cwd=BACKEND, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        import httpx

        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                if httpx.get(f"{base}{API}/health").status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
        with httpx.Client(base_url=base) as client:
            cam, token = _camera(client)
            video = tmp_path / "v.avi"
            vw = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 10, (160, 120))
            for i in range(60):
                vw.write(np.full((120, 160, 3), 10 + (i % 5), np.uint8))  # dark frames → test model reports "crack"
            vw.release()
            agent = subprocess.run([sys.executable, "-m", "edge.camera_agent", "--api", base, "--device-id", cam, "--token", token,
                                    "--source", str(video), "--loop", "--fps", "10", "--interval", "2", "--pre", "1", "--post", "1",
                                    "--keep-every", "0", "--preview-port", "0", "--run-for", "7"], cwd=BACKEND, capture_output=True, text=True, timeout=60)
            assert "uploaded" in agent.stderr, agent.stderr[-2000:]
            insps = client.get(f"{API}/inspections", params={"asset_id": "CAMA"}).json()
            assert len(insps) == 1 and insps[0]["inspection_type"] == "camera_capture"  # later detections suppressed
            clips = client.get(f"{API}/inspections/{insps[0]['id']}/clips").json()
            assert len(clips) == 1 and clips[0]["duration_s"] > 0.5  # pre-roll is shorter when the first detection is at start-up
            assert client.get(f"{API}/devices/{cam}").json()["connection"]["status"] == "online"
    finally:
        server.terminate()
        server.wait(10)
