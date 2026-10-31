"""Spatial mapping between image observations and the 3D model.

Coordinate systems are kept distinct:
* image   – pixels (u right, v down) of an evidence image
* camera  – camera frame: x right, y up, looking along −z
* model   – local 3D scene coordinates (metres, Y-up); NOT geographic
* geo     – WGS84 lat/lon, only through an asset ``geo_transform``

Localization hierarchy (method → best achievable confidence):
1. manual_component       → component_only (position unknown on the component)
2. manual_surface_pick    → approximate (engineer picked a point on the 3D surface)
3. camera_ray_mesh        → low (uncalibrated) / medium (calibrated intrinsics): ray from the camera
                            pose through the pixel, intersected with the component's real surface
                            (uploaded GLB triangles, or exact procedural boxes/beams)
   camera_ray_aabb        → low / medium: fallback when no surface mesh is available —
                            intersection with the axis-aligned bounding box
4. photogrammetry / survey → high — interface only, not implemented
5. segmentation overlay   – polyline in model coords, only from validated mapping
"""
from __future__ import annotations

import math

import numpy as np

from app.models import Asset, Component, Device

METHODS = {
    "manual_component": "component_only",
    "manual_surface_pick": "approximate",
    "camera_ray_aabb": "low",
    "camera_ray_mesh": "low",
    "photogrammetry": "high",
    "survey": "high",
}

CONFIDENCE_LEVELS = ["component_only", "low", "approximate", "medium", "high"]


class SpatialMappingError(ValueError):
    pass


def rotation_matrix(yaw_deg: float, pitch_deg: float, roll_deg: float) -> np.ndarray:
    """R = Ry(yaw) · Rx(pitch) · Rz(roll) — matches three.js Euler order 'YXZ'."""
    y, p, r = (math.radians(v) for v in (yaw_deg, pitch_deg, roll_deg))
    ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    rx = np.array([[1, 0, 0], [0, math.cos(p), -math.sin(p)], [0, math.sin(p), math.cos(p)]])
    rz = np.array([[math.cos(r), -math.sin(r), 0], [math.sin(r), math.cos(r), 0], [0, 0, 1]])
    return ry @ rx @ rz


def look_at_angles(pos, target) -> tuple[float, float]:
    d = np.asarray(target, float) - np.asarray(pos, float)
    yaw = math.degrees(math.atan2(-d[0], -d[2]))
    pitch = math.degrees(math.atan2(d[1], math.hypot(d[0], d[2])))
    return yaw, pitch


def camera_intrinsics(cam: Device, image_size: tuple[int, int] | None = None) -> tuple[float, float, float, float, bool]:
    """(fx, fy, cx, cy, calibrated) in pixels of an image of ``image_size`` (w, h).
    Calibrated intrinsics are scaled from the resolution they were measured at."""
    intr = cam.intrinsics or {}
    if {"fx", "fy", "cx", "cy"} <= intr.keys():
        fx, fy, cx, cy = (float(intr[k]) for k in ("fx", "fy", "cx", "cy"))
        if image_size and intr.get("width") and intr.get("height"):
            sx, sy = image_size[0] / float(intr["width"]), image_size[1] / float(intr["height"])
            fx, cx, fy, cy = fx * sx, cx * sx, fy * sy, cy * sy
        return fx, fy, cx, cy, bool(intr.get("calibrated"))
    w, h = image_size if image_size else (cam.resolution_w, cam.resolution_h)
    if not (cam.fov_deg and w and h):
        raise SpatialMappingError("Camera has neither intrinsics nor field-of-view + resolution configured.")
    f = (h / 2) / math.tan(math.radians(cam.fov_deg) / 2)  # vertical FOV
    return f, f, w / 2, h / 2, False


def pixel_ray(cam: Device, u: float, v: float, image_size: tuple[int, int] | None = None) -> tuple[np.ndarray, np.ndarray, bool]:
    fx, fy, cx, cy, calibrated = camera_intrinsics(cam, image_size)
    dist = (cam.intrinsics or {}).get("distortion")
    if calibrated and dist:
        import cv2

        k = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]])
        nx, ny = cv2.undistortPoints(np.array([[[u, v]]], np.float64), k, np.array(dist, np.float64)).reshape(2)
        d_cam = np.array([nx, -ny, -1.0])  # undistorted normalised coordinates (lens distortion removed)
    else:
        d_cam = np.array([(u - cx) / fx, -(v - cy) / fy, -1.0])
    d = rotation_matrix(cam.yaw_deg, cam.pitch_deg, cam.roll_deg) @ d_cam
    return np.array([cam.model_x, cam.model_y, cam.model_z]), d / np.linalg.norm(d), calibrated


