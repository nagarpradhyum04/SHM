"""Discovers installed models from ``SS_MODEL_DIR`` and keeps the DB registry in sync.

Layout: ``<model_dir>/<anything>/model_card.json`` (+ the file named in ``file``).
If no valid model is installed, inference reports an explicit unavailable state.
No fallback/random predictions are ever produced.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ModelRecord
from app.services.inference.base import TASKS, InferenceBackend, ModelUnavailableError
from app.services.settings_store import get_setting

log = logging.getLogger(__name__)

REQUIRED_CARD_FIELDS = ["id", "name", "version", "task", "framework", "file", "labels"]


class ModelRegistry:
    def __init__(self, model_dir: Path):
        self.model_dir = Path(model_dir)
        self._loaded: dict[str, InferenceBackend] = {}
        self._errors: dict[str, str] = {}
        self._cards: dict[str, dict] = {}
        self._lock = threading.Lock()

    def scan(self) -> None:
        with self._lock:
            self._loaded.clear()
            self._errors.clear()
            self._cards.clear()
            if not self.model_dir.exists():
                return
            for card_path in sorted(self.model_dir.glob("*/model_card.json")):
                key = card_path.parent.name
                try:
                    card = json.loads(card_path.read_text())
                    missing = [f for f in REQUIRED_CARD_FIELDS if f not in card]
                    if missing:
                        raise ValueError(f"model card missing fields: {missing}")
                    if card["task"] not in TASKS:
                        raise ValueError(f"unsupported task {card['task']}")
                    self._cards[card["id"]] = card
                    model_path = card_path.parent / card["file"]
                    if not model_path.exists():
                        raise FileNotFoundError(f"model file not found: {card['file']}")
                    if card["framework"] == "onnx" and card["task"] == "classification":
                        from app.services.inference.onnx_classifier import OnnxImageClassifier

                        self._loaded[card["id"]] = OnnxImageClassifier(card, model_path)
                    else:
                        raise ValueError(f"no runtime for framework={card['framework']} task={card['task']}")
                except Exception as exc:  # noqa: BLE001 - surfaced to the UI
                    self._errors[key] = str(exc)
                    log.warning("model %s not loaded: %s", card_path, exc)

    def sync_db(self, db: Session) -> None:
        active_id = (get_setting(db, "active_model") or {}).get("model_id")
        seen = set()
        for mid, card in self._cards.items():
            seen.add(mid)
            rec = db.get(ModelRecord, mid) or ModelRecord(id=mid)
            rec.name = card["name"]
            rec.task = card["task"]
            rec.categories = sorted(set((card.get("category_map") or {}).values()))
            rec.version = str(card["version"])
            rec.framework = card["framework"]
            rec.status = "installed" if mid in self._loaded else "invalid"
            rec.threshold = card.get("threshold")
            rec.dataset = card.get("dataset")
            rec.preprocessing = card.get("input")
            rec.metrics = card.get("metrics")
            rec.model_card = card
            rec.is_active = mid == self.active_id(active_id)
            db.add(rec)
        for rec in db.query(ModelRecord).all():
            if rec.id not in seen:
                rec.status = "missing_file"
                rec.is_active = False
        db.flush()

    def active_id(self, preferred: str | None) -> str | None:
        if preferred and preferred in self._loaded:
            return preferred
        return next(iter(sorted(self._loaded)), None)

    def get(self, preferred: str | None = None) -> InferenceBackend:
        mid = self.active_id(preferred)
        if mid is None:
            raise ModelUnavailableError(
                "No trained inference model is installed. Images are stored and can be reviewed manually; "
                "see backend/ml/README.md to train and install a model."
            )
        return self._loaded[mid]

    def status(self) -> dict:
        return {
            "model_dir_configured": True,
            "loaded": [
                {"id": m.model_id, "version": m.version, "task": m.task, "categories": m.categories}
                for m in self._loaded.values()
            ],
            "errors": self._errors,
            "available": bool(self._loaded),
            "ai_supported_categories": sorted({c for m in self._loaded.values() for c in m.categories}),
        }


_registry: ModelRegistry | None = None


def get_model_registry() -> ModelRegistry:
    global _registry
    if _registry is None:
        _registry = ModelRegistry(get_settings().model_dir)
        _registry.scan()
    return _registry


def set_model_registry(r: ModelRegistry | None) -> None:
    global _registry
    _registry = r
