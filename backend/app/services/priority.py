"""Documented, configurable review-priority rules.

Review priority expresses *how urgently a finding should be reviewed by an
engineer*. It is not a certified severity rating or a failure probability.
Model confidence is used only to decide whether an AI finding is eligible for
automatic prioritisation; it never raises severity on its own.

Rules (all parameters live in the ``priority_rules`` setting):

R1 category_base     – starting level from the defect category.
R2 low_ai_confidence – AI findings below ``min_ai_confidence`` become
                       ``unassessed`` (requires engineering review).
R3 extent_rules      – optional, engineer-configured thresholds on measured
                       extent (none shipped by default).
R4 critical_component– optional, raise one level for configured component types.
R5 repeated          – raise one level when the same category is observed
                       repeatedly on the same component (and, when both have
                       surface positions, within ``repeat_radius_m``).
R6 corroboration     – raise one level when a vibration anomaly from a device on
                       the same component falls within the corroboration window.
                       Synthetic (simulated/demo) and genuine (real/uploaded)
                       evidence never corroborate each other.
Unassessed findings are never auto-raised.
"""
from __future__ import annotations

import math
from datetime import timedelta

from sqlalchemy.orm import Session

from app.models import Component, Defect, Device, VibrationFeature
from app.services.settings_store import PRIORITY_LEVELS, get_setting, max_priority, raise_priority

SYNTHETIC = {"simulated", "demo"}


def evidence_class(source: str | None) -> str:
    return "synthetic" if source in SYNTHETIC else "genuine"


def _distance(a: Defect, b: Defect) -> float | None:
    if a.location_kind != "surface" or b.location_kind != "surface":
        return None
    if None in (a.pos_x, a.pos_y, a.pos_z, b.pos_x, b.pos_y, b.pos_z):
        return None
    return math.dist((a.pos_x, a.pos_y, a.pos_z), (b.pos_x, b.pos_y, b.pos_z))


def find_repeats(db: Session, defect: Defect, rules: dict) -> list[Defect]:
    if not defect.component_id:
        return []
    since = defect.observed_at - timedelta(days=rules["repeat_window_days"])
    q = db.query(Defect).filter(
        Defect.component_id == defect.component_id,
        Defect.category == defect.category,
        Defect.observed_at >= since,
        Defect.observed_at <= defect.observed_at,
        Defect.review_status != "false_positive",
    )
    if defect.id:
        q = q.filter(Defect.id != defect.id)
    out = []
    for other in q.all():
        if evidence_class(other.data_source) != evidence_class(defect.data_source):
            continue
        d = _distance(defect, other)
        if d is not None and d > rules["repeat_radius_m"]:
            continue
        out.append(other)
    return out


def find_corroborating_features(db: Session, defect: Defect, rules: dict) -> list[VibrationFeature]:
    if not defect.component_id:
        return []
    device_ids = [d.id for d in db.query(Device).filter(Device.component_id == defect.component_id).all()]
    if not device_ids:
        return []
    w = timedelta(hours=rules["corroboration_window_hours"])
    feats = (
        db.query(VibrationFeature)
        .filter(
            VibrationFeature.device_id.in_(device_ids),
            VibrationFeature.anomaly.is_(True),
            VibrationFeature.window_end >= defect.observed_at - w,
            VibrationFeature.window_start <= defect.observed_at + w,
        )
        .all()
    )
    cls = evidence_class(defect.data_source)
    return [f for f in feats if evidence_class(f.source) == cls]


def compute_priority(db: Session, defect: Defect) -> tuple[str, list[dict]]:
    rules = get_setting(db, "priority_rules")
    rationale: list[dict] = []

    base = rules["category_base"].get(defect.category, "unassessed")
    rationale.append({"rule": "R1 category_base", "effect": base, "detail": f"Base level for category '{defect.category}'."})
    level = base

    if defect.detection_source == "ai_model":
        conf = defect.model_confidence
        if conf is None or conf < rules["min_ai_confidence"]:
            rationale.append(
                {
                    "rule": "R2 low_ai_confidence",
                    "effect": "unassessed",
                    "detail": f"Model confidence {conf} is below the configured minimum {rules['min_ai_confidence']}.",
                }
            )
            return "unassessed", rationale + [_review_note()]

    if level == "unassessed":
        return "unassessed", rationale + [_review_note()]

    extent = defect.measured_extent or {}
    for rule in rules.get("extent_rules") or []:
        if rule.get("category") not in (None, defect.category):
            continue
        val = extent.get(rule.get("field"))
        if val is not None and rule.get("gte") is not None and float(val) >= float(rule["gte"]):
            new = max_priority(level, rule["priority"])
            rationale.append({"rule": "R3 extent", "effect": new, "detail": f"{rule['field']}={val} ≥ {rule['gte']}."})
            level = new

    comp = db.get(Component, defect.component_id) if defect.component_id else None
    if comp and comp.component_type in (rules.get("critical_component_types") or []):
        level = raise_priority(level)
        rationale.append({"rule": "R4 critical_component", "effect": level, "detail": f"Component type '{comp.component_type}' is configured as critical."})

    if rules.get("raise_on_repeat"):
        repeats = find_repeats(db, defect, rules)
        if len(repeats) + 1 >= rules["repeat_min_count"]:
            level = raise_priority(level)
            rationale.append(
                {
                    "rule": "R5 repeated_observation",
                    "effect": level,
                    "detail": f"{len(repeats)} earlier observation(s) of this category on the same component within {rules['repeat_window_days']} days.",
                    "refs": [r.id for r in repeats],
                }
            )

    if rules.get("raise_on_vibration_corroboration"):
        feats = find_corroborating_features(db, defect, rules)
        if feats:
            level = raise_priority(level)
            rationale.append(
                {
                    "rule": "R6 vibration_corroboration",
                    "effect": level,
                    "detail": f"{len(feats)} vibration anomaly window(s) on the same component within ±{rules['corroboration_window_hours']} h ({feats[0].source} data).",
                    "refs": [f"VF-{f.id}" for f in feats[:10]],
                }
            )

    assert level in PRIORITY_LEVELS
    return level, rationale


def _review_note() -> dict:
    return {"rule": "note", "effect": "unassessed", "detail": "Insufficient evidence for automatic prioritisation — requires engineering review."}


def apply_priority(db: Session, defect: Defect) -> bool:
    """Recompute rule-based priority unless a reviewer has set it manually. Returns True if changed."""
    if defect.priority_source == "manual":
        return False
    level, rationale = compute_priority(db, defect)
    changed = level != defect.priority
    defect.priority = level
    defect.priority_rationale = rationale
    return changed