def ray_aabb(origin: np.ndarray, direction: np.ndarray, bmin, bmax) -> tuple[np.ndarray, np.ndarray] | None:
    """Slab intersection; returns (point, outward normal) of the first hit or None."""
    tmin, tmax, normal = -math.inf, math.inf, np.zeros(3)
    for i in range(3):
        if abs(direction[i]) < 1e-12:
            if origin[i] < bmin[i] or origin[i] > bmax[i]:
                return None
            continue
        t1 = (bmin[i] - origin[i]) / direction[i]
        t2 = (bmax[i] - origin[i]) / direction[i]
        n = np.zeros(3)
        n[i] = -1.0 if t1 < t2 else 1.0
        if t1 > t2:
            t1, t2 = t2, t1
        if t1 > tmin:
            tmin, normal = t1, n
        tmax = min(tmax, t2)
        if tmin > tmax:
            return None
    if tmax < 0:
        return None
    t = tmin if tmin >= 0 else tmax
    return origin + t * direction, normal


def project_pixel_to_component(cam: Device, comp: Component, u: float, v: float, image_size: tuple[int, int] | None = None,
                               asset: Asset | None = None, storage=None) -> dict:
    """Pixel → point on the component: real surface triangles when available, otherwise its bounding box."""
    from app.services.meshes import component_triangles, ray_triangles

    if cam.device_type != "camera":
        raise SpatialMappingError("Device is not a camera.")
    origin, direction, calibrated = pixel_ray(cam, u, v, image_size)
    tris = component_triangles(comp, asset, storage) if storage is not None or comp.geometry else None
    hit, method = None, None
    if tris is not None and len(tris):
        h = ray_triangles(origin, direction, tris)
        if h is not None:
            hit, method = (h[1], h[2]), "camera_ray_mesh"
    if hit is None and comp.bbox:
        hit = ray_aabb(origin, direction, comp.bbox["min"], comp.bbox["max"])
        method = "camera_ray_aabb" if hit is not None else None
    if hit is None:
        raise SpatialMappingError("The ray through this pixel does not intersect the selected component.")
    point, normal = hit
    surface = "the component's surface mesh" if method == "camera_ray_mesh" else "the component's bounding box (no surface mesh available)"
    return {
        "method": method,
        "location_confidence": "medium" if calibrated else "low",
        "position": [round(float(c), 3) for c in point],
        "normal": [round(float(c), 4) for c in normal],
        "pixel": [round(float(u), 1), round(float(v), 1)],
        "ray_origin": origin.tolist(),
        "ray_direction": direction.tolist(),
        "intrinsics_calibrated": calibrated,
        "notes": (f"Camera ray through pixel ({u:.0f}, {v:.0f}) intersected with {surface}. "
                  + ("Calibrated intrinsics; accuracy also depends on the surveyed camera pose." if calibrated
                     else "Intrinsics derived from the nominal field of view (uncalibrated) — calibrate the camera for better accuracy.")),
    }


def model_to_geo(asset: Asset, x: float, z: float) -> dict | None:
    """Approximate local-tangent-plane conversion. Returns None without a transform."""
    t = asset.geo_transform
    if not t or t.get("origin_lat") is None or t.get("origin_lon") is None:
        return None
    h = math.radians(t.get("heading_deg", 0.0))
    s = t.get("scale", 1.0)
    east = s * (x * math.cos(h) + z * math.sin(h))
    north = s * (x * math.sin(h) - z * math.cos(h))
    lat = t["origin_lat"] + north / 111_320.0
    lon = t["origin_lon"] + east / (111_320.0 * math.cos(math.radians(t["origin_lat"])))
    return {"latitude": lat, "longitude": lon, "calibrated": bool(t.get("calibrated")), "method": t.get("method", "uncalibrated_transform")}
