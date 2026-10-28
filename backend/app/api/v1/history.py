from __future__ import annotations

import math
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_or_404, get_session
from app.models import Baseline, Component, Defect, DefectEvent, Device, EventLog, ImageRecord, Inspection, VibrationFeature
from app.schemas import BaselineOut, DefectEventOut, DefectOut, EventOut, ImageOut, InspectionOut
from app.timeutil import ensure_utc

router = APIRouter(tags=["history"])


@router.get("/events", response_model=list[EventOut])
def events(asset_id: str | None = None, component_id: str | None = None, device_id: str | None = None,
           event_type: list[str] | None = Query(None), start: datetime | None = None, end: datetime | None = None,
           limit: int = Query(300, le=5000), db: Session = Depends(get_session)):
    q = db.query(EventLog)
    if asset_id:
        q = q.filter(EventLog.asset_id == asset_id)
    if component_id:
        q = q.filter(EventLog.component_id == component_id)
    if device_id:
        q = q.filter(EventLog.device_id == device_id)
    if event_type:
        q = q.filter(EventLog.event_type.in_(event_type))
    if start:
        q = q.filter(EventLog.ts >= ensure_utc(start))
    if end:
        q = q.filter(EventLog.ts <= ensure_utc(end))
    return q.order_by(EventLog.ts.desc(), EventLog.id.desc()).limit(limit).all()


@router.get("/history/components/{component_id}")
def component_history(component_id: str, start: datetime | None = None, end: datetime | None = None, db: Session = Depends(get_session)):
    comp = get_or_404(db, Component, component_id, "Component")
    iq = db.query(Inspection).filter(Inspection.component_id == component_id)
    dq = db.query(Defect).filter(Defect.component_id == component_id)
    if start:
        iq, dq = iq.filter(Inspection.observed_at >= ensure_utc(start)), dq.filter(Defect.observed_at >= ensure_utc(start))
    if end:
        iq, dq = iq.filter(Inspection.observed_at <= ensure_utc(end)), dq.filter(Defect.observed_at <= ensure_utc(end))
    insps = iq.order_by(Inspection.observed_at).all()
    defects = dq.order_by(Defect.observed_at).all()
    imgs = {i.id: i for i in db.query(ImageRecord).filter(ImageRecord.id.in_([x.image_id for x in insps if x.image_id])).all()}
    status_events = db.query(DefectEvent).filter(DefectEvent.defect_id.in_([d.id for d in defects])).order_by(DefectEvent.created_at).all()
    return {
        "component": {"id": comp.id, "name": comp.name, "component_type": comp.component_type},
        "inspections": [{**InspectionOut.model_validate(i).model_dump(), "image": ImageOut.model_validate(imgs[i.image_id]).model_dump() if i.image_id in imgs else None} for i in insps],
        "defects": [DefectOut.model_validate(d) for d in defects],
        "defect_events": [{**DefectEventOut.model_validate(e).model_dump(), "defect_id": e.defect_id} for e in status_events],
    }


@router.get("/history/compare")
def compare(a: str, b: str, db: Session = Depends(get_session)):
    """Side-by-side comparison of two inspections. Images are NOT spatially registered."""
    ia, ib = get_or_404(db, Inspection, a, "Inspection"), get_or_404(db, Inspection, b, "Inspection")
    out = []
    for i in (ia, ib):
        img = db.get(ImageRecord, i.image_id) if i.image_id else None
        out.append({"inspection": InspectionOut.model_validate(i), "image": ImageOut.model_validate(img) if img else None,
                    "defects": [DefectOut.model_validate(d) for d in db.query(Defect).filter(Defect.inspection_id == i.id).all()]})
    same_comp = ia.component_id == ib.component_id
    return {
        "items": out,
        "same_component": same_comp,
        "same_camera": bool(ia.device_id and ia.device_id == ib.device_id),
        "days_apart": abs((ib.observed_at - ia.observed_at).total_seconds()) / 86400,
        "image_registration": "not_performed",
        "note": "Images are shown side by side without spatial registration; apparent differences may be due to viewpoint, lighting or framing.",
    }


@router.get("/history/repeated")
def repeated(asset_id: str, radius_m: float = Query(3.0, gt=0, le=50), db: Session = Depends(get_session)):
    """Groups findings of the same category on the same component (and within radius when both have surface positions)."""
    defects = db.query(Defect).filter(Defect.asset_id == asset_id, Defect.review_status != "false_positive").order_by(Defect.observed_at).all()
    clusters: list[list[Defect]] = []
    for d in defects:
        placed = False
        for c in clusters:
            ref = c[0]
            if ref.component_id != d.component_id or ref.category != d.category:
                continue
            if None not in (ref.pos_x, d.pos_x) and math.dist((ref.pos_x, ref.pos_y, ref.pos_z), (d.pos_x, d.pos_y, d.pos_z)) > radius_m:
                continue
            c.append(d)
            placed = True
            break
        if not placed:
            clusters.append([d])
    groups = [c for c in clusters if len(c) > 1]
    return [{"component_id": c[0].component_id, "category": c[0].category, "count": len(c),
             "first_observed": c[0].observed_at, "last_observed": c[-1].observed_at,
             "defects": [DefectOut.model_validate(d) for d in c]} for c in groups]


@router.get("/history/vibration")
def vibration_history(device_id: str, source: str | None = Query(None, pattern="^(real|uploaded|simulated)$"), start: datetime | None = None,
                      end: datetime | None = None, bucket_s: int = Query(0, ge=0, le=86400), db: Session = Depends(get_session)):
    dev = get_or_404(db, Device, device_id, "Device")
    q = db.query(VibrationFeature).filter(VibrationFeature.device_id == device_id)
    if source:
        q = q.filter(VibrationFeature.source == source)
    if start:
        q = q.filter(VibrationFeature.window_start >= ensure_utc(start))
    if end:
        q = q.filter(VibrationFeature.window_end <= ensure_utc(end))
    feats = q.order_by(VibrationFeature.window_start).all()
    if not feats:
        series = []
    elif bucket_s:
        buckets: dict = {}
        for f in feats:
            k = (f.source, int(f.window_start.timestamp()) // bucket_s * bucket_s)
            buckets.setdefault(k, []).append(f)
        series = [{"t": datetime.fromtimestamp(t, tz=fs[0].window_start.tzinfo), "source": s, "rms_dyn": sum(f.rms_dyn for f in fs) / len(fs),
                   "peak_dyn": max(f.peak_dyn for f in fs), "anomalies": sum(f.anomaly for f in fs), "windows": len(fs)} for (s, t), fs in sorted(buckets.items(), key=lambda kv: kv[0][1])]
    else:
        series = [{"t": f.window_start, "source": f.source, "rms_dyn": f.rms_dyn, "peak_dyn": f.peak_dyn, "anomalies": int(f.anomaly), "windows": 1,
                   "baseline_version": f.baseline_version, "data_quality": f.data_quality} for f in feats]
    bls = db.query(Baseline).filter(Baseline.device_id == device_id).order_by(Baseline.created_at).all()
    if not dev:
        raise HTTPException(404)
    return {"device_id": device_id, "series": series, "baselines": [BaselineOut.model_validate(b) for b in bls]}
