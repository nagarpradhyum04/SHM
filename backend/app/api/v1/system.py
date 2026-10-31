from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.api.deps import get_or_404, get_session
from app.config import get_settings
from app.models import ModelRecord, RULResult, SensorReading, VibrationFeature
from app.schemas import ModelOut, RULIn, RULOut, SettingIn
from app.services import fatigue, rul
from app.services.events import log_event
from app.services.inference import DEFECT_CATEGORIES, get_model_registry
from app.services.settings_store import DEFAULTS, PRIORITY_LEVELS, all_settings, get_setting, set_setting
from app.services.storage import get_storage
from app.timeutil import utcnow

router = APIRouter(tags=["system"])


def api_index():
    """Entry point of the REST API: what is available and where the documentation lives."""
    return {
        "name": "StructuraSense AI API", "version": "v1", "status": "ok",
        "documentation": "/docs", "openapi_schema": "/openapi.json",
        "examples": {"health": "/api/v1/health", "assets": "/api/v1/assets", "devices": "/api/v1/devices", "system_status": "/api/v1/system/status"},
        "device_ingestion": {"http": "POST /api/v1/ingest/readings (header X-Device-Token)",
                             "mqtt": "bridge/<device_id>/accel|env|status (token in payload)"},
    }


@router.get("/health")
def health(db: Session = Depends(get_session)):
    try:
        db.execute(text("SELECT 1"))
        ok = True
    except Exception:  # noqa: BLE001
        ok = False
    return {"status": "ok" if ok else "degraded", "database": ok, "time": utcnow()}


@router.get("/system/status")
def system_status(db: Session = Depends(get_session)):
    s = get_settings()
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    try:
        storage = {"ok": True, **get_storage().usage()}
    except OSError as exc:
        storage = {"ok": False, "error": str(exc)}
    reg = get_model_registry()
    readings = dict(db.query(SensorReading.source, func.count()).group_by(SensorReading.source).all())
    features = dict(db.query(VibrationFeature.source, func.count()).group_by(VibrationFeature.source).all())
    last_real = db.query(func.max(SensorReading.received_at)).filter(SensorReading.source == "real").scalar()
    return {
        "app": s.app_name,
        "environment": s.environment,
        "api_version": "v1",
        "database": {"ok": db_ok, "dialect": db.bind.dialect.name},
        "storage": storage,
        "models": reg.status(),
        "data_source": get_setting(db, "data_source"),
        "simulation": get_setting(db, "simulation"),
        "readings_by_source": readings,
        "features_by_source": features,
        "real_data_configured": bool(readings.get("real")),
        "last_real_reading_received_at": last_real,
        "device_auth_required": s.device_auth_required,
        "shared_device_key_configured": bool(s.device_shared_key),
        "background_enabled": s.background_enabled,
        "mqtt": _mqtt_summary(),
        "max_upload_mb": s.max_upload_mb,
        "security": {
            "user_authentication": "not_implemented",
            "note": "Single-user local development build. Add authentication/authorization before multi-user or network deployment.",
        },
        "categories": DEFECT_CATEGORIES,
        "priority_levels": PRIORITY_LEVELS,
    }


def _mqtt_summary() -> dict:
    from app.services.mqtt_bridge import bridge

    st = bridge.status()
    return {k: st[k] for k in ("enabled", "state", "broker", "last_error", "counts")}


@router.get("/settings")
def get_settings_all(db: Session = Depends(get_session)):
    return all_settings(db)


@router.put("/settings/{key}")
def put_setting(key: str, body: SettingIn, db: Session = Depends(get_session)):
    if key not in DEFAULTS:
        raise HTTPException(404, f"Unknown setting '{key}'")
    default = DEFAULTS[key]
    if isinstance(default, dict):
        if not isinstance(body.value, dict):
            raise HTTPException(422, "Setting value must be an object")
        unknown = set(body.value) - set(default)
        if unknown:
            raise HTTPException(422, f"Unknown fields for {key}: {sorted(unknown)}")
        if key == "data_source" and body.value.get("mode") not in (None, "real", "uploaded", "simulated", "all"):
            raise HTTPException(422, "mode must be real|uploaded|simulated|all")
        if key == "priority_rules":
            for cat, lvl in (body.value.get("category_base") or {}).items():
                if lvl not in PRIORITY_LEVELS:
                    raise HTTPException(422, f"Invalid priority '{lvl}' for {cat}")
        value = {**get_setting(db, key), **body.value}
    else:
        value = body.value
    val = set_setting(db, key, value, actor=body.actor)
    log_event(db, event_type="config_changed", title=f"Setting '{key}' updated", actor=body.actor, data={"key": key})
    db.commit()
    return val


@router.get("/models", response_model=list[ModelOut])
def models(db: Session = Depends(get_session)):
    return db.query(ModelRecord).order_by(ModelRecord.registered_at.desc()).all()


