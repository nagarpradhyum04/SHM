"""Model-agnostic inference interfaces.

Supported *task interfaces*: classification, detection, segmentation. An
interface existing does not mean a model for it is installed: availability is
reported per installed model in the model registry.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np

TASKS = ("classification", "detection", "segmentation")

# Damage categories the platform understands. AI support for each depends on
# the installed models' category maps.
DEFECT_CATEGORIES = [
    "suspected_crack",
    "suspected_corrosion",
    "exposed_reinforcement",
    "vibration_anomaly",
    "surface_deformation",
    "other",
    "unclassified",
]


@dataclass
class Detection:
    category: str
    label: str
    confidence: float
    bbox: list[float] | None = None  # [x0, y0, x1, y1] image pixels
    polygon: list[list[float]] | None = None  # image pixels


@dataclass
class InferenceResult:
    model_id: str
    model_version: str
    task: str
    detections: list[Detection]
    raw: dict[str, Any]
    threshold: float | None
    inference_ms: float
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "task": self.task,
            "threshold": self.threshold,
            "inference_ms": round(self.inference_ms, 2),
            "detections": [d.__dict__ for d in self.detections],
            "raw": self.raw,
            "notes": self.notes,
        }


class InferenceBackend(ABC):
    model_id: str
    version: str
    task: str
    card: dict

    @property
    def categories(self) -> list[str]:
        return sorted(set((self.card.get("category_map") or {}).values()))

    @abstractmethod
    def predict(self, bgr: np.ndarray) -> InferenceResult: ...


class ModelUnavailableError(RuntimeError):
    pass
