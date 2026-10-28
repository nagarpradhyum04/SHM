from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_or_404, get_session
from app.models import Asset, Component, Device
from app.schemas import DeviceIn, DeviceOut, DevicePatch
from app.services.device_status import connection_status
from app.services.events import broadcaster, log_event
from app.services.ingestion import issue_token
from app.services.settings_store import get_setting

router = APIRouter(tags=["devices"])


def _out(db, d: Device, th=None) -> DeviceOut:
    return DeviceOut.model_validate(d).model_copy(update={"connection": connection_status(db, d, thresholds=th)})


@router.get("/devices", response_model=list[DeviceOut])
def list_devices(asset_id: str | None = None, device_type: str | None = None, component_id: str | None = None, db: Session = Depends(get_session)):
    q = db.query(Device)
    if asset_id:
        q = q.filter(Device.asset_id == asset_id)
    if device_type:
        q = q.filter(Device.device_type == device_type)
    if component_id:
        q = q.filter(Device.component_id == component_id)
    th = get_setting(db, "device_status")
    return [_out(db, d, th) for d in q.order_by(Device.device_type, Device.id).all()]


@router.post("/devices", status_code=201)
def register_device(body: DeviceIn, db: Session = Depends(get_session)):
    """Registers a device. For real sensors a one-time ingestion token is returned (store it in the firmware config)."""
    if db.get(Device, body.id):
        raise HTTPException(409, f"Device {body.id} already exists")
    get_or_404(db, Asset, body.asset_id, "Asset")
    if body.component_id:
        comp = get_or_404(db, Component, body.component_id, "Component")
        if comp.asset_id != body.asset_id:
            raise HTTPException(400, "Component belongs to a different asset")
    dev = Device(**body.model_dump())
    token = issue_token(dev) if body.data_source == "real" else None
    db.add(dev)
    log_event(db, event_type="device_registered", title=f"Device {dev.name} registered ({dev.data_source})", asset_id=dev.asset_id,
              component_id=dev.component_id, device_id=dev.id, ref_type="device", ref_id=dev.id, data_source=dev.data_source)
    db.commit()
    broadcaster.publish("devices", {"asset_id": dev.asset_id})
    return {"device": _out(db, dev), "ingestion_token": token,
            "token_note": "Shown once. Send as header 'X-Device-Token'." if token else "Simulated devices do not accept ingested data."}


@router.get("/devices/{device_id}", response_model=DeviceOut)
def get_device(device_id: str, db: Session = Depends(get_session)):
    return _out(db, get_or_404(db, Device, device_id, "Device"))


@router.get("/devices/{device_id}/status")
def device_status(device_id: str, db: Session = Depends(get_session)):
    dev = get_or_404(db, Device, device_id, "Device")
    return {"device_id": dev.id, "data_source": dev.data_source, "last_seen_at": dev.last_seen_at, **connection_status(db, dev)}


@router.patch("/devices/{device_id}", response_model=DeviceOut)
def patch_device(device_id: str, body: DevicePatch, db: Session = Depends(get_session)):
    dev = get_or_404(db, Device, device_id, "Device")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("component_id"):
        comp = get_or_404(db, Component, changes["component_id"], "Component")
        if comp.asset_id != dev.asset_id:
            raise HTTPException(400, "Component belongs to a different asset")
    for k, v in changes.items():
        setattr(dev, k, v)
    log_event(db, event_type="config_changed", title=f"Device {dev.name} updated", asset_id=dev.asset_id, device_id=dev.id, data={"fields": sorted(changes)})
    db.commit()
    broadcaster.publish("devices", {"asset_id": dev.asset_id})
    return _out(db, dev)


@router.post("/devices/{device_id}/rotate-token")
def rotate_token(device_id: str, db: Session = Depends(get_session)):
    dev = get_or_404(db, Device, device_id, "Device")
    if dev.data_source != "real":
        raise HTTPException(400, "Only real devices have ingestion tokens.")
    token = issue_token(dev)
    log_event(db, event_type="config_changed", title=f"Ingestion token rotated for {dev.name}", asset_id=dev.asset_id, device_id=dev.id)
    db.commit()
    return {"device_id": dev.id, "ingestion_token": token}
