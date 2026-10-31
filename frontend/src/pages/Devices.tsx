import { KeyRound, Move3d, Pencil, Plus, Trash2 } from "lucide-react";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, API_BASE } from "@/api/client";
import { useApiMutation, useAssets, useComponents, useDevices } from "@/api/hooks";
import type { Device } from "@/api/types";
import { DeviceForm } from "@/components/DeviceForm";
import { Card, ConnBadge, Empty, ErrorState, Loading, Modal, Notice, PageHeader, SourceBadge } from "@/components/ui";
import { fmtAgo, humanize } from "@/lib/format";
import { focusForDevice, sceneBounds } from "@/lib/geometry";
import { useUI } from "@/store/ui";
import { PlacementEditor } from "@/twin/PlacementEditor";

const BridgeScene = lazy(() => import("@/twin/BridgeScene"));

interface DeletePreview {
  removed: Record<string, number>;
  kept: { inspections: number; clips: number; note: string };
}

function DeleteDialog({ d, onClose }: { d: Device; onClose: () => void }) {
  const preview = useQuery({ queryKey: ["delete-preview", d.id], queryFn: () => api<DeletePreview>(`/devices/${d.id}/delete-preview`) });
  const [typed, setTyped] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const del = useApiMutation(() => api(`/devices/${d.id}?actor=${encodeURIComponent(localStorage.getItem("ss.actor") || "")}`, { method: "DELETE" }),
    ["devices", "summary", "component", "events"]);
  const p = preview.data;
  return (
    <Modal title={`Delete ${d.id}?`} onClose={onClose}>
      <div className="space-y-3 text-xs">
        <p className="text-slate-300"><b>{d.name}</b> will be removed from the registry and the 3D model.</p>
        {preview.isLoading ? <Loading /> : p && (
          <>
            <div className="rounded border border-red-400/30 bg-red-500/5 p-2">
              <div className="label mb-1 text-red-300">Deleted permanently</div>
              {Object.entries(p.removed).map(([k, v]) => <div key={k}>{humanize(k)}: <b>{v.toLocaleString()}</b></div>)}
            </div>
            <div className="rounded border border-white/10 p-2 text-slate-400">{p.kept.note} ({p.kept.inspections} inspections, {p.kept.clips} clips)</div>
          </>
        )}
        {d.data_source === "real" && <Notice tone="warn">The physical device will keep trying to send data; its messages will be rejected until you register it again.</Notice>}
        <label className="block space-y-1"><span className="label">Type the device ID to confirm</span>
          <input className="input" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={d.id} aria-label="Confirm device ID" /></label>
        {err && <div className="text-red-300">{err}</div>}
        <div className="flex justify-end gap-2">
          <button className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-danger" disabled={typed !== d.id || del.isPending}
            onClick={() => del.mutate(undefined, { onSuccess: onClose, onError: (e) => setErr((e as Error).message) })}>
            <Trash2 className="h-3.5 w-3.5" />Delete device
          </button>
        </div>
      </div>
    </Modal>
  );
}

/** Dedicated placement workspace: device list · 3D view · placement editor. */
function PlacementWorkspace({ assetId, devices }: { assetId: string; devices: Device[] }) {
  const comps = useComponents(assetId);
  const assets = useAssets();
  const asset = assets.data?.find((a) => a.id === assetId);
  const selection = useUI((s) => s.selection);
  const select = useUI((s) => s.select);
  const camera = useUI((s) => s.camera);
  const pickMode = useUI((s) => s.pickMode);
  const selectedId = selection?.kind === "device" ? selection.id : null;
  const device = devices.find((d) => d.id === selectedId);
  useEffect(() => {
    if (!selectedId && devices.length) select({ kind: "device", id: devices[0].id });
  }, [selectedId, devices, select]);
  const componentMap = useMemo(() => new Map((comps.data ?? []).map((c) => [c.id, c])), [comps.data]);
  const modelKind = asset?.model_kind === "gltf" ? "gltf" : "procedural";
  const modelUrl = modelKind === "gltf" ? `${API_BASE}/assets/${assetId}/model/file?v=${encodeURIComponent(asset?.model_meta?.uploaded_at ?? "")}` : undefined;
  const bounds = useMemo(() => sceneBounds(comps.data ?? [], modelKind === "gltf" ? asset?.model_meta?.bounds : null), [comps.data, modelKind, asset?.model_meta?.bounds]);
  const choose = (d: Device) => {
    select({ kind: "device", id: d.id });
    const f = focusForDevice(d);
    camera({ type: "focus", target: f.target, radius: Math.max(f.radius, bounds.radius / 4) });
  };
  return (
    <div className="grid gap-3 lg:grid-cols-[220px_1fr_340px]">
      <Card title="Choose a device" bodyClass="max-h-[620px] overflow-auto p-2">
        {devices.map((d) => (
          <button key={d.id} onClick={() => choose(d)} className={`mb-1 w-full rounded border px-2 py-1.5 text-left ${d.id === selectedId ? "border-accent/50 bg-accent/10" : "border-white/5 hover:bg-white/5"}`}>
            <div className="mono">{d.id}</div><div className="truncate text-[11px] text-slate-400">{d.name}</div>
          </button>
        ))}
      </Card>
      <div className="relative h-[620px] overflow-hidden rounded-lg border border-accent/15 bg-ink-950">
        {comps.isLoading ? <Loading /> : (
          <Suspense fallback={<Loading label="Loading 3D view…" />}>
            <BridgeScene components={comps.data ?? []} componentMap={componentMap} devices={devices} defects={[]} heat={null}
              modelKind={modelKind} modelUrl={modelUrl} bounds={bounds} />
          </Suspense>
        )}
        {pickMode && <div className="absolute left-1/2 top-3 -translate-x-1/2 rounded-md border border-accent/50 bg-ink-950/95 px-3 py-1.5 text-xs text-accent-soft">Click on the structure…</div>}
      </div>
      <Card title={device ? `Placement — ${device.id}` : "Placement"} bodyClass="p-3">
        {device ? (
          <div className="space-y-2">
            <div className="text-xs text-slate-400">{device.name} · on <span className="mono">{device.component_id ?? "—"}</span></div>
            <PlacementEditor d={device} />
          </div>
        ) : <Empty title="Select a device" />}
      </Card>
    </div>
  );
}

