"""ONNX Runtime image classifier (e.g. crack / no-crack).

Configured entirely by its ``model_card.json`` so a model trained elsewhere
(see ``backend/ml``) can be dropped in without code changes.
"""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np

from app.services.inference.base import Detection, InferenceBackend, InferenceResult


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max())
    return e / e.sum()


class OnnxImageClassifier(InferenceBackend):
    task = "classification"

    def __init__(self, card: dict, model_path: Path):
        import onnxruntime as ort

        self.card = card
        self.model_id = card["id"]
        self.version = str(card["version"])
        self.labels: list[str] = list(card["labels"])
        self.positive_labels: list[str] = list(card.get("positive_labels") or [card.get("positive_label")])
        self.threshold = float(card.get("threshold", 0.5))
        self.output_kind = card.get("output", "softmax")  # softmax | logits | sigmoid
        inp = card.get("input", {})
        self.size = tuple(inp.get("size", [227, 227]))  # (H, W)
        self.color = inp.get("color", "rgb")
        self.layout = inp.get("layout", "NCHW")
        self.scale = float(inp.get("scale", 1 / 255))
        self.mean = np.array(inp.get("mean", [0.0, 0.0, 0.0]), dtype=np.float32)
        self.std = np.array(inp.get("std", [1.0, 1.0, 1.0]), dtype=np.float32)
        self.session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name

    def preprocess(self, bgr: np.ndarray) -> np.ndarray:
        img = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB) if self.color == "rgb" else bgr
        img = cv2.resize(img, (self.size[1], self.size[0]), interpolation=cv2.INTER_AREA)
        x = img.astype(np.float32) * self.scale
        x = (x - self.mean) / self.std
        if self.layout == "NCHW":
            x = np.transpose(x, (2, 0, 1))
        return x[None, ...].astype(np.float32)

    def predict(self, bgr: np.ndarray) -> InferenceResult:
        x = self.preprocess(bgr)
        t0 = time.perf_counter()
        out = self.session.run(None, {self.input_name: x})[0]
        ms = (time.perf_counter() - t0) * 1000
        vec = np.asarray(out, dtype=np.float32).reshape(-1)
        if self.output_kind == "sigmoid" or vec.size == 1:
            p = float(1 / (1 + np.exp(-vec[0]))) if self.output_kind != "probability" else float(vec[0])
            probs = {self.labels[0]: 1 - p, self.labels[-1]: p} if len(self.labels) == 2 else {self.labels[0]: p}
        else:
            pv = _softmax(vec) if self.output_kind == "logits" else vec
            probs = {lbl: float(pv[i]) for i, lbl in enumerate(self.labels)}
        detections = []
        cat_map = self.card.get("category_map") or {}
        for lbl in self.positive_labels:
            score = probs.get(lbl, 0.0)
            if score >= self.threshold:
                detections.append(Detection(category=cat_map.get(lbl, "unclassified"), label=lbl, confidence=score))
        top = max(probs, key=probs.get)
        return InferenceResult(
            model_id=self.model_id,
            model_version=self.version,
            task=self.task,
            detections=detections,
            raw={"probabilities": {k: round(v, 5) for k, v in probs.items()}, "top_label": top},
            threshold=self.threshold,
            inference_ms=ms,
            notes=[
                "Whole-image classification: indicates presence of the class in the image, "
                "not its location or physical size.",
                "Model confidence is not a measure of structural severity.",
            ],
        )
