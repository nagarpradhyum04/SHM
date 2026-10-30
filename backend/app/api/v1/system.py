from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.api.deps import get_or_404, get_session
from app.config import get_settings
from app.models import ModelRecord, RULResult, SensorReading, VibrationFeature
from app.schemas import ModelOut, RULIn, RULOut, SettingIn
from app.services import rul
from app.services.events import log_event
from app.services.inference import DEFECT_CATEGORIES, get_model_registry
from app.services.settings_store import DEFAULTS, PRIORITY_LEVELS, all_settings, get_setting, set_setting
from app.services.storage import get_storage
from app.timeutil import utcnow

router = APIRouter(tags=["system"])


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
    res = rul.estimate(db, body.asset_id, body.component_id)
    db.commit()
    return res


@router.get("/rul/results", response_model=list[RULOut])
def rul_results(asset_id: str | None = None, db: Session = Depends(get_session)):
    q = db.query(RULResult)
    if asset_id:
        q = q.filter(RULResult.asset_id == asset_id)
    return q.order_by(RULResult.created_at.desc()).limit(50).all()