@router.post("/models/upload", status_code=201)
async def upload_model(onnx_file: UploadFile = File(...), card_file: UploadFile = File(...), actor: str | None = Form(None),
                       db: Session = Depends(get_session)):
    """Install a trained ONNX model with its model card (as produced by backend/ml/train_crack_classifier.py).
    The model is loaded once to prove it works before it is activated; nothing is installed on failure."""
    import json
    import re
    import shutil

    from app.services.inference.registry import REQUIRED_CARD_FIELDS

    try:
        card = json.loads((await card_file.read(1_000_000)).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(422, "model_card.json is not valid JSON") from exc
    missing = [f for f in REQUIRED_CARD_FIELDS if f not in card]
    if missing:
        raise HTTPException(422, f"model card is missing fields: {missing}")
    if card["framework"] != "onnx" or card["task"] != "classification":
        raise HTTPException(422, "Only ONNX classification models are supported by this release.")
    if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,80}", str(card["id"])):
        raise HTTPException(422, "model id may only contain letters, digits, '.', '_' and '-'")
    limit = 300 * 1024 * 1024
    data = await onnx_file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, "Model file exceeds 300 MB")
    reg = get_model_registry()
    target = reg.model_dir / str(card["id"])
    backup = None
    if target.exists():
        backup = target.with_name(target.name + ".previous")
        shutil.rmtree(backup, ignore_errors=True)
        target.rename(backup)
    target.mkdir(parents=True)
    card["file"] = "model.onnx"
    (target / "model.onnx").write_bytes(data)
    (target / "model_card.json").write_text(json.dumps(card, indent=2))
    reg.scan()
    if card["id"] not in {m["id"] for m in reg.status()["loaded"]}:
        error = next(iter(reg.status()["errors"].values()), "model could not be loaded")
        shutil.rmtree(target, ignore_errors=True)
        if backup:
            backup.rename(target)
        reg.scan()
        raise HTTPException(422, f"Model could not be loaded: {error}")
    if backup:
        shutil.rmtree(backup, ignore_errors=True)
    set_setting(db, "active_model", {"model_id": card["id"]}, actor=actor)
    reg.sync_db(db)
    log_event(db, event_type="config_changed", title=f"AI model {card['id']} v{card['version']} installed", actor=actor)
    db.commit()
    return {"installed": card["id"], "version": card["version"], "metrics_recorded": card.get("metrics") is not None, **reg.status()}


@router.post("/models/reload")
def reload_models(db: Session = Depends(get_session)):
    reg = get_model_registry()
    reg.scan()
    reg.sync_db(db)
    log_event(db, event_type="config_changed", title="Model registry reloaded")
    db.commit()
    return reg.status()


@router.post("/rul/estimate", response_model=RULOut)
def rul_estimate(body: RULIn, db: Session = Depends(get_session)):
    from app.models import Asset

    get_or_404(db, Asset, body.asset_id, "Asset")
    # With a component: fatigue life from measured loading; asset-wide: input coverage summary only.
    res = fatigue.estimate(db, body.component_id) if body.component_id else rul.estimate(db, body.asset_id, None)
    log_event(db, event_type="rul_assessment", title=f"RUL assessment {res.id} ({res.status.replace('_', ' ')})", asset_id=body.asset_id,
              component_id=body.component_id, ref_type="rul", ref_id=res.id, data_source=res.data_source)
    db.commit()
    return res


@router.get("/rul/results", response_model=list[RULOut])
def rul_results(asset_id: str | None = None, component_id: str | None = None, db: Session = Depends(get_session)):
    q = db.query(RULResult)
    if asset_id:
        q = q.filter(RULResult.asset_id == asset_id)
    if component_id:
        q = q.filter(RULResult.component_id == component_id)
    return q.order_by(RULResult.created_at.desc()).limit(50).all()


@router.get("/rul/options")
def rul_options():
    return {"method": fatigue.METHOD, "detail_categories_mpa": fatigue.DETAIL_CATEGORIES, "defaults": fatigue.DEFAULT_CONFIG,
            "description": (fatigue.__doc__ or "").strip()}


@router.get("/rul/config/{component_id}")
def rul_config(component_id: str, db: Session = Depends(get_session)):
    from app.models import Component

    get_or_404(db, Component, component_id, "Component")
    return fatigue.get_config(db, component_id)


@router.put("/rul/config/{component_id}")
def put_rul_config(component_id: str, body: SettingIn, db: Session = Depends(get_session)):
    from app.models import Component

    comp = get_or_404(db, Component, component_id, "Component")
    if not isinstance(body.value, dict):
        raise HTTPException(422, "value must be an object")
    try:
        cfg = fatigue.save_config(db, component_id, body.value, body.actor)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    log_event(db, event_type="config_changed", title=f"Fatigue/RUL inputs updated for {comp.name}", asset_id=comp.asset_id,
              component_id=component_id, actor=body.actor)
    db.commit()
    return cfg
