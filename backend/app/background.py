"""Background loop: live simulation, feature extraction, device status checks, retention."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta



from app.db import get_database
from app.models import Device, SensorReading
from app.services import alert_engine, simulation, vibration
from app.services.events import broadcaster
from app.services.settings_store import get_setting
from app.timeutil import utcnow

log = logging.getLogger(__name__)
SIM_RAW_RETENTION = timedelta(hours=6)


def tick(state: dict) -> None:
    db = get_database().session()
    try:
        now = utcnow()
        if get_setting(db, "simulation").get("live_enabled"):
            n = simulation.generate_live(db, now)
            if n:
                broadcaster.publish("readings", {"source": "simulated", "count": n})
        pairs = db.query(SensorReading.device_id, SensorReading.source).filter(SensorReading.processing_status == "raw").distinct().all()
        for dev_id, source in pairs:
            dev = db.get(Device, dev_id)
            if dev:
                feats = vibration.process_device(db, dev, source, now, on_anomaly=alert_engine.on_feature_anomaly)
                if feats:
                    broadcaster.publish("features", {"device_id": dev_id, "source": source})
        alert_engine.evaluate_device_status(db, now)
        if now - state.get("last_retention", now - timedelta(hours=1)) >= timedelta(minutes=10):
            state["last_retention"] = now
            apply_retention(db, now)
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("background tick failed")
    finally:
        db.close()


def apply_retention(db, now) -> int:
    ret = get_setting(db, "retention")
    n = db.query(SensorReading).filter(SensorReading.source == "simulated", SensorReading.processing_status == "processed",
                                       SensorReading.ts < now - SIM_RAW_RETENTION).delete(synchronize_session=False)
    days = ret.get("raw_readings_days")
    if days:
        n += db.query(SensorReading).filter(SensorReading.source != "simulated", SensorReading.processing_status == "processed",
                                            SensorReading.ts < now - timedelta(days=days)).delete(synchronize_session=False)
    return n


async def run_loop(interval: float, stop: asyncio.Event) -> None:
    state: dict = {}
    while not stop.is_set():
        await asyncio.to_thread(tick, state)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass



