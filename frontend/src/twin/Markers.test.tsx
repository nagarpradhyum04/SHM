import ReactThreeTestRenderer from "@react-three/test-renderer";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Component, Defect } from "@/api/types";
import { useShowIn3D } from "@/hooks/useShowIn3D";
import { useUI } from "@/store/ui";

// drei's Html/Line/Billboard need a DOM renderer or line materials; stub them for the test renderer.
vi.mock("@react-three/drei", () => ({
  Html: () => null,
  Line: () => null,
  Billboard: ({ children }: { children: React.ReactNode }) => <group>{children}</group>,
}));

const { DefectMarkers } = await import("./Markers");

const comp: Component = {
  id: "C1", asset_id: "A", parent_id: null, name: "Deck", component_type: "deck_segment", mesh_ref: null, geometry: { type: "box", size: [2, 2, 2] },
  model_x: 0, model_y: 0, model_z: 0, bbox: { min: [-1, -1, -1], max: [1, 1, 1] }, latitude: null, longitude: null, geo_method: null, material: null, notes: null,
};
const mk = (id: string, over: Partial<Defect> = {}): Defect => ({
  id, asset_id: "A", component_id: "C1", inspection_id: null, image_id: null, category: "suspected_crack", detection_source: "manual", description: null,
  observed_at: "2020-01-01T00:00:00Z", model_id: null, model_version: null, model_label: null, model_confidence: null, location_kind: "surface",
  pos_x: 1, pos_y: 0, pos_z: 0, normal_x: 1, normal_y: 0, normal_z: 0, localization_method: "manual_surface_pick", location_confidence: "approximate",
  localization_notes: null, image_region: null, overlay: null, measured_extent: null, priority: "high", priority_source: "rules", priority_rationale: [],
  review_status: "new", assigned_reviewer: null, notes: null, follow_up_actions: null, related_defect_id: null, data_source: "demo", created_at: "", updated_at: "", ...over,
});

beforeEach(() => useUI.setState({ selection: null, focusRequest: null, layers: { ...useUI.getState().layers, defects: true, labels: false } }));

describe("3D defect markers", () => {
  it("renders one marker per locatable defect and selects the defect when clicked", async () => {
    const r = await ReactThreeTestRenderer.create(
      <DefectMarkers defects={[mk("D1"), mk("D2", { location_kind: "component", pos_x: null, pos_y: null, pos_z: null }), mk("D3", { component_id: "X", location_kind: "component", pos_x: null })]} components={new Map([["C1", comp]])} />,
    );
    const clickable = r.scene.findAll((n) => typeof n.props.onClick === "function");
    expect(clickable).toHaveLength(2); // D3 has neither a surface position nor a known component → not drawn
    await r.fireEvent(clickable[0], "click", { stopPropagation: () => {} });
    expect(useUI.getState().selection).toEqual({ kind: "defect", id: "D1" });
  });
  it("hides markers when the defect layer is off", async () => {
    useUI.setState({ layers: { ...useUI.getState().layers, defects: false } });
    const r = await ReactThreeTestRenderer.create(<DefectMarkers defects={[mk("D1")]} components={new Map([["C1", comp]])} />);
    expect(r.scene.findAll((n) => typeof n.props.onClick === "function")).toHaveLength(0);
  });
});

describe("navigation to the 3D location", () => {
  function Trigger() {
    const show = useShowIn3D();
    return <button onClick={() => show("defect", "D9")}>go</button>;
  }
  function Where() {
    return <div data-testid="path">{useLocation().pathname}</div>;
  }
  it("navigates to the digital twin and requests a focus on the selected defect", () => {
    render(
      <MemoryRouter initialEntries={["/defects"]}>
        <Routes><Route path="*" element={<><Trigger /><Where /></>} /></Routes>
      </MemoryRouter>,
    );
    act(() => screen.getByText("go").click());
    expect(screen.getByTestId("path").textContent).toBe("/twin");
    const st = useUI.getState();
    expect(st.selection).toEqual({ kind: "defect", id: "D9" });
    expect(st.focusRequest).toMatchObject({ kind: "defect", id: "D9" });
  });
});
