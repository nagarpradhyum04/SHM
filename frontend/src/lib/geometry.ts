/**
 * Pure helpers for the digital-twin scene (unit-tested, no React/three runtime state).
 * Model space: metres, Y-up. These are local model coordinates, not geographic ones.
 */
import type { Component, Defect, Device, Priority, Vec3 } from "@/api/types";
import type { DefectFilters } from "@/store/ui";
import { priorityRank } from "./priority";

export const BRIDGE_TARGET: Vec3 = [0, 35, 0];
export const BRIDGE_RADIUS = 215;

export function sub(a: Vec3, b: Vec3): Vec3 {
  return [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
}
export function len(a: Vec3): number {
  return Math.hypot(a[0], a[1], a[2]);
}
export function mid(a: Vec3, b: Vec3): Vec3 {
  return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2];
}

/** Quaternion (x,y,z,w) rotating +Y onto the direction a→b. */
export function quatFromY(a: Vec3, b: Vec3): [number, number, number, number] {
  const d = sub(b, a);
  const l = len(d) || 1;
  const v: Vec3 = [d[0] / l, d[1] / l, d[2] / l];
  const dot = v[1]; // (0,1,0)·v
  if (dot > 0.999999) return [0, 0, 0, 1];
  if (dot < -0.999999) return [1, 0, 0, 0];
  // axis = (0,1,0) × v = (v.z, 0, -v.x)
  const ax: Vec3 = [v[2], 0, -v[0]];
  const s = Math.sqrt((1 + dot) * 2);
  return [ax[0] / s, ax[1] / s, ax[2] / s, s / 2];
}

export function bboxCenter(c: Pick<Component, "bbox" | "model_x" | "model_y" | "model_z">): Vec3 {
  if (!c.bbox) return [c.model_x, c.model_y, c.model_z];
  return mid(c.bbox.min, c.bbox.max);
}
export function bboxRadius(c: Pick<Component, "bbox">): number {
  if (!c.bbox) return 5;
  return Math.max(2, len(sub(c.bbox.max, c.bbox.min)) / 2);
}

/** Where a defect marker is drawn and whether its position is exact-on-surface or only component-level. */
export function defectAnchor(d: Defect, comp?: Component | null): { position: Vec3; kind: "surface" | "component"; approximate: boolean } | null {
  if (d.location_kind === "surface" && d.pos_x !== null && d.pos_y !== null && d.pos_z !== null) {
    const approximate = d.location_confidence !== "high";
    return { position: [d.pos_x, d.pos_y, d.pos_z], kind: "surface", approximate };
  }
  if (!comp) return null;
  // Component-level: place above the component's bounding box (exact position unknown).
  const c = bboxCenter(comp);
  const top = comp.bbox ? comp.bbox.max[1] : c[1];
  return { position: [c[0], top + 1.5, c[2]], kind: "component", approximate: true };
}

export function focusForComponent(c: Component): { target: Vec3; radius: number } {
  return { target: bboxCenter(c), radius: Math.min(Math.max(bboxRadius(c) * 2.4, 12), 260) };
}
export function focusForDefect(d: Defect, comp?: Component | null): { target: Vec3; radius: number; normal?: Vec3 } | null {
  const a = defectAnchor(d, comp);
  if (!a) return null;
  const hasNormal = a.kind === "surface" && d.normal_x !== null && d.normal_y !== null && d.normal_z !== null;
  return {
    target: a.position,
    radius: a.kind === "surface" ? 14 : Math.max(18, comp ? bboxRadius(comp) * 1.6 : 18),
    ...(hasNormal ? { normal: [d.normal_x!, d.normal_y!, d.normal_z!] as Vec3 } : {}),
  };
}

/** Camera offset direction for a focus: along the surface normal when known (so the surface faces the viewer). */
export function focusDirection(current: Vec3, normal?: Vec3): Vec3 {
  let d: Vec3 = normal ? [normal[0] * 0.85 + current[0] * 0.15, normal[1] * 0.85 + current[1] * 0.15 + 0.25, normal[2] * 0.85 + current[2] * 0.15] : [...current];
  let l = len(d);
  if (l < 1e-6) d = [-0.6, 0.4, 0.7];
  l = len(d);
  d = [d[0] / l, d[1] / l, d[2] / l];
  if (!normal && d[1] < 0.15) {
    d = [d[0], 0.15, d[2]];
    l = len(d);
    d = [d[0] / l, d[1] / l, d[2] / l];
  }
  return d;
}
export function focusForDevice(dv: Device): { target: Vec3; radius: number } {
  return { target: [dv.model_x, dv.model_y, dv.model_z], radius: 16 };
}

