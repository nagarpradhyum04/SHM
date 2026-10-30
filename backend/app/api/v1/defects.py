from __future__ import annotations

import math
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_or_404, get_session
from app.api.v1.cameras import clip_out
from app.models import MediaClip
from app.models import AlertEvidence, Component, Defect, DefectEvent, Device, ImageRecord, Inspection
from app.schemas import DefectEventOut, DefectIn, DefectOut, DefectPatch, ImageOut, InspectionOut, ProjectionIn
from app.services.operations import DomainError, create_defect, update_defect
from app.services.priority import compute_priority, find_repeats
from app.services.settings_store import PRIORITY_LEVELS, get_setting
from app.services.spatial import SpatialMappingError, project_pixel_to_component
from app.timeutil import ensure_utc

router = APIRouter(tags=["defects"])

SORTS = {
    "observed_desc": Defect.observed_at.desc(),
    "observed_asc": Defect.observed_at.asc(),
    "component": Defect.component_id.asc(),
    "category": Defect.category.asc(),
    "status": Defect.review_status.asc(),
    "source": Defect.detection_source.asc(),
}


def filter_defects(db: Session, *, asset_id=None, priority=None, category=None, review_status=None, component_id=None,
                   detection_source=None, data_source=None, start=None, end=None, sort="priority", near=None):
    q = db.query(Defect)
    if asset_id:
        q = q.filter(Defect.asset_id == asset_id)
    if priority:
        q = q.filter(Defect.priority.in_(priority))
    if category:
        q = q.filter(Defect.category.in_(category))
    if review_status:
        q = q.filter(Defect.review_status.in_(review_status))
    if component_id:
        q = q.filter(Defect.component_id.in_(component_id))
    if detection_source:
        q = q.filter(Defect.detection_source.in_(detection_source))
    if data_source:
        q = q.filter(Defect.data_source.in_(data_source))
    if start:
        q = q.filter(Defect.observed_at >= ensure_utc(start))
    if end:
        q = q.filter(Defect.observed_at <= ensure_utc(end))
    if near:
        lat, lon, radius_m = near
        dlat = radius_m / 111_320.0
        dlon = radius_m / (111_320.0 * max(math.cos(math.radians(lat)), 1e-6))
        q = q.filter(Defect.latitude.between(lat - dlat, lat + dlat), Defect.longitude.between(lon - dlon, lon + dlon))
    if sort == "priority":
        rows = q.order_by(Defect.observed_at.desc()).all()
        return sorted(rows, key=lambda d: -PRIORITY_LEVELS.index(d.priority) if d.priority in PRIORITY_LEVELS else 0)
    if sort not in SORTS:
        raise HTTPException(400, f"Unknown sort '{sort}'")
    return q.order_by(SORTS[sort]).all()


@router.get("/defects", response_model=list[DefectOut])
def list_defects(asset_id: str | None = None, priority: list[str] | None = Query(None), category: list[str] | None = Query(None),
                 review_status: list[str] | None = Query(None), component_id: list[str] | None = Query(None),
                 detection_source: list[str] | None = Query(None), data_source: list[str] | None = Query(None),
                 start: datetime | None = None, end: datetime | None = None, sort: str = "priority",
                 near_lat: float | None = Query(None, ge=-90, le=90), near_lon: float | None = Query(None, ge=-180, le=180),
                 radius_m: float = Query(500, gt=0, le=100_000), db: Session = Depends(get_session)):
    """Filter findings. ``near_lat``/``near_lon``/``radius_m`` select geotagged findings (bounding-box approximation of the radius);
    findings without geographic coordinates are excluded from location filtering."""
    if (near_lat is None) != (near_lon is None):
        raise HTTPException(400, "near_lat and near_lon must be given together")
    near = (near_lat, near_lon, radius_m) if near_lat is not None else None
    return filter_defects(db, asset_id=asset_id, priority=priority, category=category, review_status=review_status, component_id=component_id,
                          detection_source=detection_source, data_source=data_source, start=start, end=end, sort=sort, near=near)


