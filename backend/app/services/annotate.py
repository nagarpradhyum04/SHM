"""Annotated evidence photo: crack region(s), centre mark and a caption band with the coordinates."""
from __future__ import annotations

import cv2
import numpy as np

from app.models import Defect


def annotate(image_bytes: bytes, d: Defect, extra_lines: list[str] | None = None) -> bytes:
    img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("image could not be decoded")
    h, w = img.shape[:2]
    s = max(w, h) / 1000.0
    r = d.image_region or {}
    for i, reg in enumerate(r.get("regions") or ([{"bbox": r["bbox"]}] if r.get("bbox") else [])):
        x0, y0, x1, y1 = (int(v) for v in reg["bbox"])
        color = (0, 0, 255) if i == 0 else (0, 165, 255)
        cv2.rectangle(img, (x0, y0), (x1, y1), color, max(2, int(3 * s)))
    if r.get("point_px"):
        cx, cy = (int(v) for v in r["point_px"])
        cv2.drawMarker(img, (cx, cy), (0, 0, 255), cv2.MARKER_CROSS, int(30 * s), max(2, int(3 * s)))
    lines = [f"{d.category.replace('_', ' ').upper()}  {d.id}" + (f"  conf {d.model_confidence:.2f}" if d.model_confidence is not None else ""),
             f"{d.observed_at:%Y-%m-%d %H:%M:%S} UTC"]
    if r.get("bbox"):
        x0, y0, x1, y1 = r["bbox"]
        c = r.get("point_px") or [(x0 + x1) / 2, (y0 + y1) / 2]
        lines.append(f"photo: x {x0:.0f}-{x1:.0f}, y {y0:.0f}-{y1:.0f} px, centre ({c[0]:.0f}, {c[1]:.0f})")
    if d.pos_x is not None:
        lines.append(f"3D model: ({d.pos_x:.2f}, {d.pos_y:.2f}, {d.pos_z:.2f}) m, confidence {d.location_confidence}")
    if d.latitude is not None:
        lines.append(f"GPS: {d.latitude:.6f}, {d.longitude:.6f}")
    lines += extra_lines or []
    fs = 0.55 * max(s, 0.6)
    lh = int(26 * max(s, 0.6))
    band = np.zeros((lh * len(lines) + lh // 2, w, 3), np.uint8)
    band[:] = (20, 14, 8)
    for i, line in enumerate(lines):
        cv2.putText(band, line, (int(10 * s) + 4, lh * (i + 1)), cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 255, 255), max(1, int(1.5 * s)), cv2.LINE_AA)
    ok, jpg = cv2.imencode(".jpg", np.vstack([img, band]), [cv2.IMWRITE_JPEG_QUALITY, 88])
    return jpg.tobytes()
