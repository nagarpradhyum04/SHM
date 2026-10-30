from tests.conftest import build_test_glb

API = "/api/v1"
NODES = [
    {"name": "Bridge", "children": [1, 2, 3]},
    {"name": "Deck Main", "box": ((-50, -1, -6), (50, 0, 6)), "translation": (0, 20, 0)},
    {"name": "Pier West", "box": ((-2, 0, -2), (2, 20, 2)), "translation": (-30, 0, 0)},
    {"name": "Pier East", "box": ((-2, 0, -2), (2, 20, 2)), "translation": (30, 0, 0)},
]


def _upload(client, aid, data, **form):
    return client.post(f"{API}/assets/{aid}/model", data=form, files={"file": ("bridge.glb", data, "model/gltf-binary")})


def test_glb_upload_registers_components_with_world_bounds(client):
    client.post(f"{API}/assets", json={"id": "GLB", "name": "My bridge"})
    assert _upload(client, "GLB", b"not a glb").status_code == 422
    r = _upload(client, "GLB", build_test_glb(NODES))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["components_created"] == 4 and body["asset"]["model_kind"] == "gltf"
    assert body["model_meta"]["bounds"] == {"min": [-50.0, 0.0, -6.0], "max": [50.0, 20.0, 6.0]} and body["model_meta"]["mesh_nodes"] == 3
    comps = {c["name"]: c for c in client.get(f"{API}/assets/GLB/components").json()}
    deck, pier = comps["Deck Main"], comps["Pier West"]
    assert deck["mesh_ref"] == "gltf-node:1" and deck["component_type"] == "deck_segment" and deck["parent_id"] == comps["Bridge"]["id"]
    assert deck["bbox"] == {"min": [-50.0, 19.0, -6.0], "max": [50.0, 20.0, 6.0]}
    assert pier["bbox"]["min"][0] == -32.0 and pier["component_type"] == "pier"
    assert comps["Bridge"]["geometry"]["type"] == "group" and comps["Bridge"]["bbox"]["max"][1] == 20.0
    f = client.get(f"{API}/assets/GLB/model/file")
    assert f.status_code == 200 and f.content[:4] == b"glTF" and "storage" not in str(body)


def test_reupload_keeps_component_ids_and_retires_missing_nodes(client):
    client.post(f"{API}/assets", json={"id": "GLB2", "name": "b"})
    _upload(client, "GLB2", build_test_glb(NODES))
    comps = {c["name"]: c["id"] for c in client.get(f"{API}/assets/GLB2/components").json()}
    d = client.post(f"{API}/defects", json={"asset_id": "GLB2", "component_id": comps["Pier West"], "category": "suspected_crack"}).json()
    revised = [NODES[0] | {"children": [1, 2]}, NODES[2], NODES[1]]  # East pier removed, node order changed
    body = _upload(client, "GLB2", build_test_glb(revised)).json()
    assert body["components_created"] == 0 and body["components_updated"] == 3 and body["components_retired"] == 1
    after = {c["name"]: c for c in client.get(f"{API}/assets/GLB2/components").json()}
    assert after["Pier West"]["id"] == comps["Pier West"] and after["Pier West"]["mesh_ref"] == "gltf-node:1"
    assert after["Pier East"]["mesh_ref"] is None and "not present" in after["Pier East"]["notes"]
    assert client.get(f"{API}/defects/{d['id']}").json()["defect"]["component_id"] == comps["Pier West"]


def test_external_buffers_and_size_limit_rejected(client, monkeypatch):
    import json
    import struct

    client.post(f"{API}/assets", json={"id": "GLB3", "name": "c"})
    js = json.dumps({"asset": {"version": "2.0"}, "buffers": [{"uri": "data.bin", "byteLength": 1}]}).encode()
    js += b" " * (-len(js) % 4)
    glb = b"glTF" + struct.pack("<II", 2, 20 + len(js)) + struct.pack("<II", len(js), 0x4E4F534A) + js
    r = _upload(client, "GLB3", glb)
    assert r.status_code == 422 and "external" in r.json()["detail"]
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_model_mb", 0.0001)
    assert _upload(client, "GLB3", build_test_glb(NODES)).status_code == 413
