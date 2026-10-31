"""Measure your webcam's lens (intrinsics) with a printed checkerboard, and store them on the camera.

Why: the 3D position of a detected crack comes from a ray through its pixel. With the nominal
field of view the ray direction is approximate ("low" confidence); with measured intrinsics it
is rated "medium". (The camera's position/orientation in the model still has to be placed well.)

1. Print a checkerboard (e.g. 9×6 inner corners, squares 25 mm) and tape it flat to a board.
2. Run, with the webcam the agent uses:
       python -m edge.calibrate_camera --source 1 --device-id WEBCAM-01
   Hold the board in front of the camera at ~15 different positions/angles; the tool grabs a view
   whenever it sees the whole board (or use --images "folder/*.jpg").
3. It prints fx, fy, cx, cy and the reprojection error, and saves them on the camera (PATCH).
   Re-run if the error is above ~1 px.
"""
from __future__ import annotations

import argparse
import glob
import json
import time
import urllib.request

import cv2
import numpy as np


def calibrate(images: list[np.ndarray], pattern: tuple[int, int], square_mm: float) -> dict:
    objp = np.zeros((pattern[0] * pattern[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:pattern[0], 0:pattern[1]].T.reshape(-1, 2) * square_mm
    obj_pts, img_pts, size = [], [], None
    for img in images:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        size = gray.shape[::-1]
        ok, corners = cv2.findChessboardCorners(gray, pattern, cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE)
        if not ok:
            continue
        corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-3))
        obj_pts.append(objp)
        img_pts.append(corners)
    if len(obj_pts) < 5:
        raise SystemExit(f"Only {len(obj_pts)} usable views found; need at least 5 (ideally 15+).")
    rms, k, dist, _, _ = cv2.calibrateCamera(obj_pts, img_pts, size, None, None)
    return {"fx": float(k[0, 0]), "fy": float(k[1, 1]), "cx": float(k[0, 2]), "cy": float(k[1, 2]), "width": int(size[0]), "height": int(size[1]),
            "distortion": [float(x) for x in dist.ravel()], "reprojection_error_px": float(rms), "views": len(obj_pts),
            "calibrated": True, "method": "opencv checkerboard calibration"}


def capture(source, pattern, n: int, timeout_s: float) -> list[np.ndarray]:
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise SystemExit(f"Cannot open camera {source!r}")
    views, last, start = [], 0.0, time.time()
    print(f"Show the checkerboard in {n} different positions/angles…")
    while len(views) < n and time.time() - start < timeout_s:
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        found, _ = cv2.findChessboardCorners(gray, pattern, cv2.CALIB_CB_FAST_CHECK)
        if found and time.time() - last > 1.5:
            views.append(frame)
            last = time.time()
            print(f"  view {len(views)}/{n} captured — move the board")
    cap.release()
    return views


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default="0", help="webcam index or video file")
    ap.add_argument("--images", help="glob of saved checkerboard photos instead of live capture")
    ap.add_argument("--cols", type=int, default=9, help="inner corners per row")
    ap.add_argument("--rows", type=int, default=6, help="inner corners per column")
    ap.add_argument("--square-mm", type=float, default=25.0)
    ap.add_argument("--views", type=int, default=15)
    ap.add_argument("--timeout", type=float, default=180)
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--device-id", help="camera to update in StructuraSense (omit to only print)")
    args = ap.parse_args()
    pattern = (args.cols, args.rows)
    if args.images:
        imgs = [cv2.imread(p) for p in sorted(glob.glob(args.images))]
        imgs = [i for i in imgs if i is not None]
    else:
        imgs = capture(int(args.source) if args.source.isdigit() else args.source, pattern, args.views, args.timeout)
    result = calibrate(imgs, pattern, args.square_mm)
    print(json.dumps(result, indent=2))
    if result["reprojection_error_px"] > 1.0:
        print("Warning: reprojection error above 1 px — use more varied views and a flat, sharp board.")
    if args.device_id:
        req = urllib.request.Request(f"{args.api.rstrip('/')}/api/v1/devices/{args.device_id}", method="PATCH",
                                     data=json.dumps({"intrinsics": result}).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            print("Saved on", json.loads(r.read())["id"])


if __name__ == "__main__":
    main()
