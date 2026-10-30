import clsx from "clsx";
import { Box, ExternalLink, ImageOff, MapPin } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, imageUrl } from "@/api/client";
import { useApiMutation, useDefectDetail } from "@/api/hooks";
import type { Clip, Defect, DefectDetail, ImageRec } from "@/api/types";
import { useShowIn3D } from "@/hooks/useShowIn3D";
import { fmtDateTime, humanize } from "@/lib/format";
import { PRIORITIES, PRIORITY_LABEL, REVIEW_STATUSES } from "@/lib/priority";
import { Chip, ErrorState, KV, Loading, Notice, PriorityBadge, SourceBadge } from "./ui";

const CONF_TEXT: Record<string, string> = {
  component_only: "Component-level only — exact position on the component is unknown",
  low: "Low — approximate projection with uncalibrated camera",
  approximate: "Approximate — point picked manually on the 3D model",
  medium: "Medium — calibrated camera projection onto bounding geometry",
  high: "High — surveyed / photogrammetric",
};

export function ClipPlayer({ clip }: { clip: Clip }) {
  return (
    <figure className="overflow-hidden rounded-md border border-white/10 bg-black">
      <video src={clip.url} controls muted playsInline className="block w-full" preload="metadata" />
      <figcaption className="flex justify-between px-2 py-1 text-[10px] text-slate-400">
        <span className="mono">{clip.id} · {clip.duration_s ? `${clip.duration_s.toFixed(1)} s` : ""} around the detection</span><SourceBadge source={clip.data_source} />
      </figcaption>
    </figure>
  );
}

export function EvidenceImage({ image, defect, className }: { image: ImageRec; defect?: Defect; className?: string }) {
  const [failed, setFailed] = useState(false);
  const region = defect?.image_region as { bbox?: number[] | null; point_px?: number[] } | null | undefined;
  const bbox = region?.bbox;
  const pt = region?.point_px;
  return (
    <figure className={clsx("relative overflow-hidden rounded-md border border-white/10 bg-black", className)}>
      {failed ? (
        <div className="flex aspect-square items-center justify-center text-xs text-slate-500"><ImageOff className="mr-1 h-4 w-4" />Image unavailable</div>
      ) : (
        <div className="relative">
          <img src={imageUrl(image.id)} alt={`Evidence ${image.id}`} className="block w-full" onError={() => setFailed(true)} />
          <svg viewBox={`0 0 ${image.width} ${image.height}`} className="pointer-events-none absolute inset-0 h-full w-full">
            {bbox && <rect x={bbox[0]} y={bbox[1]} width={bbox[2] - bbox[0]} height={bbox[3] - bbox[1]} fill="none" stroke="#22d3ee" strokeWidth={image.width / 150} />}
            {pt && <circle cx={pt[0]} cy={pt[1]} r={image.width / 40} fill="none" stroke="#22d3ee" strokeWidth={image.width / 200} />}
          </svg>
        </div>
      )}
      <figcaption className="flex items-center justify-between gap-2 border-t border-white/10 bg-ink-950/90 px-2 py-1 text-[10px] text-slate-400">
        <span className="truncate font-mono">{image.id} · {image.width}×{image.height}</span>
        <SourceBadge source={image.data_source} />
      </figcaption>
      {image.quality && !image.quality.ok && (
        <div className="absolute left-1 top-1 rounded bg-amber-500/90 px-1.5 py-0.5 text-[10px] font-medium text-black">Quality: {image.quality.issues.join(", ")}</div>
      )}
    </figure>
  );
}

