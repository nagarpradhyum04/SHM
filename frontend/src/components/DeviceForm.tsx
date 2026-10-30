import { useState } from "react";
import { api } from "@/api/client";
import { useApiMutation, useComponents } from "@/api/hooks";
import type { Capability, Device } from "@/api/types";
import { humanize } from "@/lib/format";
import { Field } from "./ui";

type Form = Record<string, string>;

export interface DeviceDefaults { component_id?: string; model_x?: number; model_y?: number; model_z?: number; device_type?: Device["device_type"] }

const CAPS_BY_TYPE: Record<string, Capability[]> = {
  camera: ["image"], accelerometer: ["acceleration"], sensor_node: ["acceleration", "temperature", "humidity"], environment: ["temperature", "humidity"],
};

export function DeviceForm({ assetId, initial, defaults, onDone }: { assetId: string; initial?: Device; defaults?: DeviceDefaults; onDone: (token?: string | null) => void }) {
  const comps = useComponents(assetId);
  const [f, setF] = useState<Form>(() => ({
    id: initial?.id ?? "", device_type: initial?.device_type ?? defaults?.device_type ?? "sensor_node", name: initial?.name ?? "", hardware_model: initial?.hardware_model ?? "",
    component_id: initial?.component_id ?? defaults?.component_id ?? "", data_source: initial?.data_source ?? "real",
    model_x: String(initial?.model_x ?? defaults?.model_x ?? 0), model_y: String(initial?.model_y ?? defaults?.model_y ?? 0), model_z: String(initial?.model_z ?? defaults?.model_z ?? 0),
    yaw_deg: String(initial?.yaw_deg ?? 0), pitch_deg: String(initial?.pitch_deg ?? 0), roll_deg: String(initial?.roll_deg ?? 0),
    latitude: initial?.latitude?.toString() ?? "", longitude: initial?.longitude?.toString() ?? "",
    sample_rate_hz: initial?.sample_rate_hz?.toString() ?? "100", firmware_version: initial?.firmware_version ?? "",
    fov_deg: initial?.fov_deg?.toString() ?? "", resolution_w: initial?.resolution_w?.toString() ?? "", resolution_h: initial?.resolution_h?.toString() ?? "",
    operational_status: initial?.operational_status ?? "active", stream_url: initial?.stream_url ?? "", notes: initial?.notes ?? "",
  }));
  const [err, setErr] = useState<string | null>(null);
  const n = (v: string) => (v.trim() === "" ? null : Number(v));
  const camera = f.device_type === "camera";
  const [caps, setCaps] = useState<Capability[]>(initial?.capabilities ?? CAPS_BY_TYPE[f.device_type]);
  const save = useApiMutation(async () => {
    const body: Record<string, unknown> = {
      name: f.name, hardware_model: f.hardware_model || null, component_id: f.component_id || null,
      model_x: +f.model_x, model_y: +f.model_y, model_z: +f.model_z, yaw_deg: +f.yaw_deg, pitch_deg: +f.pitch_deg, roll_deg: +f.roll_deg,
      latitude: n(f.latitude), longitude: n(f.longitude), firmware_version: f.firmware_version || null, notes: f.notes || null,
      ...(camera ? { fov_deg: n(f.fov_deg), resolution_w: n(f.resolution_w), resolution_h: n(f.resolution_h), stream_url: f.stream_url || null } : { sample_rate_hz: n(f.sample_rate_hz) }),
    };
    body.capabilities = caps;
    if (initial) return api(`/devices/${initial.id}`, { method: "PATCH", json: { ...body, operational_status: f.operational_status } });
    return api<{ ingestion_token: string | null }>("/devices", { method: "POST", json: { ...body, id: f.id, device_type: f.device_type, asset_id: assetId, data_source: f.data_source } });
  }, ["devices", "summary", "component"]);
  const set = (k: string) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(undefined, { onSuccess: (r: any) => onDone(r?.ingestion_token), onError: (x) => setErr((x as Error).message) }); }}>
      <div className="grid grid-cols-3 gap-2">
        {!initial && <Field label="Device ID"><input className="input" required pattern="[A-Za-z0-9_\-]{2,64}" value={f.id} onChange={set("id")} /></Field>}
        {!initial && <Field label="Type"><select className="input" value={f.device_type} onChange={(e) => { setF({ ...f, device_type: e.target.value }); setCaps(CAPS_BY_TYPE[e.target.value]); }}>
          <option value="sensor_node">Sensor node (ESP32 + MPU6050 + temp/humidity)</option><option value="accelerometer">Accelerometer only</option>
          <option value="environment">Temperature/humidity only</option><option value="camera">Camera (webcam agent)</option></select></Field>}
        {!initial && <Field label="Data source" hint="Simulated devices never accept real ingestion"><select className="input" value={f.data_source} onChange={set("data_source")}><option value="real">Real hardware</option><option value="simulated">Simulated</option></select></Field>}
        <Field label="Name"><input className="input" required value={f.name} onChange={set("name")} /></Field>
        <Field label="Hardware model"><input className="input" value={f.hardware_model} onChange={set("hardware_model")} placeholder={camera ? "USB webcam" : "ESP32 + MPU6050 + DHT22"} /></Field>
        <Field label="Component"><select className="input" value={f.component_id} onChange={set("component_id")}><option value="">—</option>{(comps.data ?? []).filter((c) => c.geometry?.type !== "group").map((c) => <option key={c.id} value={c.id}>{c.id}</option>)}</select></Field>
        {(["model_x", "model_y", "model_z"] as const).map((k) => <Field key={k} label={`${k.slice(-1).toUpperCase()} (model m)`}><input className="input" inputMode="decimal" value={f[k]} onChange={set(k)} /></Field>)}
        {(["yaw_deg", "pitch_deg", "roll_deg"] as const).map((k) => <Field key={k} label={`${k.split("_")[0]} (°)`}><input className="input" inputMode="decimal" value={f[k]} onChange={set(k)} /></Field>)}
        <Field label="Latitude (optional)"><input className="input" value={f.latitude} onChange={set("latitude")} /></Field>
        <Field label="Longitude (optional)"><input className="input" value={f.longitude} onChange={set("longitude")} /></Field>
        <Field label="Firmware / config"><input className="input" value={f.firmware_version} onChange={set("firmware_version")} /></Field>
        {camera ? (
          <>
            <Field label="Vertical FOV (°)"><input className="input" value={f.fov_deg} onChange={set("fov_deg")} /></Field>
            <Field label="Resolution W"><input className="input" value={f.resolution_w} onChange={set("resolution_w")} /></Field>
            <Field label="Resolution H"><input className="input" value={f.resolution_h} onChange={set("resolution_h")} /></Field>
            <div className="col-span-3"><Field label="Stream URL (future live cameras)"><input className="input" value={f.stream_url} onChange={set("stream_url")} /></Field></div>
          </>
        ) : <Field label="Sample rate (Hz)"><input className="input" value={f.sample_rate_hz} onChange={set("sample_rate_hz")} /></Field>}
        {initial && <Field label="Operational status"><select className="input" value={f.operational_status} onChange={set("operational_status")}>{["active", "maintenance", "decommissioned"].map((s) => <option key={s} value={s}>{humanize(s)}</option>)}</select></Field>}
      </div>
      {!camera && (
        <div className="flex flex-wrap items-center gap-3 text-xs"><span className="label">Channels</span>
          {(["acceleration", "temperature", "humidity"] as Capability[]).map((c) => (
            <label key={c} className="flex items-center gap-1"><input type="checkbox" checked={caps.includes(c)} onChange={(e) => setCaps(e.target.checked ? [...caps, c] : caps.filter((x) => x !== c))} />{c}</label>
          ))}
        </div>
      )}
      <Field label="Notes"><textarea className="input h-12" value={f.notes} onChange={set("notes")} /></Field>
      {err && <div role="alert" className="text-xs text-red-300">{err}</div>}
      <button className="btn-primary" disabled={save.isPending}>{initial ? "Save device" : "Register device"}</button>
    </form>
  );
}

