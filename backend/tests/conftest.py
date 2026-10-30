"""Test fixtures: every test gets an isolated database, storage and model directory."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

TEMPLATE: dict = {}


def _configure(tmp: Path, model_dir: Path | None = None):
    os.environ["SS_DATABASE_URL"] = f"sqlite:///{(tmp / 'test.db').as_posix()}"
    os.environ["SS_STORAGE_DIR"] = str(tmp / "storage")
    os.environ["SS_MODEL_DIR"] = str(model_dir or (tmp / "models"))
    os.environ["SS_BACKGROUND_ENABLED"] = "false"
    os.environ["SS_SEED_DEMO_DATA"] = "false"
    os.environ["SS_MQTT_ENABLED"] = "false"
    os.environ["SS_DEVICE_SHARED_KEY"] = ""
    from app.config import get_settings
    from app.db import set_database
    from app.services.inference.registry import set_model_registry
    from app.services.storage import set_storage

    get_settings.cache_clear()
    set_database(None)
    set_storage(None)
    set_model_registry(None)


def _reset_globals():
    from app.db import get_database, set_database

    try:
        get_database().dispose()
    except Exception:  # noqa: BLE001
        pass
    set_database(None)


@pytest.fixture(scope="session")
def seeded_template(tmp_path_factory):
    """Build one seeded demo DB (short simulated history) and copy it per test."""
    tmp = tmp_path_factory.mktemp("template")
    _configure(tmp)
    from app.db import get_database
    from app.main import bootstrap
    from app.seed.seed import seed_demo

    bootstrap()
    db = get_database().session()
    seed_demo(db, sim_minutes_baseline=12, sim_minutes_recent=15)
    db.commit()
    db.close()
    _reset_globals()
    return tmp


@pytest.fixture
def env(tmp_path):
    _configure(tmp_path)
    yield tmp_path
    _reset_globals()


@pytest.fixture
def client(env):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def seeded_client(tmp_path, seeded_template):
    shutil.copy(seeded_template / "test.db", tmp_path / "test.db")
    shutil.copytree(seeded_template / "storage", tmp_path / "storage")
    _configure(tmp_path)
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c
    _reset_globals()


@pytest.fixture
def db(env):
    from app.db import get_database
    from app.main import bootstrap

    bootstrap()
    s = get_database().session()
    yield s
    s.close()


@pytest.fixture
def make_asset(client):
    def _make(aid="T-BRIDGE", components=("C1", "C2")):
        r = client.post("/api/v1/assets", json={"id": aid, "name": "Test bridge", "asset_type": "bridge"})
        assert r.status_code == 201, r.text
        for c in components:
            r = client.post(f"/api/v1/assets/{aid}/components", json={
                "id": f"{aid}-{c}", "name": c, "component_type": "deck_segment", "model_x": 0, "model_y": 0, "model_z": 0,
                "bbox": {"min": [-5, -1, -5], "max": [5, 1, 5]}})
            assert r.status_code == 201, r.text
        return aid

    return _make


def png_bytes(variant="crack", seed=1) -> bytes:
    from app.seed.demo_images import generate_demo_image

    return generate_demo_image(variant, seed)[0]


def build_test_onnx_model(directory: Path) -> Path:
    """Builds a TEST-ONLY ONNX 'classifier' whose crack logit grows as mean intensity falls.
    It exists solely to exercise the inference pipeline; it is not a crack detector."""
    import json

    import numpy as np
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    directory.mkdir(parents=True, exist_ok=True)
    w = numpy_helper.from_array(np.array([[-20.0, 20.0]], dtype=np.float32), "w")
    b = numpy_helper.from_array(np.array([[10.0, -10.0]], dtype=np.float32), "b")
    nodes = [
        helper.make_node("ReduceMean", ["input"], ["m"], axes=[1, 2, 3], keepdims=0),
        helper.make_node("Unsqueeze", ["m", "ax"], ["m2"]),
        helper.make_node("MatMul", ["m2", "w"], ["mw"]),
        helper.make_node("Add", ["mw", "b"], ["tmp"]),
        helper.make_node("Neg", ["tmp"], ["logits"]),
    ]
    ax = numpy_helper.from_array(np.array([1], dtype=np.int64), "ax")
    graph = helper.make_graph(nodes, "test", [helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, 32, 32])],
                              [helper.make_tensor_value_info("logits", TensorProto.FLOAT, [1, 2])], [w, b, ax])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.save(model, directory / "model.onnx")
    card = {"id": "test-classifier", "name": "TEST-ONLY pipeline model", "version": "0.0.1-test", "task": "classification",
            "framework": "onnx", "file": "model.onnx", "labels": ["no_crack", "crack"], "positive_label": "crack",
            "category_map": {"crack": "suspected_crack"}, "output": "logits", "threshold": 0.5,
            "input": {"size": [32, 32], "color": "rgb", "layout": "NCHW", "scale": 1 / 255, "mean": [0, 0, 0], "std": [1, 1, 1]},
            "dataset": {"name": "none — test fixture"}, "metrics": None}
    (directory / "model_card.json").write_text(json.dumps(card))
    return directory


def build_test_glb(nodes: list[dict]) -> bytes:
    """Build a minimal valid GLB. Each node: {"name", "box": (min, max) or None, "translation"?, "children"?: [indices]}.
    Box nodes get a mesh whose POSITION accessor spans the box (8 vertices)."""
    import json
    import struct

    import numpy as np

    bin_parts, accessors, views, meshes, gnodes = [], [], [], [], []
    offset = 0
    for n in nodes:
        gn = {"name": n["name"]}
        if n.get("translation"):
            gn["translation"] = list(n["translation"])
        if n.get("children"):
            gn["children"] = n["children"]
        if n.get("box"):
            lo, hi = n["box"]
            verts = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])], np.float32)
            raw = verts.tobytes()
            views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(raw)})
            accessors.append({"bufferView": len(views) - 1, "componentType": 5126, "count": 8, "type": "VEC3",
                              "min": [float(v) for v in verts.min(0)], "max": [float(v) for v in verts.max(0)]})
            meshes.append({"primitives": [{"attributes": {"POSITION": len(accessors) - 1}, "mode": 0}]})
            gn["mesh"] = len(meshes) - 1
            bin_parts.append(raw)
            offset += len(raw)
        gnodes.append(gn)
    children = {c for n in nodes for c in n.get("children", [])}
    binary = b"".join(bin_parts)
    doc = {"asset": {"version": "2.0", "generator": "structurasense-test"}, "scene": 0,
           "scenes": [{"nodes": [i for i in range(len(nodes)) if i not in children]}], "nodes": gnodes, "meshes": meshes,
           "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": len(binary)}]}
    js = json.dumps(doc).encode()
    js += b" " * (-len(js) % 4)
    binary += b"\0" * (-len(binary) % 4)
    total = 12 + 8 + len(js) + 8 + len(binary)
    return (b"glTF" + struct.pack("<II", 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js
            + struct.pack("<II", len(binary), 0x004E4942) + binary)
