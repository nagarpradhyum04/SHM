"""Re-installing a model with the same id must replace the loaded model and its stored record."""
import json
from tests.conftest import build_test_onnx_model

def test_reinstall_updates_record(client, tmp_path):
    d = build_test_onnx_model(tmp_path / "m")
    for v in ("first", "second"):
        card = json.loads((d / "model_card.json").read_text()); card["metrics"] = {"tag": v}; card["threshold"] = 0.3 if v == "first" else 0.7
        r = client.post("/api/v1/models/upload", files={"onnx_file": ("model.onnx", (d / "model.onnx").read_bytes()), "card_file": ("c.json", json.dumps(card))})
        assert r.status_code == 201, r.text
        m = client.get("/api/v1/models").json()[0]
        assert (m["metrics"]["tag"], m["threshold"]) == (v, card["threshold"]), m
        from app.services.inference import get_model_registry
        reg = get_model_registry()
        assert reg._loaded["test-classifier"].card["threshold"] == card["threshold"]  # the NEW model is the one used for detection
        assert not any(p.name.endswith(".previous") for p in reg.model_dir.iterdir())
