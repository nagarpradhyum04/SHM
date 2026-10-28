"""Remaining-useful-life (RUL) module interface.

Independent from the dashboard. No validated RUL model is shipped, so the
estimator always returns an explicit *unavailable* result together with a
summary of which inputs exist. A crack classifier's confidence is never used
as a proxy for remaining life.

To implement: subclass ``RULEstimator``, validate it against reference data,
and register it in ``ESTIMATORS``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import Component, Defect, Device, Inspection, RULResult, VibrationFeature

UNAVAILABLE_MESSAGE = "RUL prediction unavailable: insufficient validated data."

REQUIRED_INPUTS = [
    "time_series_structural_measurements",
    "historical_deterioration_observations",
    "environmental_conditions",
    "loading_and_usage",
    "material_and_component_properties",
    "validated_reference_data_and_engineering_assumptions",
]


class RULEstimator(ABC):
    version: str

    @abstractmethod
    def estimate(self, db: Session, asset_id: str, component_id: str | None, coverage: dict) -> RULResult: ...


ESTIMATORS: dict[str, RULEstimator] = {}


def input_coverage(db: Session, asset_id: str, component_id: str | None) -> dict:
    dq = db.query(Defect).filter(Defect.asset_id == asset_id)
    iq = db.query(Inspection).filter(Inspection.asset_id == asset_id)
    devq = db.query(Device.id).filter(Device.asset_id == asset_id)
    if component_id:
        dq, iq, devq = dq.filter(Defect.component_id == component_id), iq.filter(Inspection.component_id == component_id), devq.filter(Device.component_id == component_id)
    dev_ids = [d for (d,) in devq.all()]
    fq = db.query(VibrationFeature.source, func.count(), func.min(VibrationFeature.window_start), func.max(VibrationFeature.window_end)).filter(
        VibrationFeature.device_id.in_(dev_ids)).group_by(VibrationFeature.source)
    feats = {s: {"windows": n, "from": a.isoformat() if a else None, "to": b.isoformat() if b else None} for s, n, a, b in fq.all()}
    comp = db.get(Component, component_id) if component_id else None
    return {
        "time_series_structural_measurements": {"available": bool(feats.get("real") or feats.get("uploaded")), "by_source": feats,
                                                "note": "Simulated data is never used for RUL."},
        "historical_deterioration_observations": {"available": dq.count() > 0, "defects": dq.count(), "inspections": iq.count(),
                                                  "note": "No quantitative deterioration measurements (e.g. crack growth) are recorded."},
        "environmental_conditions": {"available": False},
        "loading_and_usage": {"available": False},
        "material_and_component_properties": {"available": bool(comp and comp.material), "material": comp.material if comp else None},
        "validated_reference_data_and_engineering_assumptions": {"available": False},
    }


def estimate(db: Session, asset_id: str, component_id: str | None = None, estimator: str | None = None) -> RULResult:
    coverage = input_coverage(db, asset_id, component_id)
    if estimator and estimator in ESTIMATORS:
        res = ESTIMATORS[estimator].estimate(db, asset_id, component_id, coverage)
    else:
        res = RULResult(
            id=new_id("RUL"), asset_id=asset_id, component_id=component_id, status="unavailable", estimate=None, units=None, horizon=None,
            model_version=None, input_coverage=coverage, validation_status="no_validated_model",
            limitations=[
                "No validated RUL model is installed.",
                "Required inputs (environment, loading, deterioration rates, validated reference data) are not available.",
                "Crack-classifier confidence is not a proxy for remaining life.",
            ],
            message=UNAVAILABLE_MESSAGE,
        )
    db.add(res)
    db.flush()
    return res
