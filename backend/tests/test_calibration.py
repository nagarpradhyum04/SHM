import cv2
import numpy as np
import pytest

from edge.calibrate_camera import calibrate


def _render_views(k: np.ndarray, size=(640, 480), pattern=(9, 6), square=25.0, n=14):
    """Render a flat checkerboard seen from known poses through a known lens (no distortion)."""
    cols, rows = pattern[0] + 1, pattern[1] + 1
    px = 20  # pixels per square in the texture
    board = np.full(((rows + 2) * px, (cols + 2) * px), 255, np.uint8)
    for r in range(rows):
        for c in range(cols):
            if (r + c) % 2 == 0:
                board[(r + 1) * px:(r + 2) * px, (c + 1) * px:(c + 2) * px] = 0
    s = square / px  # mm per texture pixel; texture origin sits one square before the first inner corner
    rng = np.random.default_rng(1)
    views = []
    for _ in range(n):
        rx, ry = rng.uniform(-0.5, 0.5, 2)
        rvec = np.array([rx, ry, rng.uniform(-0.3, 0.3)])
        r, _ = cv2.Rodrigues(rvec)
        t = np.array([rng.uniform(-60, 0), rng.uniform(-60, 0), rng.uniform(450, 650)])
        m = np.array([[s, 0, -2 * square], [0, s, -2 * square], [0, 0, 1]])  # texture px → board mm (inner-corner origin)
        h = k @ np.column_stack([r[:, 0], r[:, 1], t]) @ m
        img = cv2.warpPerspective(board, h, size, borderValue=128)
        views.append(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR))
    return views


def test_checkerboard_calibration_recovers_known_lens():
    k = np.array([[520.0, 0, 330.0], [0, 520.0, 235.0], [0, 0, 1]])
    res = calibrate(_render_views(k), (9, 6), 25.0)
    assert res["views"] >= 10
    assert res["fx"] == pytest.approx(520, rel=0.02) and res["fy"] == pytest.approx(520, rel=0.02)
    assert res["cx"] == pytest.approx(330, abs=8) and res["cy"] == pytest.approx(235, abs=8)
    assert res["reprojection_error_px"] < 1.0 and res["calibrated"] is True