export default function Devices() {
  const assetId = useUI((s) => s.assetId) ?? undefined;
  const q = useDevices(assetId);
  const [tab, setTab] = useState<"list" | "placement">(() => (location.hash === "#placement" ? "placement" : "list"));
  const [modal, setModal] = useState<{ kind: "new" } | { kind: "edit"; d: Device } | null>(null);
  const [deleting, setDeleting] = useState<Device | null>(null);
  const [token, setToken] = useState<{ id?: string; token: string } | null>(null);
  const select = useUI((s) => s.select);
  const rotate = useApiMutation((id: string) => api<{ device_id: string; ingestion_token: string }>(`/devices/${id}/rotate-token`, { method: "POST" }), ["devices"]);
  const go = (t: "list" | "placement") => { setTab(t); history.replaceState(null, "", t === "placement" ? "#placement" : "#"); };
  return (
    <div className="pb-6">
      <PageHeader title="Device Registry" subtitle="Your IoT nodes and cameras: register, edit, place on the model, or delete."
        actions={<button className="btn-primary" onClick={() => setModal({ kind: "new" })}><Plus className="h-3.5 w-3.5" />Register device</button>} />
      <div className="mx-5 mb-3 flex gap-1 border-b border-white/10" role="tablist">
        {([["list", "All devices"], ["placement", "Placement on the model"]] as const).map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => go(k)}
            className={`-mb-px border-b-2 px-3 py-2 text-xs font-medium ${tab === k ? "border-accent text-accent-soft" : "border-transparent text-slate-400 hover:text-white"}`}>{l}</button>
        ))}
      </div>
      <div className="px-5">
        {tab === "placement" && assetId && (q.data?.length ? <PlacementWorkspace assetId={assetId} devices={q.data} /> : <Empty title="No devices to place" />)}
        {tab === "list" && (
          <Card title={`Devices (${q.data?.length ?? 0})`} bodyClass="overflow-auto">
            {q.isLoading ? <Loading /> : q.isError ? <ErrorState error={q.error} /> : !q.data?.length ? <Empty title="No devices registered">Use “Register device” to add your first IoT node or camera.</Empty> : (
              <table className="table-base">
                <thead><tr><th>Device</th><th>Type</th><th>Mounted on</th><th>Status</th><th>Last data</th><th className="text-right">Actions</th></tr></thead>
                <tbody>
                  {q.data.map((d) => (
                    <tr key={d.id}>
                      <td><div className="mono text-accent-soft">{d.id}</div><div className="text-[11px] text-slate-400">{d.name}</div></td>
                      <td>{humanize(d.device_type)} <SourceBadge source={d.data_source} className="ml-1" /></td>
                      <td className="mono">{d.component_id ?? "—"}</td>
                      <td><ConnBadge status={d.connection?.status} label={d.connection?.label} /></td>
                      <td>{fmtAgo(d.last_seen_at)}</td>
                      <td className="whitespace-nowrap text-right">
                        <button className="btn-ghost mr-1 py-0.5" title="Edit placement" onClick={() => { select({ kind: "device", id: d.id }); go("placement"); }}><Move3d className="h-3 w-3" />Place</button>
                        <button className="btn-ghost mr-1 py-0.5" title="Edit details" onClick={() => setModal({ kind: "edit", d })}><Pencil className="h-3 w-3" />Edit</button>
                        {d.data_source === "real" && <button className="btn-ghost mr-1 py-0.5" title="New token (old one stops working)"
                          onClick={() => rotate.mutate(d.id, { onSuccess: (r) => setToken({ id: r.device_id, token: r.ingestion_token }) })}><KeyRound className="h-3 w-3" /></button>}
                        <button className="btn-danger py-0.5" title="Delete device" onClick={() => setDeleting(d)} aria-label={`Delete ${d.id}`}><Trash2 className="h-3 w-3" /></button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        )}
      </div>
      {modal && assetId && (
        <Modal title={modal.kind === "new" ? "Register device" : `Edit ${modal.d.id}`} onClose={() => setModal(null)} wide>
          <DeviceForm assetId={assetId} initial={modal.kind === "edit" ? modal.d : undefined} onDone={(t) => { setModal(null); if (t) setToken({ token: t }); }} />
        </Modal>
      )}
      {deleting && <DeleteDialog d={deleting} onClose={() => setDeleting(null)} />}
      {token && (
        <Modal title="Device token" onClose={() => setToken(null)}>
          <Notice tone="warn">Shown <b>once</b>. Put it in the firmware's <code className="mono">secrets.h</code> (<code className="mono">DEVICE_TOKEN</code>) or the camera agent's <code className="mono">--token</code>.</Notice>
          <pre className="mono mt-3 select-all whitespace-pre-wrap break-all rounded bg-black/50 p-3 text-accent-soft">{token.token}</pre>
        </Modal>
      )}
    </div>
  );
}