/** Camera position for a named view around a target. */
export function viewPosition(view: "front" | "side" | "top" | "perspective", target: Vec3, radius: number): Vec3 {
  switch (view) {
    case "front":
      return [target[0], target[1] + radius * 0.05, target[2] + radius * 1.35];
    case "side":
      return [target[0] + radius * 1.45, target[1] + radius * 0.08, target[2] + 0.01];
    case "top":
      return [target[0], target[1] + radius * 1.6, target[2] + 0.01];
    default:
      return [target[0] - radius * 0.85, target[1] + radius * 0.5, target[2] + radius * 1.05];
  }
}

export function applyDefectFilters(defects: Defect[], f: DefectFilters, includeHistory: boolean): Defect[] {
  const since = f.since ? new Date(f.since).getTime() : null;
  return defects.filter((d) => {
    if (!includeHistory && f.statuses.length && !f.statuses.includes(d.review_status)) return false;
    if (f.priorities.length && !f.priorities.includes(d.priority)) return false;
    if (f.categories.length && !f.categories.includes(d.category)) return false;
    if (f.sources.length && !f.sources.includes(d.data_source)) return false;
    if (since !== null && new Date(d.observed_at).getTime() < since) return false;
    return true;
  });
}

/** Heat per component: highest open priority, and a score summing priority weights. */
export function componentHeat(defects: Defect[]): Map<string, { score: number; top: Priority }> {
  const m = new Map<string, { score: number; top: Priority }>();
  for (const d of defects) {
    if (!d.component_id) continue;
    const cur = m.get(d.component_id) ?? { score: 0, top: "unassessed" as Priority };
    cur.score += 1 + priorityRank(d.priority);
    if (priorityRank(d.priority) > priorityRank(cur.top)) cur.top = d.priority;
    m.set(d.component_id, cur);
  }
  return m;
}

/** Index components by id and compute each component's top-level ancestor (for the tree & labels). */
export function buildTree(components: Component[]) {
  const byId = new Map(components.map((c) => [c.id, c]));
  const children = new Map<string | null, Component[]>();
  for (const c of components) {
    const k = c.parent_id && byId.has(c.parent_id) ? c.parent_id : null;
    if (!children.has(k)) children.set(k, []);
    children.get(k)!.push(c);
  }
  return { byId, children };
}

/** Camera frustum corner points for coverage visualisation (yaw/pitch/roll in degrees, Euler YXZ as in the backend). */
export function frustumCorners(dv: Device, depth: number): Vec3[] {
  const fov = ((dv.fov_deg ?? 40) * Math.PI) / 180;
  const aspect = dv.resolution_w && dv.resolution_h ? dv.resolution_w / dv.resolution_h : 16 / 9;
  const h = Math.tan(fov / 2) * depth;
  const w = h * aspect;
  const local: Vec3[] = [[-w, h, -depth], [w, h, -depth], [w, -h, -depth], [-w, -h, -depth]];
  const [y, p, r] = [dv.yaw_deg, dv.pitch_deg, dv.roll_deg].map((v) => (v * Math.PI) / 180);
  const rot = (v: Vec3): Vec3 => {
    // Rz(roll)
    let [x, yy, z] = [v[0] * Math.cos(r) - v[1] * Math.sin(r), v[0] * Math.sin(r) + v[1] * Math.cos(r), v[2]];
    // Rx(pitch)
    [yy, z] = [yy * Math.cos(p) - z * Math.sin(p), yy * Math.sin(p) + z * Math.cos(p)];
    // Ry(yaw)
    [x, z] = [x * Math.cos(y) + z * Math.sin(y), -x * Math.sin(y) + z * Math.cos(y)];
    return [x + dv.model_x, yy + dv.model_y, z + dv.model_z];
  };
  return local.map(rot);
}

/** Camera framing for the current asset: uploaded-model bounds, else the union of component boxes, else the demo bridge. */
export function sceneBounds(components: Pick<Component, "bbox" | "geometry">[], modelBounds?: { min: Vec3; max: Vec3 } | null): { target: Vec3; radius: number } {
  let box = modelBounds ?? null;
  if (!box) {
    const boxes = components.filter((c) => c.bbox && c.geometry?.type !== "group").map((c) => c.bbox!);
    if (boxes.length)
      box = { min: [0, 1, 2].map((k) => Math.min(...boxes.map((b) => b.min[k]))) as Vec3, max: [0, 1, 2].map((k) => Math.max(...boxes.map((b) => b.max[k]))) as Vec3 };
  }
  if (!box) return { target: BRIDGE_TARGET, radius: BRIDGE_RADIUS };
  return { target: mid(box.min, box.max), radius: Math.max(2, len(sub(box.max, box.min)) / 2) };
}
