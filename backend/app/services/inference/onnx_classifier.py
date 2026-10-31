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

    def _probabilities(self, vec: np.ndarray) -> dict[str, float]:
        if self.output_kind == "sigmoid" or vec.size == 1:
            p = float(1 / (1 + np.exp(-vec[0]))) if self.output_kind != "probability" else float(vec[0])
            return {self.labels[0]: 1 - p, self.labels[-1]: p} if len(self.labels) == 2 else {self.labels[0]: p}
        pv = _softmax(vec) if self.output_kind == "logits" else vec
        return {lbl: float(pv[i]) for i, lbl in enumerate(self.labels)}

    def predict(self, bgr: np.ndarray) -> InferenceResult:
        x = self.preprocess(bgr)
        t0 = time.perf_counter()
        out = self.session.run(None, {self.input_name: x})[0]
        ms = (time.perf_counter() - t0) * 1000
        probs = self._probabilities(np.asarray(out, dtype=np.float32).reshape(-1))
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

    def localize(self, bgr: np.ndarray, tile_px: int | None = None, overlap: float = 0.5) -> dict:
        """Coarse crack localisation by sliding-window classification.

        The image is cut into overlapping square tiles (default ``tile_px`` from the model card, else 227 px —
        the crop size of the reference dataset) and each tile is classified. Positive tiles are grouped into
        connected regions; each region gives a pixel bounding box and a probability-weighted centre.
        This is a coarse map at tile resolution, not a pixel-accurate segmentation of the crack.
        """
        h, w = bgr.shape[:2]
        tile = int(min(tile_px or self.card.get("tile_px") or 227, h, w))
        stride = max(1, int(tile * (1 - overlap)))
        ys = list(range(0, max(h - tile, 0) + 1, stride))
        xs = list(range(0, max(w - tile, 0) + 1, stride))
        if ys[-1] + tile < h:
            ys.append(h - tile)
        if xs[-1] + tile < w:
            xs.append(w - tile)
        pos = self.positive_labels[0]
        probs = np.zeros((len(ys), len(xs)), np.float32)
        t0 = time.perf_counter()
        for i, y in enumerate(ys):
            for j, x in enumerate(xs):
                out = self.session.run(None, {self.input_name: self.preprocess(bgr[y:y + tile, x:x + tile])})[0]
                probs[i, j] = self._probabilities(np.asarray(out, np.float32).reshape(-1)).get(pos, 0.0)
        mask = (probs >= self.threshold).astype(np.uint8)
        n, labels = cv2.connectedComponents(mask, connectivity=8)
        regions = []
        for k in range(1, n):
            cells = np.argwhere(labels == k)
            wts = np.array([probs[i, j] for i, j in cells])
            x0 = min(xs[j] for _, j in cells)
            y0 = min(ys[i] for i, _ in cells)
            x1 = max(xs[j] for _, j in cells) + tile
            y1 = max(ys[i] for i, _ in cells) + tile
            cx = float(sum((xs[j] + tile / 2) * p for (i, j), p in zip(cells, wts)) / wts.sum())
            cy = float(sum((ys[i] + tile / 2) * p for (i, j), p in zip(cells, wts)) / wts.sum())
            regions.append({"bbox": [x0, y0, x1, y1], "centroid_px": [round(cx, 1), round(cy, 1)], "max_prob": round(float(wts.max()), 4),
                            "tiles": int(len(cells))})
        regions.sort(key=lambda r: (-r["max_prob"], -r["tiles"]))
        return {
            "method": "sliding-window classification (coarse, tile resolution)", "tile_px": tile, "stride_px": stride,
            "image_size": [w, h], "threshold": self.threshold, "regions": regions,
            "grid": {"xs": xs, "ys": ys, "probs": np.round(probs, 3).tolist()},
            "ms": round((time.perf_counter() - t0) * 1000, 1),
        }
