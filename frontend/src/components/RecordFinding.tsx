import { Crosshair } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/api/client";
import { useApiMutation, useDevices } from "@/api/hooks";
import type { Defect } from "@/api/types";
import { CATEGORIES, PRIORITIES, PRIORITY_LABEL } from "@/lib/priority";
import { humanize } from "@/lib/format";
import { useUI } from "@/store/ui";
import { Field, Notice } from "./ui";

type LocMode = "component" | "surface_pick" | "camera";

/** Manual finding entry with the localization hierarchy: component-level, picked surface point, or camera-pixel projection. */
export function RecordFindingForm({ assetId, componentId, inspectionId, imageId, onDone, allowPick = true }: {
  assetId: string; componentId: string; inspectionId?: string; imageId?: string; onDone: (d: Defect) => void; allowPick?: boolean;
}) {
  const [category, setCategory] = useState("suspected_crack");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState("auto");
  const [mode, setMode] = useState<LocMode>("component");
  const [cam, setCam] = useState("");
  const [u, setU] = useState("");
  const [v, setV] = useState("");
  const [extent, setExtent] = useState({ width_mm: "", length_mm: "", method: "" });
  const pickMode = useUI((s) => s.pickMode);
  const setPickMode = useUI((s) => s.setPickMode);
  const lastPick = useUI((s) => s.lastPick);
  const setPick = useUI((s) => s.setPick);
  const devices = useDevices(assetId);
  const cameras = (devices.data ?? []).filter((d) => d.device_type === "camera");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => () => { setPickMode(false); setPick(null); }, [setPickMode, setPick]);
  const pick = lastPick;

  const create = useApiMutation(async () => {
    setError(null);
    const body: Record<string, unknown> = {
      asset_id: assetId, component_id: componentId, category, description: description || null, priority,
      inspection_id: inspectionId ?? null, image_id: imageId ?? null, actor: localStorage.getItem("ss.actor") || null,
    };
    if (extent.method && (extent.width_mm || extent.length_mm))
      body.measured_extent = { method: extent.method, ...(extent.width_mm ? { width_mm: +extent.width_mm } : {}), ...(extent.length_mm ? { length_mm: +extent.length_mm } : {}) };
    if (mode === "surface_pick") {
      if (!pick) throw new Error("Pick a point on the 3D model first.");
      Object.assign(body, { location_kind: "surface", component_id: pick.componentId, pos_x: pick.point[0], pos_y: pick.point[1], pos_z: pick.point[2],
        normal_x: pick.normal[0], normal_y: pick.normal[1], normal_z: pick.normal[2], localization_method: "manual_surface_pick" });
    } else if (mode === "camera") {
      const p = await api<{ position: number[]; normal: number[]; location_confidence: string; notes: string }>("/spatial/project",
        { method: "POST", json: { camera_id: cam, component_id: componentId, u: +u, v: +v } });
      Object.assign(body, { location_kind: "surface", pos_x: p.position[0], pos_y: p.position[1], pos_z: p.position[2], normal_x: p.normal[0],
        normal_y: p.normal[1], normal_z: p.normal[2], localization_method: "camera_ray_aabb", localization_notes: p.notes,
        image_region: { point_px: [+u, +v], camera_id: cam } });
    }
    return api<Defect>("/defects", { method: "POST", json: body });
  }, ["defects", "defect", "component", "summary", "alerts", "events"]);

  return (
    <form className="space-y-3" onSubmit={(e) => {
      e.preventDefault();
      create.mutate(undefined, { onSuccess: (d) => onDone(d as Defect), onError: (err) => setError((err as Error).message) });
    }}>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Category">
          <select className="input" value={category} onChange={(e) => setCategory(e.target.value)}>
            {CATEGORIES.map((c) => <option key={c} value={c}>{humanize(c)}</option>)}
          </select>
        </Field>
        <Field label="Review priority">
          <select className="input" value={priority} onChange={(e) => setPriority(e.target.value)}>
            <option value="auto">Rule-based (recommended)</option>
            {PRIORITIES.map((p) => <option key={p} value={p}>Manual: {PRIORITY_LABEL[p]}</option>)}
          </select>
        </Field>
      </div>
      <Field label="Description"><textarea className="input h-16" value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
      <div className="grid grid-cols-3 gap-2">
        <Field label="Width (mm)"><input className="input" inputMode="decimal" value={extent.width_mm} onChange={(e) => setExtent({ ...extent, width_mm: e.target.value })} /></Field>
        <Field label="Length (mm)"><input className="input" inputMode="decimal" value={extent.length_mm} onChange={(e) => setExtent({ ...extent, length_mm: e.target.value })} /></Field>
        <Field label="Measured by"><input className="input" placeholder="e.g. crack gauge" value={extent.method} onChange={(e) => setExtent({ ...extent, method: e.target.value })} /></Field>
      </div>
      <Field label="Location" hint="Choose the most precise method you can justify. Approximate locations are labelled as such.">
        <select className="input" value={mode} onChange={(e) => setMode(e.target.value as LocMode)}>
          <option value="component">Component-level only (position unknown)</option>
          {allowPick && <option value="surface_pick">Pick approximate point on 3D surface</option>}
          <option value="camera">Project image pixel from a registered camera</option>
        </select>
      </Field>
      {mode === "surface_pick" && (
        <div className="space-y-2">
          <button type="button" className={pickMode ? "btn-primary" : "btn-ghost"} onClick={() => setPickMode(!pickMode)}>
            <Crosshair className="h-3.5 w-3.5" />{pickMode ? "Click a point on the model…" : "Pick on model"}
          </button>
          {pick && <div className="mono text-slate-300">Picked {pick.componentId} @ ({pick.point.join(", ")})</div>}
        </div>
      )}
      {mode === "camera" && (
        <div className="grid grid-cols-3 gap-2">
          <Field label="Camera">
            <select className="input" value={cam} onChange={(e) => setCam(e.target.value)} required>
              <option value="">Select…</option>
              {cameras.map((c) => <option key={c.id} value={c.id}>{c.id}</option>)}
            </select>
          </Field>
          <Field label="Pixel u"><input className="input" required value={u} onChange={(e) => setU(e.target.value)} /></Field>
          <Field label="Pixel v"><input className="input" required value={v} onChange={(e) => setV(e.target.value)} /></Field>
          <div className="col-span-3"><Notice tone="warn">Projection intersects the camera ray with the component's bounding box using the configured pose and nominal field of view. The result is approximate.</Notice></div>
        </div>
      )}
      {error && <div role="alert" className="text-xs text-red-300">{error}</div>}
      <button type="submit" className="btn-primary" disabled={create.isPending}>{create.isPending ? "Saving…" : "Record finding"}</button>
    </form>
  );
}
