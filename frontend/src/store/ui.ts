import { create } from "zustand";
import type { Priority, Vec3 } from "@/api/types";

export type SelectionKind = "component" | "device" | "defect";
export interface Selection { kind: SelectionKind; id: string }

export type LayerKey = "model" | "devices" | "defects" | "boundaries" | "heatmap" | "wireframe" | "labels" | "history" | "coverage";

export type CameraCommand =
  | { type: "fit" }
  | { type: "reset" }
  | { type: "view"; view: "front" | "side" | "top" | "perspective" }
  | { type: "focus"; target: Vec3; radius: number; normal?: Vec3 };

export interface DefectFilters { priorities: Priority[]; categories: string[]; statuses: string[]; sources: string[]; since: string | null }

export const OPEN_STATUSES = ["new", "under_review", "confirmed", "monitoring"];

export type PickPurpose = "finding" | "device_position" | "device_aim";
export interface SurfacePick { point: Vec3; normal: Vec3; componentId: string; purpose: PickPurpose }
export interface PlacementPreview { deviceId: string; model_x: number; model_y: number; model_z: number; yaw_deg: number; pitch_deg: number; roll_deg: number }

interface UIState {
  assetId: string | null;
  selection: Selection | null;
  hoverId: string | null;
  layers: Record<LayerKey, boolean>;
  filters: DefectFilters;
  reducedMotion: boolean;
  leftOpen: boolean;
  rightOpen: boolean;
  timelineOpen: boolean;
  cameraCommand: (CameraCommand & { nonce: number }) | null;
  pickMode: boolean;
  pickPurpose: PickPurpose;
  placementPreview: PlacementPreview | null;
  focusRequest: (Selection & { nonce: number }) | null;
  lastPick: SurfacePick | null;
  setAsset: (id: string) => void;
  select: (s: Selection | null) => void;
  setHover: (id: string | null) => void;
  toggleLayer: (k: LayerKey) => void;
  setFilters: (f: Partial<DefectFilters>) => void;
  setReducedMotion: (v: boolean) => void;
  togglePanel: (p: "leftOpen" | "rightOpen" | "timelineOpen") => void;
  camera: (c: CameraCommand) => void;
  setPickMode: (v: boolean, purpose?: PickPurpose) => void;
  setPick: (p: Omit<SurfacePick, "purpose"> | null) => void;
  setPlacementPreview: (p: PlacementPreview | null) => void;
  requestFocus: (s: Selection) => void;
}

const PREFS_KEY = "structurasense.view";

type Persisted = Pick<UIState, "layers" | "filters" | "reducedMotion" | "leftOpen" | "rightOpen" | "timelineOpen" | "assetId">;

function loadPrefs(): Partial<Persisted> {
  try {
    return JSON.parse(sessionStorage.getItem(PREFS_KEY) ?? "{}");
  } catch {
    return {};
  }
}

export const DEFAULT_LAYERS: Record<LayerKey, boolean> = {
  model: true, devices: true, defects: true, boundaries: false, heatmap: false, wireframe: false, labels: true, history: false, coverage: false,
};
export const DEFAULT_FILTERS: DefectFilters = { priorities: [], categories: [], statuses: OPEN_STATUSES, sources: [], since: null };

const prefs = loadPrefs();
const prefersReduced = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
// On narrow screens side panels overlay the 3D view, so start with them closed.
const wide = typeof window === "undefined" || window.innerWidth >= 1024;

export const useUI = create<UIState>((set) => ({
  assetId: prefs.assetId ?? null,
  selection: null,
  hoverId: null,
  layers: { ...DEFAULT_LAYERS, ...prefs.layers },
  filters: { ...DEFAULT_FILTERS, ...prefs.filters },
  reducedMotion: prefs.reducedMotion ?? !!prefersReduced,
  leftOpen: prefs.leftOpen ?? wide,
  rightOpen: prefs.rightOpen ?? wide,
  timelineOpen: prefs.timelineOpen ?? false,
  cameraCommand: null,
  pickMode: false,
  pickPurpose: "finding",
  placementPreview: null,
  focusRequest: null,
  lastPick: null,
  setAsset: (id) => set({ assetId: id, selection: null }),
  select: (s) => set(s ? { selection: s, rightOpen: true } : { selection: null }),
  setHover: (id) => set({ hoverId: id }),
  toggleLayer: (k) => set((st) => ({ layers: { ...st.layers, [k]: !st.layers[k] } })),
  setFilters: (f) => set((st) => ({ filters: { ...st.filters, ...f } })),
  setReducedMotion: (v) => set({ reducedMotion: v }),
  togglePanel: (p) => set((st) => ({ [p]: !st[p] }) as Partial<UIState>),
  camera: (c) => set({ cameraCommand: { ...c, nonce: Date.now() + Math.random() } }),
  setPickMode: (v, purpose) => set((st) => ({ pickMode: v, pickPurpose: purpose ?? st.pickPurpose })),
  setPick: (p) => set((st) => ({ lastPick: p ? { ...p, purpose: st.pickPurpose } : null, pickMode: false })),
  setPlacementPreview: (p) => set({ placementPreview: p }),
  requestFocus: (s) => set({ selection: s, rightOpen: true, focusRequest: { ...s, nonce: Date.now() } }),
}));

// Persist view preferences for the current browser session.
useUI.subscribe((st) => {
  const p: Persisted = { layers: st.layers, filters: st.filters, reducedMotion: st.reducedMotion, leftOpen: st.leftOpen,
    rightOpen: st.rightOpen, timelineOpen: st.timelineOpen, assetId: st.assetId };
  try {
    sessionStorage.setItem(PREFS_KEY, JSON.stringify(p));
  } catch {
    /* storage unavailable: preferences simply aren't persisted */
  }
});
