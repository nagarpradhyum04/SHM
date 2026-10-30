from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_or_404, get_session
from app.models import Baseline, Device, EnvironmentReading, SensorReading, VibrationFeature
from app.schemas import (BaselineIn, BaselineOut, EnvironmentBatchIn, EnvironmentReadingOut, FeatureOut, ReadingBatchIn, ReadingOut,
                         SimulationGenerateIn)
from app.services import alert_engine, environment, ingestion, simulation, vibration
from app.services.events import broadcaster, log_event
from app.services.settings_store import get_setting, set_setting
from app.timeutil import ensure_utc, utcnow

router = APIRouter(tags=["sensors"])
Source = Query(None, pattern="^(real|uploaded|simulated)$")


@router.post("/ingest/readings", status_code=202)
def ingest_readings(body: ReadingBatchIn, x_device_token: str | None = Header(None), db: Session = Depends(get_session)):
    """Device ingestion endpoint (ESP32 + MPU6050 contract v1). Requires ``X-Device-Token``."""
    dev = db.get(Device, body.device_id)
    if dev is None or not ingestion.authenticate(dev, x_device_token):
        raise HTTPException(401, "Unknown device or invalid device token")
    if dev.device_type not in ("accelerometer", "sensor_node"):
        raise HTTPException(400, "Device does not measure acceleration")
    if dev.operational_status == "decommissioned":
        raise HTTPException(409, "Device is decommissioned")
    try:
        result = ingestion.ingest(db, dev, body.readings, "real")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if body.firmware_version:
        dev.firmware_version = body.firmware_version
    db.commit()
    return result


