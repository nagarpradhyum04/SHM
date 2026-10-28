from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_or_404, get_session
from app.ids import new_id
from app.models import Alert, Asset, Component, Defect, Device, Inspection
from app.schemas import AssetIn, AssetOut, AssetPatch, ComponentIn, ComponentOut, ComponentPatch, DefectOut, DeviceOut, InspectionOut
from app.services.device_status import connection_status
from app.services.events import log_event
from app.services.settings_store import get_setting
from app.services.spatial import model_to_geo
from app.timeutil import utcnow

router = APIRouter(tags=["assets"])

OPEN_REVIEW = ["new", "under_review", "confirmed", "monitoring"]


@router.get("/assets", response_model=list[AssetOut])
def list_assets(db: Session = Depends(get_session)):
    return db.query(Asset).order_by(Asset.is_demo.desc(), Asset.name).all()


@router.post("/assets", response_model=AssetOut, status_code=201)
def create_asset(body: AssetIn, db: Session = Depends(get_session)):
    aid = body.id or new_id("AST")
    if db.get(Asset, aid):
        raise HTTPException(409, f"Asset {aid} already exists")
    data = body.model_dump(exclude={"id"})
    if body.geo_transform:
        data["geo_transform"] = body.geo_transform.model_dump()
    asset = Asset(id=aid, **data)
    db.add(asset)
    log_event(db, event_type="asset_created", title=f"Asset {asset.name} registered", asset_id=aid, ref_type="asset", ref_id=aid)
    db.commit()
    return asset


@router.get("/assets/{asset_id}", response_model=AssetOut)
def get_asset(asset_id: str, db: Session = Depends(get_session)):
    return get_or_404(db, Asset, asset_id, "Asset")


@router.patch("/assets/{asset_id}", response_model=AssetOut)
def patch_asset(asset_id: str, body: AssetPatch, db: Session = Depends(get_session)):
    asset = get_or_404(db, Asset, asset_id, "Asset")
    changes = body.model_dump(exclude_unset=True)
    if "geo_transform" in changes and body.geo_transform is not None:
        changes["geo_transform"] = body.geo_transform.model_dump()
    for k, v in changes.items():
        setattr(asset, k, v)
    log_event(db, event_type="config_changed", title=f"Asset {asset.name} updated", asset_id=asset_id, data={"fields": sorted(changes)})
    db.commit()
    return asset


@router.get("/assets/{asset_id}/summary")
def asset_summary(asset_id: str, db: Session = Depends(get_session)):
    """Metrics computed from stored records only. ``None`` means no data (not zero risk)."""
    get_or_404(db, Asset, asset_id, "Asset")
    comps = sum(1 for (g,) in db.query(Component.geometry).filter(Component.asset_id == asset_id).all() if not g or g.get("type") != "group")
    insp_q = db.query(Inspection).filter(Inspection.asset_id == asset_id)
    last_insp = insp_q.order_by(Inspection.observed_at.desc()).first()
    open_q = db.query(Defect).filter(Defect.asset_id == asset_id, Defect.review_status.in_(OPEN_REVIEW))
    by_prio = dict(db.query(Defect.priority, func.count()).filter(Defect.asset_id == asset_id, Defect.review_status.in_(OPEN_REVIEW)).group_by(Defect.priority).all())
    devices = db.query(Device).filter(Device.asset_id == asset_id).all()
    th = get_setting(db, "device_status")
    statuses = [connection_status(db, d, thresholds=th) for d in devices]
    count = lambda *s: sum(1 for x in statuses if x["status"] in s)  # noqa: E731
    alerts = dict(db.query(Alert.status, func.count()).filter(Alert.asset_id == asset_id).group_by(Alert.status).all())
    high_alerts = db.query(func.count()).select_from(Alert).filter(Alert.asset_id == asset_id, Alert.status != "resolved",
                                                                  Alert.priority.in_(["high", "critical"])).scalar()
    sources = dict(db.query(Defect.data_source, func.count()).filter(Defect.asset_id == asset_id).group_by(Defect.data_source).all())
    return {
        "asset_id": asset_id,
        "components": comps,
        "inspections": insp_q.count(),
        "inspections_last_30d": insp_q.filter(Inspection.observed_at >= utcnow() - timedelta(days=30)).count(),
        "latest_inspection_at": last_insp.observed_at if last_insp else None,
        "open_findings": open_q.count(),
        "open_by_priority": by_prio,
        "high_priority_reviews": by_prio.get("high", 0) + by_prio.get("critical", 0),
        "devices_total": len(devices),
        "devices_online_real": count("online"),
        "devices_stale": count("stale"),
        "devices_offline": count("offline"),
        "devices_never_connected": count("never_connected"),
        "devices_simulated": count("simulated", "simulated_idle"),
        "alerts_open": alerts.get("open", 0),
        "alerts_acknowledged": alerts.get("acknowledged", 0),
        "alerts_high_unresolved": high_alerts,
        "finding_sources": sources,
    }


@router.get("/assets/{asset_id}/components", response_model=list[ComponentOut])
def list_components(asset_id: str, db: Session = Depends(get_session)):
    get_or_404(db, Asset, asset_id, "Asset")
    return db.query(Component).filter(Component.asset_id == asset_id).order_by(Component.id).all()


@router.post("/assets/{asset_id}/components", response_model=ComponentOut, status_code=201)
def create_component(asset_id: str, body: ComponentIn, db: Session = Depends(get_session)):
    get_or_404(db, Asset, asset_id, "Asset")
    if db.get(Component, body.id):
        raise HTTPException(409, f"Component {body.id} already exists")
    if body.parent_id:
        parent = get_or_404(db, Component, body.parent_id, "Parent component")
        if parent.asset_id != asset_id:
            raise HTTPException(400, "Parent component belongs to a different asset")
    comp = Component(asset_id=asset_id, **body.model_dump())
    db.add(comp)
    db.commit()
    return comp


@router.get("/components/{component_id}")
def component_detail(component_id: str, db: Session = Depends(get_session)):
    comp = get_or_404(db, Component, component_id, "Component")
    asset = db.get(Asset, comp.asset_id)
    children = db.query(Component).filter(Component.parent_id == component_id).all()
    ids = [component_id] + [c.id for c in children]
    devices = db.query(Device).filter(Device.component_id.in_(ids)).all()
    defects = db.query(Defect).filter(Defect.component_id.in_(ids)).order_by(Defect.observed_at.desc()).all()
    insps = db.query(Inspection).filter(Inspection.component_id.in_(ids)).order_by(Inspection.observed_at.desc()).limit(50).all()
    th = get_setting(db, "device_status")
    geo = None
    if comp.latitude is not None:
        geo = {"latitude": comp.latitude, "longitude": comp.longitude, "method": comp.geo_method or "recorded"}
    elif asset:
        derived = model_to_geo(asset, comp.model_x, comp.model_z)
        if derived:
            geo = {**derived, "method": "derived:" + derived["method"]}
    return {
        "component": ComponentOut.model_validate(comp),
        "children": [ComponentOut.model_validate(c) for c in children],
        "devices": [DeviceOut.model_validate(d).model_copy(update={"connection": connection_status(db, d, thresholds=th)}) for d in devices],
        "defects": [DefectOut.model_validate(d) for d in defects],
        "inspections": [InspectionOut.model_validate(i) for i in insps],
        "geo": geo,
        "coordinate_note": "model_x/y/z are local 3D model coordinates (metres, Y-up), not geographic coordinates.",
    }


@router.patch("/components/{component_id}", response_model=ComponentOut)
def patch_component(component_id: str, body: ComponentPatch, db: Session = Depends(get_session)):
    comp = get_or_404(db, Component, component_id, "Component")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(comp, k, v)
    db.commit()
    return comp
