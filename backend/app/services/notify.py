"""Alert messages: Telegram, email, SMS (Twilio) and webhooks (JSON / Discord / Slack / ntfy).

Flow: ``raise_alert`` → ``enqueue_for_alert`` writes one pending ``NotificationLog`` row per enabled,
configured channel (same transaction as the alert) → the background loop calls ``dispatch_pending``,
which sends with retries (1 min, 5 min) so a slow or failing provider never blocks detection.

Messages carry the crack coordinates that are known: pixel region in the photo, 3D model coordinates
with the localisation method/confidence, and GPS when the structure has a model-to-world transform.
Simulated/demo alerts are not sent unless ``include_simulated`` is enabled.
"""
from __future__ import annotations

import base64
import json
import logging
import smtplib
import ssl
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import timedelta
from email.message import EmailMessage

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Alert, AlertEvidence, Asset, Component, Defect, Device, ImageRecord, NotificationLog
from app.services.settings_store import PRIORITY_LEVELS, get_setting, set_setting
from app.services.storage import get_storage
from app.timeutil import utcnow

log = logging.getLogger(__name__)

CHANNELS = ("telegram", "email", "sms", "webhook")
SECRET_KEY = "notification_secrets"
SECRET_FIELDS = {
    "telegram": ["telegram_bot_token", "telegram_chat_ids"],
    "email": ["smtp_host", "smtp_port", "smtp_security", "smtp_user", "smtp_password", "smtp_from", "smtp_to"],
    "sms": ["twilio_account_sid", "twilio_auth_token", "twilio_from", "twilio_to"],
    "webhook": ["webhook_url", "webhook_format"],
}
SENSITIVE = {"telegram_bot_token", "smtp_password", "twilio_auth_token", "webhook_url"}
REQUIRED = {
    "telegram": ["telegram_bot_token", "telegram_chat_ids"],
    "email": ["smtp_host", "smtp_from", "smtp_to"],
    "sms": ["twilio_account_sid", "twilio_auth_token", "twilio_from", "twilio_to"],
    "webhook": ["webhook_url"],
}
METHOD_LABELS = {
    "camera_ray_mesh": "camera ray on the surface mesh",
    "camera_ray_aabb": "camera ray on the bounding box (approx.)",
    "manual_surface_pick": "point picked on the model",
    "manual_component": "part only",
    "photogrammetry": "photogrammetry",
    "survey": "survey",
}
RETRY_DELAYS = [timedelta(minutes=1), timedelta(minutes=5)]
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1


# ----------------------------------------------------------------------------- configuration


def effective_config(db: Session) -> dict:
    """Secrets from the database (entered in Settings) override environment variables."""
    s = get_settings()
    stored = get_setting(db, SECRET_KEY) or {}
    cfg = {}
    for fields in SECRET_FIELDS.values():
        for f in fields:
            v = stored.get(f)
            cfg[f] = v if v not in (None, "") else getattr(s, f, None)
    return cfg


def configured(cfg: dict) -> dict[str, bool]:
    return {ch: all(cfg.get(f) not in (None, "") for f in REQUIRED[ch]) for ch in CHANNELS}


def _mask(field: str, value) -> str | None:
    if value in (None, ""):
        return None
    if field in SENSITIVE:
        v = str(value)
        return "••••" + v[-4:] if len(v) > 8 else "••••"
    return str(value)


def public_config(db: Session) -> dict:
    cfg = effective_config(db)
    return {
        "preferences": get_setting(db, "notifications"),
        "configured": configured(cfg),
        "fields": {ch: {f: _mask(f, cfg.get(f)) for f in fields} for ch, fields in SECRET_FIELDS.items()},
    }


