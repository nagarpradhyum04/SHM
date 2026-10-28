import { KeyRound, Plus } from "lucide-react";
import { useState } from "react";
import { api } from "@/api/client";
import { useApiMutation, useComponents, useDevices } from "@/api/hooks";
import type { Device } from "@/api/types";
import { Card, ConnBadge, Empty, ErrorState, Field, Loading, Modal, Notice, PageHeader, SourceBadge } from "@/components/ui";
import { useShowIn3D } from "@/hooks/useShowIn3D";
import { fmtAgo, humanize } from "@/lib/format";
import { useUI } from "@/store/ui";

type Form = Record<string, string>;

function DeviceForm({ assetId, initial, onDone }: { assetId: string; initial?: Device; onDone: (token?: string | null) => void }) {
  const comps = useComponents(assetId);
  const [f, setF] = useState<Form>(() => ({
    id: initial?.id ?? "", device_type: initial?.device_type ?? "accelerometer", name: initial?.name ?? "", hardware_model: initial?.hardware_model ?? "",
    component_id: initial?.component_id ?? "", data_source: initial?.data_source ?? "real",
    model_x: String(initial?.model_x ?? 0), model_y: String(initial?.model_y ?? 0), model_z: String(initial?.model_z ?? 0),
    yaw_deg: String(initial?.yaw_deg ?? 0), pitch_deg: String(initial?.pitch_deg ?? 0), roll_deg: String(initial?.roll_deg ?? 0),
    latitude: initial?.latitude?.toString() ?? "", longitude: initial?.longitude?.toString() ?? "",
    sample_rate_hz: initial?.sample_rate_hz?.toString() ?? "100", firmware_version: initial?.firmware_version ?? "",
    fov_deg: initial?.fov_deg?.toString() ?? "", resolution_w: initial?.resolution_w?.toString() ?? "", resolution_h: initial?.resolution_h?.toString() ?? "",
    operational_status: initial?.operational_status ?? "active", stream_url: initial?.stream_url ?? "", notes: initial?.notes ?? "",
  }));
  const [err, setErr] = useState<string | null>(null);
  const n = (v: string) => (v.trim() === "" ? null : Number(v));
  const camera = f.device_type === "camera";
  const save = useApiMutation(async () => {
    const body: Record<string, unknown> = {
      name: f.name, hardware_model: f.hardware_model || null, component_id: f.component_id || null,
      model_x: +f.model_x, model_y: +f.model_y, model_z: +f.model_z, yaw_deg: +f.yaw_deg, pitch_deg: +f.pitch_deg, roll_deg: +f.roll_deg,
      latitude: n(f.latitude), longitude: n(f.longitude), firmware_version: f.firmware_version || null, notes: f.notes || null,
      ...(camera ? { fov_deg: n(f.fov_deg), resolution_w: n(f.resolution_w), resolution_h: n(f.resolution_h), stream_url: f.stream_url || null } : { sample_rate_hz: n(f.sample_rate_hz) }),
    };
    if (initial) return api(`/devices/${initial.id}`, { method: "PATCH", json: { ...body, operational_status: f.operational_status } });
    return api<{ ingestion_token: string | null }>("/devices", { method: "POST", json: { ...body, id: f.id, device_type: f.device_type, asset_id: assetId, data_source: f.data_source } });
  }, ["devices", "summary", "component"]);
  const set = (k: string) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(undefined, { onSuccess: (r: any) => onDone(r?.ingestion_token), onError: (x) => setErr((x as Error).message) }); }}>
      <div className="grid grid-cols-3 gap-2">
        {!initial && <Field label="Device ID"><input className="input" required pattern="[A-Za-z0-9_\-]{2,64}" value={f.id} onChange={set("id")} /></Field>}
        {!initial && <Field label="Type"><select className="input" value={f.device_type} onChange={set("device_type")}><option value="accelerometer">Accelerometer (e.g. MPU6050)</option><option value="camera">Camera</option></select></Field>}
        {!initial && <Field label="Data source" hint="Simulated devices never accept real ingestion"><select className="input" value={f.data_source} onChange={set("data_source")}><option value="real">Real hardware</option><option value="simulated">Simulated</option></select></Field>}
        <Field label="Name"><input className="input" required value={f.name} onChange={set("name")} /></Field>
        <Field label="Hardware model"><input className="input" value={f.hardware_model} onChange={set("hardware_model")} placeholder={camera ? "" : "ESP32 + MPU6050"} /></Field>
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
      <Field label="Notes"><textarea className="input h-12" value={f.notes} onChange={set("notes")} /></Field>
      {err && <div role="alert" className="text-xs text-red-300">{err}</div>}
      <button className="btn-primary" disabled={save.isPending}>{initial ? "Save device" : "Register device"}</button>
    </form>
  );
}

