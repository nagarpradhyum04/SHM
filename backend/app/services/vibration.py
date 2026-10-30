"""Vibration feature extraction and baseline comparison.

Feature definition ``vib-features-v1`` (per fixed, non-overlapping window):
* mean/std/rms per axis of raw acceleration (g)
* magnitude a = sqrt(ax² + ay² + az²); dynamic part d = a − mean(a) (removes gravity/static tilt)
* rms_dyn = sqrt(mean(d²)); peak_dyn = max |d|
* completeness = samples / (window_s × sample_rate); duplicates = repeated sequence numbers;
  gaps = sequence jumps > 1

Anomaly rule ``vib-anomaly-v1`` (only on windows with completeness ≥ min_window_completeness
and an active baseline from the *same data source*):
* rms_dyn  > baseline.rms_dyn_mean  + k   · σ_rms
* peak_dyn > baseline.peak_dyn_mean + k_p · σ_peak
where σ = max(baseline std, 5 % of baseline mean) to avoid zero-variance baselines.

Absolute limits (optional, set by the responsible engineer in Settings → vibration):
* rms_dyn  > abs_rms_dyn_limit_g   → "rms_dyn_above_absolute_limit"
* peak_dyn > abs_peak_dyn_limit_g  → "peak_dyn_above_absolute_limit"
These are evaluated on complete windows even before a baseline exists. No default values
are shipped: a limit only applies once it has been configured.

An anomaly flags a window for review. It is not, by itself, evidence of damage
(traffic, wind, temperature and sensor faults all cause spikes).
"""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import Baseline, Device, SensorReading, VibrationFeature
from app.services.settings_store import get_setting

FEATURE_VERSION = "vib-features-v1"
ANOMALY_RULE_VERSION = "vib-anomaly-v1"
SIGMA_FLOOR_FRACTION = 0.05


def compute_features(ax, ay, az, seqs) -> dict:
    """Pure function: compute window features from arrays of samples."""
    a = np.column_stack([np.asarray(ax, float), np.asarray(ay, float), np.asarray(az, float)])
    n = len(a)
    if n == 0:
        raise ValueError("no samples")
    mag = np.linalg.norm(a, axis=1)
    dyn = mag - mag.mean()
    seqs = np.asarray(seqs, dtype=np.int64)
    uniq = np.unique(seqs)
    duplicates = int(n - len(uniq))
    gaps = int(np.sum(np.diff(uniq) > 1)) if len(uniq) > 1 else 0
    return {
        "sample_count": n,
        "duplicate_count": duplicates,
        "gap_count": gaps,
        "mean_x": float(a[:, 0].mean()), "mean_y": float(a[:, 1].mean()), "mean_z": float(a[:, 2].mean()),
        "std_x": float(a[:, 0].std()), "std_y": float(a[:, 1].std()), "std_z": float(a[:, 2].std()),
        "rms_x": float(np.sqrt((a[:, 0] ** 2).mean())), "rms_y": float(np.sqrt((a[:, 1] ** 2).mean())),
        "rms_z": float(np.sqrt((a[:, 2] ** 2).mean())),
        "rms_dyn": float(np.sqrt((dyn ** 2).mean())),
        "peak_dyn": float(np.abs(dyn).max()),
    }


def evaluate_anomaly(features: dict, baseline: Baseline | None, cfg: dict, completeness: float | None) -> tuple[bool, list[str], dict]:
    thresholds = {
        "rule_version": ANOMALY_RULE_VERSION,
        "k_sigma": cfg["anomaly_k_sigma"],
        "peak_k_sigma": cfg["peak_k_sigma"],
        "min_window_completeness": cfg["min_window_completeness"],
        "sigma_floor_fraction": SIGMA_FLOOR_FRACTION,
    }
    if completeness is not None and completeness < cfg["min_window_completeness"]:
        return False, ["not_evaluated:incomplete_window"], thresholds
    reasons: list[str] = []
    abs_rms, abs_pk = cfg.get("abs_rms_dyn_limit_g"), cfg.get("abs_peak_dyn_limit_g")
    if abs_rms is not None or abs_pk is not None:
        thresholds.update({"abs_rms_dyn_limit_g": abs_rms, "abs_peak_dyn_limit_g": abs_pk})
    if abs_rms is not None and features["rms_dyn"] > abs_rms:
        reasons.append("rms_dyn_above_absolute_limit")
    if abs_pk is not None and features["peak_dyn"] > abs_pk:
        reasons.append("peak_dyn_above_absolute_limit")
    if baseline is None:
        return bool(reasons), reasons or ["not_evaluated:no_baseline"], thresholds
    s_rms = max(baseline.rms_dyn_std, SIGMA_FLOOR_FRACTION * baseline.rms_dyn_mean)
    s_pk = max(baseline.peak_dyn_std, SIGMA_FLOOR_FRACTION * baseline.peak_dyn_mean)
    rms_lim = baseline.rms_dyn_mean + cfg["anomaly_k_sigma"] * s_rms
    pk_lim = baseline.peak_dyn_mean + cfg["peak_k_sigma"] * s_pk
    thresholds.update({"rms_dyn_limit": rms_lim, "peak_dyn_limit": pk_lim, "baseline_id": baseline.id, "baseline_version": baseline.version})
    if features["rms_dyn"] > rms_lim:
        reasons.append("rms_dyn_above_baseline")
    if features["peak_dyn"] > pk_lim:
        reasons.append("peak_dyn_above_baseline")
    return bool(reasons), reasons, thresholds


