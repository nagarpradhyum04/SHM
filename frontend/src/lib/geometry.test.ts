import { describe, expect, it } from "vitest";
import type { Component, Defect, Device } from "@/api/types";
import { DEFAULT_FILTERS } from "@/store/ui";
import { applyDefectFilters, componentHeat, defectAnchor, focusDirection, focusForDefect, frustumCorners, quatFromY } from "./geometry";

const comp = (over: Partial<Component> = {}): Component => ({
  id: "C1", asset_id: "A", parent_id: null, name: "Deck", component_type: "deck_segment", mesh_ref: "proc:C1",
  geometry: { type: "box", size: [10, 2, 4] }, model_x: 0, model_y: 10, model_z: 0,
  bbox: { min: [-5, 9, -2], max: [5, 11, 2] }, latitude: null, longitude: null, geo_method: null, material: "concrete", notes: null, ...over,
});

const defect = (over: Partial<Defect> = {}): Defect => ({
  id: "D1", asset_id: "A", component_id: "C1", inspection_id: null, image_id: null, category: "suspected_crack", detection_source: "manual",
  description: null, observed_at: new Date().toISOString(), model_id: null, model_version: null, model_label: null, model_confidence: null,
  location_kind: "component", pos_x: null, pos_y: null, pos_z: null, normal_x: null, normal_y: null, normal_z: null,
  localization_method: "manual_component", location_confidence: "component_only", localization_notes: null, image_region: null, overlay: null,
  measured_extent: null, priority: "medium", priority_source: "rules", priority_rationale: [], review_status: "new", assigned_reviewer: null,
  notes: null, follow_up_actions: null, related_defect_id: null, data_source: "uploaded", created_at: "", updated_at: "", ...over,
});

describe("defectAnchor", () => {
  it("places surface findings at their recorded model coordinates and flags non-surveyed ones as approximate", () => {
    const a = defectAnchor(defect({ location_kind: "surface", pos_x: 1, pos_y: 2, pos_z: 3, location_confidence: "approximate" }), comp());
    expect(a).toEqual({ position: [1, 2, 3], kind: "surface", approximate: true });
    const s = defectAnchor(defect({ location_kind: "surface", pos_x: 1, pos_y: 2, pos_z: 3, location_confidence: "high" }), comp());
    expect(s?.approximate).toBe(false);
  });
  it("places component-level findings above the component and never claims an exact position", () => {
    const a = defectAnchor(defect(), comp());
    expect(a?.kind).toBe("component");
    expect(a?.approximate).toBe(true);
    expect(a?.position).toEqual([0, 12.5, 0]);
  });
  it("returns null when neither a surface position nor the component is known", () => {
    expect(defectAnchor(defect(), null)).toBeNull();
  });
});

describe("focus helpers", () => {
  it("focuses surface defects along their surface normal", () => {
    const f = focusForDefect(defect({ location_kind: "surface", pos_x: 0, pos_y: 0, pos_z: 0, normal_x: 1, normal_y: 0, normal_z: 0 }), comp());
    expect(f?.normal).toEqual([1, 0, 0]);
    const dir = focusDirection([0, 0, 1], f!.normal);
    expect(dir[0]).toBeGreaterThan(0.8);
    expect(Math.hypot(...dir)).toBeCloseTo(1);
  });
  it("keeps the camera above the target when no normal is known", () => {
    const d = focusDirection([1, -1, 0]);
    expect(d[1]).toBeGreaterThan(0);
  });
});

describe("quatFromY", () => {
  it("rotates +Y onto the beam direction", () => {
    const [x, y, z, w] = quatFromY([0, 0, 0], [1, 0, 0]);
    // rotate (0,1,0) by q
    const v = [0, 1, 0];
    const t = [2 * (y * v[2] - z * v[1]), 2 * (z * v[0] - x * v[2]), 2 * (x * v[1] - y * v[0])];
    const r = [v[0] + w * t[0] + (y * t[2] - z * t[1]), v[1] + w * t[1] + (z * t[0] - x * t[2]), v[2] + w * t[2] + (x * t[1] - y * t[0])];
    expect(r[0]).toBeCloseTo(1);
    expect(r[1]).toBeCloseTo(0);
    expect(r[2]).toBeCloseTo(0);
  });
});

describe("filters and heat", () => {
  const ds = [
    defect({ id: "a", priority: "high" }),
    defect({ id: "b", priority: "low", review_status: "repaired" }),
    defect({ id: "c", priority: "critical", category: "suspected_corrosion", data_source: "demo" }),
  ];
  it("filters by review priority, category, source and hides closed findings unless history is on", () => {
    expect(applyDefectFilters(ds, DEFAULT_FILTERS, false).map((d) => d.id)).toEqual(["a", "c"]);
    expect(applyDefectFilters(ds, DEFAULT_FILTERS, true).map((d) => d.id)).toEqual(["a", "b", "c"]);
    expect(applyDefectFilters(ds, { ...DEFAULT_FILTERS, priorities: ["high", "critical"] }, true).map((d) => d.id)).toEqual(["a", "c"]);
    expect(applyDefectFilters(ds, { ...DEFAULT_FILTERS, categories: ["suspected_corrosion"] }, true).map((d) => d.id)).toEqual(["c"]);
    expect(applyDefectFilters(ds, { ...DEFAULT_FILTERS, sources: ["uploaded"] }, true).map((d) => d.id)).toEqual(["a", "b"]);
  });
  it("aggregates heat per component with the highest priority", () => {
    const h = componentHeat(ds);
    expect(h.get("C1")?.top).toBe("critical");
    expect(h.get("C1")?.score).toBe(4 + 2 + 5);
  });
});

describe("frustumCorners", () => {
  it("points a zero-yaw camera along -Z", () => {
    const cam = { model_x: 0, model_y: 0, model_z: 0, yaw_deg: 0, pitch_deg: 0, roll_deg: 0, fov_deg: 40, resolution_w: 1600, resolution_h: 900 } as Device;
    const k = frustumCorners(cam, 10);
    k.forEach((p) => expect(p[2]).toBeCloseTo(-10));
  });
  it("matches the backend yaw convention (yaw 90° looks along -X)", () => {
    const cam = { model_x: 0, model_y: 0, model_z: 0, yaw_deg: 90, pitch_deg: 0, roll_deg: 0, fov_deg: 40 } as Device;
    const k = frustumCorners(cam, 10);
    k.forEach((p) => expect(p[0]).toBeCloseTo(-10));
  });
});
