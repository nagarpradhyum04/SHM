"""Ingestion and analysis of device-computed vibration summaries.

Payload (e.g. the "Smart Bridge Monitor" sketch, every 0.5 s):
    {"vib": 0.0055, "peak": 0.0124, "level": "CALM", "tilt": 29.42, "temp": 29.5, "hum": 51.0,
     "mpu": true, "dht": true, "simulated": false}
* vib  – RMS of the dynamic acceleration magnitude over the publish interval (g, gravity removed on the device)
* peak – largest dynamic magnitude in that interval (g)
* tilt – angle between the sensor's z axis and gravity (degrees)
Optional: "token", "seq", "t_ms" (UTC epoch ms). Without "t_ms" the server's receive time is used.

60 s window features (``vib-summary-v1``): rms_dyn = sqrt(mean(vib²)), peak_dyn = max(peak),
tilt_mean_deg = mean(tilt), completeness = summaries received / expected. They feed the same absolute-limit
and baseline rules as raw-stream features. Tilt change against a reference raises a separate alert when a
limit is configured. Raw samples are not available from summaries, so load-cycle (fatigue) analysis needs the
raw-stream firmware.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Device, EnvironmentReading, SensorSummary, VibrationFeature
from app.services import alert_engine, environment
from app.services.events import broadcaster
from app.services.settings_store import get_setting
from app.services.vibration import active_baseline, evaluate_anomaly
from app.timeutil import ensure_utc, utcnow

FEATURE_VERSION = "vib-summary-v1"
ENV_MIN_INTERVAL_S = 2.0


def is_summary_payload(p: dict) -> bool:
    return "vib" in p or "peak" in p or "tilt" in p


def _num(v, lo: float, hi: float, name: str):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} is not a number") from exc
    if not math.isfinite(f) or not lo <= f <= hi:
        raise ValueError(f"{name}={v} outside {lo}…{hi}")
    return f


def ingest_summary(db: Session, dev: Device, p: dict, source: str = "real") -> dict:
    if p.get("simulated") is True:
        raise ValueError("Payload is flagged simulated; simulated values are never stored as real data.")
    if source == "real" and dev.data_source != "real":
        raise ValueError("Device is registered as simulated; real readings cannot be attributed to it.")
    now = utcnow()
    vib = _num(p.get("vib"), 0, 16, "vib")
    peak = _num(p.get("peak"), 0, 32, "peak")
    tilt = _num(p.get("tilt"), -180, 180, "tilt")
    if p.get("t_ms") is not None:
        ts, time_source = datetime.fromtimestamp(float(p["t_ms"]) / 1000, tz=timezone.utc), "device"
        if (ts - now).total_seconds() > 300:
            raise ValueError("timestamp in the future")
    else:
        ts, time_source = now, "server"
    mpu_ok = p.get("mpu") if isinstance(p.get("mpu"), bool) else None
    dht_ok = p.get("dht") if isinstance(p.get("dht"), bool) else None
    stored = False
    if vib is not None or peak is not None or tilt is not None:
        db.add(SensorSummary(device_id=dev.id, ts=ts, seq=p.get("seq") if isinstance(p.get("seq"), int) else None, vib_rms_g=vib, peak_g=peak,
                             tilt_deg=tilt, device_level=str(p["level"])[:20] if p.get("level") else None, mpu_ok=mpu_ok, dht_ok=dht_ok,
                             time_source=time_source, source=source, received_at=now))
        stored = True
    env_stored = 0
    if p.get("temp") is not None and p.get("hum") is not None and dht_ok is not False:
        last = db.query(func.max(EnvironmentReading.ts)).filter(EnvironmentReading.device_id == dev.id, EnvironmentReading.source == source).scalar()
        if last is None or (ts - last).total_seconds() >= ENV_MIN_INTERVAL_S:
            sensor = (dev.config or {}).get("env_sensor") or "DHT11"
            r = environment.ingest(db, dev, [{"temp_c": p["temp"], "rh": p["hum"], "sensor": sensor, "ts": ts}], source)
            env_stored = r["accepted"]
    if source == "real" and (stored or env_stored):
        dev.last_seen_at = max(dev.last_seen_at, ts) if dev.last_seen_at else ts
    cfg = dict(dev.config or {})
    cfg["last_status"] = {"mpu_ok": mpu_ok, "dht_ok": dht_ok, "device_level": p.get("level"), "format": "summary",
                          "received_at": now.isoformat()}
    dev.config = cfg
    broadcaster.publish("readings", {"device_id": dev.id, "source": source})
    return {"accepted": int(stored) + env_stored, "rejected": 0, "errors": [], "summary": stored, "environment": env_stored}


def _floor(ts: datetime, window_s: int) -> datetime:
    e = int(ts.timestamp())
    return datetime.fromtimestamp(e - e % window_s, tz=timezone.utc)


def process_device(db: Session, dev: Device, source: str, until: datetime) -> list[VibrationFeature]:
    """Aggregate complete 60 s windows of summaries into features and evaluate the alert rules."""
    cfg = get_setting(db, "vibration")
    window_s = int(cfg["window_s"])
    interval = float((dev.config or {}).get("summary_interval_s") or 0.5)
    first = (db.query(func.min(SensorSummary.ts))
             .filter(SensorSummary.device_id == dev.id, SensorSummary.source == source, SensorSummary.processing_status == "raw").scalar())
    if first is None:
        return []
    start = _floor(ensure_utc(first), window_s)
    baseline = active_baseline(db, dev.id, source)
    created = []
    while start + timedelta(seconds=window_s) <= until:
        end = start + timedelta(seconds=window_s)
        rows = (db.query(SensorSummary).filter(SensorSummary.device_id == dev.id, SensorSummary.source == source,
                                               SensorSummary.ts >= start, SensorSummary.ts < end, SensorSummary.processing_status == "raw").all())
        vib = np.array([r.vib_rms_g for r in rows if r.vib_rms_g is not None], float)
        pk = np.array([r.peak_g for r in rows if r.peak_g is not None], float)
        tilt = np.array([r.tilt_deg for r in rows if r.tilt_deg is not None], float)
        if len(vib):
            expected = int(round(window_s / interval))
            completeness = min(1.0, len(vib) / expected)
            feats = {"rms_dyn": float(np.sqrt(np.mean(vib ** 2))), "peak_dyn": float(pk.max()) if len(pk) else float(vib.max())}
            anomaly, reasons, thresholds = evaluate_anomaly(feats, baseline, cfg, completeness)
            vf = VibrationFeature(
                device_id=dev.id, component_id=dev.component_id, source=source, window_start=start, window_end=end, window_s=window_s,
                sample_count=len(vib), expected_count=expected, missing_ratio=max(0.0, 1 - completeness), duplicate_count=0, gap_count=0,
                rms_dyn=feats["rms_dyn"], peak_dyn=feats["peak_dyn"], tilt_mean_deg=float(tilt.mean()) if len(tilt) else None,
                feature_version=FEATURE_VERSION, baseline_id=baseline.id if baseline else None, baseline_version=baseline.version if baseline else None,
                baseline_ratio=(feats["rms_dyn"] / baseline.rms_dyn_mean) if baseline and baseline.rms_dyn_mean > 0 else None,
                anomaly=anomaly, anomaly_reasons=reasons, thresholds=thresholds,
                data_quality="ok" if completeness >= cfg["min_window_completeness"] else "incomplete",
            )
            db.add(vf)
            db.flush()
            created.append(vf)
            if anomaly:
                alert_engine.on_feature_anomaly(db, vf, dev)
            if vf.tilt_mean_deg is not None and vf.data_quality == "ok":
                check_tilt(db, dev, vf, cfg)
        for r in rows:
            r.processing_status = "processed"
        start = end
        if not rows:
            nxt = (db.query(func.min(SensorSummary.ts)).filter(SensorSummary.device_id == dev.id, SensorSummary.source == source,
                                                                SensorSummary.ts >= end).scalar())
            if nxt is None:
                break
            start = max(end, _floor(ensure_utc(nxt), window_s))
    if created:
        broadcaster.publish("features", {"device_id": dev.id, "source": source})
    return created


def check_tilt(db: Session, dev: Device, vf: VibrationFeature, cfg: dict) -> None:
    """The first complete window becomes the tilt reference (resettable); alert when |tilt − reference| > limit."""
    dcfg = dict(dev.config or {})
    if dcfg.get("tilt_reference_deg") is None:
        dcfg["tilt_reference_deg"] = round(vf.tilt_mean_deg, 3)
        dcfg["tilt_reference_set_at"] = vf.window_end.isoformat()
        dev.config = dcfg
        return
    limit = cfg.get("tilt_change_limit_deg")
    change = vf.tilt_mean_deg - float(dcfg["tilt_reference_deg"])
    if limit is None or abs(change) <= float(limit):
        return
    vf.anomaly_reasons = (vf.anomaly_reasons or []) + ["tilt_change_above_limit"]
    alert_engine.raise_alert(
        db, rule_type="tilt_change", asset_id=dev.asset_id, component_id=dev.component_id, device_id=dev.id,
        dedup_key=f"tilt_change:{dev.id}:{vf.source}", title=f"Tilt changed at {dev.name}",
        message=(f"Mean tilt {vf.tilt_mean_deg:.2f}° in {vf.window_start:%H:%M}–{vf.window_end:%H:%M} vs reference "
                 f"{float(dcfg['tilt_reference_deg']):.2f}° (change {change:+.2f}°, limit ±{float(limit):g}°). "
                 "Check first whether the sensor mount moved."),
        evidence=[alert_engine.Evidence("vibration_feature", f"VF-{vf.id}", "window tilt", {"tilt_mean_deg": vf.tilt_mean_deg,
                                                                                           "reference_deg": dcfg["tilt_reference_deg"], "limit_deg": limit})],
        data_source=vf.source, now=vf.window_end,
    )


def reset_tilt_reference(db: Session, dev: Device, value: float | None = None) -> dict:
    """Set the reference to ``value`` or to the mean tilt of the last 60 s of summaries."""
    if value is None:
        since = utcnow() - timedelta(seconds=60)
        vals = [t for (t,) in db.query(SensorSummary.tilt_deg).filter(SensorSummary.device_id == dev.id, SensorSummary.ts >= since,
                                                                       SensorSummary.tilt_deg.isnot(None)).all()]
        if not vals:
            raise ValueError("No tilt readings in the last 60 s.")
        value = float(np.mean(vals))
    cfg = dict(dev.config or {})
    cfg["tilt_reference_deg"], cfg["tilt_reference_set_at"] = round(float(value), 3), utcnow().isoformat()
    dev.config = cfg
    return {"tilt_reference_deg": cfg["tilt_reference_deg"], "set_at": cfg["tilt_reference_set_at"]}
