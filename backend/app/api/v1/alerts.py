from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_or_404, get_session
from app.models import Alert, AlertEvent, AlertEvidence, AlertRule
from app.schemas import AlertActionIn, AlertEventOut, AlertEvidenceOut, AlertOut, AlertRuleOut, AlertRulePatch
from app.services import alert_engine
from app.services.events import log_event
from app.services.settings_store import PRIORITY_LEVELS
from app.timeutil import ensure_utc

router = APIRouter(tags=["alerts"])


@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(asset_id: str | None = None, status: list[str] | None = Query(None), priority: list[str] | None = Query(None),
                rule_type: list[str] | None = Query(None), component_id: str | None = None, start: datetime | None = None,
                end: datetime | None = None, limit: int = Query(500, le=5000), db: Session = Depends(get_session)):
    q = db.query(Alert)
    if asset_id:
        q = q.filter(Alert.asset_id == asset_id)
    if status:
        q = q.filter(Alert.status.in_(status))
    if priority:
        q = q.filter(Alert.priority.in_(priority))
    if rule_type:
        q = q.filter(Alert.rule_type.in_(rule_type))
    if component_id:
        q = q.filter(Alert.component_id == component_id)
    if start:
        q = q.filter(Alert.last_seen_at >= ensure_utc(start))
    if end:
        q = q.filter(Alert.first_seen_at <= ensure_utc(end))
    rows = q.order_by(Alert.last_seen_at.desc()).limit(limit).all()
    order = {"open": 0, "acknowledged": 1, "resolved": 2}
    return sorted(rows, key=lambda a: (order.get(a.status, 3), -PRIORITY_LEVELS.index(a.priority) if a.priority in PRIORITY_LEVELS else 0))


@router.get("/alerts/{alert_id}")
def alert_detail(alert_id: str, db: Session = Depends(get_session)):
    a = get_or_404(db, Alert, alert_id, "Alert")
    ev = db.query(AlertEvidence).filter(AlertEvidence.alert_id == a.id).order_by(AlertEvidence.created_at).all()
    hist = db.query(AlertEvent).filter(AlertEvent.alert_id == a.id).order_by(AlertEvent.created_at, AlertEvent.id).all()
    return {"alert": AlertOut.model_validate(a), "evidence": [AlertEvidenceOut.model_validate(e) for e in ev],
            "history": [AlertEventOut.model_validate(h) for h in hist]}


def _act(alert_id: str, action: str, body: AlertActionIn, db: Session):
    a = get_or_404(db, Alert, alert_id, "Alert")
    try:
        alert_engine.transition(db, a, action, body.actor, body.note, body.assigned_to)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return AlertOut.model_validate(a)


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertOut)
def acknowledge(alert_id: str, body: AlertActionIn, db: Session = Depends(get_session)):
    return _act(alert_id, "acknowledge", body, db)


@router.post("/alerts/{alert_id}/resolve", response_model=AlertOut)
def resolve(alert_id: str, body: AlertActionIn, db: Session = Depends(get_session)):
    return _act(alert_id, "resolve", body, db)


@router.post("/alerts/{alert_id}/reopen", response_model=AlertOut)
def reopen(alert_id: str, body: AlertActionIn, db: Session = Depends(get_session)):
    return _act(alert_id, "reopen", body, db)


@router.post("/alerts/{alert_id}/assign", response_model=AlertOut)
def assign(alert_id: str, body: AlertActionIn, db: Session = Depends(get_session)):
    return _act(alert_id, "assign", body, db)


@router.get("/alert-rules", response_model=list[AlertRuleOut])
def rules(db: Session = Depends(get_session)):
    return db.query(AlertRule).order_by(AlertRule.rule_type).all()


@router.patch("/alert-rules/{rule_id}", response_model=AlertRuleOut)
def patch_rule(rule_id: str, body: AlertRulePatch, db: Session = Depends(get_session)):
    r = get_or_404(db, AlertRule, rule_id, "Alert rule")
    changes = body.model_dump(exclude_unset=True, exclude={"actor"})
    for k, v in changes.items():
        setattr(r, k, v)
    r.version += 1
    log_event(db, event_type="config_changed", title=f"Alert rule '{r.name}' updated to v{r.version}", actor=body.actor, data=changes)
    db.commit()
    return r


@router.post("/alerts/evaluate")
def evaluate(db: Session = Depends(get_session)):
    res = alert_engine.evaluate_device_status(db)
    db.commit()
    return {"evaluated": len(res), "outcomes": [o for _, o in res]}
