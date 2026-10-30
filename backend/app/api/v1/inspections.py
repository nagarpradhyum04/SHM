from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_or_404, get_session
from app.config import get_settings
from app.models import Defect, ImageRecord, Inspection
from app.schemas import DefectOut, ImageOut, InspectionOut
from app.seed.demo_images import VARIANTS, generate_demo_image
from app.services.imaging import ImageValidationError, validate_image
from app.services.operations import DomainError, run_image_inspection
from app.services.storage import get_storage
from app.timeutil import ensure_utc

router = APIRouter(tags=["inspections"])


def _result(db, insp: Inspection, defects: list[Defect]):
    img = db.get(ImageRecord, insp.image_id) if insp.image_id else None
    from app.api.v1.cameras import clip_out
    from app.models import MediaClip

    clips = db.query(MediaClip).filter(MediaClip.inspection_id == insp.id).all()
    return {"inspection": InspectionOut.model_validate(insp), "image": ImageOut.model_validate(img) if img else None,
            "defects": [DefectOut.model_validate(d) for d in defects], "clips": [clip_out(c) for c in clips]}


@router.post("/inspections/image", status_code=201)
async def upload_image_inspection(
    file: UploadFile = File(...),
    asset_id: str = Form(...),
    component_id: str | None = Form(None),
    device_id: str | None = Form(None),
    observed_at: datetime | None = Form(None),
    performed_by: str | None = Form(None),
    notes: str | None = Form(None),
    db: Session = Depends(get_session),
):
    """Validate an uploaded image, store it, run the configured model (if any) and record the inspection."""
    limit = int(get_settings().max_upload_mb * 1024 * 1024)
    data = await file.read(limit + 1)
    try:
        img = validate_image(data, file.content_type)
    except ImageValidationError as exc:
        raise HTTPException(422 if len(data) <= limit else 413, str(exc)) from exc
    try:
        insp, defects = run_image_inspection(db, img, asset_id=asset_id, component_id=component_id or None, device_id=device_id or None,
                                             data_source="uploaded", original_filename=file.filename, observed_at=ensure_utc(observed_at),
                                             performed_by=performed_by, notes=notes)
    except DomainError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return _result(db, insp, defects)


class DemoInspectionIn(BaseModel):
    asset_id: str
    component_id: str | None = None
    variant: str = "crack"
    seed: int = 1
    performed_by: str | None = None


@router.get("/demo-images")
def demo_images():
    return [{"variant": k, "description": v, "label": "SYNTHETIC DEMO IMAGE"} for k, v in VARIANTS.items()]


@router.get("/demo-images/{variant}")
def demo_image_preview(variant: str, seed: int = 1):
    if variant not in VARIANTS:
        raise HTTPException(404, "Unknown demo image")
    data, _ = generate_demo_image(variant, seed)
    return Response(data, media_type="image/png")


@router.post("/inspections/demo", status_code=201)
def demo_inspection(body: DemoInspectionIn, db: Session = Depends(get_session)):
    """Run the normal inspection pipeline on a synthetic, clearly-labelled demonstration image."""
    if body.variant not in VARIANTS:
        raise HTTPException(400, "Unknown demo image variant")
    data, _ = generate_demo_image(body.variant, body.seed)
    img = validate_image(data)
    try:
        insp, defects = run_image_inspection(db, img, asset_id=body.asset_id, component_id=body.component_id, data_source="demo",
                                             original_filename=f"synthetic_{body.variant}_{body.seed}.png", performed_by=body.performed_by,
                                             notes="Synthetic demonstration image.")
    except DomainError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return _result(db, insp, defects)


@router.get("/inspections")
def list_inspections(asset_id: str | None = None, component_id: str | None = None, status: str | None = None,
                     start: datetime | None = None, end: datetime | None = None, limit: int = Query(200, le=2000), db: Session = Depends(get_session)):
    q = db.query(Inspection)
    if asset_id:
        q = q.filter(Inspection.asset_id == asset_id)
    if component_id:
        q = q.filter(Inspection.component_id == component_id)
    if status:
        q = q.filter(Inspection.status == status)
    if start:
        q = q.filter(Inspection.observed_at >= ensure_utc(start))
    if end:
        q = q.filter(Inspection.observed_at <= ensure_utc(end))
    rows = q.order_by(Inspection.observed_at.desc()).limit(limit).all()
    defect_counts = {}
    for d in db.query(Defect.inspection_id).filter(Defect.inspection_id.in_([r.id for r in rows])).all():
        defect_counts[d[0]] = defect_counts.get(d[0], 0) + 1
    return [{**InspectionOut.model_validate(r).model_dump(), "defect_count": defect_counts.get(r.id, 0)} for r in rows]


@router.get("/inspections/{inspection_id}")
def get_inspection(inspection_id: str, db: Session = Depends(get_session)):
    insp = get_or_404(db, Inspection, inspection_id, "Inspection")
    return _result(db, insp, db.query(Defect).filter(Defect.inspection_id == insp.id).all())


@router.get("/images/{image_id}", response_model=ImageOut)
def get_image(image_id: str, db: Session = Depends(get_session)):
    return get_or_404(db, ImageRecord, image_id, "Image")


@router.get("/images/{image_id}/file")
def get_image_file(image_id: str, db: Session = Depends(get_session)):
    rec = get_or_404(db, ImageRecord, image_id, "Image")
    storage = get_storage()
    if not storage.exists(rec.storage_key):
        raise HTTPException(410, "Image file is missing from storage")
    return Response(storage.read(rec.storage_key), media_type=rec.content_type, headers={"Cache-Control": "private, max-age=3600"})
