import { KeyRound, Plus } from "lucide-react";
import { useState } from "react";
import { api } from "@/api/client";
import { useApiMutation, useDevices } from "@/api/hooks";
import type { Device } from "@/api/types";
import { DeviceForm } from "@/components/DeviceForm";
import { Card, ConnBadge, Empty, ErrorState, Loading, Modal, Notice, PageHeader, SourceBadge } from "@/components/ui";
import { useShowIn3D } from "@/hooks/useShowIn3D";
import { fmtAgo, humanize } from "@/lib/format";
import { useUI } from "@/store/ui";

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