export default function Devices() {
  const assetId = useUI((s) => s.assetId) ?? undefined;
  const q = useDevices(assetId);
  const show3d = useShowIn3D();
  const [modal, setModal] = useState<{ kind: "new" } | { kind: "edit"; d: Device } | null>(null);
  const [token, setToken] = useState<{ id?: string; token: string } | null>(null);
  const rotate = useApiMutation((id: string) => api<{ device_id: string; ingestion_token: string }>(`/devices/${id}/rotate-token`, { method: "POST" }), ["devices"]);
  return (
    <div className="pb-6">
      <PageHeader title="Device Registry" subtitle="Cameras and sensors, their installation pose in the 3D model, data source and connection status."
        actions={<button className="btn-primary" onClick={() => setModal({ kind: "new" })}><Plus className="h-3.5 w-3.5" />Register device</button>} />
      <div className="space-y-3 px-5">
        <Notice>Status is derived from the last time real data was received. <b>Simulated</b> devices have no physical hardware and are never reported as connected. <b>Never connected</b>, <b>stale</b> and <b>offline</b> devices provide no evidence about structural condition.</Notice>
        <Card title={`Devices (${q.data?.length ?? 0})`} bodyClass="overflow-auto">
          {q.isLoading ? <Loading /> : q.isError ? <ErrorState error={q.error} /> : !q.data?.length ? <Empty title="No devices registered" /> : (
            <table className="table-base">
              <thead><tr><th>ID</th><th>Name</th><th>Type</th><th>Component</th><th>Model position</th><th>Data source</th><th>Status</th><th>Last seen</th><th>Firmware</th><th /></tr></thead>
              <tbody>
                {q.data.map((d) => (
                  <tr key={d.id}>
                    <td className="mono text-accent-soft">{d.id}</td><td>{d.name}<div className="text-[10px] text-slate-500">{d.hardware_model}</div></td><td>{humanize(d.device_type)}</td>
                    <td className="mono">{d.component_id ?? "—"}</td><td className="mono">{d.model_x.toFixed(1)}, {d.model_y.toFixed(1)}, {d.model_z.toFixed(1)}</td>
                    <td><SourceBadge source={d.data_source} /></td><td><ConnBadge status={d.connection?.status} label={d.connection?.label} /></td>
                    <td>{fmtAgo(d.last_seen_at)}</td><td className="mono">{d.firmware_version ?? "—"}</td>
                    <td className="whitespace-nowrap">
                      <button className="btn-ghost mr-1 py-0.5" onClick={() => show3d("device", d.id)}>3D</button>
                      <button className="btn-ghost mr-1 py-0.5" onClick={() => setModal({ kind: "edit", d })}>Edit</button>
                      {d.data_source === "real" && <button className="btn-ghost py-0.5" title="Issue a new ingestion token (old one stops working)"
                        onClick={() => rotate.mutate(d.id, { onSuccess: (r) => setToken({ id: r.device_id, token: r.ingestion_token }) })}><KeyRound className="h-3 w-3" /></button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
      {modal && assetId && (
        <Modal title={modal.kind === "new" ? "Register device" : `Edit ${modal.d.id}`} onClose={() => setModal(null)} wide>
          <DeviceForm assetId={assetId} initial={modal.kind === "edit" ? modal.d : undefined} onDone={(t) => { setModal(null); if (t) setToken({ token: t }); }} />
        </Modal>
      )}
      {token && (
        <Modal title="Device ingestion token" onClose={() => setToken(null)}>
          <Notice tone="warn">This token is shown <b>once</b>. Store it in the device firmware configuration (sent as the <code className="mono">X-Device-Token</code> header). It is stored only as a hash on the server.</Notice>
          <pre className="mono mt-3 select-all break-all rounded bg-black/50 p-3 text-accent-soft">{token.token}</pre>
        </Modal>
      )}
    </div>
  );
}
