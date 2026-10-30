"""Minimal GLB (binary glTF 2.0) inspection for structural-model uploads.

Only self-contained ``.glb`` files are accepted (a ``.gltf`` with external buffers/textures
would need several files). The parser validates the container, walks the scene graph and
computes a world-space axis-aligned bounding box for every node that has a mesh, using the
POSITION accessor min/max values that glTF requires. Nothing is rendered here.

glTF is Y-up and in metres by specification. Many exporters respect that, but the uploader
should confirm units/orientation; the metadata records what was found, not a guarantee.
Components registered from nodes use ``mesh_ref = "gltf-node:<index>"`` — the frontend maps
three.js objects back to node indices via GLTFLoader's parser associations, so renamed or
duplicate node names cannot break the mapping.
"""
from __future__ import annotations

import json
import re
import struct

import numpy as np

GLB_MAGIC = b"glTF"
JSON_CHUNK = 0x4E4F534A
KEYWORDS = [
    ("pylon", "pylon"), ("tower", "pylon"), ("deck", "deck_segment"), ("slab", "deck_segment"), ("girder", "girder"),
    ("beam", "beam"), ("pier", "pier"), ("column", "pier_column"), ("cable", "stay_cable"), ("stay", "stay_cable"),
    ("bearing", "bearing"), ("abutment", "abutment"), ("foundation", "foundation"), ("pile", "foundation"),
    ("joint", "expansion_joint"), ("arch", "arch"), ("truss", "truss_member"), ("wall", "wall"), ("dam", "dam_body"),
]


class GltfError(ValueError):
    pass


def parse_glb(data: bytes) -> dict:
    if len(data) < 20 or data[:4] != GLB_MAGIC:
        raise GltfError("Not a GLB file (expected binary glTF 2.0, .glb).")
    version, length = struct.unpack_from("<II", data, 4)
    if version != 2:
        raise GltfError(f"Unsupported glTF version {version}; only 2.0 is supported.")
    if length != len(data):
        raise GltfError("GLB length header does not match the file size (truncated upload?).")
    chunk_len, chunk_type = struct.unpack_from("<II", data, 12)
    if chunk_type != JSON_CHUNK:
        raise GltfError("GLB is missing its JSON chunk.")
    try:
        doc = json.loads(data[20:20 + chunk_len].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GltfError("GLB JSON chunk is not valid JSON.") from exc
    for b in doc.get("buffers", []):
        if "uri" in b:
            raise GltfError("Model references external buffer files; export a self-contained .glb.")
    return doc


def _local_matrix(node: dict) -> np.ndarray:
    if "matrix" in node:
        return np.array(node["matrix"], dtype=float).reshape(4, 4).T  # glTF is column-major
    t = np.array(node.get("translation", [0, 0, 0]), float)
    x, y, z, w = node.get("rotation", [0, 0, 0, 1])
    r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    s = np.diag(node.get("scale", [1, 1, 1]))
    m = np.eye(4)
    m[:3, :3] = r @ s
    m[:3, 3] = t
    return m


def _mesh_local_bounds(doc: dict, mesh_index: int) -> tuple[np.ndarray, np.ndarray] | None:
    lo, hi = None, None
    for prim in doc["meshes"][mesh_index].get("primitives", []):
        acc_i = prim.get("attributes", {}).get("POSITION")
        if acc_i is None:
            continue
        acc = doc["accessors"][acc_i]
        if "min" not in acc or "max" not in acc:
            continue
        a, b = np.array(acc["min"][:3], float), np.array(acc["max"][:3], float)
        lo = a if lo is None else np.minimum(lo, a)
        hi = b if hi is None else np.maximum(hi, b)
    return None if lo is None else (lo, hi)


def sanitize_id(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_\-:.]+", "-", name).strip("-")
    return s[:60] or "node"


def guess_type(name: str) -> str:
    low = name.lower()
    return next((t for k, t in KEYWORDS if k in low), "structural_member")


def analyse(doc: dict) -> dict:
    """Return node list (index, name, parent, world bbox for mesh nodes) and scene bounds."""
    nodes = doc.get("nodes", [])
    scene_i = doc.get("scene", 0)
    scenes = doc.get("scenes") or [{"nodes": list(range(len(nodes)))}]
    roots = scenes[scene_i].get("nodes", []) if scene_i < len(scenes) else []
    out: list[dict] = []
    seen: set[int] = set()

    def walk(i: int, parent_m: np.ndarray, parent: int | None, depth: int):
        if i in seen or depth > 64:
            return
        seen.add(i)
        n = nodes[i]
        m = parent_m @ _local_matrix(n)
        bbox = None
        if "mesh" in n:
            lb = _mesh_local_bounds(doc, n["mesh"])
            if lb is not None:
                lo, hi = lb
                corners = np.array([[x, y, z, 1] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
                w = (m @ corners.T).T[:, :3]
                bbox = {"min": [round(float(v), 4) for v in w.min(0)], "max": [round(float(v), 4) for v in w.max(0)]}
        out.append({"index": i, "name": n.get("name") or f"node_{i}", "parent": parent, "has_mesh": "mesh" in n, "bbox": bbox})
        for c in n.get("children", []):
            walk(c, m, i, depth + 1)

    for r in roots:
        walk(r, np.eye(4), None, 0)
    boxes = [n["bbox"] for n in out if n["bbox"]]
    bounds = None
    if boxes:
        bounds = {"min": [min(b["min"][k] for b in boxes) for k in range(3)], "max": [max(b["max"][k] for b in boxes) for k in range(3)]}
    return {"nodes": out, "bounds": bounds, "mesh_nodes": sum(1 for n in out if n["has_mesh"]),
            "generator": (doc.get("asset") or {}).get("generator"), "extensions_required": doc.get("extensionsRequired", [])}
