from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.models import NotificationLog
from app.services import notify
from app.services.events import log_event
from app.services.settings_store import PRIORITY_LEVELS, get_setting, set_setting

router = APIRouter(tags=["notifications"])


class NotificationConfigIn(BaseModel):
    preferences: dict | None = None
    secrets: dict | None = None
    actor: str | None = None


@router.get("/notifications/config")
def get_config(db: Session = Depends(get_session)):
    """Preferences plus which channels are configured. Secrets are masked and never returned."""
    return notify.public_config(db)


@router.put("/notifications/config")
def put_config(body: NotificationConfigIn, db: Session = Depends(get_session)):
    if body.preferences is not None:
        prefs = {**get_setting(db, "notifications"), **body.preferences}
        if prefs["min_priority"] not in PRIORITY_LEVELS:
            raise HTTPException(422, "min_priority must be a priority level")
        if set(prefs.get("channels", {})) - set(notify.CHANNELS):
            raise HTTPException(422, f"channels must be among {notify.CHANNELS}")
        set_setting(db, "notifications", prefs, actor=body.actor)
    if body.secrets is not None:
        try:
            notify.save_secrets(db, body.secrets, body.actor)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    log_event(db, event_type="config_changed", title="Notification settings updated", actor=body.actor)
    db.commit()
    return notify.public_config(db)


@router.post("/notifications/test")
def test(channel: str = Query(..., pattern="^(telegram|email|sms|webhook)$"), db: Session = Depends(get_session)):
    """Send a test message now on one channel and report the provider's answer."""
    try:
        row = notify.send_test(db, channel)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return {"channel": channel, "status": row.status, "error": row.error}


@router.get("/notifications/log")
def delivery_log(limit: int = Query(50, le=500), db: Session = Depends(get_session)):
    rows = db.query(NotificationLog).order_by(NotificationLog.id.desc()).limit(limit).all()
    return [{"id": r.id, "alert_id": r.alert_id, "channel": r.channel, "status": r.status, "attempts": r.attempts, "error": r.error,
             "subject": r.subject, "is_test": r.is_test, "created_at": r.created_at, "sent_at": r.sent_at} for r in rows]