def save_secrets(db: Session, values: dict, actor: str | None) -> None:
    """Empty strings leave a stored value unchanged; null clears it."""
    allowed = {f for fields in SECRET_FIELDS.values() for f in fields}
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f"Unknown fields: {sorted(unknown)}")
    stored = dict(get_setting(db, SECRET_KEY) or {})
    for k, v in values.items():
        if v is None:
            stored.pop(k, None)
        elif v != "":
            stored[k] = v
    set_setting(db, SECRET_KEY, stored, actor=actor)


# ----------------------------------------------------------------------------- message content


def _rank(p: str) -> int:
    return PRIORITY_LEVELS.index(p) if p in PRIORITY_LEVELS else 0


def _alert_defect(db: Session, alert: Alert) -> Defect | None:
    ev = (db.query(AlertEvidence).filter(AlertEvidence.alert_id == alert.id, AlertEvidence.evidence_type == "defect")
          .order_by(AlertEvidence.id.desc()).first())
    return db.get(Defect, ev.ref_id) if ev and ev.ref_id else None


def build_message(db: Session, alert: Alert) -> dict:
    asset = db.get(Asset, alert.asset_id)
    comp = db.get(Component, alert.component_id) if alert.component_id else None
    dev = db.get(Device, alert.device_id) if alert.device_id else None
    d = _alert_defect(db, alert)
    sim = alert.data_source in ("simulated", "demo")
    lines = [f"{'[SIMULATED] ' if sim else ''}[{alert.priority.upper()}] {alert.title}",
             f"Structure: {asset.name if asset else alert.asset_id}"]
    if comp:
        lines.append(f"Part: {comp.name} ({comp.id})")
    if dev:
        lines.append(f"Device: {dev.name} ({dev.id})")
    lines.append(f"Time: {alert.last_seen_at:%Y-%m-%d %H:%M:%S} UTC")
    coords: dict = {}
    image_bytes = None
    if d is not None:
        region = d.image_region or {}
        if region.get("bbox"):
            x0, y0, x1, y1 = region["bbox"]
            cx, cy = region.get("point_px") or [(x0 + x1) / 2, (y0 + y1) / 2]
            lines.append(f"Crack in photo: x {x0:.0f}–{x1:.0f}, y {y0:.0f}–{y1:.0f} px (centre {cx:.0f}, {cy:.0f})")
            coords["image_px"] = {"bbox": [x0, y0, x1, y1], "centre": [cx, cy]}
        if d.pos_x is not None:
            lines.append(f"On 3D model: ({d.pos_x:.2f}, {d.pos_y:.2f}, {d.pos_z:.2f}) m local · {METHOD_LABELS.get(d.localization_method, d.localization_method)} · "
                         f"location confidence {d.location_confidence}")
            coords["model_m"] = [d.pos_x, d.pos_y, d.pos_z]
            coords["method"], coords["confidence"] = d.localization_method, d.location_confidence
        elif d.component_id:
            lines.append("On 3D model: part known, exact position on it unknown")
        if d.latitude is not None:
            lines.append(f"GPS: {d.latitude:.6f}, {d.longitude:.6f} https://maps.google.com/?q={d.latitude},{d.longitude}")
            coords["gps"] = [d.latitude, d.longitude]
        if d.model_confidence is not None:
            lines.append(f"AI: {d.category.replace('_', ' ')}, confidence {d.model_confidence:.2f} ({d.model_id} v{d.model_version})")
        if d.image_id:
            img = db.get(ImageRecord, d.image_id)
            if img and get_storage().exists(img.storage_key):
                raw = get_storage().read(img.storage_key)
                try:  # photo with the crack box and coordinates drawn on it
                    from app.services.annotate import annotate

                    image_bytes = (annotate(raw, d), "image/jpeg")
                except ValueError:
                    image_bytes = (raw, img.content_type)
    elif alert.message:
        lines.append(alert.message[:400])
    url = f"{get_settings().public_dashboard_url.rstrip('/')}/alerts?id={alert.id}"
    lines += [f"Alert {alert.id}: {url}", "Automated screening alert — requires engineering review."]
    return {"subject": lines[0][:300], "text": "\n".join(lines), "image": image_bytes, "url": url, "coordinates": coords,
            "alert": {"id": alert.id, "rule": alert.rule_type, "priority": alert.priority, "status": alert.status,
                      "asset_id": alert.asset_id, "component_id": alert.component_id, "device_id": alert.device_id,
                      "data_source": alert.data_source, "defect_id": d.id if d else None}}


