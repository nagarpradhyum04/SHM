"""Alert engine: evaluates observations against configurable rules and raises
traceable, deduplicated alerts with evidence and an audit trail.

Deduplication: while an alert with the same ``dedup_key`` is open or
acknowledged, new occurrences are appended to it (occurrence count + evidence).
Cooldown: after an alert is resolved, re-occurrences within the rule's
``cooldown_s`` are recorded on the resolved alert instead of raising a new one.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import Alert, AlertEvent, AlertEvidence, AlertRule, Component, Defect, Device, VibrationFeature
from app.services.events import broadcaster, log_event
from app.services.priority import SYNTHETIC, apply_priority, evidence_class
from app.timeutil import utcnow

DEFAULT_RULES: list[dict] = [
    {"rule_type": "new_visual_defect", "name": "New visual defect", "priority": "medium", "cooldown_s": 3600,
     "description": "A new visual finding (AI or manual) was recorded on a component. Alert priority follows the finding's review priority when assessed.", "params": {}},
    {"rule_type": "vibration_anomaly", "name": "Vibration anomaly", "priority": "medium", "cooldown_s": 1800,
     "description": "A vibration feature window exceeded its baseline threshold (see feature thresholds). A spike alone is not evidence of structural damage.", "params": {}},
    {"rule_type": "repeated_observation", "name": "Repeated observation", "priority": "medium", "cooldown_s": 86400,
     "description": "The same defect category was observed repeatedly on the same component (priority rule R5).", "params": {}},
    {"rule_type": "combined_visual_vibration", "name": "Combined visual + vibration review", "priority": "high", "cooldown_s": 86400,
     "description": "A visual finding and a vibration anomaly were recorded for the same component within the configured window.", "params": {"window_hours": 24}},
    {"rule_type": "camera_unavailable", "name": "Camera unavailable", "priority": "low", "cooldown_s": 3600,
     "description": "A real camera that previously reported has not been seen within the offline threshold.", "params": {}},
    {"rule_type": "sensor_offline", "name": "Sensor offline", "priority": "medium", "cooldown_s": 3600,
     "description": "A real sensor has not reported within the offline threshold. Missing data is not evidence of normal condition.", "params": {}},
    {"rule_type": "stale_data", "name": "Stale data", "priority": "low", "cooldown_s": 1800,
     "description": "A real sensor's latest reading is older than the stale threshold.", "params": {}},
    {"rule_type": "image_quality", "name": "Image-quality issue", "priority": "low", "cooldown_s": 3600,
     "description": "An inspection image was flagged by the quality heuristics (blur/exposure/contrast).", "params": {}},
    {"rule_type": "data_validation_failure", "name": "Data validation failure", "priority": "low", "cooldown_s": 1800,
     "description": "Incoming sensor data failed validation (malformed, duplicate or out-of-range).", "params": {}},
]

ACTIVE = ("open", "acknowledged")


def ensure_default_rules(db: Session) -> None:
    existing = {r.rule_type for r in db.query(AlertRule).all()}
    for r in DEFAULT_RULES:
        if r["rule_type"] not in existing:
            db.add(AlertRule(id=f"RULE-{r['rule_type'].upper()}", **r))
    db.flush()


@dataclass
class Evidence:
    evidence_type: str
    ref_id: str | None
    summary: str
    data: dict | None = None


def raise_alert(
    db: Session,
    *,
    rule_type: str,
    asset_id: str,
    dedup_key: str,
    title: str,
    message: str,
    evidence: list[Evidence],
    component_id: str | None = None,
    device_id: str | None = None,
    priority: str | None = None,
    data_source: str = "real",
    now=None,
) -> tuple[Alert | None, str]:
    """Returns (alert, outcome) where outcome is created | deduplicated | suppressed_cooldown | rule_disabled."""
    now = now or utcnow()
    db.flush()  # dedup/cooldown queries must see pending changes in this session
    rule = db.query(AlertRule).filter(AlertRule.rule_type == rule_type).one_or_none()
    if rule is None or not rule.enabled:
        return None, "rule_disabled"
    prio = priority if priority and priority != "unassessed" else rule.priority

    existing = (
        db.query(Alert).filter(Alert.dedup_key == dedup_key, Alert.status.in_(ACTIVE)).order_by(Alert.created_at.desc()).first()
    )
    if existing:
        existing.occurrence_count += 1
        existing.last_seen_at = now
        if _rank(prio) > _rank(existing.priority):
            db.add(AlertEvent(alert_id=existing.id, event_type="priority_raised", note=f"{existing.priority} → {prio}", created_at=now))
            existing.priority = prio
        _add_evidence(db, existing, evidence, now)
        db.add(AlertEvent(alert_id=existing.id, event_type="repeated_occurrence", note=message, created_at=now))
        broadcaster.publish("alerts", {"asset_id": asset_id})
        return existing, "deduplicated"

    recent_resolved = (
        db.query(Alert)
        .filter(Alert.dedup_key == dedup_key, Alert.status == "resolved", Alert.resolved_at >= now - timedelta(seconds=rule.cooldown_s))
        .order_by(Alert.resolved_at.desc())
        .first()
    )
    if recent_resolved:
        recent_resolved.occurrence_count += 1
        recent_resolved.last_seen_at = now
        _add_evidence(db, recent_resolved, evidence, now)
        db.add(AlertEvent(alert_id=recent_resolved.id, event_type="suppressed_during_cooldown", note=message, created_at=now))
        return recent_resolved, "suppressed_cooldown"

    alert = Alert(
        id=new_id("ALT"),
        rule_id=rule.id,
        rule_type=rule_type,
        rule_version=rule.version,
        rule_snapshot={"name": rule.name, "params": rule.params, "cooldown_s": rule.cooldown_s, "default_priority": rule.priority},
        asset_id=asset_id,
        component_id=component_id,
        device_id=device_id,
        title=title,
        message=message,
        priority=prio,
        status="open",
        dedup_key=dedup_key,
        first_seen_at=now,
        last_seen_at=now,
        data_source=data_source,
        created_at=now,
    )
    db.add(alert)
    db.flush()
    _add_evidence(db, alert, evidence, now)
    db.add(AlertEvent(alert_id=alert.id, event_type="created", to_status="open", actor="alert-engine", note=f"Rule {rule.name} v{rule.version}", created_at=now))
    log_event(
        db, event_type="alert_raised", title=title, asset_id=asset_id, component_id=component_id, device_id=device_id,
        ref_type="alert", ref_id=alert.id, priority=prio, data_source=data_source, ts=now,
    )
    broadcaster.publish("alerts", {"asset_id": asset_id, "alert_id": alert.id})
    return alert, "created"


def _rank(p: str) -> int:
    from app.services.settings_store import PRIORITY_LEVELS

    return PRIORITY_LEVELS.index(p) if p in PRIORITY_LEVELS else 0


def _add_evidence(db: Session, alert: Alert, evidence: list[Evidence], now) -> None:
    for ev in evidence:
        db.add(AlertEvidence(alert_id=alert.id, evidence_type=ev.evidence_type, ref_id=ev.ref_id, summary=ev.summary, data=ev.data, created_at=now))


def transition(db: Session, alert: Alert, action: str, actor: str | None, note: str | None = None, assigned_to: str | None = None) -> Alert:
    now = utcnow()
    before = alert.status
    if action == "acknowledge":
        if alert.status != "open":
            raise ValueError("Only open alerts can be acknowledged.")
        alert.status = "acknowledged"
        alert.acknowledged_by = actor
        alert.acknowledged_at = now
    elif action == "resolve":
        if alert.status == "resolved":
            raise ValueError("Alert is already resolved.")
        if not note:
            raise ValueError("Resolution notes are required.")
        alert.status = "resolved"
        alert.resolved_by = actor
        alert.resolved_at = now
        alert.resolution_notes = note
    elif action == "reopen":
        if alert.status != "resolved":
            raise ValueError("Only resolved alerts can be reopened.")
        alert.status = "open"
        alert.resolved_at = None
    elif action == "assign":
        alert.assigned_to = assigned_to
        alert.follow_up_action = note
    else:
        raise ValueError(f"Unknown action {action}")
    db.add(AlertEvent(alert_id=alert.id, event_type=action, from_status=before, to_status=alert.status, actor=actor, note=note or assigned_to, created_at=now))
    if action in ("acknowledge", "resolve", "reopen"):
        log_event(db, event_type=f"alert_{action}d" if action != "reopen" else "alert_reopened", title=f"{alert.title} — {action}d by {actor or 'unknown'}",
                  asset_id=alert.asset_id, component_id=alert.component_id, ref_type="alert", ref_id=alert.id, priority=alert.priority, actor=actor, ts=now)
    broadcaster.publish("alerts", {"asset_id": alert.asset_id, "alert_id": alert.id})
    return alert


# ----------------------------------------------------------------------------- triggers


def on_defect_recorded(db: Session, defect: Defect) -> list[tuple[Alert | None, str]]:
    results = []
    comp = db.get(Component, defect.component_id) if defect.component_id else None
    where = comp.name if comp else "unassigned component"
    if defect.category != "vibration_anomaly":
        results.append(
            raise_alert(
                db,
                rule_type="new_visual_defect",
                asset_id=defect.asset_id,
                component_id=defect.component_id,
                dedup_key=f"new_visual_defect:{defect.asset_id}:{defect.component_id}",
                title=(f"New {defect.category.replace('_', ' ')} on {where}" if defect.category not in ("other", "unclassified")
                       else f"New {defect.category} observation on {where}"),
                message=f"{defect.id} recorded via {defect.detection_source} (priority {defect.priority}).",
                evidence=[Evidence("defect", defect.id, f"{defect.category} — {defect.priority}", {"image_id": defect.image_id, "inspection_id": defect.inspection_id})],
                priority=defect.priority,
                data_source=defect.data_source,
                now=defect.created_at,
            )
        )
    for item in defect.priority_rationale or []:
        if item.get("rule") == "R5 repeated_observation":
            results.append(
                raise_alert(
                    db, rule_type="repeated_observation", asset_id=defect.asset_id, component_id=defect.component_id,
                    dedup_key=f"repeated_observation:{defect.component_id}:{defect.category}",
                    title=f"Repeated {defect.category.replace('_', ' ')} observations on {where}",
                    message=item["detail"],
                    evidence=[Evidence("defect", defect.id, "latest observation")] + [Evidence("defect", r, "earlier observation") for r in item.get("refs", [])],
                    priority=defect.priority, data_source=defect.data_source, now=defect.created_at,
                )
            )
        if item.get("rule") == "R6 vibration_corroboration":
            results.append(_combined_alert(db, defect, item.get("refs", []), item["detail"]))
    return results


def _combined_alert(db: Session, defect: Defect, feature_refs: list[str], detail: str):
    comp = db.get(Component, defect.component_id) if defect.component_id else None
    return raise_alert(
        db, rule_type="combined_visual_vibration", asset_id=defect.asset_id, component_id=defect.component_id,
        dedup_key=f"combined_visual_vibration:{defect.component_id}",
        title=f"Visual finding and vibration anomaly on {comp.name if comp else defect.component_id}",
        message=detail + " Engineering review recommended; this is not a failure prediction.",
        evidence=[Evidence("defect", defect.id, f"{defect.category} ({defect.data_source})")] + [Evidence("vibration_feature", r, "anomalous window") for r in feature_refs],
        data_source=defect.data_source, now=defect.created_at,
    )


def on_feature_anomaly(db: Session, feature: VibrationFeature, device: Device) -> list:
    results = [
        raise_alert(
            db, rule_type="vibration_anomaly", asset_id=device.asset_id, component_id=device.component_id, device_id=device.id,
            dedup_key=f"vibration_anomaly:{device.id}:{feature.source}",
            title=f"Vibration anomaly at {device.name}" + (" (SIMULATED)" if feature.source == "simulated" else ""),
            message=f"Window {feature.window_start:%H:%M:%S}–{feature.window_end:%H:%M:%S}: "
                    f"rms_dyn={feature.rms_dyn:.4f} g, ratio to baseline v{feature.baseline_version}={feature.baseline_ratio:.2f}. "
                    f"Reasons: {', '.join(feature.anomaly_reasons or [])}.",
            evidence=[Evidence("vibration_feature", f"VF-{feature.id}", "anomalous feature window",
                               {"thresholds": feature.thresholds, "feature_version": feature.feature_version, "baseline_id": feature.baseline_id})],
            data_source=feature.source, now=feature.window_end,
        )
    ]
    log_event(db, event_type="sensor_anomaly", title=f"Vibration anomaly — {device.name}", asset_id=device.asset_id, component_id=device.component_id,
              device_id=device.id, ref_type="vibration_feature", ref_id=f"VF-{feature.id}", data_source=feature.source, ts=feature.window_end)
    # Re-evaluate visual findings on the same component (corroboration rule R6).
    if device.component_id:
        rule = db.query(AlertRule).filter(AlertRule.rule_type == "combined_visual_vibration").one()
        window = timedelta(hours=(rule.params or {}).get("window_hours", 24))
        cls = evidence_class(feature.source)
        defects = (
            db.query(Defect)
            .filter(Defect.component_id == device.component_id, Defect.observed_at >= feature.window_start - window,
                    Defect.observed_at <= feature.window_end + window, Defect.category != "vibration_anomaly",
                    Defect.review_status.notin_(["false_positive", "closed", "repaired"]))
            .all()
        )
        for d in defects:
            if evidence_class(d.data_source) != cls:
                continue
            if apply_priority(db, d):
                from app.models import DefectEvent

                db.add(DefectEvent(defect_id=d.id, event_type="priority_changed", to_value=d.priority, actor="rules-engine",
                                   note="Recomputed after corroborating vibration anomaly."))
            results.append(_combined_alert(db, d, [f"VF-{feature.id}"], f"Vibration anomaly VF-{feature.id} within the corroboration window."))
    return results


def on_image_quality(db: Session, *, asset_id: str, component_id: str | None, device_id: str | None, inspection_id: str, image_id: str,
                     quality: dict, data_source: str):
    return raise_alert(
        db, rule_type="image_quality", asset_id=asset_id, component_id=component_id, device_id=device_id,
        dedup_key=f"image_quality:{device_id or component_id or asset_id}",
        title="Inspection image quality issue", message=f"Issues: {', '.join(quality['issues'])}. Results from this image may be unreliable.",
        evidence=[Evidence("inspection", inspection_id, "inspection"), Evidence("image", image_id, "image", quality)], data_source=data_source,
    )


def on_validation_failure(db: Session, device: Device, errors: list[str], source: str):
    return raise_alert(
        db, rule_type="data_validation_failure", asset_id=device.asset_id, component_id=device.component_id, device_id=device.id,
        dedup_key=f"data_validation_failure:{device.id}", title=f"Data validation failure — {device.name}",
        message="; ".join(errors[:5]) + (f" (+{len(errors) - 5} more)" if len(errors) > 5 else ""),
        evidence=[Evidence("device", device.id, f"{len(errors)} rejected item(s)", {"errors": errors[:20]})], data_source=source,
    )


def evaluate_device_status(db: Session, now=None) -> list:
    """Periodic check: offline/stale real devices raise alerts. Simulated devices never do."""
    from app.services.device_status import connection_status

    now = now or utcnow()
    results = []
    for dev in db.query(Device).filter(Device.operational_status == "active").all():
        if dev.data_source in SYNTHETIC:
            continue
        st = connection_status(db, dev, now)
        if st["status"] == "offline":
            rule = "camera_unavailable" if dev.device_type == "camera" else "sensor_offline"
            results.append(raise_alert(db, rule_type=rule, asset_id=dev.asset_id, component_id=dev.component_id, device_id=dev.id,
                                       dedup_key=f"{rule}:{dev.id}", title=f"{dev.name} offline",
                                       message=f"Last seen {st['age_s']:.0f} s ago. No data is being received; the structure's condition is unknown, not normal.",
                                       evidence=[Evidence("device", dev.id, st["status"], st)], now=now))
        elif st["status"] == "stale" and dev.device_type != "camera":
            results.append(raise_alert(db, rule_type="stale_data", asset_id=dev.asset_id, component_id=dev.component_id, device_id=dev.id,
                                       dedup_key=f"stale_data:{dev.id}", title=f"Stale data from {dev.name}",
                                       message=f"Latest reading is {st['age_s']:.0f} s old.", evidence=[Evidence("device", dev.id, st["status"], st)], now=now))
    return results
