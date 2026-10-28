"""Spatial mapping between image observations and the 3D model.

Coordinate systems are kept distinct:
* image   – pixels (u right, v down) of an evidence image
* camera  – camera frame: x right, y up, looking along −z
* model   – local 3D scene coordinates (metres, Y-up); NOT geographic
* geo     – WGS84 lat/lon, only through an asset ``geo_transform``

Localization hierarchy (method → best achievable confidence):
1. manual_component       → component_only (position unknown on the component)
2. manual_surface_pick    → approximate (engineer picked a point on the 3D surface)
3. camera_ray_aabb        → low (uncalibrated intrinsics) / medium (calibrated):
                            ray from camera pose through pixel, intersected with the
                            component's axis-aligned bounding box (coarse proxy for its surface)
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


def camera_intrinsics(cam: Device) -> tuple[float, float, float, float, bool]:
    intr = cam.intrinsics or {}
    if {"fx", "fy", "cx", "cy"} <= intr.keys():
        return intr["fx"], intr["fy"], intr["cx"], intr["cy"], bool(intr.get("calibrated"))
    if not (cam.fov_deg and cam.resolution_w and cam.resolution_h):
        raise SpatialMappingError("Camera has neither intrinsics nor field-of-view + resolution configured.")
    f = (cam.resolution_h / 2) / math.tan(math.radians(cam.fov_deg) / 2)  # vertical FOV
    return f, f, cam.resolution_w / 2, cam.resolution_h / 2, False


def pixel_ray(cam: Device, u: float, v: float) -> tuple[np.ndarray, np.ndarray, bool]:
    fx, fy, cx, cy, calibrated = camera_intrinsics(cam)
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


def project_pixel_to_component(cam: Device, comp: Component, u: float, v: float) -> dict:
    if cam.device_type != "camera":
        raise SpatialMappingError("Device is not a camera.")
    if not comp.bbox:
        raise SpatialMappingError("Component has no bounding box for projection.")
    origin, direction, calibrated = pixel_ray(cam, u, v)
    hit = ray_aabb(origin, direction, comp.bbox["min"], comp.bbox["max"])
    if hit is None:
        raise SpatialMappingError("The ray through this pixel does not intersect the selected component.")
    point, normal = hit
    return {
        "method": "camera_ray_aabb",
        "location_confidence": "medium" if calibrated else "low",
        "position": [round(float(c), 3) for c in point],
        "normal": [float(c) for c in normal],
        "ray_origin": origin.tolist(),
        "ray_direction": direction.tolist(),
        "intrinsics_calibrated": calibrated,
        "notes": (
            "Approximate: ray intersected with the component's bounding box, not its true surface. "
            + ("Intrinsics calibrated." if calibrated else "Intrinsics derived from nominal FOV (uncalibrated).")
        ),
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
