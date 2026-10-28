"""Simulation provider for development/demonstration.

Every generated sample is stored with ``source='simulated'`` and only for
devices registered with ``data_source='simulated'``. Simulated devices are
never reported as physically connected.

Signal model (illustrative, not calibrated to any real structure): gravity on
the Z axis + two low-frequency sinusoidal modes whose amplitude is modulated
by random "traffic" bursts + white noise. An optional anomaly episode
multiplies the dynamic amplitude.
"""
from __future__ import annotations

import math
import zlib
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import func, insert
from sqlalchemy.orm import Session

from app.models import Device, SensorReading


def _device_constant(device_id: str) -> float:
    """Stable per-device value in [0, 1) (crc32, unlike hash(), is not randomised per process)."""
    return (zlib.crc32(device_id.encode()) % 10_000) / 10_000


def _signal(n: int, rate: float, t0: float, rng: np.random.Generator, amp_scale: float = 1.0, anomaly_mask=None, phase: float = 0.0):
    # Deterministic in absolute time so consecutive chunks (live mode) form one continuous, stationary signal.
    t = t0 + np.arange(n) / rate
    # traffic envelope: periodic smooth bursts
    env = 0.4 + 0.6 * np.clip(np.sin(2 * math.pi * t / 47.0 + 2 * math.pi * phase) ** 8, 0, 1.5)
    if anomaly_mask is not None:
        env = env * np.where(anomaly_mask, 5.0, 1.0)
    m1 = 0.012 * np.sin(2 * math.pi * 0.85 * t + 0.3)
    m2 = 0.006 * np.sin(2 * math.pi * 2.3 * t + 1.1)
    dyn = amp_scale * env * (m1 + m2)
    ax = 0.01 + 0.3 * dyn + rng.normal(0, 0.002, n)
    ay = -0.005 + 0.2 * dyn + rng.normal(0, 0.002, n)
    az = 1.0 + dyn + rng.normal(0, 0.002, n)
    return ax, ay, az


def generate(db: Session, device: Device, start: datetime, end: datetime, anomaly_windows: list[tuple[datetime, datetime]] | None = None,
             seed: int | None = None) -> int:
    if device.data_source != "simulated":
        raise ValueError("Simulation is only allowed for devices registered as simulated.")
    rate = device.sample_rate_hz or 10.0
    n = int((end - start).total_seconds() * rate)
    if n <= 0:
        return 0
    rng = np.random.default_rng(seed)
    t_rel = np.arange(n) / rate
    mask = np.zeros(n, dtype=bool)
    for a0, a1 in anomaly_windows or []:
        mask |= (t_rel >= (a0 - start).total_seconds()) & (t_rel < (a1 - start).total_seconds())
    k = _device_constant(device.id)
    amp = 1.0 + round(k * 7) / 10.0
    ax, ay, az = _signal(n, rate, start.timestamp(), rng, amp, mask, phase=k)
    last_seq = db.query(func.max(SensorReading.seq)).filter(SensorReading.device_id == device.id, SensorReading.source == "simulated").scalar()
    seq0 = (last_seq or 0) + 1
    rows = [
        {
            "device_id": device.id, "component_id": device.component_id, "ts": start + timedelta(seconds=float(t_rel[i])),
            "seq": seq0 + i, "ax": float(ax[i]), "ay": float(ay[i]), "az": float(az[i]), "quality": "ok", "source": "simulated",
            "processing_status": "raw", "received_at": end,
        }
        for i in range(n)
    ]
    for i in range(0, n, 5000):
        db.execute(insert(SensorReading), rows[i : i + 5000])
    device.last_seen_at = start + timedelta(seconds=float(t_rel[-1]))
    return n


def generate_live(db: Session, now: datetime) -> int:
    """Append simulated samples since each simulated sensor's last sample (max 10 minutes catch-up)."""
    total = 0
    for dev in db.query(Device).filter(Device.data_source == "simulated", Device.device_type != "camera", Device.operational_status == "active").all():
        last = db.query(func.max(SensorReading.ts)).filter(SensorReading.device_id == dev.id, SensorReading.source == "simulated").scalar()
        start = max(last + timedelta(seconds=1 / (dev.sample_rate_hz or 10)), now - timedelta(minutes=10)) if last else now - timedelta(seconds=60)
        if (now - start).total_seconds() >= 1:
            total += generate(db, dev, start, now)
    return total
