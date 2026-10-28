API = "/api/v1"


def test_asset_create_and_retrieve(client):
    r = client.post(f"{API}/assets", json={"id": "BR-1", "name": "River bridge", "asset_type": "bridge", "latitude": 12.9, "longitude": 77.5})
    assert r.status_code == 201
    got = client.get(f"{API}/assets/BR-1").json()
    assert got["name"] == "River bridge" and got["latitude"] == 12.9 and got["is_demo"] is False
    assert any(a["id"] == "BR-1" for a in client.get(f"{API}/assets").json())
    assert client.post(f"{API}/assets", json={"id": "BR-1", "name": "dup"}).status_code == 409
    assert client.post(f"{API}/assets", json={"name": "bad", "latitude": 123}).status_code == 422
    assert client.get(f"{API}/assets/NOPE").status_code == 404


def test_asset_summary_has_no_invented_values(client, make_asset):
    aid = make_asset()
    s = client.get(f"{API}/assets/{aid}/summary").json()
    assert s["inspections"] == 0 and s["latest_inspection_at"] is None and s["open_findings"] == 0
    assert s["components"] == 2 and s["devices_total"] == 0


def test_component_association(client, make_asset):
    aid = make_asset()
    other = make_asset("OTHER", components=("X",))
    comp = f"{aid}-C1"
    r = client.post(f"{API}/devices", json={"id": "ACC-T1", "device_type": "accelerometer", "name": "acc", "asset_id": aid,
                                            "component_id": comp, "sample_rate_hz": 10})
    assert r.status_code == 201 and r.json()["ingestion_token"]
    r = client.post(f"{API}/defects", json={"asset_id": aid, "component_id": comp, "category": "suspected_crack"})
    assert r.status_code == 201
    detail = client.get(f"{API}/components/{comp}").json()
    assert detail["component"]["id"] == comp
    assert [d["id"] for d in detail["devices"]] == ["ACC-T1"]
    assert len(detail["defects"]) == 1
    assert "not geographic" in detail["coordinate_note"]
    # cross-asset association is rejected
    assert client.post(f"{API}/defects", json={"asset_id": aid, "component_id": f"{other}-X", "category": "other"}).status_code == 400
    assert client.post(f"{API}/devices", json={"id": "ACC-T2", "device_type": "accelerometer", "name": "x", "asset_id": aid,
                                               "component_id": f"{other}-X"}).status_code == 400


def test_demo_seed_component_registry(seeded_client):
    comps = seeded_client.get(f"{API}/assets/DEMO-BRIDGE-01/components").json()
    ids = {c["id"] for c in comps}
    assert {"DECK-S01", "TWR-W-LEG-N", "PIER-E-CAP", "CBL-W-N-M01", "BRG-ABT-E-S"} <= ids
    assert len(ids) == len(comps)  # stable unique IDs
    for c in comps:
        if c["geometry"]["type"] != "group":
            assert c["bbox"] and c["mesh_ref"] == f"proc:{c['id']}"
    asset = seeded_client.get(f"{API}/assets/DEMO-BRIDGE-01").json()
    assert asset["is_demo"] and asset["latitude"] is None
