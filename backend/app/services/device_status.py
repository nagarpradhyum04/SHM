"""Device connection status. Distinguishes offline/stale/never-connected from
healthy, and never reports a simulated device as physically connected."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Device
from app.services.settings_store import get_setting
from app.timeutil import utcnow

STATUS_LABELS = {
    "online": "Online — reporting",
    "stale": "Stale — data older than threshold",
    "offline": "Offline — not reporting",
    "never_connected": "Never connected",
    "simulated": "Simulated source (no physical device)",
    "simulated_idle": "Simulated source — idle",
    "maintenance": "Maintenance",
    "decommissioned": "Decommissioned",
}


def connection_status(db: Session, dev: Device, now=None, thresholds: dict | None = None) -> dict:
    now = now or utcnow()
    th = thresholds or get_setting(db, "device_status")
    age = (now - dev.last_seen_at).total_seconds() if dev.last_seen_at else None
    if dev.operational_status in ("maintenance", "decommissioned"):
        status = dev.operational_status
    elif dev.data_source in ("simulated", "demo"):
        status = "simulated" if age is not None and age <= th["stale_after_s"] else "simulated_idle"
    elif age is None:
        status = "never_connected"
    elif age > th["offline_after_s"]:
        status = "offline"
    elif age > th["stale_after_s"]:
        status = "stale"
    else:
        status = "online"
    return {
        "status": status,
        "label": STATUS_LABELS[status],
        "age_s": age,
        "physically_connected": status in ("online", "stale"),
        "is_simulated": dev.data_source in ("simulated", "demo"),
        "thresholds": th,
    }
