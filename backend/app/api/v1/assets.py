from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_or_404, get_session
from app.config import get_settings
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


# ----------------------------------------------------------------------------- uploaded 3D models

UNSUPPORTED_EXTENSIONS = {"KHR_draco_mesh_compression": "Draco", "EXT_meshopt_compression": "meshopt"}


@router.post("/assets/{asset_id}/model", status_code=201)
async def upload_model(asset_id: str, file: UploadFile = File(...), register_components: bool = Form(True), id_prefix: str = Form(""),
                       actor: str | None = Form(None), db: Session = Depends(get_session)):
    """Upload a self-contained GLB structural model. Optionally registers every named node as a component
    (mesh_ref = "gltf-node:<index>", world bounding box from the file). Re-uploading a revised model keeps
    existing component IDs (matched by node name), so findings and devices stay attached."""
    from app.services.gltf import GltfError, analyse, guess_type, parse_glb, sanitize_id
    from app.services.storage import get_storage

    asset = get_or_404(db, Asset, asset_id, "Asset")
    limit = int(get_settings().max_model_mb * 1024 * 1024)
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"Model exceeds {get_settings().max_model_mb:g} MB")
    try:
        doc = parse_glb(data)
    except GltfError as exc:
        raise HTTPException(422, str(exc)) from exc
    info = analyse(doc)
    blocked = [UNSUPPORTED_EXTENSIONS[e] for e in info["extensions_required"] if e in UNSUPPORTED_EXTENSIONS]
    if blocked:
        raise HTTPException(422, f"{', '.join(blocked)}-compressed meshes are not supported offline; re-export without mesh compression.")
    if not info["mesh_nodes"]:
        raise HTTPException(422, "The model contains no mesh nodes.")
    key = f"models/{asset_id}/{new_id('MDL')}.glb"
    get_storage().save(key, data)
    asset.model_kind, asset.model_ref, asset.model_file_key = "gltf", f"upload:{(file.filename or 'model.glb')[:200]}", key
    asset.model_meta = {"filename": file.filename, "size_bytes": len(data), "uploaded_at": utcnow().isoformat(), "nodes": len(info["nodes"]),
                        "mesh_nodes": info["mesh_nodes"], "bounds": info["bounds"], "generator": info["generator"],
                        "convention": "glTF: Y-up, metres (verify the exporter settings)"}
    created = updated = retired = 0
    if register_components:
        nodes = {n["index"]: n for n in info["nodes"]}
        kids: dict[int, list[int]] = {}
        for n in info["nodes"]:
            if n["parent"] is not None:
                kids.setdefault(n["parent"], []).append(n["index"])

        def union(i: int):
            boxes = [b for b in [nodes[i]["bbox"]] + [union(c) for c in kids.get(i, [])] if b]
            if not boxes:
                return None
            return {"min": [min(b["min"][k] for b in boxes) for k in range(3)], "max": [max(b["max"][k] for b in boxes) for k in range(3)]}

        existing = {c.name: c for c in db.query(Component).filter(Component.asset_id == asset_id).all() if (c.geometry or {}).get("source") == "gltf"}
        used_ids = {c.id for c in db.query(Component.id).all()}
        registered: dict[int, Component] = {}
        for n in info["nodes"]:  # parents are visited before children
            bbox = union(n["index"])
            if bbox is None or (not n["has_mesh"] and n["parent"] is None and not n["name"]):
                continue
            parent = n["parent"]
            while parent is not None and parent not in registered:
                parent = nodes[parent]["parent"]
            geom = {"type": "gltf_node" if n["has_mesh"] else "group", "source": "gltf", "node": n["index"]}
            ctr = [(bbox["min"][k] + bbox["max"][k]) / 2 for k in range(3)]
            comp = existing.pop(n["name"], None)
            if comp is None:
                cid = f"{id_prefix}{sanitize_id(n['name'])}"
                base, k = cid, 1
                while cid in used_ids:
                    k += 1
                    cid = f"{base}-{k}"
                used_ids.add(cid)
                comp = Component(id=cid, asset_id=asset_id, name=n["name"], component_type=guess_type(n["name"]) if n["has_mesh"] else "assembly")
                db.add(comp)
                created += 1
            else:
                updated += 1
            comp.mesh_ref = f"gltf-node:{n['index']}"
            comp.geometry, comp.bbox = geom, bbox
            comp.model_x, comp.model_y, comp.model_z = ctr
            comp.parent_id = registered[parent].id if parent is not None else None
            registered[n["index"]] = comp
            db.flush()
        for comp in existing.values():  # nodes that disappeared from the revised model
            comp.mesh_ref = None
            comp.notes = ((comp.notes or "") + " [not present in current 3D model]").strip()
            retired += 1
    log_event(db, event_type="config_changed", title=f"3D model uploaded for {asset.name} ({info['mesh_nodes']} mesh nodes)", asset_id=asset_id,
              actor=actor, data={"created": created, "updated": updated, "retired": retired})
    db.commit()
    return {"asset": AssetOut.model_validate(asset), "components_created": created, "components_updated": updated, "components_retired": retired,
            "model_meta": asset.model_meta}


@router.get("/assets/{asset_id}/model/file")
def model_file(asset_id: str, db: Session = Depends(get_session)):
    from app.services.storage import get_storage

    asset = get_or_404(db, Asset, asset_id, "Asset")
    if not asset.model_file_key or not get_storage().exists(asset.model_file_key):
        raise HTTPException(404, "No uploaded model for this asset")
    return Response(get_storage().read(asset.model_file_key), media_type="model/gltf-binary", headers={"Cache-Control": "private, max-age=600"})


@router.delete("/assets/{asset_id}/model")
def remove_model(asset_id: str, db: Session = Depends(get_session)):
    """Stop using the uploaded model (the file and registered components are kept for history)."""
    asset = get_or_404(db, Asset, asset_id, "Asset")
    asset.model_kind = "procedural" if asset.is_demo else "none"
    asset.model_ref = "procedural:cable-stayed-v1" if asset.is_demo else None
    log_event(db, event_type="config_changed", title=f"Uploaded 3D model detached from {asset.name}", asset_id=asset_id)
    db.commit()
    return AssetOut.model_validate(asset)
