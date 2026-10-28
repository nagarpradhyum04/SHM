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

export interface SurfacePick { point: Vec3; normal: Vec3; componentId: string }

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
  setPickMode: (v: boolean) => void;
  setPick: (p: SurfacePick | null) => void;
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

export const useUI = create<UIState>((set) => ({
  assetId: prefs.assetId ?? null,
  selection: null,
  hoverId: null,
  layers: { ...DEFAULT_LAYERS, ...prefs.layers },
  filters: { ...DEFAULT_FILTERS, ...prefs.filters },
  reducedMotion: prefs.reducedMotion ?? !!prefersReduced,
  leftOpen: prefs.leftOpen ?? true,
  rightOpen: prefs.rightOpen ?? true,
  timelineOpen: prefs.timelineOpen ?? true,
  cameraCommand: null,
  pickMode: false,
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
  setPickMode: (v) => set({ pickMode: v }),
  setPick: (p) => set({ lastPick: p, pickMode: false }),
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
