"""Runtime-configurable settings persisted in ``system_config``.

Defaults are documented here. Priority-rule defaults are *placeholders for
configuration by the responsible engineer*; they are not engineering thresholds.
"""
from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.orm import Session

from app.models import SystemConfig

PRIORITY_LEVELS = ["unassessed", "low", "medium", "high", "critical"]
DATA_SOURCES = ["real", "uploaded", "simulated", "demo"]

DEFAULTS: dict[str, Any] = {
    # Which sensor data sources the dashboard displays. Each is always labelled.
    "data_source": {"mode": "simulated", "options": ["real", "uploaded", "simulated", "all"]},
    "priority_rules": {
        "description": (
            "Rule-based review priority. Defaults are placeholders that must be reviewed and "
            "set by the responsible engineer. Priority expresses review urgency, not certified "
            "structural severity or failure probability."
        ),
        "category_base": {
            "suspected_crack": "medium",
            "suspected_corrosion": "medium",
            "exposed_reinforcement": "high",
            "vibration_anomaly": "medium",
            "surface_deformation": "high",
            "other": "unassessed",
            "unclassified": "unassessed",
        },
        # AI detections below this model confidence are not auto-prioritised.
        "min_ai_confidence": 0.5,
        "repeat_window_days": 90,
        "repeat_min_count": 2,
        "repeat_radius_m": 3.0,
        "raise_on_repeat": True,
        "corroboration_window_hours": 24,
        "raise_on_vibration_corroboration": True,
        # Extent rules are intentionally empty: no default thresholds are shipped.
        # Example entry: {"category": "suspected_crack", "field": "width_mm", "gte": 0.3, "priority": "high"}
        "extent_rules": [],
        "critical_component_types": [],
    },
    "device_status": {"stale_after_s": 120, "offline_after_s": 900},
    "vibration": {
        "window_s": 60,
        "anomaly_k_sigma": 4.0,
        "peak_k_sigma": 6.0,
        "min_baseline_windows": 10,
        "min_window_completeness": 0.8,
        # Absolute limits in g on the dynamic part of the acceleration magnitude. None = not configured.
        "abs_rms_dyn_limit_g": None,
        "abs_peak_dyn_limit_g": None,
    },
    # Ambient temperature / humidity limits (None = not configured). These describe exposure conditions
    # (thermal cycling, condensation, freeze-thaw); they do not detect cracks.
    "environment": {
        "temp_max_c": None,
        "temp_min_c": None,
        "humidity_max_pct": None,
        "condensation_margin_c": None,
        "consecutive_samples": 3,
    },
    # Webcam agent: once an AI finding from a camera is open, identical detections within this period are
    # not stored again (prevents one persistent crack from creating a new record every few seconds).
    "camera": {"repeat_suppression_s": 3600, "periodic_keep_s": 3600},
    "simulation": {"live_enabled": False, "sample_rate_hz": 10},
    "display": {"reduced_motion": False, "units": "metric"},
    "retention": {"raw_readings_days": 30, "features_days": 3650, "images_days": None},
    "active_model": {"model_id": None},
}


def get_setting(db: Session, key: str) -> Any:
    row = db.get(SystemConfig, key)
    default = copy.deepcopy(DEFAULTS.get(key))
    if row is None:
        return default
    if isinstance(default, dict) and isinstance(row.value, dict):
        merged = default
        merged.update(row.value)
        return merged
    return row.value


def set_setting(db: Session, key: str, value: Any, actor: str | None = None) -> Any:
    row = db.get(SystemConfig, key)
    if row is None:
        row = SystemConfig(key=key, value=value, updated_by=actor)
        db.add(row)
    else:
        row.value = value
        row.updated_by = actor
    db.flush()
    return get_setting(db, key)


def all_settings(db: Session) -> dict[str, Any]:
    keys = set(DEFAULTS) | {r.key for r in db.query(SystemConfig).all()}
    return {k: get_setting(db, k) for k in sorted(keys)}


def raise_priority(level: str, steps: int = 1) -> str:
    if level == "unassessed":
        return level
    idx = min(PRIORITY_LEVELS.index(level) + steps, len(PRIORITY_LEVELS) - 1)
    return PRIORITY_LEVELS[idx]


def max_priority(a: str, b: str) -> str:
    return a if PRIORITY_LEVELS.index(a) >= PRIORITY_LEVELS.index(b) else b