# ----------------------------------------------------------------------------- enqueue / dispatch


def enqueue_for_alert(db: Session, alert: Alert, reason: str = "created") -> list[NotificationLog]:
    prefs = get_setting(db, "notifications")
    if not prefs.get("enabled"):
        return []
    if _rank(alert.priority) < _rank(prefs.get("min_priority", "high")):
        return []
    if alert.data_source in ("simulated", "demo") and not prefs.get("include_simulated"):
        return []
    rules = prefs.get("rule_types") or []
    if rules and alert.rule_type not in rules:
        return []
    ok = configured(effective_config(db))
    rows = []
    for ch in CHANNELS:
        if prefs.get("channels", {}).get(ch) and ok[ch]:
            row = NotificationLog(alert_id=alert.id, channel=ch, subject=f"{reason}: {alert.title}"[:300])
            db.add(row)
            rows.append(row)
    return rows


def _http(req: urllib.request.Request, timeout=15) -> bytes:
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    b = uuid.uuid4().hex
    parts = [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()]
    for k, (name, data, ctype) in files.items():
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\nContent-Type: {ctype}\r\n\r\n'.encode() + data + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={b}"


def send_telegram(cfg: dict, msg: dict) -> None:
    base = f"{get_settings().telegram_api_base.rstrip('/')}/bot{cfg['telegram_bot_token']}"
    for chat in [c.strip() for c in str(cfg["telegram_chat_ids"]).split(",") if c.strip()]:
        if msg.get("image"):
            data, ctype = msg["image"]
            body, ct = _multipart({"chat_id": chat, "caption": msg["text"][:1024]}, {"photo": ("crack." + ctype.split("/")[-1], data, ctype)})
            _http(urllib.request.Request(f"{base}/sendPhoto", data=body, method="POST", headers={"Content-Type": ct}))
            if len(msg["text"]) > 1024:
                _http(urllib.request.Request(f"{base}/sendMessage", data=json.dumps({"chat_id": chat, "text": msg["text"]}).encode(),
                                             method="POST", headers={"Content-Type": "application/json"}))
        else:
            _http(urllib.request.Request(f"{base}/sendMessage", data=json.dumps({"chat_id": chat, "text": msg["text"], "disable_web_page_preview": True}).encode(),
                                         method="POST", headers={"Content-Type": "application/json"}))


