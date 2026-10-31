"""World-space triangle meshes of components, for ray casting camera pixels onto real surfaces.

* Uploaded GLB models: the actual triangles of the component's glTF node (and its children),
  transformed to world coordinates.
* Procedural demo bridge: exact boxes / oriented beams; cables are approximated by a square
  section of the same radius.

Ray–triangle intersection uses the Möller–Trumbore algorithm (vectorised with numpy).
"""
from __future__ import annotations

import json
import struct
from collections import OrderedDict

import numpy as np

from app.services.gltf import _local_matrix

_COMPONENT_DTYPES = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_TYPE_SIZES = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
_CACHE: OrderedDict = OrderedDict()
_CACHE_MAX = 256


def _box_tris(half: np.ndarray, rot: np.ndarray, center: np.ndarray) -> np.ndarray:
    sx, sy, sz = half
    c = np.array([[x, y, z] for x in (-sx, sx) for y in (-sy, sy) for z in (-sz, sz)], float)
    c = c @ rot.T + center
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    tris = []
    for a, b, d, e in faces:
        tris += [(c[a], c[b], c[d]), (c[a], c[d], c[e])]
    return np.array(tris)


def _rot_y_to(direction: np.ndarray) -> np.ndarray:
    """Rotation matrix taking +Y onto ``direction`` (same convention as the frontend beams)."""
    v = direction / np.linalg.norm(direction)
    y = np.array([0.0, 1.0, 0.0])
    c = float(y @ v)
    if c > 0.999999:
        return np.eye(3)
    if c < -0.999999:
        return np.diag([1.0, -1.0, -1.0])
    axis = np.cross(y, v)
    s = np.linalg.norm(axis)
    k = axis / s
    kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + s * kx + (1 - c) * (kx @ kx)


def procedural_triangles(geometry: dict, center: list[float]) -> np.ndarray | None:
    g = geometry or {}
    if g.get("type") == "box":
        return _box_tris(np.array(g["size"], float) / 2, np.eye(3), np.array(center, float))
    if g.get("type") in ("beam", "cable"):
        a, b = np.array(g["start"], float), np.array(g["end"], float)
        length = np.linalg.norm(b - a)
        if g["type"] == "beam":
            half = np.array([g["section"][0] / 2, length / 2, g["section"][1] / 2])
        else:
            half = np.array([g["radius"], length / 2, g["radius"]])
        return _box_tris(half, _rot_y_to(b - a), (a + b) / 2)
    return None


# ----------------------------------------------------------------------------- GLB


def _split_glb(data: bytes) -> tuple[dict, bytes]:
    json_len = struct.unpack_from("<I", data, 12)[0]
    doc = json.loads(data[20:20 + json_len])
    off = 20 + json_len
    binary = b""
    if off + 8 <= len(data):
        blen, btype = struct.unpack_from("<II", data, off)
        if btype == 0x004E4942:
            binary = data[off + 8: off + 8 + blen]
    return doc, binary


def _accessor(doc: dict, binary: bytes, index: int) -> np.ndarray:
    acc = doc["accessors"][index]
    view = doc["bufferViews"][acc["bufferView"]]
    dtype = np.dtype(_COMPONENT_DTYPES[acc["componentType"]])
    ncomp = _TYPE_SIZES[acc["type"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = view.get("byteStride") or dtype.itemsize * ncomp
    count = acc["count"]
    if stride == dtype.itemsize * ncomp:
        arr = np.frombuffer(binary, dtype=dtype, count=count * ncomp, offset=start).reshape(count, ncomp)
    else:
        raw = np.frombuffer(binary, dtype=np.uint8, count=stride * (count - 1) + dtype.itemsize * ncomp, offset=start)
        arr = np.stack([np.frombuffer(raw[i * stride: i * stride + dtype.itemsize * ncomp].tobytes(), dtype=dtype) for i in range(count)])
    return arr


def _world_matrices(doc: dict) -> dict[int, np.ndarray]:
    nodes = doc.get("nodes", [])
    scenes = doc.get("scenes") or [{"nodes": list(range(len(nodes)))}]
    out: dict[int, np.ndarray] = {}

    def walk(i: int, parent: np.ndarray, depth: int):
        if i in out or depth > 64:
            return
        out[i] = parent @ _local_matrix(nodes[i])
        for ch in nodes[i].get("children", []):
            walk(ch, out[i], depth + 1)

    for r in scenes[doc.get("scene", 0)].get("nodes", []):
        walk(r, np.eye(4), 0)
    return out


def gltf_node_triangles(data: bytes, node_index: int, include_children: bool = True) -> np.ndarray | None:
    doc, binary = _split_glb(data)
    nodes = doc.get("nodes", [])
    world = _world_matrices(doc)
    todo, tris = [node_index], []
    while todo:
        i = todo.pop()
        n = nodes[i]
        if include_children:
            todo += n.get("children", [])
        if "mesh" not in n or i not in world:
            continue
        m = world[i]
        for prim in doc["meshes"][n["mesh"]].get("primitives", []):
            if prim.get("mode", 4) != 4 or "POSITION" not in prim.get("attributes", {}):
                continue
            pos = _accessor(doc, binary, prim["attributes"]["POSITION"]).astype(float)
            pos = (np.c_[pos, np.ones(len(pos))] @ m.T)[:, :3]
            idx = _accessor(doc, binary, prim["indices"]).reshape(-1).astype(np.int64) if "indices" in prim else np.arange(len(pos))
            idx = idx[: len(idx) - len(idx) % 3].reshape(-1, 3)
            tris.append(pos[idx])
    return np.concatenate(tris) if tris else None


def component_triangles(comp, asset, storage) -> np.ndarray | None:
    """Triangles for a component, or None if no surface geometry is known."""
    ref = comp.mesh_ref or ""
    if ref.startswith("gltf-node:") and asset is not None and asset.model_file_key:
        key = (asset.model_file_key, ref)
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
        if not storage.exists(asset.model_file_key):
            return None
        tris = gltf_node_triangles(storage.read(asset.model_file_key), int(ref.split(":")[1]))
        _CACHE[key] = tris
        if len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
        return tris
    if comp.geometry and comp.geometry.get("type") in ("box", "beam", "cable"):
        return procedural_triangles(comp.geometry, [comp.model_x, comp.model_y, comp.model_z])
    return None


def ray_triangles(origin: np.ndarray, direction: np.ndarray, tris: np.ndarray, eps: float = 1e-9):
    """Nearest hit (t, point, unit normal facing the ray) of a ray with triangles, or None."""
    v0, v1, v2 = tris[:, 0], tris[:, 1], tris[:, 2]
    e1, e2 = v1 - v0, v2 - v0
    p = np.cross(direction, e2)
    det = np.einsum("ij,ij->i", e1, p)
    ok = np.abs(det) > eps
    inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
    s = origin - v0
    u = np.einsum("ij,ij->i", s, p) * inv
    q = np.cross(s, e1)
    v = (q @ direction) * inv
    t = np.einsum("ij,ij->i", e2, q) * inv
    hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > eps)
    if not hit.any():
        return None
    i = int(np.argmin(np.where(hit, t, np.inf)))
    n = np.cross(e1[i], e2[i])
    n = n / (np.linalg.norm(n) or 1.0)
    if n @ direction > 0:
        n = -n
    return float(t[i]), origin + t[i] * direction, n
