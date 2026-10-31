import io

import numpy as np
import pytest
from PIL import Image

from tests.conftest import build_test_glb, build_test_onnx_model

API = "/api/v1"


@pytest.fixture
def model_client(env):
    build_test_onnx_model(env / "models" / "t")
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def _png(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


def _image_with_dark_patch(w=640, h=480, box=(400, 240, 560, 400)):
    a = np.full((h, w, 3), 235, np.uint8)  # bright = "no crack" for the test model
    x0, y0, x1, y1 = box
    a[y0:y1, x0:x1] = 15  # dark = "crack" for the test model
    return a


def test_sliding_window_localisation_finds_the_region(env):
    import json

    from app.services.inference.onnx_classifier import OnnxImageClassifier

    d = build_test_onnx_model(env / "m")
    clf = OnnxImageClassifier(json.loads((d / "model_card.json").read_text()), d / "model.onnx")
    loc = clf.localize(_image_with_dark_patch()[:, :, ::-1].copy(), tile_px=80)
    assert loc["regions"], loc
    r = loc["regions"][0]
    x0, y0, x1, y1 = r["bbox"]
    assert x0 >= 360 and y0 >= 200 and x1 <= 600 and y1 <= 440  # around the dark patch, not elsewhere
    cx, cy = r["centroid_px"]
    assert 420 < cx < 540 and 260 < cy < 380
    assert "coarse" in loc["method"]


def _setup_camera(c, with_glb=False):
    c.post(f"{API}/assets", json={"id": "LOC", "name": "loc"})
    if with_glb:
        glb = build_test_glb([{"name": "Wall", "box": ((-10, 0, -0.5), (10, 10, 0.5))}])
        c.post(f"{API}/assets/LOC/model", files={"file": ("w.glb", glb, "model/gltf-binary")})
        comp = c.get(f"{API}/assets/LOC/components").json()[0]["id"]
    else:
        c.post(f"{API}/assets/LOC/components", json={"id": "LOC-WALL", "name": "Wall", "component_type": "wall", "model_x": 0, "model_y": 5,
                                                     "model_z": 0, "geometry": {"type": "box", "size": [20, 10, 1]},
                                                     "bbox": {"min": [-10, 0, -0.5], "max": [10, 10, 0.5]}})
        comp = "LOC-WALL"
    # camera 10 m in front of the wall (+Z), looking at it (yaw 0 → looking along −Z), 60° vertical FOV
    r = c.post(f"{API}/devices", json={"id": "CAM-L", "device_type": "camera", "name": "cam", "asset_id": "LOC", "component_id": comp,
                                       "model_x": 0, "model_y": 5, "model_z": 10, "fov_deg": 60, "resolution_w": 640, "resolution_h": 480})
    return comp, r.json()["ingestion_token"]


@pytest.mark.parametrize("with_glb", [False, True])
def test_camera_detection_gets_3d_coordinates_on_the_surface(model_client, with_glb):
    c = model_client
    comp, token = _setup_camera(c, with_glb)
    r = c.post(f"{API}/cameras/CAM-L/frames", files={"file": ("f.png", _png(_image_with_dark_patch()), "image/png")},
               headers={"X-Device-Token": token}).json()
    assert r["stored"] and r["defects"], r
    d = r["defects"][0]
    assert d["location_kind"] == "surface" and d["localization_method"] == "camera_ray_mesh" and d["location_confidence"] == "low"
    assert d["pos_z"] == pytest.approx(0.5, abs=1e-3)  # on the wall's front face, not a bounding box guess
    assert d["pos_x"] > 0 and d["pos_y"] < 5  # crack is right of and below the image centre
    assert d["image_region"]["point_px"] and d["image_region"]["regions"]
    assert "uncalibrated" in d["localization_notes"]


def test_calibrated_camera_and_geo_reference(model_client):
    c = model_client
    comp, token = _setup_camera(c)
    c.patch(f"{API}/devices/CAM-L", json={"intrinsics": {"fx": 415.7, "fy": 415.7, "cx": 320, "cy": 240, "width": 640, "height": 480, "calibrated": True}})
    c.patch(f"{API}/assets/LOC", json={"geo_transform": {"origin_lat": 23.0225, "origin_lon": 72.5714, "heading_deg": 0, "calibrated": False}})
    r = c.post(f"{API}/cameras/CAM-L/frames", files={"file": ("f.png", _png(_image_with_dark_patch(1280, 960, (800, 480, 1120, 800))), "image/png")},
               headers={"X-Device-Token": token}).json()
    d = r["defects"][0]
    assert d["location_confidence"] == "medium"  # calibrated intrinsics, scaled from 640×480 to the 1280×960 frame
    assert d["latitude"] == pytest.approx(23.0225, abs=1e-3) and d["longitude"] == pytest.approx(72.5714, abs=1e-3)
    assert "UNCALIBRATED model-to-world" in d["localization_notes"]


def test_upload_without_camera_keeps_image_coordinates_only(model_client):
    c = model_client
    c.post(f"{API}/assets", json={"id": "UP", "name": "up"})
    r = c.post(f"{API}/inspections/image", data={"asset_id": "UP"}, files={"file": ("x.png", _png(_image_with_dark_patch()), "image/png")}).json()
    d = r["defects"][0]
    assert d["component_id"] is None and d["location_kind"] == "component" and d["image_region"]["bbox"]
    assert "image only" in d["localization_notes"]
