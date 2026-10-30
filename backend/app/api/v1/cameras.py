"""Camera (webcam agent) endpoints: frame analysis, event clips and heartbeats.

The camera agent (``backend/edge/camera_agent.py``) keeps a short ring buffer of frames,
periodically sends a snapshot to ``POST /cameras/{id}/frames`` and, when the backend reports
a finding, uploads a short clip around that moment to ``POST /inspections/{id}/clip``.
All three calls authenticate with the camera's ingestion token (``X-Device-Token``).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_or_404, get_session
from app.config import get_settings
from app.ids import new_id
from app.models import Defect, Device, Inspection, MediaClip
from app.schemas import DefectOut, InspectionOut
from app.services import ingestion
from app.services.events import broadcaster, log_event
from app.services.imaging import ImageValidationError, validate_image
from app.services.operations import infer, run_image_inspection
from app.services.settings_store import get_setting
from app.services.storage import get_storage
from app.timeutil import ensure_utc, utcnow

router = APIRouter(tags=["cameras"])
OPEN = ["new", "under_review", "confirmed", "monitoring"]


def _auth_camera(db: Session, device_id: str, token: str | None) -> Device:
    dev = db.get(Device, device_id)
    if dev is None or not ingestion.authenticate(dev, token):
        raise HTTPException(401, "Unknown device or invalid device token")
    if dev.device_type != "camera":
        raise HTTPException(400, "Device is not a camera")
    if dev.data_source != "real":
        raise HTTPException(400, "Simulated camera registrations cannot submit real frames")
    if dev.operational_status == "decommissioned":
        raise HTTPException(409, "Device is decommissioned")
    return dev


def clip_out(c: MediaClip) -> dict:
    return {"id": c.id, "inspection_id": c.inspection_id, "device_id": c.device_id, "content_type": c.content_type, "size_bytes": c.size_bytes,
            "duration_s": c.duration_s, "started_at": c.started_at, "data_source": c.data_source, "created_at": c.created_at,
            "url": f"/api/v1/clips/{c.id}/file"}


@router.post("/cameras/{device_id}/frames")
async def submit_frame(device_id: str, file: UploadFile = File(...), store: str = Form("on_finding"), captured_at: datetime | None = Form(None),
                       x_device_token: str | None = Header(None), db: Session = Depends(get_session)):
    """Analyse one camera frame. ``store=on_finding`` (default) keeps the frame only when the model reports a finding;
    ``store=always`` keeps it regardless (used for periodic reference snapshots)."""
    dev = _auth_camera(db, device_id, x_device_token)
    if store not in ("on_finding", "always"):
        raise HTTPException(422, "store must be on_finding or always")
    limit = int(get_settings().max_upload_mb * 1024 * 1024)
    data = await file.read(limit + 1)
    try:
        img = validate_image(data, file.content_type)
    except ImageValidationError as exc:
        raise HTTPException(422 if len(data) <= limit else 413, str(exc)) from exc
    now = utcnow()
    observed = ensure_utc(captured_at) or now
    dev.last_seen_at = now
    outcome = infer(db, img)
    detections = outcome.result.detections if outcome.result else []
    resp = {"model_status": outcome.status, "detections": [d.__dict__ for d in detections], "stored": False, "request_clip": False,
            "inspection": None, "defects": [], "suppressed_by": None}
    if detections and store == "on_finding":
        window = timedelta(seconds=get_setting(db, "camera")["repeat_suppression_s"])
        prior = (db.query(Defect).join(Inspection, Defect.inspection_id == Inspection.id)
                 .filter(Inspection.device_id == dev.id, Defect.detection_source == "ai_model", Defect.review_status.in_(OPEN),
                         Defect.category.in_([d.category for d in detections]), Defect.observed_at >= observed - window)
                 .order_by(Defect.observed_at.desc()).first())
        if prior:
            resp["suppressed_by"] = prior.id
            db.commit()
            return resp
    if detections or store == "always":
        insp, defects = run_image_inspection(
            db, img, asset_id=dev.asset_id, component_id=dev.component_id, device_id=dev.id, data_source="real",
            original_filename=file.filename, observed_at=observed, inspection_type="camera_capture", inference=outcome,
            notes="Automatic camera capture" + (" (finding)" if detections else " (periodic reference)"))
        resp.update({"stored": True, "request_clip": bool(defects), "inspection": InspectionOut.model_validate(insp),
                     "defects": [DefectOut.model_validate(d) for d in defects]})
    db.commit()
    broadcaster.publish("devices", {"asset_id": dev.asset_id})
    return resp


MAGIC = {"video/webm": (0, b"\x1a\x45\xdf\xa3"), "video/mp4": (4, b"ftyp")}


@router.post("/inspections/{inspection_id}/clip", status_code=201)
async def upload_clip(inspection_id: str, file: UploadFile = File(...), started_at: datetime | None = Form(None),
                      duration_s: float | None = Form(None, ge=0, le=600), x_device_token: str | None = Header(None),
                      db: Session = Depends(get_session)):
    """Attach a short video clip (WebM/VP8 or MP4) to an inspection produced by the same camera."""
    insp = get_or_404(db, Inspection, inspection_id, "Inspection")
    if not insp.device_id:
        raise HTTPException(400, "Inspection is not from a camera")
    _auth_camera(db, insp.device_id, x_device_token)
    limit = int(get_settings().max_clip_mb * 1024 * 1024)
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"Clip exceeds {get_settings().max_clip_mb:g} MB")
    ctype = next((t for t, (off, m) in MAGIC.items() if data[off:off + len(m)] == m), None)
    if ctype is None:
        raise HTTPException(422, "Unsupported clip format (WebM or MP4 required)")
    cid = new_id("CLP")
    key = f"clips/{insp.asset_id}/{cid}.{'webm' if ctype == 'video/webm' else 'mp4'}"
    get_storage().save(key, data)
    clip = MediaClip(id=cid, asset_id=insp.asset_id, device_id=insp.device_id, inspection_id=insp.id, storage_key=key, content_type=ctype,
                     size_bytes=len(data), duration_s=duration_s, started_at=ensure_utc(started_at), data_source=insp.data_source)
    db.add(clip)
    log_event(db, event_type="camera_clip", title=f"Camera clip stored for {insp.id}", asset_id=insp.asset_id, component_id=insp.component_id,
              device_id=insp.device_id, ref_type="inspection", ref_id=insp.id, data_source=insp.data_source)
    db.commit()
    broadcaster.publish("inspections", {"asset_id": insp.asset_id})
    return clip_out(clip)


@router.get("/clips/{clip_id}/file")
def clip_file(clip_id: str, db: Session = Depends(get_session)):
    c = get_or_404(db, MediaClip, clip_id, "Clip")
    st = get_storage()
    if not st.exists(c.storage_key):
        raise HTTPException(410, "Clip file is missing from storage")
    return Response(st.read(c.storage_key), media_type=c.content_type, headers={"Cache-Control": "private, max-age=3600"})


@router.get("/inspections/{inspection_id}/clips")
def inspection_clips(inspection_id: str, db: Session = Depends(get_session)):
    get_or_404(db, Inspection, inspection_id, "Inspection")
    return [clip_out(c) for c in db.query(MediaClip).filter(MediaClip.inspection_id == inspection_id).order_by(MediaClip.created_at).all()]


class HeartbeatIn(BaseModel):
    stream_url: str | None = Field(None, max_length=300, pattern=r"^https?://")
    fw: str | None = Field(None, max_length=60)
    info: dict | None = None


@router.post("/devices/{device_id}/heartbeat")
def heartbeat(device_id: str, body: HeartbeatIn, x_device_token: str | None = Header(None), db: Session = Depends(get_session)):
    """Liveness report from an agent/firmware. For cameras it also marks the camera as seen (frames are being captured)."""
    dev = db.get(Device, device_id)
    if dev is None or not ingestion.authenticate(dev, x_device_token):
        raise HTTPException(401, "Unknown device or invalid device token")
    cfg = dict(dev.config or {})
    cfg["last_status"] = {**(body.info or {}), "received_at": utcnow().isoformat()}
    dev.config = cfg
    if body.stream_url:
        dev.stream_url = body.stream_url
    if body.fw:
        dev.firmware_version = body.fw
    if dev.device_type == "camera" and dev.data_source == "real":
        dev.last_seen_at = utcnow()
    db.commit()
    broadcaster.publish("devices", {"asset_id": dev.asset_id})
    return {"ok": True, "server_time": utcnow()}



