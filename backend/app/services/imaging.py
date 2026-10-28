"""Image validation and quality checks (OpenCV)."""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

from app.config import get_settings

_FORMAT_TO_MIME = {"JPEG": "image/jpeg", "PNG": "image/png", "BMP": "image/bmp", "WEBP": "image/webp"}


class ImageValidationError(ValueError):
    pass


@dataclass
class ValidatedImage:
    data: bytes
    content_type: str
    width: int
    height: int
    sha256: str
    extension: str
    bgr: np.ndarray


def validate_image(data: bytes, declared_type: str | None = None) -> ValidatedImage:
    """Validate size, real file type (by decoding, not by extension) and dimensions."""
    settings = get_settings()
    max_bytes = int(settings.max_upload_mb * 1024 * 1024)
    if not data:
        raise ImageValidationError("Empty file.")
    if len(data) > max_bytes:
        raise ImageValidationError(f"File exceeds the {settings.max_upload_mb:g} MB limit.")
    Image.MAX_IMAGE_PIXELS = settings.max_image_pixels
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = im.format
            im.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ImageValidationError("File is not a readable image.") from exc
    mime = _FORMAT_TO_MIME.get(fmt or "")
    if mime is None or mime not in settings.allowed_image_types:
        raise ImageValidationError(f"Unsupported image format: {fmt}. Allowed: {', '.join(settings.allowed_image_types)}.")
    arr = np.frombuffer(data, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ImageValidationError("Image could not be decoded.")
    h, w = bgr.shape[:2]
    if w < 32 or h < 32:
        raise ImageValidationError("Image is too small (minimum 32×32 pixels).")
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/bmp": "bmp", "image/webp": "webp"}[mime]
    return ValidatedImage(data=data, content_type=mime, width=w, height=h, sha256=hashlib.sha256(data).hexdigest(), extension=ext, bgr=bgr)


def assess_quality(bgr: np.ndarray) -> dict:
    """Simple, documented image-quality heuristics. Flags issues; does not reject."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    # Median of per-tile Laplacian variance: robust to small sharp regions (text, edges) in an otherwise blurred image.
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    h, w = gray.shape
    tiles = [lap[i * h // 4:(i + 1) * h // 4, j * w // 4:(j + 1) * w // 4].var() for i in range(4) for j in range(4)]
    blur = float(np.median(tiles))
    brightness = float(gray.mean())
    contrast = float(gray.std())
    issues = []
    if blur < 20.0:
        issues.append("possible_blur")
    if brightness < 35:
        issues.append("underexposed")
    if brightness > 225:
        issues.append("overexposed")
    if contrast < 8:
        issues.append("low_contrast")
    return {
        "method": "opencv-heuristics-v2",
        "laplacian_variance": round(blur, 2),
        "mean_brightness": round(brightness, 1),
        "contrast_std": round(contrast, 1),
        "issues": issues,
        "ok": not issues,
        "note": "Heuristic thresholds: blur<20 (median tile Laplacian variance), brightness<35 or >225, contrast std<8.",
    }
