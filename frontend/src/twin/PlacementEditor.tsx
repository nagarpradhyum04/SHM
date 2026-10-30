import { Crosshair, Save, Target, Undo2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/api/client";
import { useApiMutation } from "@/api/hooks";
import type { Device, Vec3 } from "@/api/types";
import { Field, Notice } from "@/components/ui";
import { useUI } from "@/store/ui";

/** Yaw/pitch (degrees) that point a device's −Z axis from `from` to `to` (same convention as the backend). */
export function aimAngles(from: Vec3, to: Vec3): { yaw: number; pitch: number } {
  const d = [to[0] - from[0], to[1] - from[1], to[2] - from[2]];
  return {
    yaw: +((Math.atan2(-d[0], -d[2]) * 180) / Math.PI).toFixed(2),
    pitch: +((Math.atan2(d[1], Math.hypot(d[0], d[2])) * 180) / Math.PI).toFixed(2),
  };
}

/** Offset a picked surface point along its normal so the device marker sits on, not inside, the surface. */
export function offsetFromSurface(point: Vec3, normal: Vec3, distance: number): Vec3 {
  return [0, 1, 2].map((i) => +(point[i] + normal[i] * distance).toFixed(3)) as Vec3;
}

type Pose = { model_x: number; model_y: number; model_z: number; yaw_deg: number; pitch_deg: number; roll_deg: number };
const KEYS: (keyof Pose)[] = ["model_x", "model_y", "model_z", "yaw_deg", "pitch_deg", "roll_deg"];
const LABEL: Record<keyof Pose, string> = { model_x: "X (m)", model_y: "Y (m)", model_z: "Z (m)", yaw_deg: "Yaw °", pitch_deg: "Pitch °", roll_deg: "Roll °" };

export function PlacementEditor({ d }: { d: Device }) {
  const orig: Pose = { model_x: d.model_x, model_y: d.model_y, model_z: d.model_z, yaw_deg: d.yaw_deg, pitch_deg: d.pitch_deg, roll_deg: d.roll_deg };
  const [pose, setPose] = useState<Pose>(orig);
  const [component, setComponent] = useState<string | null>(d.component_id);
  const [msg, setMsg] = useState<string | null>(null);
  const { pickMode, pickPurpose, setPickMode, lastPick, setPick, setPlacementPreview } = useUI();
  const dirty = KEYS.some((k) => pose[k] !== orig[k]) || component !== d.component_id;

  // Reset when another device is selected; clear preview on unmount.
  useEffect(() => {
    setPose(orig);
    setComponent(d.component_id);
    setMsg(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [d.id]);
  useEffect(() => () => setPlacementPreview(null), [setPlacementPreview]);
  useEffect(() => {
    setPlacementPreview(dirty ? { deviceId: d.id, ...pose } : null);
  }, [pose, dirty, d.id, setPlacementPreview]);

  // Consume picks made for this editor.
  useEffect(() => {
    if (!lastPick) return;
    if (lastPick.purpose === "device_position") {
      const p = offsetFromSurface(lastPick.point, lastPick.normal, d.device_type === "camera" ? 1.0 : 0.15);
      setPose((s) => ({ ...s, model_x: p[0], model_y: p[1], model_z: p[2] }));
      setComponent(lastPick.componentId);
      setMsg(`Placed on ${lastPick.componentId}. Review and save.`);
    } else if (lastPick.purpose === "device_aim") {
      const a = aimAngles([pose.model_x, pose.model_y, pose.model_z], lastPick.point);
      setPose((s) => ({ ...s, yaw_deg: a.yaw, pitch_deg: a.pitch, roll_deg: 0 }));
      setMsg("Camera aimed at the picked point. Review and save.");
    } else return;
    setPick(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastPick]);

  const save = useApiMutation(() => api(`/devices/${d.id}`, { method: "PATCH", json: { ...pose, component_id: component } }), ["devices", "component", "summary"]);

  return (
    <div className="space-y-2 rounded-md border border-accent/20 p-2">
      <div className="label">Placement (local model coordinates)</div>
      <div className="grid grid-cols-3 gap-1.5">
        {KEYS.map((k) => (
          <Field key={k} label={LABEL[k]}>
            <input className="input py-1" inputMode="decimal" value={pose[k]} aria-label={LABEL[k]}
              onChange={(e) => { const v = parseFloat(e.target.value); if (!Number.isNaN(v)) setPose({ ...pose, [k]: v }); }} />
          </Field>
        ))}
      </div>
      <div className="text-[10px] text-slate-500">Attached to: <span className="mono">{component ?? "—"}</span></div>
      <div className="flex flex-wrap gap-1.5">
        <button className={pickMode && pickPurpose === "device_position" ? "btn-primary" : "btn-ghost"} onClick={() => setPickMode(!(pickMode && pickPurpose === "device_position"), "device_position")}>
          <Crosshair className="h-3.5 w-3.5" />Pick position on model
        </button>
        {d.device_type === "camera" && (
          <button className={pickMode && pickPurpose === "device_aim" ? "btn-primary" : "btn-ghost"} onClick={() => setPickMode(!(pickMode && pickPurpose === "device_aim"), "device_aim")}>
            <Target className="h-3.5 w-3.5" />Aim at point
          </button>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <button className="btn-primary" disabled={!dirty || save.isPending}
          onClick={() => save.mutate(undefined, { onSuccess: () => { setMsg("Placement saved."); setPlacementPreview(null); }, onError: (e) => setMsg((e as Error).message) })}>
          <Save className="h-3.5 w-3.5" />Save placement
        </button>
        <button className="btn-ghost" disabled={!dirty} onClick={() => { setPose(orig); setComponent(d.component_id); setMsg(null); }}><Undo2 className="h-3.5 w-3.5" />Revert</button>
      </div>
      {msg && <div className="text-[11px] text-slate-300">{msg}</div>}
      <Notice>The marker previews the new pose before saving. This records where you installed the device in the model; it does not move hardware.</Notice>
    </div>
  );
}