function ReviewControls({ d }: { d: Defect }) {
  const [notes, setNotes] = useState(d.notes ?? "");
  const [reviewer, setReviewer] = useState(d.assigned_reviewer ?? "");
  const [follow, setFollow] = useState(d.follow_up_actions ?? "");
  const [actor, setActor] = useState(() => localStorage.getItem("ss.actor") ?? "");
  useEffect(() => {
    setNotes(d.notes ?? "");
    setReviewer(d.assigned_reviewer ?? "");
    setFollow(d.follow_up_actions ?? "");
  }, [d.id, d.notes, d.assigned_reviewer, d.follow_up_actions]);
  const patch = useApiMutation((body: Record<string, unknown>) => api<Defect>(`/defects/${d.id}`, { method: "PATCH", json: { ...body, actor: actor || null } }),
    ["defects", "defect", "component", "summary", "events", "alerts"]);
  const saveActor = (v: string) => {
    setActor(v);
    try { localStorage.setItem("ss.actor", v); } catch { /* ignore */ }
  };
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <label className="space-y-1"><span className="label">Review status</span>
          <select className="input" value={d.review_status} onChange={(e) => patch.mutate({ review_status: e.target.value })} aria-label="Review status">
            {REVIEW_STATUSES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
          </select>
        </label>
        <label className="space-y-1"><span className="label">Priority</span>
          <select className="input" value={d.priority_source === "manual" ? d.priority : "auto"} onChange={(e) => patch.mutate({ priority: e.target.value })} aria-label="Priority override">
            <option value="auto">Rules ({PRIORITY_LABEL[d.priority]})</option>
            {PRIORITIES.map((p) => <option key={p} value={p}>Override: {PRIORITY_LABEL[p]}</option>)}
          </select>
        </label>
      </div>
      <input className="input" placeholder="Your name (recorded in audit trail)" value={actor} onChange={(e) => saveActor(e.target.value)} aria-label="Reviewer name" />
      <input className="input" placeholder="Assigned reviewer" value={reviewer} onChange={(e) => setReviewer(e.target.value)} aria-label="Assigned reviewer" />
      <textarea className="input h-14" placeholder="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} aria-label="Notes" />
      <textarea className="input h-12" placeholder="Follow-up actions" value={follow} onChange={(e) => setFollow(e.target.value)} aria-label="Follow-up actions" />
      <div className="flex items-center gap-2">
        <button className="btn-primary" disabled={patch.isPending}
          onClick={() => patch.mutate({ notes: notes || null, assigned_reviewer: reviewer || null, follow_up_actions: follow || null })}>Save review</button>
        {patch.isSuccess && <span className="text-[11px] text-emerald-300">Saved</span>}
        {patch.isError && <span className="text-[11px] text-red-300">{(patch.error as Error).message}</span>}
      </div>
    </div>
  );
}