def send_email(cfg: dict, msg: dict) -> None:
    em = EmailMessage()
    em["Subject"] = f"StructuraSense: {msg['subject']}"
    em["From"] = cfg["smtp_from"]
    em["To"] = ", ".join(a.strip() for a in str(cfg["smtp_to"]).split(","))
    em.set_content(msg["text"])
    if msg.get("image"):
        data, ctype = msg["image"]
        main, sub = ctype.split("/")
        em.add_attachment(data, maintype=main, subtype=sub, filename=f"crack.{sub}")
    port = int(cfg.get("smtp_port") or 587)
    security = (cfg.get("smtp_security") or "starttls").lower()
    if security == "ssl":
        server = smtplib.SMTP_SSL(cfg["smtp_host"], port, timeout=20, context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(cfg["smtp_host"], port, timeout=20)
        if security == "starttls":
            server.starttls(context=ssl.create_default_context())
    try:
        if cfg.get("smtp_user"):
            server.login(cfg["smtp_user"], cfg["smtp_password"] or "")
        server.send_message(em)
    finally:
        server.quit()


def send_sms(cfg: dict, msg: dict) -> None:
    base = get_settings().twilio_api_base.rstrip("/")
    url = f"{base}/2010-04-01/Accounts/{cfg['twilio_account_sid']}/Messages.json"
    auth = base64.b64encode(f"{cfg['twilio_account_sid']}:{cfg['twilio_auth_token']}".encode()).decode()
    text = msg["text"]
    short = "\n".join(line for line in text.splitlines() if not line.startswith("Automated"))[:600]
    for to in [t.strip() for t in str(cfg["twilio_to"]).split(",") if t.strip()]:
        body = urllib.parse.urlencode({"From": cfg["twilio_from"], "To": to, "Body": short}).encode()
        _http(urllib.request.Request(url, data=body, method="POST", headers={"Authorization": f"Basic {auth}",
                                                                              "Content-Type": "application/x-www-form-urlencoded"}))


def send_webhook(cfg: dict, msg: dict) -> None:
    fmt = (cfg.get("webhook_format") or "json").lower()
    if fmt == "discord":
        data, ct = json.dumps({"content": msg["text"][:1900]}).encode(), "application/json"
    elif fmt == "slack":
        data, ct = json.dumps({"text": msg["text"]}).encode(), "application/json"
    elif fmt == "ntfy":
        data, ct = msg["text"].encode(), "text/plain; charset=utf-8"
    else:
        payload = {k: v for k, v in msg.items() if k != "image"}
        data, ct = json.dumps(payload, default=str).encode(), "application/json"
    headers = {"Content-Type": ct}
    if fmt == "ntfy":
        headers.update({"Title": msg["subject"][:200].encode("ascii", "ignore").decode(), "Click": msg["url"]})
    _http(urllib.request.Request(cfg["webhook_url"], data=data, method="POST", headers=headers))


SENDERS = {"telegram": send_telegram, "email": send_email, "sms": send_sms, "webhook": send_webhook}


def _error_text(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        try:
            body = exc.read()[:300].decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            body = ""
        return f"HTTP {exc.code}: {body}"
    return f"{type(exc).__name__}: {exc}"[:500]


def deliver(db: Session, row: NotificationLog, cfg: dict) -> None:
    now = utcnow()
    row.attempts += 1
    try:
        if row.is_test:
            msg = {"subject": "Test message", "text": "StructuraSense AI test message — notifications are working.",
                   "image": None, "url": get_settings().public_dashboard_url, "coordinates": {}, "alert": None}
        else:
            alert = db.get(Alert, row.alert_id)
            if alert is None:
                raise ValueError("alert no longer exists")
            msg = build_message(db, alert)
        SENDERS[row.channel](cfg, msg)
        row.status, row.sent_at, row.error = "sent", now, None
    except Exception as exc:  # noqa: BLE001 - recorded and retried
        row.error = _error_text(exc)
        if row.attempts >= MAX_ATTEMPTS or row.is_test:
            row.status = "failed"
        else:
            row.next_attempt_at = now + RETRY_DELAYS[row.attempts - 1]
        log.warning("notification %s via %s failed: %s", row.id, row.channel, row.error)


def dispatch_pending(db: Session, now=None, limit: int = 20) -> int:
    now = now or utcnow()
    rows = (db.query(NotificationLog).filter(NotificationLog.status == "pending", NotificationLog.next_attempt_at <= now)
            .order_by(NotificationLog.id).limit(limit).all())
    if not rows:
        return 0
    cfg = effective_config(db)
    for row in rows:
        deliver(db, row, cfg)
    db.flush()
    return len(rows)


def send_test(db: Session, channel: str) -> NotificationLog:
    if channel not in CHANNELS:
        raise ValueError("unknown channel")
    cfg = effective_config(db)
    if not configured(cfg)[channel]:
        raise ValueError(f"{channel} is not configured (missing: {', '.join(f for f in REQUIRED[channel] if not cfg.get(f))})")
    row = NotificationLog(channel=channel, subject="Test message", is_test=True)
    db.add(row)
    db.flush()
    deliver(db, row, cfg)
    return row
