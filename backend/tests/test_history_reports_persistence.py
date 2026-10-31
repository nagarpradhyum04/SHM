from datetime import timedelta

from app.timeutil import utcnow

API = "/api/v1"


def test_history_endpoints(seeded_client):
    h = seeded_client.get(f"{API}/history/components/DECK-S09").json()
    assert len(h["inspections"]) >= 3 and len(h["defects"]) == 3
    assert all(i["image"] for i in h["inspections"])
    ids = [i["id"] for i in h["inspections"]]
    cmp = seeded_client.get(f"{API}/history/compare", params={"a": ids[0], "b": ids[-1]}).json()
    assert cmp["image_registration"] == "not_performed" and cmp["same_component"] and cmp["days_apart"] > 90
    rep = seeded_client.get(f"{API}/history/repeated", params={"asset_id": "DEMO-BRIDGE-01"}).json()
    assert any(g["component_id"] == "DECK-S09" and g["count"] == 3 for g in rep)
    vib = seeded_client.get(f"{API}/history/vibration", params={"device_id": "ACC-03", "source": "simulated"}).json()
    assert vib["series"] and vib["baselines"] and all(s["source"] == "simulated" for s in vib["series"])
    old = seeded_client.get(f"{API}/events", params={"asset_id": "DEMO-BRIDGE-01", "end": (utcnow() - timedelta(days=50)).isoformat()}).json()
    assert old and all(e["ts"] < (utcnow() - timedelta(days=50)).isoformat() for e in old)
    recent = seeded_client.get(f"{API}/events", params={"asset_id": "DEMO-BRIDGE-01", "event_type": "alert_raised"}).json()
    assert recent and all(e["event_type"] == "alert_raised" for e in recent)


def test_pdf_report_generation(seeded_client):
    now = utcnow()
    r = seeded_client.post(f"{API}/reports", json={"asset_id": "DEMO-BRIDGE-01", "period_start": (now - timedelta(days=120)).isoformat(),
                                                   "period_end": (now + timedelta(minutes=1)).isoformat(), "actor": "eng"})
    assert r.status_code == 201, r.text
    rep = r.json()
    assert rep["includes_simulated"] and rep["summary"]["defects"] == 10
    assert any("SIMULATED" in w for w in rep["summary"]["warnings"])
    pdf = seeded_client.get(f"{API}/reports/{rep['id']}/download")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content[:5] == b"%PDF-"
    assert len(pdf.content) > 20_000
    html = seeded_client.get(f"{API}/reports/{rep['id']}/print").text
    assert "Limitations" in html and "RUL prediction unavailable" in html and rep["id"] in html
    assert seeded_client.post(f"{API}/reports", json={"asset_id": "DEMO-BRIDGE-01", "period_start": now.isoformat(),
                                                      "period_end": (now - timedelta(days=1)).isoformat()}).status_code == 400


def test_empty_report_has_no_invented_content(client, make_asset):
    aid = make_asset()
    now = utcnow()
    rep = client.post(f"{API}/reports", json={"asset_id": aid, "period_start": (now - timedelta(days=1)).isoformat(),
                                              "period_end": now.isoformat()}).json()
    assert rep["summary"]["defects"] == 0 and not rep["includes_simulated"]
    assert client.get(f"{API}/reports/{rep['id']}/download").content[:5] == b"%PDF-"


def test_persistence_across_restart(env):
    from fastapi.testclient import TestClient

    from app.db import get_database, set_database
    from app.main import create_app

    with TestClient(create_app()) as c:
        c.post(f"{API}/assets", json={"id": "P1", "name": "persist"})
        c.post(f"{API}/assets/P1/components", json={"id": "P1-C", "name": "c", "component_type": "deck_segment"})
        d = c.post(f"{API}/defects", json={"asset_id": "P1", "component_id": "P1-C", "category": "suspected_crack"}).json()
    get_database().dispose()
    set_database(None)  # simulate process restart: new engine, same file
    with TestClient(create_app()) as c:
        got = c.get(f"{API}/defects/{d['id']}").json()
        assert got["defect"]["category"] == "suspected_crack"
        assert c.get(f"{API}/alerts", params={"asset_id": "P1"}).json()
        assert c.get(f"{API}/assets/P1").status_code == 200


def test_rul_is_unavailable_without_inputs(seeded_client):
    # component level: fatigue method states exactly which engineering inputs are missing
    r = seeded_client.post(f"{API}/rul/estimate", json={"asset_id": "DEMO-BRIDGE-01", "component_id": "DECK-S09"}).json()
    assert r["status"] == "unavailable" and r["estimate"] is None
    assert "stress-per-g" in r["message"] and "detail category" in r["message"]
    # asset level: input-coverage summary only, never a number
    a = seeded_client.post(f"{API}/rul/estimate", json={"asset_id": "DEMO-BRIDGE-01"}).json()
    assert a["status"] == "unavailable" and a["message"] == "RUL prediction unavailable: insufficient validated data."
    cov = a["input_coverage"]["time_series_structural_measurements"]
    assert cov["available"] is False and "simulated" in cov["by_source"]


def test_system_status_and_settings(seeded_client):
    s = seeded_client.get(f"{API}/system/status").json()
    assert s["database"]["ok"] and s["storage"]["ok"] and s["models"]["available"] is False
    assert s["security"]["user_authentication"] == "not_implemented"
    assert s["real_data_configured"] is False and s["readings_by_source"].get("simulated")
    r = seeded_client.put(f"{API}/settings/data_source", json={"value": {"mode": "real"}})
    assert r.json()["mode"] == "real"
    assert seeded_client.put(f"{API}/settings/data_source", json={"value": {"mode": "fake"}}).status_code == 422
    assert seeded_client.put(f"{API}/settings/nope", json={"value": 1}).status_code == 404


def test_migrations_match_models(env):
    """The Alembic head must match the ORM models (no un-migrated schema changes)."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.db import Base, get_database
    from app.migrate import upgrade_to_head

    upgrade_to_head(get_database().url)
    with get_database().engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []
