"""Procedural cable-stayed demonstration bridge.

This is a DEVELOPMENT ASSET, not a surveyed representation of any real bridge.
It is the single source of truth for the demo component registry: each
component gets a stable ID, type, name, model-space transform, bounding box and a
geometry descriptor that the frontend renders. A real GLB/GLTF model can replace
it by mapping its node names to component IDs (``mesh_ref``).

Model space: metres, Y-up, bridge axis along X, water surface at y≈2.
"""
from __future__ import annotations

import math

ASSET_ID = "DEMO-BRIDGE-01"

DECK_TOP = 30.0
DECK_THK = 0.8
DECK_WIDTH = 24.0
HALF_W = DECK_WIDTH / 2
L = 400.0
TOWER_X = 100.0
PIER_X = 150.0
SEG = 25.0
GIRDER_TOP = DECK_TOP - DECK_THK  # 29.2
GIRDER_H = 2.4
BEARING_TOP = GIRDER_TOP - GIRDER_H  # 26.8
BEARING_H = 0.6
CAP_TOP = BEARING_TOP - BEARING_H  # 26.2


def _bbox_box(c, s):
    return {"min": [c[i] - s[i] / 2 for i in range(3)], "max": [c[i] + s[i] / 2 for i in range(3)]}


def _bbox_seg(a, b, pad):
    return {"min": [min(a[i], b[i]) - pad for i in range(3)], "max": [max(a[i], b[i]) + pad for i in range(3)]}


def _r(v):
    return [round(x, 3) for x in v]


class _Builder:
    def __init__(self):
        self.items: list[dict] = []

    def group(self, cid, name, ctype, parent=None):
        self.items.append({"id": cid, "name": name, "component_type": ctype, "parent_id": parent, "geometry": {"type": "group"},
                           "center": None, "bbox": None})

    def box(self, cid, name, ctype, center, size, parent=None, material="concrete"):
        self.items.append({"id": cid, "name": name, "component_type": ctype, "parent_id": parent, "material": material,
                           "geometry": {"type": "box", "size": _r(size)}, "center": _r(center), "bbox": _bbox_box(center, size)})

    def beam(self, cid, name, ctype, a, b, section, parent=None, material="concrete"):
        c = [(a[i] + b[i]) / 2 for i in range(3)]
        self.items.append({"id": cid, "name": name, "component_type": ctype, "parent_id": parent, "material": material,
                           "geometry": {"type": "beam", "start": _r(a), "end": _r(b), "section": _r(section)},
                           "center": _r(c), "bbox": _bbox_seg(a, b, max(section) / 2)})

    def cable(self, cid, name, a, b, radius, parent):
        c = [(a[i] + b[i]) / 2 for i in range(3)]
        self.items.append({"id": cid, "name": name, "component_type": "stay_cable", "parent_id": parent, "material": "steel_strand",
                           "geometry": {"type": "cable", "start": _r(a), "end": _r(b), "radius": radius},
                           "center": _r(c), "bbox": _bbox_seg(a, b, radius)})


def leg_z(y: float) -> float:
    """Tower legs lean inward: z = 17 at y=0 → 8 at y=112."""
    return 17.0 - 9.0 * y / 112.0


