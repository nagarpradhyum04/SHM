import { describe, expect, it } from "vitest";
import type { Component } from "@/api/types";
import { sceneBounds } from "@/lib/geometry";
import { nodeIndexFromMeshRef } from "./GltfModel";
import { aimAngles, offsetFromSurface } from "./PlacementEditor";

describe("device placement helpers", () => {
  it("aims along -Z for yaw 0 and matches the backend yaw/pitch convention", () => {
    expect(aimAngles([0, 0, 0], [0, 0, -10])).toEqual({ yaw: 0, pitch: 0 });
    expect(aimAngles([0, 0, 0], [-10, 0, 0]).yaw).toBeCloseTo(90);
    expect(aimAngles([0, 0, 0], [0, 10, -10]).pitch).toBeCloseTo(45);
  });
  it("offsets a picked point along the surface normal", () => {
    expect(offsetFromSurface([1, 2, 3], [0, 1, 0], 0.15)).toEqual([1, 2.15, 3]);
  });
});

describe("uploaded model mapping", () => {
  it("parses gltf node references only", () => {
    expect(nodeIndexFromMeshRef("gltf-node:12")).toBe(12);
    expect(nodeIndexFromMeshRef("proc:DECK-S01")).toBeNull();
    expect(nodeIndexFromMeshRef(null)).toBeNull();
  });
  it("frames the camera on model bounds, else component boxes", () => {
    const b = sceneBounds([], { min: [-10, 0, -2], max: [10, 4, 2] });
    expect(b.target).toEqual([0, 2, 0]);
    expect(b.radius).toBeCloseTo(Math.hypot(20, 4, 4) / 2);
    const comps = [{ bbox: { min: [0, 0, 0], max: [2, 2, 2] }, geometry: { type: "gltf_node" } }] as unknown as Component[];
    expect(sceneBounds(comps).target).toEqual([1, 1, 1]);
  });
});
