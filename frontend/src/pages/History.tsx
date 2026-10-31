import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, qs } from "@/api/client";
import { useComponents, useDevices, useEvents } from "@/api/hooks";
import type { Baseline, Defect, DefectEvent, ImageRec, Inspection } from "@/api/types";
import { EvidenceImage } from "@/components/DefectEvidence";
import { Card, Chip, Empty, ErrorState, Loading, Notice, PageHeader, PriorityBadge, SourceBadge } from "@/components/ui";
import { useShowIn3D } from "@/hooks/useShowIn3D";
import { fmtDate, fmtDateTime, humanize } from "@/lib/format";
import { useUI } from "@/store/ui";

interface CompHistory {
  component: { id: string; name: string; component_type: string };
  inspections: (Inspection & { image: ImageRec | null })[];
  defects: Defect[];
  defect_events: (DefectEvent & { defect_id: string })[];
}
interface Compare { items: { inspection: Inspection; image: ImageRec | null; defects: Defect[] }[]; same_component: boolean; same_camera: boolean; days_apart: number; note: string }
interface RepeatGroup { component_id: string; category: string; count: number; first_observed: string; last_observed: string; defects: Defect[] }

function ComparePanel({ a, b }: { a: string; b: string }) {
  const q = useQuery({ queryKey: ["compare", a, b], queryFn: () => api<Compare>(`/history/compare${qs({ a, b })}`) });
  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState error={q.error} />;
  const c = q.data!;
  return (
    <div className="space-y-2 p-3">
      <Notice tone="warn"><b>Not spatially registered.</b> {c.note} {c.same_camera ? "Same camera." : "Different or unknown cameras."} {c.days_apart.toFixed(1)} days apart.</Notice>
      <div className="grid grid-cols-2 gap-3">
        {c.items.map((it) => (
          <div key={it.inspection.id} className="space-y-1">
            <div className="text-xs text-slate-300">{fmtDateTime(it.inspection.observed_at)} · <span className="mono">{it.inspection.id}</span></div>
            {it.image ? <EvidenceImage image={it.image} /> : <Empty title="No image" />}
            {it.defects.map((d) => <div key={d.id} className="flex items-center gap-2 text-[11px]"><span className="mono">{d.id}</span>{humanize(d.category)}<PriorityBadge p={d.priority} /></div>)}
          </div>
        ))}
      </div>
    </div>
  );
}

function VibrationHistory({ assetId }: { assetId: string }) {
  const devs = useDevices(assetId);
  const sensors = (devs.data ?? []).filter((d) => d.device_type !== "camera");
  const [dev, setDev] = useState("");
  const [bucket, setBucket] = useState("300");
  const id = dev || sensors[0]?.id;
  const q = useQuery({
    queryKey: ["vibration-history", id, bucket],
    queryFn: () => api<{ series: { t: string; source: string; rms_dyn: number; peak_dyn: number; anomalies: number; windows: number }[]; baselines: Baseline[] }>(`/history/vibration${qs({ device_id: id, bucket_s: bucket })}`),
    enabled: !!id,
  });
  const bySource = new Map<string, { t: number; rms: number; peak: number; anomalies: number }[]>();
  (q.data?.series ?? []).forEach((s) => bySource.set(s.source, [...(bySource.get(s.source) ?? []), { t: new Date(s.t).getTime(), rms: s.rms_dyn, peak: s.peak_dyn, anomalies: s.anomalies }]));
  const colors: Record<string, string> = { simulated: "#e879f9", real: "#34d399", uploaded: "#38bdf8" };
  return (
    <Card title="Vibration features across recorded windows" actions={
      <>
        <select className="input w-40" value={id ?? ""} onChange={(e) => setDev(e.target.value)} aria-label="Sensor">{sensors.map((s) => <option key={s.id} value={s.id}>{s.id}</option>)}</select>
        <select className="input w-32" value={bucket} onChange={(e) => setBucket(e.target.value)} aria-label="Aggregation"><option value="0">Per window</option><option value="300">5-min mean</option><option value="3600">Hourly mean</option><option value="86400">Daily mean</option></select>
      </>
    } bodyClass="p-3">
      {q.isLoading ? <Loading /> : !q.data?.series.length ? <Empty title="No vibration features recorded" /> : (
        <>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart margin={{ left: -10, right: 8 }}>
              <CartesianGrid stroke="#1e293b" strokeDasharray="2 4" />
              <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} stroke="#475569" fontSize={10} tickFormatter={(t) => fmtDateTime(new Date(t).toISOString())} allowDuplicatedCategory={false} />
              <YAxis stroke="#475569" fontSize={10} tickFormatter={(v) => v.toFixed(3)} />
              <Tooltip contentStyle={{ background: "#060b16", border: "1px solid rgba(34,211,238,.3)", fontSize: 11 }} labelFormatter={(t) => fmtDateTime(new Date(t as number).toISOString())} formatter={(v: number) => v.toFixed(4)} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              {[...bySource.entries()].map(([src, data]) => (
                <Line key={src} data={data} dataKey="rms" name={`rms_dyn (${src.toUpperCase()})`} stroke={colors[src] ?? "#22d3ee"} dot={false} isAnimationActive={false} />
              ))}
            </LineChart>
          </ResponsiveContainer>
          <div className="label mb-1 mt-2">Baseline changes</div>
          <table className="table-base">
            <thead><tr><th>Created</th><th>Version</th><th>Source</th><th>Windows</th><th>rms_dyn μ</th><th>By</th><th>Active</th></tr></thead>
            <tbody>{q.data.baselines.map((b) => <tr key={b.id}><td>{fmtDateTime(b.created_at)}</td><td>v{b.version}</td><td><SourceBadge source={b.source} /></td><td>{b.n_windows}</td><td className="mono">{b.rms_dyn_mean.toFixed(4)}</td><td>{b.created_by ?? "—"}</td><td>{b.active ? "✓" : ""}</td></tr>)}</tbody>
          </table>
        </>
      )}
    </Card>
  );
}

