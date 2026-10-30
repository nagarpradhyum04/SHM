import { Box, ClipboardPlus, Cpu, Crosshair, History, ImagePlus, Move3d, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useComponentDetail } from "@/api/hooks";
import type { Component, Device } from "@/api/types";
import { CameraPreview } from "@/components/CameraPreview";
import { DefectEvidence } from "@/components/DefectEvidence";
import { DeviceForm } from "@/components/DeviceForm";
import { EnvironmentChart } from "@/components/EnvironmentChart";
import { RecordFindingForm } from "@/components/RecordFinding";
import { FeaturesChart, ReadingsChart, SourceGate } from "@/components/SensorCharts";
import { UploadInspection } from "@/components/UploadInspection";
import { ConnBadge, Empty, ErrorState, KV, Loading, Modal, Notice, PriorityBadge, SourceBadge } from "@/components/ui";
import { fmtAgo, fmtDateTime, humanize } from "@/lib/format";
import { focusForComponent, focusForDevice } from "@/lib/geometry";
import { useUI } from "@/store/ui";
import { PlacementEditor } from "./PlacementEditor";

function ComponentDetails({ id, assetId }: { id: string; assetId: string }) {
  const q = useComponentDetail(id);
  const select = useUI((s) => s.select);
  const camera = useUI((s) => s.camera);
  const [modal, setModal] = useState<"finding" | "upload" | "device" | null>(null);
  const [newToken, setNewToken] = useState<string | null>(null);
  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const { component: c, children, devices, defects, inspections, geo } = q.data!;
  const open = defects.filter((d) => !["repaired", "closed", "false_positive"].includes(d.review_status));
  return (
    <div className="space-y-3">
      <div>
        <div className="text-sm font-semibold text-white">{c.name}</div>
        <div className="font-mono text-[11px] text-accent-soft">{c.id}</div>
      </div>
      <div>
        <KV k="Type" v={humanize(c.component_type)} />
        <KV k="Material" v={humanize(c.material)} />
        <KV k="Parent" v={c.parent_id ?? "—"} mono />
        <KV k="3D reference" v={c.mesh_ref} mono />
        <KV k="Model coords" v={<span title="Local 3D model coordinates (metres), not GPS">{c.model_x.toFixed(1)}, {c.model_y.toFixed(1)}, {c.model_z.toFixed(1)} <span className="text-slate-500">(local)</span></span>} mono />
        <KV k="Geographic" v={geo ? `${geo.latitude.toFixed(6)}, ${geo.longitude.toFixed(6)} (${geo.method}${geo.calibrated === false ? ", approximate" : ""})` : "Not available — no surveyed position or calibrated transform"} />
      </div>
      <div className="flex flex-wrap gap-1.5">
        {c.bbox && <button className="btn-ghost" onClick={() => { const f = focusForComponent(c); camera({ type: "focus", target: f.target, radius: f.radius }); }}><Crosshair className="h-3.5 w-3.5" />Focus</button>}
        {c.geometry?.type !== "group" && <button className="btn-primary" onClick={() => setModal("finding")}><ClipboardPlus className="h-3.5 w-3.5" />Record finding</button>}
        {c.geometry?.type !== "group" && <button className="btn-ghost" onClick={() => setModal("upload")}><ImagePlus className="h-3.5 w-3.5" />Inspect image</button>}
        <Link className="btn-ghost" to={`/history?component=${c.id}`}><History className="h-3.5 w-3.5" />History</Link>
        {c.geometry?.type !== "group" && <button className="btn-ghost" onClick={() => setModal("device")}><Cpu className="h-3.5 w-3.5" />Add device here</button>}
      </div>
      {children.length > 0 && (
        <details>
          <summary className="label cursor-pointer">Sub-components ({children.length})</summary>
          <ul className="mt-1 max-h-40 overflow-auto">
            {children.map((k) => <li key={k.id}><button className="w-full truncate rounded px-1 py-0.5 text-left text-[11px] text-slate-300 hover:bg-white/5" onClick={() => select({ kind: "component", id: k.id })}>{k.name}</button></li>)}
          </ul>
        </details>
      )}
      <div>
        <div className="label mb-1">Findings ({open.length} open / {defects.length} total)</div>
        {defects.length === 0 && <div className="text-[11px] text-slate-500">No findings recorded. This does not imply the component is in good condition.</div>}
        <ul className="space-y-1">
          {defects.map((d) => (
            <li key={d.id}>
              <button className="flex w-full items-center justify-between gap-2 rounded border border-white/5 px-2 py-1 text-left hover:bg-white/5" onClick={() => select({ kind: "defect", id: d.id })}>
                <span className="min-w-0"><span className="block truncate text-[11px] text-slate-200">{humanize(d.category)}</span><span className="font-mono text-[10px] text-slate-500">{d.id} · {fmtDateTime(d.observed_at)}</span></span>
                <PriorityBadge p={d.priority} />
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <div className="label mb-1">Devices ({devices.length})</div>
        {devices.map((d) => (
          <button key={d.id} className="mb-1 flex w-full items-center justify-between rounded border border-white/5 px-2 py-1 text-left text-[11px] hover:bg-white/5" onClick={() => select({ kind: "device", id: d.id })}>
            <span className="font-mono">{d.id}</span><ConnBadge status={d.connection?.status} label={d.connection?.label} />
          </button>
        ))}
        {!devices.length && <div className="text-[11px] text-slate-500">No devices installed on this component.</div>}
      </div>
      <div className="label">Inspections: {inspections.length}{inspections[0] ? ` · latest ${fmtDateTime(inspections[0].observed_at)}` : ""}</div>
      {modal === "finding" && (
        <Modal title={`Record finding — ${c.name}`} onClose={() => setModal(null)}>
          <RecordFindingForm assetId={assetId} componentId={c.id} onDone={(d) => { setModal(null); select({ kind: "defect", id: d.id }); }} />
        </Modal>
      )}
      {modal === "device" && (
        <Modal title={`Register device on ${c.name}`} onClose={() => setModal(null)} wide>
          <DeviceForm assetId={assetId} defaults={{ component_id: c.id, model_x: +c.model_x.toFixed(2), model_y: +(c.bbox ? c.bbox.max[1] + 0.3 : c.model_y).toFixed(2), model_z: +c.model_z.toFixed(2) }}
            onDone={(token) => { setModal(null); setNewToken(token ?? null); }} />
        </Modal>
      )}
      {newToken && (
        <Modal title="Device ingestion token" onClose={() => setNewToken(null)}>
          <Notice tone="warn">Shown <b>once</b>. Put it in the firmware/agent configuration (<code className="mono">DEVICE_TOKEN</code>). Select the new device marker and use <b>Edit placement</b> to position it precisely.</Notice>
          <pre className="mono mt-3 select-all whitespace-pre-wrap break-all rounded bg-black/50 p-3 text-accent-soft">{newToken}</pre>
        </Modal>
      )}
      {modal === "upload" && (
        <Modal title={`Image inspection — ${c.name}`} onClose={() => setModal(null)}>
          <UploadInspection assetId={assetId} defaultComponent={c.id} />
        </Modal>
      )}
    </div>
  );
}

function DeviceDetails({ d, comp }: { d: Device; comp?: Component }) {
  const camera = useUI((s) => s.camera);
  const [editing, setEditing] = useState(false);
  const select = useUI((s) => s.select);
  const conn = d.connection;
  return (
    <div className="space-y-3">
      <div>
        <div className="text-sm font-semibold text-white">{d.name}</div>
        <div className="font-mono text-[11px] text-accent-soft">{d.id}</div>
      </div>
      <div className="flex flex-wrap gap-1.5"><ConnBadge status={conn?.status} label={conn?.label} /><SourceBadge source={d.data_source} /></div>
      {conn?.is_simulated && <Notice>Simulated device — no physical hardware is connected. Its readings are generated by the simulation provider and always labelled “Simulated”.</Notice>}
      {conn?.status === "never_connected" && <Notice tone="warn">This device has never reported. Absence of data is not evidence of normal condition.</Notice>}
      <div>
        <KV k="Type" v={humanize(d.device_type)} />
        <KV k="Hardware" v={d.hardware_model} />
        <KV k="Component" v={comp ? <button className="text-accent-soft hover:underline" onClick={() => select({ kind: "component", id: comp.id })}>{comp.name}</button> : d.component_id} />
        <KV k="Status" v={conn?.label} />
        <KV k="Last seen" v={d.last_seen_at ? `${fmtDateTime(d.last_seen_at)} (${fmtAgo(d.last_seen_at)})` : "Never"} />
        <KV k="Model coords" v={`${d.model_x.toFixed(1)}, ${d.model_y.toFixed(1)}, ${d.model_z.toFixed(1)} (local)`} mono />
        <KV k="Orientation" v={`yaw ${d.yaw_deg.toFixed(1)}° · pitch ${d.pitch_deg.toFixed(1)}° · roll ${d.roll_deg.toFixed(1)}°`} mono />
        {d.device_type === "camera" ? (
          <>
            <KV k="Field of view" v={d.fov_deg ? `${d.fov_deg}° (vertical) · ${d.resolution_w}×${d.resolution_h}` : "Not configured"} />
            <KV k="Calibration" v={(d.intrinsics as any)?.calibrated ? "Calibrated intrinsics" : "Uncalibrated (nominal FOV)"} />
            <KV k="Stream" v={d.stream_url ?? "Not configured"} />
          </>
        ) : (
          <>
            <KV k="Sample rate" v={d.sample_rate_hz ? `${d.sample_rate_hz} Hz` : "—"} />
            <KV k="Firmware" v={d.firmware_version ?? "—"} />
          </>
        )}
      </div>
      {d.config?.last_status && (
        <div className="rounded border border-white/5 px-2 py-1">
          <div className="label mb-0.5">Last status report ({d.config.transport ?? "http"})</div>
          <div className="mono flex flex-wrap gap-x-3 text-slate-300">
            {Object.entries(d.config.last_status).filter(([k]) => k !== "received_at").map(([k, v]) => <span key={k}>{k}={String(v)}</span>)}
          </div>
          <div className="text-[10px] text-slate-500">received {fmtAgo(d.config.last_status.received_at)}</div>
        </div>
      )}
      <div className="flex flex-wrap gap-1.5">
        <button className="btn-ghost" onClick={() => { const f = focusForDevice(d); camera({ type: "focus", target: f.target, radius: f.radius }); }}><Crosshair className="h-3.5 w-3.5" />Focus</button>
        <button className={editing ? "btn-primary" : "btn-ghost"} onClick={() => setEditing(!editing)}><Move3d className="h-3.5 w-3.5" />Edit placement</button>
      </div>
      {editing && <PlacementEditor d={d} />}
      {d.device_type !== "camera" ? (
        <SourceGate device={d}>{(src) => (
          <div className="space-y-3">
            {(d.capabilities ?? ["acceleration"]).includes("acceleration") && <ReadingsChart device={d} source={src} height={140} />}
            {(d.capabilities ?? ["acceleration"]).includes("acceleration") && <FeaturesChart device={d} source={src} height={150} limit={120} />}
            {(d.capabilities ?? []).some((c) => c === "temperature" || c === "humidity") && <EnvironmentChart device={d} source={src} height={140} />}
            <Link className="btn-ghost" to={`/sensors?device=${d.id}`}>Open in Sensor Analytics</Link>
          </div>
        )}</SourceGate>
      ) : (
        <CameraImages d={d} />
      )}
    </div>
  );
}

function CameraImages({ d }: { d: Device }) {
  return (
    <div className="space-y-2">
      <CameraPreview d={d} />
      <div className="label mb-1">Captured / associated inspections</div>
      <Link className="btn-ghost" to={`/inspections?device=${d.id}`}>View inspections from this camera</Link>
      <p className="text-[11px] text-slate-500">Frames are analysed by the installed model; event clips are stored with the resulting inspection.</p>
    </div>
  );
}

export function DetailsPanel({ assetId, components, devices }: { assetId: string; components: Map<string, Component>; devices: Device[] }) {
  const selection = useUI((s) => s.selection);
  const select = useUI((s) => s.select);
  const togglePanel = useUI((s) => s.togglePanel);
  const title = selection ? { component: "Component", device: "Device", defect: "Finding evidence" }[selection.kind] : "Details";
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-white/5 px-3 py-2">
        <h2 className="panel-title flex items-center gap-1.5"><Box className="h-3 w-3" />{title}</h2>
        <div className="flex gap-1">
          {selection && <button className="rounded p-1 text-slate-400 hover:text-white" aria-label="Clear selection" onClick={() => select(null)}><X className="h-3.5 w-3.5" /></button>}
          <button className="rounded px-1 text-[11px] text-slate-400 hover:text-white" onClick={() => togglePanel("rightOpen")} aria-label="Collapse details panel">»</button>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {!selection && <Empty title="Nothing selected">Click a structural component, device or defect marker in the 3D view, or use the component tree.</Empty>}
        {selection?.kind === "component" && <ComponentDetails id={selection.id} assetId={assetId} />}
        {selection?.kind === "device" && (() => {
          const d = devices.find((x) => x.id === selection.id);
          return d ? <DeviceDetails d={d} comp={d.component_id ? components.get(d.component_id) : undefined} /> : <Loading />;
        })()}
        {selection?.kind === "defect" && <DefectEvidence id={selection.id} compact />}
      </div>
    </div>
  );
}
