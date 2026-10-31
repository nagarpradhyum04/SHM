import { useQuery } from "@tanstack/react-query";
import { Box, Film, Video, VideoOff } from "lucide-react";
import { useState } from "react";
import { api, API_BASE } from "@/api/client";
import { useDevices, useSystemStatus } from "@/api/hooks";
import type { Clip, Defect, Device } from "@/api/types";
import { ClipPlayer } from "@/components/DefectEvidence";
import { Card, ConnBadge, Empty, Loading, Modal, Notice, PageHeader, PriorityBadge } from "@/components/ui";
import { useShowIn3D } from "@/hooks/useShowIn3D";
import { fmtAgo, fmtDateTime, humanize } from "@/lib/format";
import { useUI } from "@/store/ui";

interface Detection { defect: Defect; inspection_id: string; annotated_url: string; clips: Clip[] }

function LiveView({ d }: { d: Device }) {
  const [failed, setFailed] = useState(false);
  const [nonce, setNonce] = useState(0);
  if (!d.stream_url || failed) {
    return (
      <div className="flex aspect-video flex-col items-center justify-center gap-2 bg-black/60 text-center text-xs text-slate-400">
        <VideoOff className="h-6 w-6" />
        {d.stream_url ? "Live view not reachable — is the camera agent running?" : "No live view yet — start the camera agent on the laptop with the webcam."}
        {d.stream_url && <button className="btn-ghost" onClick={() => { setFailed(false); setNonce(nonce + 1); }}>Retry</button>}
      </div>
    );
  }
  return <img key={nonce} src={`${API_BASE}/cameras/${d.id}/live?n=${nonce}`} alt={`Live view of ${d.name}`} className="block aspect-video w-full bg-black object-contain" onError={() => setFailed(true)} />;
}

function CameraTile({ d }: { d: Device }) {
  const q = useQuery({ queryKey: ["camera-detections", d.id], queryFn: () => api<Detection[]>(`/cameras/${d.id}/detections?limit=6`), refetchInterval: 5000 });
  const [open, setOpen] = useState<Detection | null>(null);
  const show3d = useShowIn3D();
  const latest = q.data?.[0];
  const fresh = latest && Date.now() - new Date(latest.defect.observed_at).getTime() < 120_000;
  return (
    <Card title={<span className="flex items-center gap-1.5"><Video className="h-3.5 w-3.5" />{d.name}</span>}
      actions={<><ConnBadge status={d.connection?.status} label={d.connection?.label} /><span className="mono text-[10px] text-slate-500">{d.id}</span></>}>
      <div className="relative">
        <LiveView d={d} />
        {fresh && <div className="absolute left-2 top-2 animate-pulse rounded bg-red-600/90 px-2 py-1 text-[11px] font-semibold text-white">DEFECT DETECTED {fmtAgo(latest!.defect.observed_at)}</div>}
      </div>
      <div className="space-y-1 p-2">
        <div className="label">Detections</div>
        {q.isLoading ? <Loading /> : !q.data?.length ? <div className="text-[11px] text-slate-500">None yet.</div> : q.data.map((x) => (
          <button key={x.defect.id} onClick={() => setOpen(x)} className="flex w-full items-center gap-2 rounded border border-white/5 p-1 text-left hover:bg-white/5">
            <img src={x.annotated_url} alt="" className="h-10 w-16 rounded object-cover" loading="lazy" />
            <div className="min-w-0 flex-1 text-[11px]">
              <div className="text-slate-200">{humanize(x.defect.category)} · {fmtDateTime(x.defect.observed_at)}</div>
              <div className="mono truncate text-slate-500">
                {x.defect.pos_x !== null ? `(${x.defect.pos_x.toFixed(2)}, ${x.defect.pos_y!.toFixed(2)}, ${x.defect.pos_z!.toFixed(2)}) m` : "position: part only"}
                {x.clips.length > 0 && " · clip"}
              </div>
            </div>
            <PriorityBadge p={x.defect.priority} />
          </button>
        ))}
      </div>
      {open && (
        <Modal title={`${humanize(open.defect.category)} — ${open.defect.id}`} onClose={() => setOpen(null)} wide>
          <div className="grid gap-3 md:grid-cols-2">
            <div className="space-y-2">
              <img src={open.annotated_url} alt="Annotated detection photo" className="w-full rounded border border-white/10" />
              <a className="btn-ghost" href={open.annotated_url} download={`${open.defect.id}.jpg`}>Download photo</a>
            </div>
            <div className="space-y-2">
              {open.clips.length ? open.clips.map((c) => <ClipPlayer key={c.id} clip={c} />) : (
                <Notice><Film className="mr-1 inline h-3 w-3" />The clip (30 s before + 30 s after) is uploaded about 30 s after the detection.</Notice>
              )}
              <button className="btn-primary" onClick={() => show3d("defect", open.defect.id)}><Box className="h-3.5 w-3.5" />Show on 3D model</button>
            </div>
          </div>
        </Modal>
      )}
    </Card>
  );
}

export default function LiveCameras() {
  const assetId = useUI((s) => s.assetId) ?? undefined;
  const devices = useDevices(assetId);
  const status = useSystemStatus();
  const cams = (devices.data ?? []).filter((d) => d.device_type === "camera");
  return (
    <div className="pb-6">
      <PageHeader title="Live cameras" subtitle="Live webcam view, automatic crack checks, and the photo + 60 s clip saved for every detection." />
      <div className="space-y-3 px-5">
        {status.data && !status.data.models.available && (
          <Notice tone="warn">No crack-detection model is installed, so the live view works but nothing is detected yet. Install one in Settings → AI model.</Notice>
        )}
        {devices.isLoading ? <Loading /> : !cams.length ? (
          <Empty title="No cameras registered">Register a Camera in Device Registry, then run the camera agent on the laptop with the webcam.</Empty>
        ) : <div className="grid gap-3 xl:grid-cols-2">{cams.map((d) => <CameraTile key={d.id} d={d} />)}</div>}
      </div>
    </div>
  );
}
