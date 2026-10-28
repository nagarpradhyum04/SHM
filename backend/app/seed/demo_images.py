"""Procedurally generated SYNTHETIC demonstration images.

These are not photographs of any structure. Each carries a visible
"SYNTHETIC DEMO IMAGE" watermark and is stored with ``data_source='demo'``.
"""
from __future__ import annotations

import cv2
import numpy as np

VARIANTS = {
    "crack": "Synthetic concrete texture with a drawn crack-like line",
    "corrosion": "Synthetic concrete texture with rust-coloured staining",
    "exposed_rebar": "Synthetic spalled patch with drawn rebar-like bars",
    "clean": "Synthetic concrete texture with no drawn defect",
    "blurry": "Synthetic texture, heavily blurred (to exercise the quality check)",
}


def _concrete(rng: np.random.Generator, size: int) -> np.ndarray:
    base = rng.normal(150, 12, (size, size)).astype(np.float32)
    base = cv2.GaussianBlur(base, (0, 0), 2.0)
    coarse = cv2.resize(rng.normal(0, 14, (size // 16, size // 16)).astype(np.float32), (size, size), interpolation=cv2.INTER_CUBIC)
    img = base + coarse
    for _ in range(int(size * size / 900)):
        x, y = rng.integers(0, size, 2)
        r = int(rng.integers(1, 4))
        cv2.circle(img, (int(x), int(y)), r, float(rng.normal(115, 15)), -1)
    img = np.clip(img, 0, 255).astype(np.uint8)
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def _crack(img, rng):
    h, w = img.shape[:2]
    pts = [(int(rng.integers(w * 0.35, w * 0.6)), int(rng.integers(h * 0.05, h * 0.15)))]
    angle = rng.uniform(1.3, 1.8)
    for _ in range(60):
        angle = float(np.clip(angle + rng.normal(0, 0.25), 0.9, 2.2))
        step = rng.uniform(6, 12)
        x, y = pts[-1]
        pts.append((int(np.clip(x + step * np.cos(angle), 0, w - 1)), int(np.clip(y + step * np.sin(angle), 0, h - 1))))
    for i in range(len(pts) - 1):
        cv2.line(img, pts[i], pts[i + 1], (40, 40, 42), int(rng.integers(2, 4)), cv2.LINE_AA)
    return {"polyline_px": pts}


def _corrosion(img, rng):
    h, w = img.shape[:2]
    overlay = img.copy()
    for _ in range(6):
        c = (int(rng.integers(w * 0.2, w * 0.8)), int(rng.integers(h * 0.2, h * 0.8)))
        axes = (int(rng.integers(20, 70)), int(rng.integers(40, 120)))
        cv2.ellipse(overlay, c, axes, float(rng.uniform(0, 180)), 0, 360, (30, 70, 140), -1)
    overlay = cv2.GaussianBlur(overlay, (0, 0), 9)
    cv2.addWeighted(overlay, 0.45, img, 0.55, 0, img)
    return {}


def _rebar(img, rng):
    h, w = img.shape[:2]
    x0, y0, x1, y1 = int(w * 0.2), int(h * 0.35), int(w * 0.8), int(h * 0.7)
    cv2.rectangle(img, (x0, y0), (x1, y1), (95, 95, 98), -1)
    for k in range(3):
        y = y0 + 20 + k * 35
        cv2.line(img, (x0 + 5, y), (x1 - 5, y), (35, 55, 95), 9, cv2.LINE_AA)
    return {"bbox_px": [x0, y0, x1, y1]}


def generate_demo_image(variant: str, seed: int = 0, size: int = 512) -> tuple[bytes, dict]:
    if variant not in VARIANTS:
        raise ValueError(f"unknown demo variant {variant}")
    rng = np.random.default_rng(seed)
    img = _concrete(rng, size)
    meta: dict = {}
    if variant == "crack":
        meta = _crack(img, rng)
    elif variant == "corrosion":
        meta = _corrosion(img, rng)
    elif variant == "exposed_rebar":
        meta = _rebar(img, rng)
    elif variant == "blurry":
        _crack(img, rng)
        img = cv2.GaussianBlur(img, (0, 0), 12)
    cv2.rectangle(img, (0, size - 28), (size, size), (20, 20, 20), -1)
    cv2.putText(img, "SYNTHETIC DEMO IMAGE - NOT A REAL STRUCTURE", (8, size - 9), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    meta.update({"variant": variant, "description": VARIANTS[variant], "synthetic": True, "seed": seed})
    return buf.tobytes(), meta
