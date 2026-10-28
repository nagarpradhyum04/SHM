import io

from tests.conftest import build_test_onnx_model, png_bytes

API = "/api/v1"


def _upload(client, aid, data, name="x.png", ctype="image/png", comp=None):
    return client.post(f"{API}/inspections/image", data={"asset_id": aid, **({"component_id": comp} if comp else {})},
                       files={"file": (name, io.BytesIO(data), ctype)})


def test_upload_validation(client, make_asset):
    aid = make_asset()
    assert _upload(client, aid, b"not an image at all", "x.png").status_code == 422
    assert _upload(client, aid, b"").status_code == 422
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 64)).save(buf, format="GIF")
    r = _upload(client, aid, buf.getvalue(), "x.gif", "image/gif")
    assert r.status_code == 422 and "Unsupported" in r.json()["detail"]
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, format="PNG")
    assert _upload(client, aid, buf.getvalue()).status_code == 422  # too small
    # extension lies are caught by decoding: PNG content named .jpg is stored as PNG
    r = _upload(client, aid, png_bytes(), "photo.jpg", "image/jpeg")
    assert r.status_code == 201 and r.json()["image"]["content_type"] == "image/png"
    assert "storage_key" not in r.json()["image"]


def test_upload_size_limit(client, make_asset, monkeypatch):
    aid = make_asset()
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_upload_mb", 0.01)
    assert _upload(client, aid, png_bytes() + b"\0" * 20000).status_code == 413


def test_model_unavailable_is_explicit(client, make_asset):
    aid = make_asset()
    r = _upload(client, aid, png_bytes(), comp=f"{aid}-C1")
    assert r.status_code == 201
    body = r.json()
    assert body["inspection"]["status"] == "model_unavailable"
    assert body["inspection"]["model_id"] is None
    assert body["defects"] == []  # never a fabricated prediction
    assert client.get(f"{API}/system/status").json()["models"]["available"] is False
    img = client.get(f"{API}/images/{body['image']['id']}/file")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"


def test_inference_success_with_installed_model(env):
    build_test_onnx_model(env / "models" / "test-classifier")
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as client:
        client.post(f"{API}/assets", json={"id": "A1", "name": "a"})
        client.post(f"{API}/assets/A1/components", json={"id": "A1-C", "name": "c", "component_type": "deck_segment"})
        status = client.get(f"{API}/system/status").json()["models"]
        assert status["available"] and status["ai_supported_categories"] == ["suspected_crack"]
        models = client.get(f"{API}/models").json()
        assert models[0]["id"] == "test-classifier" and models[0]["status"] == "installed" and models[0]["is_active"]
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (128, 128), (10, 10, 10)).save(buf, format="PNG")  # dark => test model says "crack"
        r = _upload(client, "A1", buf.getvalue(), comp="A1-C").json()
        insp = r["inspection"]
        assert insp["status"] == "completed" and insp["model_id"] == "test-classifier" and insp["model_version"] == "0.0.1-test"
        assert insp["inference_output"]["raw"]["probabilities"]["crack"] > 0.5
        assert len(r["defects"]) == 1
        d = r["defects"][0]
        assert d["detection_source"] == "ai_model" and d["model_confidence"] > 0.5
        assert d["location_kind"] == "component" and d["location_confidence"] == "component_only"
        buf = io.BytesIO()
        Image.new("RGB", (128, 128), (250, 250, 250)).save(buf, format="PNG")
        r = _upload(client, "A1", buf.getvalue(), comp="A1-C").json()
        assert r["inspection"]["status"] == "completed" and r["defects"] == []


def test_low_quality_image_raises_alert(client, make_asset):
    aid = make_asset()
    r = _upload(client, aid, png_bytes("blurry", 3), comp=f"{aid}-C1").json()
    assert "possible_blur" in r["image"]["quality"]["issues"]
    alerts = client.get(f"{API}/alerts", params={"asset_id": aid, "rule_type": "image_quality"}).json()
    assert len(alerts) == 1


def test_demo_inspection_is_labelled(client, make_asset):
    aid = make_asset()
    r = client.post(f"{API}/inspections/demo", json={"asset_id": aid, "variant": "crack"}).json()
    assert r["inspection"]["data_source"] == "demo" and r["image"]["data_source"] == "demo"