def active_baseline(db: Session, device_id: str, source: str) -> Baseline | None:
    return (
        db.query(Baseline)
        .filter(Baseline.device_id == device_id, Baseline.source == source, Baseline.active.is_(True))
        .order_by(Baseline.version.desc())
        .first()
    )


def _floor_window(ts: datetime, window_s: int) -> datetime:
    epoch = int(ts.timestamp())
    return datetime.fromtimestamp(epoch - epoch % window_s, tz=ts.tzinfo)


def process_device(db: Session, device: Device, source: str, until: datetime, on_anomaly=None) -> list[VibrationFeature]:
    """Compute features for all complete windows not yet processed, up to ``until``."""
    cfg = get_setting(db, "vibration")
    window_s = int(cfg["window_s"])
    last_end = (
        db.query(func.max(VibrationFeature.window_end))
        .filter(VibrationFeature.device_id == device.id, VibrationFeature.source == source)
        .scalar()
    )
    first_ts = (
        db.query(func.min(SensorReading.ts))
        .filter(SensorReading.device_id == device.id, SensorReading.source == source, SensorReading.processing_status == "raw")
        .scalar()
    )
    if first_ts is None:
        return []
    start = last_end if last_end and last_end > first_ts else _floor_window(first_ts, window_s)
    if last_end and first_ts > last_end:
        start = _floor_window(first_ts, window_s)
    created: list[VibrationFeature] = []
    baseline = active_baseline(db, device.id, source)
    while start + timedelta(seconds=window_s) <= until:
        end = start + timedelta(seconds=window_s)
        rows = (
            db.query(SensorReading.ax, SensorReading.ay, SensorReading.az, SensorReading.seq, SensorReading.id)
            .filter(SensorReading.device_id == device.id, SensorReading.source == source,
                    SensorReading.ts >= start, SensorReading.ts < end, SensorReading.quality != "invalid")
            .all()
        )
        if rows:
            ax, ay, az, seqs, ids = zip(*rows)
            feats = compute_features(ax, ay, az, seqs)
            expected = int(window_s * device.sample_rate_hz) if device.sample_rate_hz else None
            completeness = (feats["sample_count"] - feats["duplicate_count"]) / expected if expected else None
            anomaly, reasons, thresholds = evaluate_anomaly(feats, baseline, cfg, completeness)
            quality = "ok" if completeness is None or completeness >= cfg["min_window_completeness"] else "incomplete"
            vf = VibrationFeature(
                device_id=device.id, component_id=device.component_id, source=source, window_start=start, window_end=end,
                window_s=window_s, expected_count=expected,
                missing_ratio=None if completeness is None else max(0.0, 1 - completeness),
                feature_version=FEATURE_VERSION, baseline_id=baseline.id if baseline else None,
                baseline_version=baseline.version if baseline else None,
                baseline_ratio=(feats["rms_dyn"] / baseline.rms_dyn_mean) if baseline and baseline.rms_dyn_mean > 0 else None,
                anomaly=anomaly, anomaly_reasons=reasons, thresholds=thresholds, data_quality=quality, **feats,
            )
            db.add(vf)
            db.flush()
            db.query(SensorReading).filter(SensorReading.id.in_(ids)).update({"processing_status": "processed"}, synchronize_session=False)
            created.append(vf)
            if anomaly and on_anomaly:
                on_anomaly(db, vf, device)
        start = end
        # Skip empty stretches quickly
        if not rows:
            nxt = (
                db.query(func.min(SensorReading.ts))
                .filter(SensorReading.device_id == device.id, SensorReading.source == source, SensorReading.ts >= end)
                .scalar()
            )
            if nxt is None:
                break
            start = max(end, _floor_window(nxt, window_s))
    return created


def create_baseline(db: Session, device: Device, source: str, start: datetime, end: datetime, actor: str | None = None, notes: str | None = None) -> Baseline:
    cfg = get_setting(db, "vibration")
    feats = (
        db.query(VibrationFeature)
        .filter(VibrationFeature.device_id == device.id, VibrationFeature.source == source,
                VibrationFeature.window_start >= start, VibrationFeature.window_end <= end, VibrationFeature.data_quality == "ok")
        .all()
    )
    if len(feats) < cfg["min_baseline_windows"]:
        raise ValueError(f"Baseline needs at least {cfg['min_baseline_windows']} complete feature windows; found {len(feats)}.")
    rms = np.array([f.rms_dyn for f in feats])
    pk = np.array([f.peak_dyn for f in feats])
    prev = db.query(func.max(Baseline.version)).filter(Baseline.device_id == device.id, Baseline.source == source).scalar() or 0
    db.query(Baseline).filter(Baseline.device_id == device.id, Baseline.source == source).update({"active": False})
    b = Baseline(
        id=new_id("BSL"), device_id=device.id, version=prev + 1, source=source, window_start=start, window_end=end,
        n_windows=len(feats), feature_version=FEATURE_VERSION, rms_dyn_mean=float(rms.mean()), rms_dyn_std=float(rms.std()),
        peak_dyn_mean=float(pk.mean()), peak_dyn_std=float(pk.std()), active=True, notes=notes, created_by=actor,
    )
    db.add(b)
    db.flush()
    return b
