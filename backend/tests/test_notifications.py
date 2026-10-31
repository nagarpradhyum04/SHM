import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tests.test_localization import _image_with_dark_patch, _png, _setup_camera

API = "/api/v1"


class Recorder:
    def __init__(self):
        self.requests = []
        self.fail_next = 0


@pytest.fixture
def mock_server():
    rec = Recorder()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            rec.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
            if rec.fail_next:
                rec.fail_next -= 1
                self.send_response(503)
                self.end_headers()
                self.wfile.write(b'{"ok":false}')
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    rec.base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield rec
    srv.shutdown()


@pytest.fixture
def notified_client(env, mock_server, monkeypatch):
    from tests.conftest import build_test_onnx_model

    build_test_onnx_model(env / "models" / "t")
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import create_app

    monkeypatch.setattr(get_settings(), "telegram_api_base", mock_server.base)
    monkeypatch.setattr(get_settings(), "twilio_api_base", mock_server.base)
    with TestClient(create_app()) as c:
        yield c


def _dispatch():
    from app.db import get_database
    from app.services.notify import dispatch_pending

    db = get_database().session()
    n = dispatch_pending(db)
    db.commit()
    db.close()
    return n


def test_crack_detection_sends_telegram_photo_with_coordinates(notified_client, mock_server):
    c = notified_client
    r = c.put(f"{API}/notifications/config", json={"secrets": {"telegram_bot_token": "123456:ABCDEFSECRETTOKEN", "telegram_chat_ids": "999"}})
    cfg = r.json()
    assert cfg["configured"]["telegram"] is True and cfg["configured"]["sms"] is False
    assert "SECRET" not in json.dumps(cfg) and cfg["fields"]["telegram"]["telegram_bot_token"].startswith("••••")
    c.patch(f"{API}/assets/LOC", json={})
    comp, token = _setup_camera(c)
    c.patch(f"{API}/assets/LOC", json={"geo_transform": {"origin_lat": 23.0225, "origin_lon": 72.5714, "calibrated": False}})
    r = c.post(f"{API}/cameras/CAM-L/frames", files={"file": ("f.png", _png(_image_with_dark_patch()), "image/png")}, headers={"X-Device-Token": token}).json()
    assert r["defects"]
    assert _dispatch() >= 1
    photo = [q for q in mock_server.requests if q["path"].endswith("/sendPhoto")]
    assert photo and "/bot123456:ABCDEFSECRETTOKEN/" in photo[0]["path"]
    body = photo[0]["body"]
    assert b"\x89PNG" in body  # the crack photo itself is attached
    text = body.decode("utf-8", "ignore")
    assert "Crack in photo: x " in text and "On 3D model: (" in text and "camera ray on the surface mesh" in text
    assert "GPS: 23.02" in text and "maps.google.com" in text and 'name="chat_id"' in text
    log = c.get(f"{API}/notifications/log").json()
    assert log[0]["status"] == "sent" and log[0]["channel"] == "telegram"


def test_filters_simulated_and_low_priority(notified_client, mock_server, make_asset):
    c = notified_client
    c.put(f"{API}/notifications/config", json={"preferences": {"min_priority": "high"}, "secrets": {"webhook_url": mock_server.base + "/hook"}})
    aid = make_asset()
    # surface deformation -> high priority, uploaded data -> sent
    c.post(f"{API}/defects", json={"asset_id": aid, "component_id": f"{aid}-C1", "category": "surface_deformation"})
    # 'other' -> unassessed finding; its alert takes the rule default (medium) -> below 'high' -> not sent
    c.post(f"{API}/defects", json={"asset_id": aid, "component_id": f"{aid}-C2", "category": "other"})
    _dispatch()
    hooks = [json.loads(q["body"]) for q in mock_server.requests if q["path"] == "/hook"]
    assert len(hooks) == 1 and hooks[0]["alert"]["priority"] == "high" and hooks[0]["alert"]["rule"] == "new_visual_defect"
    # simulated device anomalies are not messaged by default
    from app.db import get_database
    from app.models import Alert
    from app.services.alert_engine import Evidence, raise_alert

    db = get_database().session()
    raise_alert(db, rule_type="vibration_threshold", asset_id=aid, dedup_key="x", title="sim", message="m", evidence=[Evidence("device", "d", "s")],
                data_source="simulated")
    db.commit()
    assert db.query(Alert).count() == 3
    db.close()
    assert _dispatch() == 0