def build_components() -> list[dict]:
    b = _Builder()
    # ------------------------------------------------------------- deck
    b.group("DECK", "Bridge deck", "deck_system")
    b.group("DECK-SLAB", "Deck slab segments", "deck_group", "DECK")
    n_seg = int(L / SEG)
    for i in range(n_seg):
        x0 = -L / 2 + i * SEG
        b.box(f"DECK-S{i + 1:02d}", f"Deck segment S{i + 1:02d}", "deck_segment",
              [x0 + SEG / 2, DECK_TOP - DECK_THK / 2, 0], [SEG - 0.08, DECK_THK, DECK_WIDTH], "DECK-SLAB")
    b.group("GIRDERS", "Main edge girders", "girder_group", "DECK")
    spans = [("W", -L / 2, -TOWER_X, "west side span"), ("M", -TOWER_X, TOWER_X, "main span"), ("E", TOWER_X, L / 2, "east side span")]
    for code, x0, x1, label in spans:
        for side, z in (("N", -HALF_W + 1.0), ("S", HALF_W - 1.0)):
            b.box(f"GIR-{code}-{side}", f"Edge girder {side} — {label}", "girder",
                  [(x0 + x1) / 2, GIRDER_TOP - GIRDER_H / 2, z], [x1 - x0 - 0.1, GIRDER_H, 1.2], "GIRDERS")
    b.group("FLOORBEAMS", "Floor beams (cross girders)", "floorbeam_group", "DECK")
    for i in range(n_seg + 1):
        x = -L / 2 + i * SEG
        x = max(min(x, L / 2 - 0.8), -L / 2 + 0.8)
        b.box(f"FB-{i:02d}", f"Floor beam FB-{i:02d}", "floor_beam", [x, GIRDER_TOP - 0.9, 0], [1.2, 1.8, DECK_WIDTH - 3.2], "FLOORBEAMS")
    b.group("JOINTS", "Expansion joints", "joint_group", "DECK")
    for code, x in (("W", -L / 2 + 0.4), ("E", L / 2 - 0.4)):
        b.box(f"JNT-{code}", f"Expansion joint — {'west' if code == 'W' else 'east'} abutment", "expansion_joint",
              [x, DECK_TOP + 0.02, 0], [0.5, 0.1, DECK_WIDTH - 0.6], "JOINTS", material="steel")

    # ------------------------------------------------------------- towers
    for code, x, label in (("W", -TOWER_X, "West"), ("E", TOWER_X, "East")):
        tid = f"TWR-{code}"
        b.group(tid, f"{label} pylon", "pylon", None)
        top = 112.0
        for side, sgn in (("N", -1), ("S", 1)):
            b.beam(f"{tid}-LEG-{side}", f"{label} pylon leg {side}", "pylon_leg",
                   [x, 0.0, sgn * leg_z(0)], [x, top, sgn * leg_z(top)], [4.0, 3.0], tid)
        y_low = CAP_TOP - 1.25
        b.beam(f"{tid}-XB-LOW", f"{label} pylon lower cross beam", "pylon_crossbeam",
               [x, y_low, -leg_z(y_low)], [x, y_low, leg_z(y_low)], [4.0, 2.5], tid)
        y_up = 100.0
        b.beam(f"{tid}-XB-UP", f"{label} pylon upper cross beam", "pylon_crossbeam",
               [x, y_up, -leg_z(y_up)], [x, y_up, leg_z(y_up)], [3.0, 3.0], tid)
        b.box(f"FND-{tid}", f"{label} pylon foundation (pile cap)", "foundation", [x, -1.0, 0], [16.0, 6.0, 42.0], tid)
        for side, z in (("N", -HALF_W + 1.0), ("S", HALF_W - 1.0)):
            b.box(f"BRG-{tid}-{side}", f"Bearing {label} pylon {side}", "bearing",
                  [x, BEARING_TOP - BEARING_H / 2, z], [1.6, BEARING_H, 1.6], tid, material="steel_elastomer")

    # ------------------------------------------------------------- piers
    b.group("PIERS", "Side-span piers", "pier_group")
    for code, x, label in (("W", -PIER_X, "West"), ("E", PIER_X, "East")):
        pid = f"PIER-{code}"
        b.group(pid, f"{label} side-span pier", "pier", "PIERS")
        for side, z in (("N", -8.0), ("S", 8.0)):
            b.beam(f"{pid}-COL-{side}", f"{label} pier column {side}", "pier_column", [x, 0.0, z], [x, CAP_TOP - 1.6, z], [3.0, 3.0], pid)
        b.box(f"{pid}-CAP", f"{label} pier cap", "pier_cap", [x, CAP_TOP - 0.8, 0], [4.0, 1.6, 23.0], pid)
        b.box(f"FND-{pid}", f"{label} pier foundation", "foundation", [x, -1.0, 0], [8.0, 6.0, 26.0], pid)
        for side, z in (("N", -HALF_W + 1.0), ("S", HALF_W - 1.0)):
            b.box(f"BRG-{pid}-{side}", f"Bearing {label} pier {side}", "bearing",
                  [x, BEARING_TOP - BEARING_H / 2, z], [1.4, BEARING_H, 1.4], pid, material="steel_elastomer")

    # ------------------------------------------------------------- abutments
    b.group("ABUTMENTS", "Abutments", "abutment_group")
    for code, x, label in (("W", -L / 2 - 3.0, "West"), ("E", L / 2 + 3.0, "East")):
        aid = f"ABT-{code}"
        b.box(aid, f"{label} abutment", "abutment", [x, CAP_TOP / 2, 0], [6.0, CAP_TOP, 28.0], "ABUTMENTS")
        bx = x + (3.0 - 0.9) * (1 if code == "W" else -1)
        for side, z in (("N", -HALF_W + 1.0), ("S", HALF_W - 1.0)):
            b.box(f"BRG-{aid}-{side}", f"Bearing {label} abutment {side}", "bearing",
                  [bx, BEARING_TOP - BEARING_H / 2, z], [1.2, BEARING_H, 1.2], "ABUTMENTS", material="steel_elastomer")

    # ------------------------------------------------------------- stay cables
    n_c = 8
    for code, tx, label in (("W", -TOWER_X, "West"), ("E", TOWER_X, "East")):
        gid = f"CBL-{code}"
        b.group(gid, f"Stay cables — {label} pylon", "cable_group")
        for side, sgn in (("N", -1), ("S", 1)):
            for direction, dsgn in (("M", 1 if code == "W" else -1), ("S", -1 if code == "W" else 1)):
                for k in range(n_c):
                    y_t = 74.0 + k * 4.5
                    top = [tx, y_t, sgn * (leg_z(y_t) - 0.2)]
                    dx = 22.0 + (n_c - 1 - k) * 10.6
                    deck = [tx + dsgn * dx, DECK_TOP + 0.3, sgn * (HALF_W - 0.6)]
                    span = "main span" if direction == "M" else "side span"
                    b.cable(f"{gid}-{side}-{direction}{k + 1:02d}", f"Stay cable {label} {side} {span} #{k + 1}", deck, top, 0.18, gid)
    return b.items


def component_count() -> int:
    return sum(1 for c in build_components() if c["geometry"]["type"] != "group")


if __name__ == "__main__":  # pragma: no cover
    items = build_components()
    print(len(items), "components;", component_count(), "with geometry")
    print(math.dist(items[0]["center"], [0, 0, 0]))