@router.post("/sensors/{device_id}/upload", status_code=202)
async def upload_history(device_id: str, file: UploadFile = File(...), db: Session = Depends(get_session)):
    """Upload historical readings as CSV (stored with source='uploaded')."""
    dev = get_or_404(db, Device, device_id, "Device")
    if dev.device_type == "camera":
        raise HTTPException(400, "Device is not a sensor")
    raw = await file.read(10 * 1024 * 1024 + 1)
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413, "CSV exceeds 10 MB")
    try:
        rows = ingestion.parse_csv(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(400, f"Invalid CSV: {exc}") from exc
    total = {"accepted": 0, "rejected": 0, "duplicates": 0, "errors": []}
    try:
        for i in range(0, len(rows), 2000):
            r = ingestion.ingest(db, dev, rows[i : i + 2000], "uploaded")
            for k in ("accepted", "rejected", "duplicates"):
                total[k] += r[k]
            total["errors"] += r["errors"]
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    log_event(db, event_type="data_upload", title=f"{total['accepted']} uploaded readings for {dev.name}", asset_id=dev.asset_id,
              device_id=dev.id, data_source="uploaded")
    db.commit()
    total["errors"] = total["errors"][:50]
    return {**total, "source": "uploaded"}


@router.get("/sensors/{device_id}/latest")
def latest_reading(device_id: str, source: str | None = Source, db: Session = Depends(get_session)):
    dev = get_or_404(db, Device, device_id, "Device")
    q = db.query(SensorReading).filter(SensorReading.device_id == device_id)
    if source:
        q = q.filter(SensorReading.source == source)
    r = q.order_by(SensorReading.ts.desc()).first()
    th = get_setting(db, "device_status")
    if r is None:
        return {"device_id": device_id, "reading": None, "message": "No readings recorded."}
    age = (utcnow() - r.ts).total_seconds()
    return {"device_id": device_id, "reading": ReadingOut.model_validate(r), "age_s": age, "is_stale": age > th["stale_after_s"],
            "data_source": r.source, "device_data_source": dev.data_source}


@router.get("/sensors/{device_id}/readings", response_model=list[ReadingOut])
def readings(device_id: str, source: str | None = Source, start: datetime | None = None, end: datetime | None = None,
             limit: int = Query(600, ge=1, le=20000), db: Session = Depends(get_session)):
    get_or_404(db, Device, device_id, "Device")
    q = db.query(SensorReading).filter(SensorReading.device_id == device_id)
    if source:
        q = q.filter(SensorReading.source == source)
    if start:
        q = q.filter(SensorReading.ts >= ensure_utc(start))
    if end:
        q = q.filter(SensorReading.ts <= ensure_utc(end))
    rows = q.order_by(SensorReading.ts.desc()).limit(limit).all()
    return list(reversed(rows))


@router.get("/sensors/{device_id}/features", response_model=list[FeatureOut])
def features(device_id: str, source: str | None = Source, start: datetime | None = None, end: datetime | None = None,
             limit: int = Query(500, ge=1, le=10000), db: Session = Depends(get_session)):
    get_or_404(db, Device, device_id, "Device")
    q = db.query(VibrationFeature).filter(VibrationFeature.device_id == device_id)
    if source:
        q = q.filter(VibrationFeature.source == source)
    if start:
        q = q.filter(VibrationFeature.window_start >= ensure_utc(start))
    if end:
        q = q.filter(VibrationFeature.window_end <= ensure_utc(end))
    rows = q.order_by(VibrationFeature.window_start.desc()).limit(limit).all()
    return list(reversed(rows))


@router.post("/sensors/{device_id}/analyze", response_model=list[FeatureOut])
def analyze(device_id: str, source: str = Query(..., pattern="^(real|uploaded|simulated)$"), db: Session = Depends(get_session)):
    dev = get_or_404(db, Device, device_id, "Device")
    feats = vibration.process_device(db, dev, source, utcnow(), on_anomaly=alert_engine.on_feature_anomaly)
    db.commit()
    return feats


@router.get("/sensors/{device_id}/baselines", response_model=list[BaselineOut])
def baselines(device_id: str, db: Session = Depends(get_session)):
    get_or_404(db, Device, device_id, "Device")
    return db.query(Baseline).filter(Baseline.device_id == device_id).order_by(Baseline.source, Baseline.version.desc()).all()


@router.post("/sensors/{device_id}/baselines", response_model=BaselineOut, status_code=201)
def create_baseline(device_id: str, body: BaselineIn, db: Session = Depends(get_session)):
    dev = get_or_404(db, Device, device_id, "Device")
    try:
        b = vibration.create_baseline(db, dev, body.source, ensure_utc(body.window_start), ensure_utc(body.window_end), body.actor, body.notes)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    log_event(db, event_type="baseline_created", title=f"Baseline v{b.version} ({b.source}) for {dev.name}", asset_id=dev.asset_id,
              component_id=dev.component_id, device_id=dev.id, ref_type="baseline", ref_id=b.id, data_source=b.source, actor=body.actor)
    db.commit()
    return b


@router.get("/simulation")
def simulation_status(db: Session = Depends(get_session)):
    return {**get_setting(db, "simulation"), "note": "Simulated data is always stored and displayed with source='simulated'."}


@router.put("/simulation")
def set_simulation(body: dict, db: Session = Depends(get_session)):
    cur = get_setting(db, "simulation")
    if "live_enabled" in body:
        cur["live_enabled"] = bool(body["live_enabled"])
    val = set_setting(db, "simulation", cur, actor=body.get("actor"))
    log_event(db, event_type="config_changed", title=f"Live simulation {'enabled' if cur['live_enabled'] else 'disabled'}", actor=body.get("actor"))
    db.commit()
    return val


@router.post("/simulation/generate")
def simulation_generate(body: SimulationGenerateIn, db: Session = Depends(get_session)):
    q = db.query(Device).filter(Device.data_source == "simulated", Device.device_type != "camera")
    if body.device_id:
        q = q.filter(Device.id == body.device_id)
    devs = q.all()
    if not devs:
        raise HTTPException(400, "No simulated sensor devices match.")
    now = utcnow()
    total = 0
    for dev in devs:
        last = db.query(SensorReading.ts).filter(SensorReading.device_id == dev.id, SensorReading.source == "simulated").order_by(SensorReading.ts.desc()).first()
        start = now - timedelta(minutes=body.minutes)
        if last and last[0] + timedelta(seconds=0.1) > start:
            start = last[0] + timedelta(seconds=0.1)
        end = now
        if end <= start:
            continue
        anomalies = [(start + (end - start) / 2, start + (end - start) / 2 + timedelta(minutes=min(3, body.minutes / 3)))] if body.inject_anomaly else []
        total += simulation.generate(db, dev, start, end, anomaly_windows=anomalies)
        vibration.process_device(db, dev, "simulated", now, on_anomaly=alert_engine.on_feature_anomaly)
    db.commit()
    broadcaster.publish("readings", {"source": "simulated"})
    return {"generated": total, "devices": [d.id for d in devs], "source": "simulated"}


@router.post("/ingest/environment", status_code=202)
def ingest_environment(body: EnvironmentBatchIn, x_device_token: str | None = Header(None), db: Session = Depends(get_session)):
    """Temperature/humidity ingestion over HTTP (the MQTT bridge uses the same validation)."""
    dev = db.get(Device, body.device_id)
    if dev is None or not ingestion.authenticate(dev, x_device_token):
        raise HTTPException(401, "Unknown device or invalid device token")
    if dev.device_type == "camera":
        raise HTTPException(400, "Cameras do not report environment readings")
    try:
        res = environment.ingest(db, dev, body.readings, "real")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return res


@router.get("/sensors/{device_id}/environment")
def environment_series(device_id: str, source: str | None = Source, start: datetime | None = None, end: datetime | None = None,
                       bucket_s: int = Query(0, ge=0, le=86400), limit: int = Query(2000, ge=1, le=50000), db: Session = Depends(get_session)):
    """Raw (bucket_s=0) or aggregated temperature / humidity / dew point with 0 °C crossings."""
    get_or_404(db, Device, device_id, "Device")
    q = db.query(EnvironmentReading).filter(EnvironmentReading.device_id == device_id)
    if source:
        q = q.filter(EnvironmentReading.source == source)
    if start:
        q = q.filter(EnvironmentReading.ts >= ensure_utc(start))
    if end:
        q = q.filter(EnvironmentReading.ts <= ensure_utc(end))
    rows = list(reversed(q.order_by(EnvironmentReading.ts.desc()).limit(limit).all()))
    latest = rows[-1] if rows else None
    return {
        "device_id": device_id,
        "latest": {**EnvironmentReadingOut.model_validate(latest).model_dump(),
                   "dew_point_c": environment.dew_point_c(latest.temperature_c, latest.humidity_pct),
                   "age_s": (utcnow() - latest.ts).total_seconds()} if latest else None,
        "series": environment.aggregate(rows, bucket_s),
        "sensor_spec": environment.SENSOR_SPECS.get((latest.sensor_model or "").upper()) if latest else None,
        "note": "Ambient exposure context. Temperature and humidity cannot detect cracks.",
    }


@router.get("/mqtt/status")
def mqtt_status():
    from app.services.mqtt_bridge import bridge

    return bridge.status()
