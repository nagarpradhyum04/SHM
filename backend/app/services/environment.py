"""Ambient temperature / relative-humidity readings (e.g. a DHT22 on the ESP32 sensor node).

What these measurements can and cannot do:
* They describe exposure conditions — thermal cycling, freeze-thaw cycles, periods of high
  humidity or near-condensation — which are known drivers of deterioration and which influence
  vibration measurements (stiffness changes with temperature).
* They CANNOT detect or confirm cracks. They are used as context next to visual findings and
  vibration features, and for configurable exposure alerts.

Dew point uses the Magnus approximation (a=17.62, b=243.12 °C), adequate for −45…60 °C.
"""
from __future__ import annotations

import math
from datetime import datetime

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.models import Device, EnvironmentReading
from app.services import alert_engine
from app.services.events import broadcaster
from app.services.settings_store import get_setting
from app.timeutil import ensure_utc, utcnow

TEMP_RANGE_C = (-40.0, 125.0)  # covers DHT22 (−40…80), DS18B20 (−55…125 clipped), BME280 (−40…85)
MAX_FUTURE_S = 300


def dew_point_c(temp_c: float, rh_pct: float) -> float | None:
    if temp_c is None or rh_pct is None or rh_pct <= 0:
        return None
    a, b = 17.62, 243.12
    g = math.log(rh_pct / 100.0) + a * temp_c / (b + temp_c)
    return b * g / (a - g)


def _validate(r: dict, now: datetime) -> tuple[dict | None, str | None]:
    t, h = r.get("temperature_c", r.get("temp_c")), r.get("humidity_pct", r.get("rh"))
    try:
        t = None if t is None else float(t)
        h = None if h is None else float(h)
    except (TypeError, ValueError):
        return None, "non-numeric temperature/humidity"
    if t is None and h is None:
        return None, "neither temperature nor humidity present"
    if t is not None and (not math.isfinite(t) or not TEMP_RANGE_C[0] <= t <= TEMP_RANGE_C[1]):
        return None, f"temperature {t} outside {TEMP_RANGE_C}"
    if h is not None and (not math.isfinite(h) or not 0.0 <= h <= 100.0):
        return None, f"humidity {h} outside 0–100 %"
    quality = "ok"
    ts = r.get("ts")
    if ts is None and r.get("t_ms") is not None:
        ts = datetime.fromtimestamp(float(r["t_ms"]) / 1000.0, tz=now.tzinfo)
    if ts is None:
        ts, quality = now, "suspect"
    elif isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None, "invalid timestamp"
    ts = ensure_utc(ts)
    if (ts - now).total_seconds() > MAX_FUTURE_S:
        return None, "timestamp in the future"
    seq = r.get("seq")
    return {"ts": ts, "seq": int(seq) if seq is not None else None, "temperature_c": t, "humidity_pct": h,
            "sensor_model": (str(r.get("sensor"))[:40] if r.get("sensor") else None), "quality": quality}, None


def ingest(db: Session, dev: Device, readings: list[dict], source: str) -> dict:
    if source not in ("real", "uploaded"):
        raise ValueError("Environment ingestion accepts only real or uploaded data.")
    if source == "real" and dev.data_source != "real":
        raise ValueError("Device is registered as simulated; real readings cannot be attributed to it.")
    now = utcnow()
    rows, errors = [], []
    seqs = [r.get("seq") for r in readings if isinstance(r, dict) and r.get("seq") is not None]
    existing = set()
    if seqs:
        existing = {s for (s,) in db.query(EnvironmentReading.seq).filter(
            EnvironmentReading.device_id == dev.id, EnvironmentReading.source == source, EnvironmentReading.seq.in_(seqs)).all()}
    for r in readings:
        v, err = _validate(r if isinstance(r, dict) else {}, now)
        if err:
            errors.append(err)
            continue
        if v["seq"] is not None and v["seq"] in existing:
            errors.append(f"duplicate seq {v['seq']}")
            continue
        if v["seq"] is not None:
            existing.add(v["seq"])
        rows.append({**v, "device_id": dev.id, "component_id": dev.component_id, "source": source, "received_at": now})
    if rows:
        db.execute(insert(EnvironmentReading), rows)
        if source == "real":
            latest = max(r["ts"] for r in rows)
            dev.last_seen_at = max(dev.last_seen_at, latest) if dev.last_seen_at else latest
        evaluate_thresholds(db, dev, source)
    if errors:
        alert_engine.on_validation_failure(db, dev, errors, source)
    broadcaster.publish("environment", {"device_id": dev.id, "count": len(rows)})
    return {"accepted": len(rows), "rejected": len(readings) - len(rows), "errors": errors[:50], "source": source}