export default function HistoryPage() {
  const assetId = useUI((s) => s.assetId) ?? undefined;
  const [params, setParams] = useSearchParams();
  const comps = useComponents(assetId);
  const component = params.get("component") || "";
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [pair, setPair] = useState<string[]>([]);
  const [etype, setEtype] = useState("");
  const show3d = useShowIn3D();
  const range = { start: start ? new Date(start).toISOString() : undefined, end: end ? new Date(end + "T23:59:59").toISOString() : undefined };
  const hist = useQuery({ queryKey: ["comp-history", component, range.start, range.end], queryFn: () => api<CompHistory>(`/history/components/${component}${qs(range)}`), enabled: !!component });
  const repeated = useQuery({ queryKey: ["repeated", assetId], queryFn: () => api<RepeatGroup[]>(`/history/repeated${qs({ asset_id: assetId })}`), enabled: !!assetId });
  const events = useEvents({ asset_id: assetId, component_id: component || undefined, ...range, event_type: etype ? [etype] : undefined, limit: 300 });
  const geom = (comps.data ?? []).filter((c) => c.geometry?.type !== "group");
  const togglePair = (id: string) => setPair((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p.slice(-1), id]));

  return (
    <div className="space-y-3 pb-6">
      <PageHeader title="Historical Analysis" subtitle="Previous inspections, observation comparison, defect status changes, repeated observations, vibration history and baselines."
        actions={
          <>
            <select className="input w-60" value={component} onChange={(e) => { setPair([]); setParams(e.target.value ? { component: e.target.value } : {}); }} aria-label="Component">
              <option value="">Select a component…</option>{geom.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.id})</option>)}
            </select>
            <input type="date" className="input w-36" value={start} onChange={(e) => setStart(e.target.value)} aria-label="From" />
            <input type="date" className="input w-36" value={end} onChange={(e) => setEnd(e.target.value)} aria-label="To" />
          </>
        } />
      <div className="grid gap-3 px-5 xl:grid-cols-2">
        <Card title={component ? `Inspections — ${hist.data?.component.name ?? component}` : "Component inspections"} actions={pair.length === 2 ? <Chip className="border-accent/50 text-accent-soft">comparing 2</Chip> : component ? <span className="text-[10px] text-slate-500">select two to compare</span> : null}>
          {!component ? <Empty title="Select a component" /> : hist.isLoading ? <Loading /> : hist.isError ? <ErrorState error={hist.error} /> : !hist.data!.inspections.length ? <Empty title="No inspections in range" /> : (
            <div className="grid grid-cols-2 gap-2 p-3 md:grid-cols-3">
              {hist.data!.inspections.map((i) => (
                <button key={i.id} onClick={() => togglePair(i.id)} className={clsx("rounded-md border p-1 text-left", pair.includes(i.id) ? "border-accent shadow-glow" : "border-white/10 hover:border-white/30")}>
                  {i.image ? <EvidenceImage image={i.image} /> : <div className="aspect-square bg-black/40" />}
                  <div className="mt-1 text-[10px] text-slate-400">{fmtDate(i.observed_at)} · {humanize(i.status)}</div>
                </button>
              ))}
            </div>
          )}
        </Card>
        <Card title="Comparison">{pair.length === 2 ? <ComparePanel a={pair[0]} b={pair[1]} /> : <Empty title="Select two inspections to compare">Images are shown side by side; no spatial registration is performed.</Empty>}</Card>
        <Card title="Findings & status changes" bodyClass="max-h-96 overflow-auto">
          {!component ? <Empty title="Select a component" /> : !hist.data ? <Loading /> : (
            <table className="table-base">
              <thead><tr><th>When</th><th>Finding</th><th>Event</th><th>Change</th><th>By</th></tr></thead>
              <tbody>
                {[...hist.data.defect_events].reverse().map((e) => (
                  <tr key={e.id} className="row-hover" onClick={() => show3d("defect", e.defect_id)}><td>{fmtDateTime(e.created_at)}</td><td className="mono">{e.defect_id}</td><td>{humanize(e.event_type)}</td>
                    <td>{e.from_value ?? ""}{e.from_value || e.to_value ? " → " : ""}{e.to_value ?? ""}</td><td>{e.actor ?? "—"}</td></tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card title="Repeated observations at the same mapped location" bodyClass="max-h-96 overflow-auto">
          {repeated.isLoading ? <Loading /> : !repeated.data?.length ? <Empty title="No repeated observations" /> : (
            <ul className="space-y-2 p-3">
              {repeated.data.map((g) => (
                <li key={`${g.component_id}-${g.category}-${g.first_observed}`} className="rounded border border-white/10 p-2">
                  <div className="flex items-center justify-between text-xs"><span><span className="mono text-accent-soft">{g.component_id}</span> · {humanize(g.category)} · {g.count}×</span><span className="text-slate-400">{fmtDate(g.first_observed)} → {fmtDate(g.last_observed)}</span></div>
                  <div className="mt-1 flex flex-wrap gap-1">{g.defects.map((d) => <button key={d.id} onClick={() => show3d("defect", d.id)} className="chip border-white/15 text-slate-300 hover:border-accent/50">{d.id} · {d.priority}</button>)}</div>
                </li>
              ))}
            </ul>
          )}
        </Card>
        {assetId && <VibrationHistory assetId={assetId} />}
        <Card title="Remaining life" bodyClass="space-y-2 p-3">
          <p className="text-xs text-slate-300">Fatigue-life estimates from measured loading now have their own section.</p>
          <Link className="btn-primary" to="/rul">Open Remaining Life</Link>
        </Card>
        <Card title="Event log" className="xl:col-span-2" actions={
          <select className="input w-48" value={etype} onChange={(e) => setEtype(e.target.value)} aria-label="Event type">
            <option value="">All event types</option>{["inspection", "defect_recorded", "defect_status", "sensor_anomaly", "alert_raised", "alert_acknowledged", "alert_resolved", "baseline_created", "device_registered", "config_changed", "report_generated", "data_upload"].map((t) => <option key={t} value={t}>{humanize(t)}</option>)}
          </select>
        } bodyClass="max-h-96 overflow-auto">
          {events.isLoading ? <Loading /> : !events.data?.length ? <Empty title="No events in range" /> : (
            <table className="table-base">
              <thead><tr><th>Time</th><th>Type</th><th>Event</th><th>Component</th><th>Priority</th><th>Data</th><th>Actor</th></tr></thead>
              <tbody>{events.data.map((e) => (
                <tr key={e.id}><td>{fmtDateTime(e.ts)}</td><td>{humanize(e.event_type)}</td><td>{e.title}</td><td className="mono">{e.component_id ?? "—"}</td>
                  <td>{e.priority ? <PriorityBadge p={e.priority} /> : "—"}</td><td><SourceBadge source={e.data_source} /></td><td>{e.actor ?? "—"}</td></tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      </div>
    </div>
  );
}
