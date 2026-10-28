"""Domain operations shared by the API and the demo seeder."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import Component, Defect, DefectEvent, Device, ImageRecord, Inspection
from app.services import alert_engine
from app.services.events import broadcaster, log_event
from app.services.imaging import ValidatedImage, assess_quality
from app.services.inference import ModelUnavailableError, get_model_registry
from app.services.priority import apply_priority
from app.services.settings_store import get_setting
from app.services.spatial import METHODS
from app.services.storage import get_storage
from app.timeutil import utcnow

REVIEW_STATUSES = ["new", "under_review", "confirmed", "monitoring", "false_positive", "repaired", "closed"]


class DomainError(ValueError):
    pass


def store_image(db: Session, img: ValidatedImage, *, asset_id: str, component_id: str | None, device_id: str | None,
                data_source: str, original_filename: str | None, captured_at: datetime | None) -> ImageRecord:
    rec_id = new_id("IMG")
    key = f"images/{asset_id}/{rec_id}.{img.extension}"
    get_storage().save(key, img.data)
    rec = ImageRecord(
        id=rec_id, asset_id=asset_id, component_id=component_id, device_id=device_id, storage_key=key,
        original_filename=(original_filename or "")[:255] or None, content_type=img.content_type, width=img.width, height=img.height,
        size_bytes=len(img.data), sha256=img.sha256, data_source=data_source, quality=assess_quality(img.bgr), captured_at=captured_at,
    )
    db.add(rec)
    db.flush()
    return rec


def run_image_inspection(db: Session, img: ValidatedImage, *, asset_id: str, component_id: str | None, device_id: str | None = None,
                         data_source: str = "uploaded", original_filename: str | None = None, observed_at: datetime | None = None,
                         performed_by: str | None = None, notes: str | None = None) -> tuple[Inspection, list[Defect]]:
    """Validate associations, store the image, run the configured model if any, record the inspection
    and create AI findings. Never fabricates a prediction when no model is installed."""
    _check_assoc(db, asset_id, component_id, device_id)
    observed_at = observed_at or utcnow()
    image = store_image(db, img, asset_id=asset_id, component_id=component_id, device_id=device_id, data_source=data_source,
                        original_filename=original_filename, captured_at=observed_at)
    insp = Inspection(id=new_id("INS"), asset_id=asset_id, component_id=component_id, device_id=device_id, image_id=image.id,
                      inspection_type="camera_capture" if device_id else "image_upload", data_source=data_source,
                      performed_by=performed_by, notes=notes, observed_at=observed_at)
    defects: list[Defect] = []
    registry = get_model_registry()
    try:
        model = registry.get((get_setting(db, "active_model") or {}).get("model_id"))
    except ModelUnavailableError as exc:
        insp.status = "model_unavailable"
        insp.inference_output = {"status": "model_unavailable", "message": str(exc)}
        model = None
    if model is not None:
        try:
            result = model.predict(img.bgr)
            insp.status = "completed"
            insp.model_id, insp.model_version = result.model_id, result.model_version
            insp.inference_output = result.to_dict()
            insp.inference_ms = result.inference_ms
        except Exception as exc:  # noqa: BLE001 - recorded, surfaced
            insp.status = "inference_failed"
            insp.inference_output = {"status": "inference_failed", "error": str(exc)}
            result = None
    db.add(insp)
    db.flush()
    log_event(db, event_type="inspection", title=f"Image inspection {insp.id} ({insp.status.replace('_', ' ')})", asset_id=asset_id,
              component_id=component_id, device_id=device_id, ref_type="inspection", ref_id=insp.id, data_source=data_source, ts=observed_at)
    if model is not None and insp.status == "completed":
        for det in result.detections:
            defects.append(create_defect(db, {
                "asset_id": asset_id, "component_id": component_id, "inspection_id": insp.id, "image_id": image.id,
                "category": det.category, "detection_source": "ai_model", "description": f"AI {result.task}: '{det.label}'",
                "observed_at": observed_at, "model_id": result.model_id, "model_version": result.model_version, "model_label": det.label,
                "model_confidence": det.confidence, "image_region": {"bbox": det.bbox} if det.bbox else None,
                "location_kind": "component", "localization_method": "manual_component", "data_source": data_source,
            }, actor="inference"))
    if not image.quality["ok"]:
        alert_engine.on_image_quality(db, asset_id=asset_id, component_id=component_id, device_id=device_id, inspection_id=insp.id,
                                      image_id=image.id, quality=image.quality, data_source=data_source)
    broadcaster.publish("inspections", {"asset_id": asset_id})
    return insp, defects


def _check_assoc(db: Session, asset_id: str, component_id: str | None, device_id: str | None) -> None:
    from app.models import Asset

    if db.get(Asset, asset_id) is None:
        raise DomainError(f"Unknown asset {asset_id}")
    if component_id:
        comp = db.get(Component, component_id)
        if comp is None or comp.asset_id != asset_id:
            raise DomainError(f"Component {component_id} does not belong to asset {asset_id}")
    if device_id:
        dev = db.get(Device, device_id)
        if dev is None or dev.asset_id != asset_id:
            raise DomainError(f"Device {device_id} does not belong to asset {asset_id}")


def create_defect(db: Session, data: dict, actor: str | None = None) -> Defect:
    _check_assoc(db, data["asset_id"], data.get("component_id"), None)
    method = data.get("localization_method") or "manual_component"
    if method not in METHODS:
        raise DomainError(f"Unknown localization method {method}")
    kind = data.get("location_kind") or ("surface" if data.get("pos_x") is not None else "component")
    if kind == "surface" and any(data.get(k) is None for k in ("pos_x", "pos_y", "pos_z")):
        raise DomainError("Surface-level location requires pos_x, pos_y and pos_z.")
    if kind == "component" and not data.get("component_id"):
        raise DomainError("Component-level location requires a component_id.")
    if kind == "surface" and method == "manual_component":
        method = "manual_surface_pick"
    if data.get("detection_source") == "ai_model" and not data.get("model_id"):
        raise DomainError("AI-sourced findings must reference the model that produced them.")
    data = dict(data)
    now = data.pop("created_at", None) or utcnow()
    d = Defect(
        id=new_id("DEF", 6), created_at=now, updated_at=now,
        **{k: v for k, v in data.items() if hasattr(Defect, k) and k not in ("id", "location_kind", "localization_method", "location_confidence")},
    )
    d.location_kind = kind
    d.localization_method = method
    d.location_confidence = data.get("location_confidence") or METHODS[method]
    d.observed_at = data.get("observed_at") or now
    if data.get("priority") and data.get("priority") != "auto":
        d.priority, d.priority_source = data["priority"], "manual"
        d.priority_rationale = [{"rule": "manual", "effect": d.priority, "detail": f"Set manually by {actor or 'reviewer'}."}]
    db.add(d)
    db.flush()
    apply_priority(db, d)
    db.add(DefectEvent(defect_id=d.id, event_type="created", to_value=d.review_status, actor=actor, note=f"priority {d.priority}", created_at=now))
    log_event(db, event_type="defect_recorded", title=f"{d.category.replace('_', ' ').capitalize()} recorded ({d.id})", asset_id=d.asset_id,
              component_id=d.component_id, ref_type="defect", ref_id=d.id, priority=d.priority, data_source=d.data_source, actor=actor, ts=d.observed_at)
    alert_engine.on_defect_recorded(db, d)
    broadcaster.publish("defects", {"asset_id": d.asset_id, "defect_id": d.id})
    return d


UPDATABLE = {"review_status", "priority", "assigned_reviewer", "notes", "follow_up_actions", "description", "component_id",
             "location_kind", "pos_x", "pos_y", "pos_z", "normal_x", "normal_y", "normal_z", "localization_method",
             "location_confidence", "localization_notes", "measured_extent", "overlay", "category"}


def update_defect(db: Session, d: Defect, changes: dict, actor: str | None) -> Defect:
    now = utcnow()
    unknown = set(changes) - UPDATABLE
    if unknown:
        raise DomainError(f"Fields not updatable: {sorted(unknown)}")
    if "review_status" in changes and changes["review_status"] not in REVIEW_STATUSES:
        raise DomainError("Invalid review status")
    if "component_id" in changes and changes["component_id"]:
        _check_assoc(db, d.asset_id, changes["component_id"], None)
    if "localization_method" in changes and changes["localization_method"] not in METHODS:
        raise DomainError("Invalid localization method")
    for field, value in changes.items():
        old = getattr(d, field)
        if field == "priority":
            if value == "auto":
                d.priority_source = "rules"
                apply_priority(db, d)
                db.add(DefectEvent(defect_id=d.id, event_type="priority_changed", from_value=old, to_value=d.priority, actor=actor,
                                   note="Returned to rule-based priority", created_at=now))
                continue
            d.priority, d.priority_source = value, "manual"
            d.priority_rationale = (d.priority_rationale or []) + [{"rule": "manual", "effect": value, "detail": f"Override by {actor or 'reviewer'}."}]
        else:
            setattr(d, field, value)
        if old != value:
            etype = {"review_status": "status_changed", "priority": "priority_changed", "notes": "note"}.get(field, f"{field}_changed")
            if field.startswith(("pos_", "normal_", "location", "localization")):
                etype = "location_changed"
            db.add(DefectEvent(defect_id=d.id, event_type=etype, from_value=_s(old), to_value=_s(value), actor=actor, created_at=now))
    if "localization_method" in changes and "location_confidence" not in changes:
        d.location_confidence = METHODS[d.localization_method]
    if any(k.startswith("pos_") for k in changes) and d.pos_x is not None:
        d.location_kind = changes.get("location_kind", "surface")
    d.updated_at = now
    if "review_status" in changes:
        log_event(db, event_type="defect_status", title=f"{d.id} → {d.review_status.replace('_', ' ')}", asset_id=d.asset_id,
                  component_id=d.component_id, ref_type="defect", ref_id=d.id, priority=d.priority, actor=actor, data_source=d.data_source)
    broadcaster.publish("defects", {"asset_id": d.asset_id, "defect_id": d.id})
    return d


def _s(v) -> str | None:
    if v is None:
        return None
    s = str(v)
    return s[:200]