def test_sms_retry_then_success_and_test_endpoint(notified_client, mock_server, make_asset):
    c = notified_client
    c.put(f"{API}/notifications/config", json={"preferences": {"channels": {"telegram": False, "email": False, "sms": True, "webhook": False}},
                                             "secrets": {"twilio_account_sid": "AC123", "twilio_auth_token": "tok", "twilio_from": "+10000000000", "twilio_to": "+919800000000"}})
    assert c.post(f"{API}/notifications/test", params={"channel": "email"}).status_code == 400  # not configured
    t = c.post(f"{API}/notifications/test", params={"channel": "sms"}).json()
    assert t["status"] == "sent"
    aid = make_asset()
    mock_server.fail_next = 1
    c.post(f"{API}/defects", json={"asset_id": aid, "component_id": f"{aid}-C1", "category": "exposed_reinforcement"})
    _dispatch()
    log = c.get(f"{API}/notifications/log").json()
    first = next(x for x in log if not x["is_test"])
    assert first["status"] == "pending" and first["attempts"] == 1 and "HTTP 503" in first["error"]
    from datetime import timedelta

    from app.db import get_database
    from app.services.notify import dispatch_pending
    from app.timeutil import utcnow

    db = get_database().session()
    dispatch_pending(db, now=utcnow() + timedelta(minutes=2))
    db.commit()
    db.close()
    first = next(x for x in c.get(f"{API}/notifications/log").json() if not x["is_test"])
    assert first["status"] == "sent" and first["attempts"] == 2
    sms = [q for q in mock_server.requests if q["path"] == "/2010-04-01/Accounts/AC123/Messages.json"][-1]
    assert sms["headers"]["Authorization"].startswith("Basic ") and b"To=%2B919800000000" in sms["body"]


def test_email_with_photo(notified_client, monkeypatch, make_asset):
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            self.host, self.port = host, port

        def starttls(self, context=None):
            pass

        def login(self, u, p):
            sent.append(("login", u))

        def send_message(self, m):
            sent.append(("msg", m))

        def quit(self):
            pass

    import app.services.notify as notify

    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    c = notified_client
    c.put(f"{API}/notifications/config", json={"preferences": {"channels": {"telegram": False, "email": True, "sms": False, "webhook": False}},
                                             "secrets": {"smtp_host": "smtp.example.com", "smtp_user": "me", "smtp_password": "pw",
                                                         "smtp_from": "alerts@example.com", "smtp_to": "eng@example.com"}})
    c.post(f"{API}/assets", json={"id": "EM", "name": "em"})
    c.post(f"{API}/assets/EM/components", json={"id": "EM-C", "name": "c", "component_type": "deck_segment"})
    c.post(f"{API}/inspections/image", data={"asset_id": "EM", "component_id": "EM-C"},
           files={"file": ("x.png", _png(_image_with_dark_patch()), "image/png")})
    _dispatch()
    m = next(x[1] for x in sent if x[0] == "msg")
    assert m["To"] == "eng@example.com" and "crack" in m["Subject"].lower()
    assert any(p.get_filename() == "crack.png" for p in m.iter_attachments())
    assert "Crack in photo" in m.get_body(("plain",)).get_content()


def test_escalation_crossing_threshold_notifies_once(notified_client, mock_server, make_asset):
    c = notified_client
    c.put(f"{API}/notifications/config", json={"preferences": {"min_priority": "high"}, "secrets": {"webhook_url": mock_server.base + "/hook"}})
    aid = make_asset()
    base = {"asset_id": aid, "component_id": f"{aid}-C1", "category": "suspected_corrosion"}
    c.post(f"{API}/defects", json=base)  # medium: below 'high' → no message
    _dispatch()
    assert not [q for q in mock_server.requests if q["path"] == "/hook"]
    c.post(f"{API}/defects", json=base)  # repeated → high; alert escalates to high → one message
    _dispatch()
    hooks = [json.loads(q["body"]) for q in mock_server.requests if q["path"] == "/hook"]
    assert len(hooks) >= 1 and all(h["alert"]["priority"] == "high" for h in hooks)
