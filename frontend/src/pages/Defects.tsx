import clsx from "clsx";
import { Box, Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useComponents, useDefects } from "@/api/hooks";
import { DefectEvidence } from "@/components/DefectEvidence";
import { RecordFindingForm } from "@/components/RecordFinding";
import { Card, Chip, Empty, ErrorState, Field, Loading, Modal, PageHeader, PriorityBadge, SourceBadge } from "@/components/ui";
import { useShowIn3D } from "@/hooks/useShowIn3D";
import { fmtDateTime, humanize } from "@/lib/format";
import { CATEGORIES, PRIORITIES, PRIORITY_COLOR, PRIORITY_LABEL, REVIEW_STATUSES } from "@/lib/priority";
import { useUI } from "@/store/ui";

const toggle = (arr: string[], v: string) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);

export default function Defects() {
  const assetId = useUI((s) => s.assetId) ?? undefined;
  const [priority, setPriority] = useState<string[]>([]);
  const [category, setCategory] = useState<string[]>([]);
  const [status, setStatus] = useState<string[]>([]);
  const [component, setComponent] = useState("");
  const [detection, setDetection] = useState("");
  const [source, setSource] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [sort, setSort] = useState("priority");
  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newComp, setNewComp] = useState("");
  const show3d = useShowIn3D();
  const comps = useComponents(assetId);
  const q = useDefects({
    asset_id: assetId, priority, category, review_status: status, component_id: component ? [component] : undefined,
    detection_source: detection ? [detection] : undefined, data_source: source ? [source] : undefined,
    start: start ? new Date(start).toISOString() : undefined, end: end ? new Date(end + "T23:59:59").toISOString() : undefined, sort,
  }, !!assetId);
  const compName = useMemo(() => new Map((comps.data ?? []).map((c) => [c.id, c.name])), [comps.data]);
  const geomComps = (comps.data ?? []).filter((c) => c.geometry?.type !== "group");

  return (
    <div className="flex h-full flex-col">
      <PageHeader title="Defect Registry" subtitle="All recorded findings with evidence, review priority, localisation method and review status. Priority ≠ certified structural severity."
        actions={<button className="btn-primary" onClick={() => setCreating(true)}><Plus className="h-3.5 w-3.5" />Record finding</button>} />
      <div className="mx-5 mb-3 flex flex-wrap items-center gap-x-4 gap-y-2 panel px-3 py-2">
        <div className="flex flex-wrap items-center gap-1"><span className="label mr-1">Priority</span>
          {PRIORITIES.map((p) => (
            <button key={p} aria-pressed={priority.includes(p)} onClick={() => setPriority(toggle(priority, p))} className={clsx("chip", !priority.includes(p) && "opacity-50")}
              style={{ borderColor: `${PRIORITY_COLOR[p]}66`, color: PRIORITY_COLOR[p] }}>{PRIORITY_LABEL[p]}</button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-1"><span className="label mr-1">Status</span>
          {REVIEW_STATUSES.map((s) => <button key={s} aria-pressed={status.includes(s)} onClick={() => setStatus(toggle(status, s))} className={clsx("chip", status.includes(s) ? "border-accent/50 text-accent-soft" : "border-white/10 text-slate-400")}>{humanize(s)}</button>)}
        </div>
        <div className="flex flex-wrap items-center gap-1"><span className="label mr-1">Category</span>
          {CATEGORIES.map((c) => <button key={c} aria-pressed={category.includes(c)} onClick={() => setCategory(toggle(category, c))} className={clsx("chip", category.includes(c) ? "border-accent/50 text-accent-soft" : "border-white/10 text-slate-400")}>{humanize(c)}</button>)}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <select className="input w-36" value={component} onChange={(e) => setComponent(e.target.value)} aria-label="Component"><option value="">All components</option>{geomComps.map((c) => <option key={c.id} value={c.id}>{c.id}</option>)}</select>
          <select className="input w-32" value={detection} onChange={(e) => setDetection(e.target.value)} aria-label="Detection source"><option value="">Any detection</option><option value="ai_model">AI model</option><option value="manual">Manual</option><option value="sensor_rule">Sensor rule</option></select>
          <select className="input w-32" value={source} onChange={(e) => setSource(e.target.value)} aria-label="Data source"><option value="">Any data source</option>{["real", "uploaded", "demo", "simulated"].map((s) => <option key={s} value={s}>{humanize(s)}</option>)}</select>
          <input type="date" className="input w-36" value={start} onChange={(e) => setStart(e.target.value)} aria-label="Observed from" />
          <input type="date" className="input w-36" value={end} onChange={(e) => setEnd(e.target.value)} aria-label="Observed to" />
          <select className="input w-36" value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort">
            <option value="priority">Sort: priority</option><option value="observed_desc">Sort: newest</option><option value="observed_asc">Sort: oldest</option>
            <option value="component">Sort: component</option><option value="category">Sort: category</option><option value="status">Sort: status</option><option value="source">Sort: detection source</option>
          </select>
        </div>
      </div>
      <div className="grid min-h-0 flex-1 gap-3 px-5 pb-5 lg:grid-cols-[1fr_420px]">
        <Card title={`Findings (${q.data?.length ?? 0})`} bodyClass="overflow-auto">
          {q.isLoading ? <Loading /> : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !q.data?.length ? <Empty title="No findings match these filters" /> : (
            <table className="table-base" data-testid="defect-table">
              <thead><tr><th>Priority</th><th>ID</th><th>Category</th><th>Component</th><th>Observed</th><th>Detection</th><th>Location</th><th>Status</th><th>Data</th><th /></tr></thead>
              <tbody>
                {q.data.map((d) => (
                  <tr key={d.id} className={clsx("row-hover", selected === d.id && "bg-accent/[0.06]")} onClick={() => setSelected(d.id)}>
                    <td><PriorityBadge p={d.priority} /></td><td className="mono">{d.id}</td><td>{humanize(d.category)}</td>
                    <td title={d.component_id ?? ""}>{d.component_id ? compName.get(d.component_id) ?? d.component_id : "—"}</td>
                    <td>{fmtDateTime(d.observed_at)}</td><td>{humanize(d.detection_source)}{d.model_confidence !== null && <span className="text-slate-500"> ({d.model_confidence.toFixed(2)})</span>}</td>
                    <td><Chip title={d.localization_method}>{d.location_kind === "surface" ? `surface · ${d.location_confidence}` : "component"}</Chip></td>
                    <td>{humanize(d.review_status)}</td><td><SourceBadge source={d.data_source} /></td>
                    <td><button className="btn-ghost py-0.5" onClick={(e) => { e.stopPropagation(); show3d("defect", d.id); }} aria-label={`Show ${d.id} in 3D`}><Box className="h-3 w-3" />3D</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card title="Evidence" bodyClass="overflow-auto p-3">
          {selected ? <DefectEvidence id={selected} /> : <Empty title="Select a finding">Evidence image, model output, location method, priority rationale and review history appear here.</Empty>}
        </Card>
      </div>
      {creating && assetId && (
        <Modal title="Record finding" onClose={() => setCreating(false)}>
          <Field label="Component"><select className="input mb-3" value={newComp} onChange={(e) => setNewComp(e.target.value)}><option value="">Select component…</option>{geomComps.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.id})</option>)}</select></Field>
          {newComp && <RecordFindingForm assetId={assetId} componentId={newComp} allowPick={false} onDone={(d) => { setCreating(false); setSelected(d.id); }} />}
          {!newComp && <p className="text-[11px] text-slate-500">To pick an approximate surface point, record the finding from the Digital Twin instead.</p>}
        </Modal>
      )}
    </div>
  );
}
