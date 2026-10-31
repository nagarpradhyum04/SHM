"""Settings → AI model → 'Train & install' job: output streaming, install of the produced model, failure reporting.
The trainer is replaced by a small script here; the real trainer is exercised in the manual run recorded in the README."""
from __future__ import annotations

import sys
import time

from tests.conftest import build_test_onnx_model


def _wait(client, states=("done", "failed", "cancelled"), timeout=30):
    for _ in range(timeout * 10):
        s = client.get("/api/v1/models/train").json()
        if s["state"] in states:
            return s
        time.sleep(0.1)
    raise AssertionError(s)


def test_training_job_installs_model(client, tmp_path, monkeypatch):
    from app.services import model_training

    out = tmp_path / "build"
    build_test_onnx_model(out)
    monkeypatch.setattr(model_training, "OUT_DIR", out)
    script = "import time\nprint('STEP dataset ready', flush=True)\nprint('PROGRESS download 10 MB', flush=True)\nprint('PROGRESS download 20 MB', flush=True)\nprint('STEP training', flush=True)\n"
    s = model_training.job.start(None, 3000, 5, cmd_override=[sys.executable, "-c", script])
    assert s["state"] == "running"
    assert client.post("/api/v1/models/train", json={}).status_code in (202, 409)
    s = _wait(client)
    assert s["state"] == "done", s
    assert s["result"]["installed"] == "test-classifier"
    assert [l for l in s["log"] if l.startswith("PROGRESS")] == ["PROGRESS download 20 MB"]  # progress lines collapse
    st = client.get("/api/v1/system/status").json()
    assert st["models"]["available"] is True


def test_training_job_reports_failure(client, tmp_path, monkeypatch):
    from app.services import model_training

    monkeypatch.setattr(model_training, "OUT_DIR", tmp_path / "missing")
    script = "import sys\nprint('STEP downloading', flush=True)\nprint('Automatic download failed (HTTP 403).', flush=True)\nsys.exit(1)\n"
    model_training.job.start(None, 3000, 5, cmd_override=[sys.executable, "-c", script])
    s = _wait(client)
    assert s["state"] == "failed" and "download failed" in s["error"]


def test_training_rejects_missing_dataset_path(client):
    r = client.post("/api/v1/models/train", json={"data_path": "/nonexistent/dataset.zip"})
    assert r.status_code == 422 and "does not exist" in r.json()["detail"]
