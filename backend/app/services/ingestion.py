"""Sensor ingestion: payload validation, duplicate-sequence rejection, device auth."""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import math
import secrets
from datetime import datetime

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Device, SensorReading
from app.services import alert_engine
from app.services.events import broadcaster
from app.timeutil import ensure_utc, utcnow

ACCEL_LIMIT_G = 16.0  # MPU6050 maximum full-scale range
GYRO_LIMIT_DPS = 2000.0
MAX_FUTURE_S = 300


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(dev: Device) -> str:
    token = secrets.token_urlsafe(32)
    dev.token_hash = hash_token(token)
    return token


def authenticate(dev: Device, token: str | None) -> bool:
    settings = get_settings()
    if not settings.device_auth_required:
        return True
    if not token:
        return False
    if settings.device_shared_key and hmac.compare_digest(token, settings.device_shared_key):
        return True
    return bool(dev.token_hash) and hmac.compare_digest(hash_token(token), dev.token_hash)


def _validate(r: dict, now: datetime) -> tuple[dict | None, str | None]:
    try:
        seq = int(r["seq"])
        ax, ay, az = (float(r[k]) for k in ("ax", "ay", "az"))
    except (KeyError, TypeError, ValueError):
        return None, "missing or non-numeric seq/ax/ay/az"
    if seq < 0:
        return None, f"seq {seq}: negative sequence number"
    vals = [ax, ay, az]
    gyro = [r.get(k) for k in ("gx", "gy", "gz")]
    if any(not math.isfinite(v) for v in vals) or any(abs(v) > ACCEL_LIMIT_G for v in vals):
        return None, f"seq {seq}: acceleration non-finite or beyond ±{ACCEL_LIMIT_G} g"
    try:
        gyro = [None if g is None else float(g) for g in gyro]
    except (TypeError, ValueError):
        return None, f"seq {seq}: non-numeric gyro value"
    if any(g is not None and (not math.isfinite(g) or abs(g) > GYRO_LIMIT_DPS) for g in gyro):
        return None, f"seq {seq}: gyro beyond ±{GYRO_LIMIT_DPS} deg/s"
    quality = "ok"
    ts = r.get("ts")
    if ts is None:
        ts, quality = now, "suspect"  # server receive time substituted
    else:
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                return None, f"seq {seq}: invalid timestamp"
        ts = ensure_utc(ts)
        if (ts - now).total_seconds() > MAX_FUTURE_S:
            return None, f"seq {seq}: timestamp in the future"
    temp = r.get("temperature_c")
    return {"seq": seq, "ts": ts, "ax": ax, "ay": ay, "az": az, "gx": gyro[0], "gy": gyro[1], "gz": gyro[2],
            "temperature_c": float(temp) if temp is not None else None, "quality": quality}, None


def ingest(db: Session, dev: Device, readings: list[dict], source: str) -> dict:
    if source not in ("real", "uploaded"):
        raise ValueError("Ingestion accepts only real or uploaded data; simulated data comes from the simulation provider.")
    if source == "real" and dev.data_source != "real":
        raise ValueError("Device is registered as simulated; real readings cannot be attributed to it.")
    if len(readings) > get_settings().max_readings_per_request:
        raise ValueError(f"Too many readings in one request (max {get_settings().max_readings_per_request}).")
    now = utcnow()
    errors: list[str] = []
    valid: list[dict] = []
    for r in readings:
        v, err = _validate(r if isinstance(r, dict) else {}, now)
        if err:
            errors.append(err)
        else:
            valid.append(v)
    seqs = [v["seq"] for v in valid]
    existing: set[int] = set()
    for i in range(0, len(seqs), 500):
        chunk = seqs[i : i + 500]
        existing |= {s for (s,) in db.query(SensorReading.seq).filter(SensorReading.device_id == dev.id, SensorReading.source == source,
                                                                         SensorReading.seq.in_(chunk)).all()}
    seen: set[int] = set()
    rows, dups = [], 0
    for v in valid:
        if v["seq"] in existing or v["seq"] in seen:
            dups += 1
            continue
        seen.add(v["seq"])
        rows.append({**v, "device_id": dev.id, "component_id": dev.component_id, "source": source, "processing_status": "raw", "received_at": now})
    if rows:
        db.execute(insert(SensorReading), rows)
        latest = max(r["ts"] for r in rows)
        if source == "real":
            dev.last_seen_at = max(dev.last_seen_at or latest, latest) if dev.last_seen_at else latest
    if dups:
        errors.append(f"{dups} duplicate sequence number(s) rejected")
    if errors:
        alert_engine.on_validation_failure(db, dev, errors, source)
    broadcaster.publish("readings", {"device_id": dev.id, "source": source, "count": len(rows)})
    return {"accepted": len(rows), "rejected": len(readings) - len(rows), "duplicates": dups, "errors": errors[:50], "source": source}


def parse_csv(text: str) -> list[dict]:
    """CSV columns: seq,ts,ax,ay,az[,gx,gy,gz,temperature_c] (header required)."""
    reader = csv.DictReader(io.StringIO(text))
    required = {"seq", "ts", "ax", "ay", "az"}
    if not reader.fieldnames or not required <= {f.strip() for f in reader.fieldnames}:
        raise ValueError(f"CSV header must include {sorted(required)}")
    out = []
    for row in reader:
        row = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k}
        out.append({k: (None if v in ("", None) else v) for k, v in row.items()})
    return out