@router.post("/defects", response_model=DefectOut, status_code=201)
def create(body: DefectIn, db: Session = Depends(get_session)):
    data = body.model_dump(exclude={"actor"})
    data["detection_source"] = "manual"
    data["data_source"] = "uploaded"
    if body.inspection_id:
        insp = get_or_404(db, Inspection, body.inspection_id, "Inspection")
        data["data_source"] = insp.data_source
        data["image_id"] = data.get("image_id") or insp.image_id
    elif body.image_id:
        data["data_source"] = get_or_404(db, ImageRecord, body.image_id, "Image").data_source
    try:
        d = create_defect(db, data, actor=body.actor)
    except DomainError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return d


@router.get("/defects/{defect_id}")
def detail(defect_id: str, db: Session = Depends(get_session)):
    d = get_or_404(db, Defect, defect_id, "Defect")
    comp = db.get(Component, d.component_id) if d.component_id else None
    img = db.get(ImageRecord, d.image_id) if d.image_id else None
    insp = db.get(Inspection, d.inspection_id) if d.inspection_id else None
    events = db.query(DefectEvent).filter(DefectEvent.defect_id == d.id).order_by(DefectEvent.created_at).all()
    rules = get_setting(db, "priority_rules")
    related = find_repeats(db, d, {**rules, "repeat_window_days": 3650})
    later = db.query(Defect).filter(Defect.related_defect_id == d.id).all()
    alert_ids = sorted({e.alert_id for e in db.query(AlertEvidence).filter(AlertEvidence.ref_id == d.id).all()})
    camera = db.get(Device, insp.device_id) if insp and insp.device_id else None
    return {
        "defect": DefectOut.model_validate(d),
        "component": {"id": comp.id, "name": comp.name, "component_type": comp.component_type} if comp else None,
        "image": ImageOut.model_validate(img) if img else None,
        "inspection": InspectionOut.model_validate(insp) if insp else None,
        "camera": {"id": camera.id, "name": camera.name} if camera else None,
        "events": [DefectEventOut.model_validate(e) for e in events],
        "related": [DefectOut.model_validate(r) for r in related + later],
        "alert_ids": alert_ids,
        "clips": [clip_out(c) for c in db.query(MediaClip).filter(MediaClip.inspection_id == d.inspection_id).all()] if d.inspection_id else [],
    }


@router.patch("/defects/{defect_id}", response_model=DefectOut)
def patch(defect_id: str, body: DefectPatch, db: Session = Depends(get_session)):
    d = get_or_404(db, Defect, defect_id, "Defect")
    changes = body.model_dump(exclude_unset=True, exclude={"actor"})
    try:
        update_defect(db, d, changes, body.actor)
    except DomainError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return d


@router.post("/defects/{defect_id}/recompute-priority", response_model=DefectOut)
def recompute(defect_id: str, db: Session = Depends(get_session)):
    d = get_or_404(db, Defect, defect_id, "Defect")
    level, rationale = compute_priority(db, d)
    if d.priority_source == "rules" and level != d.priority:
        db.add(DefectEvent(defect_id=d.id, event_type="priority_changed", from_value=d.priority, to_value=level, actor="rules-engine"))
    if d.priority_source == "rules":
        d.priority, d.priority_rationale = level, rationale
    db.commit()
    return d


@router.post("/spatial/project")
def project(body: ProjectionIn, db: Session = Depends(get_session)):
    """Project an image pixel from a registered camera onto a component (approximate, see spatial module docs)."""
    cam = get_or_404(db, Device, body.camera_id, "Camera")
    comp = get_or_404(db, Component, body.component_id, "Component")
    try:
        return project_pixel_to_component(cam, comp, body.u, body.v)
    except SpatialMappingError as exc:
        raise HTTPException(400, str(exc)) from exc
