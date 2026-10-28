from datetime import timedelta

API = "/api/v1"


def test_alert_creation_dedup_and_workflow(client, make_asset):
    aid = make_asset()
    comp = f"{aid}-C1"
    for _ in range(3):
        client.post(f"{API}/defects", json={"asset_id": aid, "component_id": comp, "category": "exposed_reinforcement"})
    alerts = client.get(f"{API}/alerts", params={"asset_id": aid, "rule_type": "new_visual_defect"}).json()
    assert len(alerts) == 1 and alerts[0]["occurrence_count"] == 3  # deduplicated per component
    a = alerts[0]
    detail = client.get(f"{API}/alerts/{a['id']}").json()
    assert len([e for e in detail["evidence"] if e["evidence_type"] == "defect"]) == 3
    assert detail["alert"]["rule_snapshot"]["name"] == "New visual defect"
    # workflow + audit trail
    assert client.post(f"{API}/alerts/{a['id']}/resolve", json={"actor": "eng"}).status_code == 409  # notes required
    assert client.post(f"{API}/alerts/{a['id']}/acknowledge", json={"actor": "eng"}).json()["status"] == "acknowledged"
    assert client.post(f"{API}/alerts/{a['id']}/acknowledge", json={"actor": "eng"}).status_code == 409
    assert client.post(f"{API}/alerts/{a['id']}/assign", json={"actor": "eng", "assigned_to": "inspector", "note": "site visit"}).json()["assigned_to"] == "inspector"
    r = client.post(f"{API}/alerts/{a['id']}/resolve", json={"actor": "eng", "note": "patched"}).json()
    assert r["status"] == "resolved" and r["resolution_notes"] == "patched"
    hist = [h["event_type"] for h in client.get(f"{API}/alerts/{a['id']}").json()["history"]]
    assert hist[:1] == ["created"] and {"acknowledge", "assign", "resolve"} <= set(hist)
    # cooldown: new occurrence right after resolution does not open a new alert
    client.post(f"{API}/defects", json={"asset_id": aid, "component_id": comp, "category": "exposed_reinforcement"})
    alerts = client.get(f"{API}/alerts", params={"asset_id": aid, "rule_type": "new_visual_defect"}).json()
    assert len(alerts) == 1 and alerts[0]["status"] == "resolved"
    hist = [h["event_type"] for h in client.get(f"{API}/alerts/{a['id']}").json()["history"]]
    assert "suppressed_during_cooldown" in hist


def test_cooldown_expiry_creates_new_alert(db):
    from app.models import Asset, Component
    from app.services.alert_engine import Evidence, raise_alert
    from app.timeutil import utcnow

    db.add(Asset(id="A", name="a"))
    db.add(Component(id="A-C", asset_id="A", name="c", component_type="x"))
    db.flush()
    t0 = utcnow()
    a1, o1 = raise_alert(db, rule_type="stale_data", asset_id="A", dedup_key="k", title="t", message="m", evidence=[Evidence("device", "d", "s")], now=t0)
    assert o1 == "created"
    a1.status, a1.resolved_at = "resolved", t0
    _, o2 = raise_alert(db, rule_type="stale_data", asset_id="A", dedup_key="k", title="t", message="m", evidence=[], now=t0 + timedelta(seconds=60))
    assert o2 == "suppressed_cooldown"
    a3, o3 = raise_alert(db, rule_type="stale_data", asset_id="A", dedup_key="k", title="t", message="m", evidence=[], now=t0 + timedelta(hours=2))
    assert o3 == "created" and a3.id != a1.id


def test_disabled_rule_raises_nothing(client, make_asset):
    aid = make_asset()
    rule = next(r for r in client.get(f"{API}/alert-rules").json() if r["rule_type"] == "new_visual_defect")
    r = client.patch(f"{API}/alert-rules/{rule['id']}", json={"enabled": False, "actor": "admin"}).json()
    assert r["version"] == rule["version"] + 1
    client.post(f"{API}/defects", json={"asset_id": aid, "component_id": f"{aid}-C1", "category": "suspected_crack"})
    assert client.get(f"{API}/alerts", params={"asset_id": aid}).json() == []


def test_seeded_combined_alert_is_traceable(seeded_client):
    alerts = seeded_client.get(f"{API}/alerts", params={"asset_id": "DEMO-BRIDGE-01"}).json()
    types = {a["rule_type"] for a in alerts}
    assert {"new_visual_defect", "vibration_anomaly", "repeated_observation", "combined_visual_vibration"} <= types
    combined = next(a for a in alerts if a["rule_type"] == "combined_visual_vibration")
    ev = seeded_client.get(f"{API}/alerts/{combined['id']}").json()["evidence"]
    assert {"defect", "vibration_feature"} <= {e["evidence_type"] for e in ev}
    vib = next(a for a in alerts if a["rule_type"] == "vibration_anomaly")
    assert "SIMULATED" in vib["title"] and vib["data_source"] == "simulated"
