API = "/api/v1"


def test_defect_location_kinds(client, make_asset):
    aid = make_asset()
    comp = f"{aid}-C1"
    r = client.post(f"{API}/defects", json={"asset_id": aid, "component_id": comp, "category": "suspected_crack"})
    d = r.json()
    assert d["location_kind"] == "component" and d["pos_x"] is None and d["location_confidence"] == "component_only"
    r = client.post(f"{API}/defects", json={"asset_id": aid, "component_id": comp, "category": "suspected_crack", "location_kind": "surface",
                                            "pos_x": 1, "pos_y": 2, "pos_z": 3, "localization_method": "manual_surface_pick"})
    d = r.json()
    assert d["location_kind"] == "surface" and d["location_confidence"] == "approximate" and d["pos_y"] == 2
    # surface without coordinates rejected; component-level without component rejected
    assert client.post(f"{API}/defects", json={"asset_id": aid, "component_id": comp, "category": "other", "location_kind": "surface"}).status_code == 400
    assert client.post(f"{API}/defects", json={"asset_id": aid, "category": "other"}).status_code == 400
    # measured extent requires a method
    assert client.post(f"{API}/defects", json={"asset_id": aid, "component_id": comp, "category": "other",
                                               "measured_extent": {"width_mm": 0.3}}).status_code == 422


def test_priority_rules_and_unassessed(client, make_asset):
    aid = make_asset()
    comp = f"{aid}-C1"
    base = {"asset_id": aid, "component_id": comp}
    assert client.post(f"{API}/defects", json={**base, "category": "other"}).json()["priority"] == "unassessed"
    first = client.post(f"{API}/defects", json={**base, "category": "suspected_corrosion"}).json()
    assert first["priority"] == "medium" and first["priority_source"] == "rules"
    second = client.post(f"{API}/defects", json={**base, "category": "suspected_corrosion"}).json()
    assert second["priority"] == "high"  # R5 repeated observation
    assert any(r["rule"].startswith("R5") for r in second["priority_rationale"])
    # manual override is recorded and preserved; 'auto' returns to rules
    r = client.patch(f"{API}/defects/{first['id']}", json={"priority": "low", "actor": "eng"}).json()
    assert r["priority"] == "low" and r["priority_source"] == "manual"
    r = client.patch(f"{API}/defects/{first['id']}", json={"priority": "auto", "actor": "eng"}).json()
    assert r["priority_source"] == "rules"
    ev = client.get(f"{API}/defects/{first['id']}").json()["events"]
    assert [e["event_type"] for e in ev].count("priority_changed") == 2


def test_extent_rules_are_configurable(client, make_asset):
    aid = make_asset()
    client.put(f"{API}/settings/priority_rules", json={"value": {"extent_rules": [
        {"category": "suspected_crack", "field": "width_mm", "gte": 0.3, "priority": "critical"}]}})
    d = client.post(f"{API}/defects", json={"asset_id": aid, "component_id": f"{aid}-C1", "category": "suspected_crack",
                                            "measured_extent": {"width_mm": 0.5, "method": "crack gauge"}}).json()
    assert d["priority"] == "critical"
    assert client.put(f"{API}/settings/priority_rules", json={"value": {"category_base": {"other": "bogus"}}}).status_code == 422


def test_filter_by_priority_and_sort(seeded_client):
    allp = seeded_client.get(f"{API}/defects", params={"asset_id": "DEMO-BRIDGE-01"}).json()
    assert allp
    high = seeded_client.get(f"{API}/defects", params=[("asset_id", "DEMO-BRIDGE-01"), ("priority", "high"), ("priority", "critical")]).json()
    assert high and all(d["priority"] in ("high", "critical") for d in high)
    assert len(high) == sum(d["priority"] in ("high", "critical") for d in allp)
    order = ["unassessed", "low", "medium", "high", "critical"]
    ranks = [order.index(d["priority"]) for d in allp]
    assert ranks == sorted(ranks, reverse=True)
    cat = seeded_client.get(f"{API}/defects", params={"asset_id": "DEMO-BRIDGE-01", "category": "suspected_crack"}).json()
    assert cat and all(d["category"] == "suspected_crack" for d in cat)
    comp = seeded_client.get(f"{API}/defects", params={"component_id": "DECK-S09", "sort": "observed_asc"}).json()
    assert [d["observed_at"] for d in comp] == sorted(d["observed_at"] for d in comp)
    assert seeded_client.get(f"{API}/defects", params={"sort": "nope"}).status_code == 400


def test_review_status_workflow(client, make_asset):
    aid = make_asset()
    d = client.post(f"{API}/defects", json={"asset_id": aid, "component_id": f"{aid}-C1", "category": "suspected_crack"}).json()
    assert client.patch(f"{API}/defects/{d['id']}", json={"review_status": "bogus"}).status_code == 422
    r = client.patch(f"{API}/defects/{d['id']}", json={"review_status": "confirmed", "notes": "seen on site", "actor": "eng"})
    assert r.status_code == 200 and r.json()["review_status"] == "confirmed"
    types = [e["event_type"] for e in client.get(f"{API}/defects/{d['id']}").json()["events"]]
    assert types[0] == "created" and "status_changed" in types and "note" in types


def test_spatial_projection(seeded_client):
    r = seeded_client.post(f"{API}/spatial/project", json={"camera_id": "CAM-01", "component_id": "GIR-M-S", "u": 960, "v": 540})
    assert r.status_code == 200
    p = r.json()
    assert p["method"] == "camera_ray_aabb" and p["location_confidence"] == "low" and not p["intrinsics_calibrated"]
    bbox = next(c for c in seeded_client.get(f"{API}/assets/DEMO-BRIDGE-01/components").json() if c["id"] == "GIR-M-S")["bbox"]
    assert all(bbox["min"][i] - 1e-6 <= p["position"][i] <= bbox["max"][i] + 1e-6 for i in range(3))
    miss = seeded_client.post(f"{API}/spatial/project", json={"camera_id": "CAM-01", "component_id": "ABT-E", "u": 960, "v": 540})
    assert miss.status_code == 400


def test_geotagged_filter(client, make_asset):
    aid = make_asset()
    base = {"asset_id": aid, "component_id": f"{aid}-C1", "category": "suspected_crack"}
    near = client.post(f"{API}/defects", json={**base, "latitude": 12.97, "longitude": 77.59}).json()
    client.post(f"{API}/defects", json={**base, "latitude": 13.50, "longitude": 77.59})
    client.post(f"{API}/defects", json=base)  # not geotagged
    got = client.get(f"{API}/defects", params={"near_lat": 12.9701, "near_lon": 77.5901, "radius_m": 200}).json()
    assert [d["id"] for d in got] == [near["id"]]
    assert client.get(f"{API}/defects", params={"near_lat": 12.97}).status_code == 400