export function DefectEvidenceBody({ data, compact }: { data: DefectDetail; compact?: boolean }) {
  const d = data.defect;
  const show3d = useShowIn3D();
  const out = data.inspection?.inference_output as Record<string, any> | null | undefined;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <PriorityBadge p={d.priority} />
        <Chip>{humanize(d.review_status)}</Chip>
        <SourceBadge source={d.data_source} />
        {d.priority_source === "manual" && <Chip title="Priority set manually by a reviewer">manual priority</Chip>}
      </div>
      <div>
        <div className="text-sm font-semibold text-white">{humanize(d.category)}</div>
        <div className="font-mono text-[11px] text-slate-400">{d.id}</div>
        {d.description && <p className="mt-1 text-xs text-slate-300">{d.description}</p>}
      </div>
      {data.image ? <EvidenceImage image={data.image} defect={d} /> : <Notice>No image evidence attached to this finding.</Notice>}
      {(data.clips ?? []).map((c) => <ClipPlayer key={c.id} clip={c} />)}
      <div>
        <KV k="Observed" v={fmtDateTime(d.observed_at)} />
        <KV k="Component" v={data.component ? `${data.component.name} (${data.component.id})` : "Unassigned"} />
        <KV k="Detection" v={humanize(d.detection_source)} />
        {data.camera && <KV k="Camera" v={`${data.camera.name} (${data.camera.id})`} />}
        {d.detection_source === "ai_model" ? (
          <>
            <KV k="Model" v={`${d.model_id} v${d.model_version}`} mono />
            <KV k="Model output" v={<span>{d.model_label} · confidence {d.model_confidence?.toFixed(3)} <span className="text-slate-500">(not a severity measure)</span></span>} />
          </>
        ) : (
          <KV k="Model output" v={data.inspection?.status === "model_unavailable" ? "No model installed — finding entered manually" : "Manual finding"} />
        )}
        {out?.threshold !== undefined && <KV k="Threshold" v={out.threshold} mono />}
        <KV k="Location" v={`${humanize(d.location_kind)}-level · ${humanize(d.localization_method)}`} />
        <KV k="Loc. confidence" v={CONF_TEXT[d.location_confidence] ?? d.location_confidence} />
        {d.pos_x !== null && <KV k="Model coords" v={`${d.pos_x.toFixed(2)}, ${d.pos_y!.toFixed(2)}, ${d.pos_z!.toFixed(2)} (local m)`} mono />}
        {d.localization_notes && <KV k="Loc. notes" v={d.localization_notes} />}
        {d.measured_extent && <KV k="Measured extent" v={JSON.stringify(d.measured_extent)} mono />}
      </div>
      {d.location_confidence !== "high" && (
        <Notice tone="warn"><MapPin className="mr-1 inline h-3 w-3" />Location is {d.location_kind === "component" ? "known only at component level" : "approximate"} — not survey-grade.</Notice>
      )}
      <div className="flex flex-wrap gap-2">
        <button className="btn-primary" onClick={() => show3d("defect", d.id)}><Box className="h-3.5 w-3.5" />Show in 3D</button>
        {!compact && <Link className="btn-ghost" to={`/history?component=${d.component_id ?? ""}`}>Component history</Link>}
      </div>
      <details open={!compact}>
        <summary className="label cursor-pointer select-none">Priority rationale</summary>
        <ul className="mt-1 space-y-1">
          {(d.priority_rationale ?? []).map((r, i) => (
            <li key={i} className="rounded border border-white/5 bg-white/[0.02] px-2 py-1 text-[11px]">
              <span className="font-mono text-accent-soft">{r.rule}</span> → <span className="text-slate-200">{r.effect}</span>
              <div className="text-slate-400">{r.detail}</div>
            </li>
          ))}
        </ul>
      </details>
      <details open>
        <summary className="label cursor-pointer select-none">Review</summary>
        <div className="mt-2"><ReviewControls d={d} /></div>
      </details>
      <details>
        <summary className="label cursor-pointer select-none">Review history ({data.events.length})</summary>
        <ol className="mt-1 space-y-1 border-l border-white/10 pl-3">
          {data.events.map((e) => (
            <li key={e.id} className="text-[11px]">
              <span className="text-slate-400">{fmtDateTime(e.created_at)}</span> · <span className="text-slate-200">{humanize(e.event_type)}</span>
              {(e.from_value || e.to_value) && <span className="text-slate-400"> {e.from_value ?? "∅"} → {e.to_value ?? "∅"}</span>}
              {e.actor && <span className="text-slate-500"> by {e.actor}</span>}
              {e.note && <div className="text-slate-500">{e.note}</div>}
            </li>
          ))}
        </ol>
      </details>
      {data.related.length > 0 && (
        <details open>
          <summary className="label cursor-pointer select-none">Related observations ({data.related.length})</summary>
          <ul className="mt-1 space-y-1">
            {data.related.map((r) => (
              <li key={r.id} className="flex items-center justify-between rounded border border-white/5 px-2 py-1 text-[11px]">
                <span className="font-mono">{r.id}</span><span className="text-slate-400">{fmtDateTime(r.observed_at)}</span><PriorityBadge p={r.priority} />
              </li>
            ))}
          </ul>
        </details>
      )}
      {data.alert_ids.length > 0 && (
        <div className="text-[11px] text-slate-400">Linked alerts: {data.alert_ids.map((a) => (
          <Link key={a} className="mr-2 font-mono text-accent-soft hover:underline" to={`/alerts?id=${a}`}>{a}<ExternalLink className="ml-0.5 inline h-2.5 w-2.5" /></Link>
        ))}</div>
      )}
    </div>
  );
}

export function DefectEvidence({ id, compact }: { id: string; compact?: boolean }) {
  const q = useDefectDetail(id);
  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  return q.data ? <DefectEvidenceBody data={q.data} compact={compact} /> : null;
}