def _violations(cfg: dict, r: EnvironmentReading) -> list[str]:
    out = []
    t, h = r.temperature_c, r.humidity_pct
    if t is not None and cfg.get("temp_max_c") is not None and t > cfg["temp_max_c"]:
        out.append("temperature_above_max")
    if t is not None and cfg.get("temp_min_c") is not None and t < cfg["temp_min_c"]:
        out.append("temperature_below_min")
    if h is not None and cfg.get("humidity_max_pct") is not None and h > cfg["humidity_max_pct"]:
        out.append("humidity_above_max")
    if t is not None and h is not None and cfg.get("condensation_margin_c") is not None:
        dp = dew_point_c(t, h)
        if dp is not None and t - dp < cfg["condensation_margin_c"]:
            out.append("near_condensation")
    return out


def evaluate_thresholds(db: Session, dev: Device, source: str):
    """Raise an alert when the last N samples all violate the same configured limit."""
    cfg = get_setting(db, "environment")
    if all(cfg.get(k) is None for k in ("temp_max_c", "temp_min_c", "humidity_max_pct", "condensation_margin_c")):
        return None
    n = max(1, int(cfg.get("consecutive_samples") or 1))
    db.flush()
    last = (db.query(EnvironmentReading).filter(EnvironmentReading.device_id == dev.id, EnvironmentReading.source == source)
            .order_by(EnvironmentReading.ts.desc()).limit(n).all())
    if len(last) < n:
        return None
    common = set(_violations(cfg, last[0]))
    for r in last[1:]:
        common &= set(_violations(cfg, r))
    if not common:
        return None
    r0 = last[0]
    return alert_engine.raise_alert(
        db, rule_type="environment_threshold", asset_id=dev.asset_id, component_id=dev.component_id, device_id=dev.id,
        dedup_key=f"environment_threshold:{dev.id}:{','.join(sorted(common))}",
        title=f"Environmental condition outside configured range at {dev.name}",
        message=f"{n} consecutive samples: {', '.join(sorted(common))} (latest {r0.temperature_c} °C, {r0.humidity_pct} % RH). "
                "Exposure context only — this does not indicate a crack.",
        evidence=[alert_engine.Evidence("device", dev.id, "environment samples",
                  {"limits": cfg, "latest": {"ts": r0.ts.isoformat(), "temperature_c": r0.temperature_c, "humidity_pct": r0.humidity_pct}})],
        data_source=source,
    )


def aggregate(rows: list[EnvironmentReading], bucket_s: int) -> list[dict]:
    """Per-bucket mean/min/max, mean dew point and number of 0 °C crossings (freeze-thaw indicator)."""
    buckets: dict[tuple[str, int], list[EnvironmentReading]] = {}
    for r in rows:
        k = (r.source, int(r.ts.timestamp()) // bucket_s * bucket_s) if bucket_s else (r.source, int(r.ts.timestamp() * 1000))
        buckets.setdefault(k, []).append(r)
    out = []
    for (src, t), rs in sorted(buckets.items(), key=lambda kv: kv[0][1]):
        temps = [r.temperature_c for r in rs if r.temperature_c is not None]
        hums = [r.humidity_pct for r in rs if r.humidity_pct is not None]
        dps = [d for r in rs if (d := dew_point_c(r.temperature_c, r.humidity_pct)) is not None]
        crossings = sum(1 for a, b in zip(temps, temps[1:]) if (a < 0) != (b < 0))
        out.append({
            "t": datetime.fromtimestamp(t if bucket_s else t / 1000, tz=rs[0].ts.tzinfo).isoformat(), "source": src, "n": len(rs),
            "temp_mean": sum(temps) / len(temps) if temps else None, "temp_min": min(temps) if temps else None, "temp_max": max(temps) if temps else None,
            "rh_mean": sum(hums) / len(hums) if hums else None, "rh_max": max(hums) if hums else None,
            "dew_point_mean": sum(dps) / len(dps) if dps else None, "zero_crossings": crossings,
        })
    return out
