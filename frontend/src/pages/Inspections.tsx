import { ClipboardPlus } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "@/api/client";
import { useComponents, useInspections } from "@/api/hooks";
import type { Clip, DefectDetail, ImageRec, Inspection } from "@/api/types";
import { useQuery } from "@tanstack/react-query";
import { ClipPlayer, EvidenceImage } from "@/components/DefectEvidence";
import { RecordFindingForm } from "@/components/RecordFinding";
import { UploadInspection } from "@/components/UploadInspection";
import { Card, Chip, Empty, ErrorState, KV, Loading, Modal, Notice, PageHeader, PriorityBadge, SourceBadge } from "@/components/ui";
import { fmtDateTime, humanize } from "@/lib/format";
import { useUI } from "@/store/ui";

const STATUS_CLS: Record<string, string> = {
  completed: "border-emerald-400/40 text-emerald-300",
  model_unavailable: "border-amber-400/40 text-amber-300",
  inference_failed: "border-red-400/40 text-red-300",
};

function InspectionDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const q = useQuery({ queryKey: ["inspection", id], queryFn: () => api<{ inspection: Inspection; image: ImageRec | null; defects: DefectDetail["defect"][]; clips: Clip[] }>(`/inspections/${id}`) });
  const [record, setRecord] = useState(false);
  const setSel = useUI((s) => s.select);
  return (
    <Modal title={`Inspection ${id}`} onClose={onClose} wide>
      {q.isLoading ? <Loading /> : q.isError ? <ErrorState error={q.error} /> : (() => {
        const { inspection: i, image, defects, clips } = q.data!;
        return (
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">{image ? <EvidenceImage image={image} /> : <Empty title="No image" />}{clips.map((c) => <ClipPlayer key={c.id} clip={c} />)}</div>
            <div className="space-y-3">
              <div className="flex flex-wrap gap-1.5"><Chip className={STATUS_CLS[i.status]}>{humanize(i.status)}</Chip><SourceBadge source={i.data_source} /></div>
              <div>
                <KV k="Observed" v={fmtDateTime(i.observed_at)} />
                <KV k="Component" v={i.component_id ?? "Unassigned"} mono />
                <KV k="Camera" v={i.device_id ?? "—"} mono />
                <KV k="Type" v={humanize(i.inspection_type)} />
                <KV k="Performed by" v={i.performed_by} />
                <KV k="Model" v={i.model_id ? `${i.model_id} v${i.model_version}` : "None"} mono />
                {i.inference_ms !== null && <KV k="Inference time" v={`${i.inference_ms.toFixed(1)} ms`} />}
                {image?.quality && <KV k="Image quality" v={image.quality.ok ? "No issues flagged" : image.quality.issues.join(", ")} />}
                <KV k="Notes" v={i.notes} />
              </div>
              {i.status === "model_unavailable" && <Notice tone="warn">No model was installed when this image was processed. No prediction exists; findings must be recorded manually.</Notice>}
              {i.inference_output && i.status !== "model_unavailable" && (
                <details><summary className="label cursor-pointer">Raw model output</summary><pre className="mono mt-1 max-h-40 overflow-auto rounded bg-black/40 p-2">{JSON.stringify(i.inference_output, null, 2)}</pre></details>
              )}
              <div>
                <div className="label mb-1">Findings from this inspection ({defects.length})</div>
                {defects.map((d) => (
                  <div key={d.id} className="mb-1 flex items-center justify-between rounded border border-white/5 px-2 py-1 text-xs">
                    <span><span className="mono">{d.id}</span> {humanize(d.category)} · {humanize(d.detection_source)}</span><PriorityBadge p={d.priority} />
                  </div>
                ))}
              </div>
              {i.component_id && !record && <button className="btn-primary" onClick={() => setRecord(true)}><ClipboardPlus className="h-3.5 w-3.5" />Record finding from this image</button>}
              {record && i.component_id && (
                <RecordFindingForm assetId={i.asset_id} componentId={i.component_id} inspectionId={i.id} imageId={i.image_id ?? undefined} allowPick={false}
                  onDone={(d) => { setRecord(false); setSel({ kind: "defect", id: d.id }); q.refetch(); }} />
              )}
            </div>
          </div>
        );
      })()}
    </Modal>
  );
}

export default function Inspections() {
  const assetId = useUI((s) => s.assetId) ?? undefined;
  const [params, setParams] = useSearchParams();
  const [component, setComponent] = useState(params.get("component") ?? "");
  const [status, setStatus] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const device = params.get("device") ?? "";
  const comps = useComponents(assetId);
  const q = useInspections({ asset_id: assetId, component_id: component || undefined, status: status || undefined,
    start: start ? new Date(start).toISOString() : undefined, end: end ? new Date(end + "T23:59:59").toISOString() : undefined });
  const rows = (q.data ?? []).filter((r) => !device || r.device_id === device);
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="pb-6">
      <PageHeader title="Inspections" subtitle="Image-based inspections: validation, storage, model inference (when a model is installed) and inspection history." />
      <div className="grid gap-3 px-5 xl:grid-cols-[440px_1fr]">
        <Card title="New image inspection" bodyClass="p-3">{assetId ? <UploadInspection assetId={assetId} /> : <Loading />}</Card>
        <Card title={`Inspection history (${rows.length})`} actions={
          <div className="flex flex-wrap gap-1.5">
            <select className="input w-40" value={component} onChange={(e) => setComponent(e.target.value)} aria-label="Filter by component">
              <option value="">All components</option>{(comps.data ?? []).filter((c) => c.geometry?.type !== "group").map((c) => <option key={c.id} value={c.id}>{c.id}</option>)}
            </select>
            <select className="input w-36" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status">
              <option value="">All statuses</option>{["completed", "model_unavailable", "inference_failed"].map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
            </select>
            <input type="date" className="input w-36" value={start} onChange={(e) => setStart(e.target.value)} aria-label="From date" />
            <input type="date" className="input w-36" value={end} onChange={(e) => setEnd(e.target.value)} aria-label="To date" />
            {device && <button className="chip border-accent/40 text-accent-soft" onClick={() => { params.delete("device"); setParams(params); }}>camera {device} ✕</button>}
          </div>
        } bodyClass="max-h-[640px] overflow-auto">
          {q.isLoading ? <Loading /> : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !rows.length ? <Empty title="No inspections match">Upload an image to create the first inspection.</Empty> : (
            <table className="table-base">
              <thead><tr><th>Observed</th><th>ID</th><th>Component</th><th>Camera</th><th>Status</th><th>Model</th><th>Findings</th><th>Source</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="row-hover" onClick={() => setOpen(r.id)}>
                    <td>{fmtDateTime(r.observed_at)}</td><td className="mono">{r.id}</td><td className="mono">{r.component_id ?? "—"}</td><td className="mono">{r.device_id ?? "—"}</td>
                    <td><Chip className={STATUS_CLS[r.status]}>{humanize(r.status)}</Chip></td><td className="mono">{r.model_id ? `${r.model_id} v${r.model_version}` : "—"}</td>
                    <td>{r.defect_count}</td><td><SourceBadge source={r.data_source} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
      {open && <InspectionDetail id={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
