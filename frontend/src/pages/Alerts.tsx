import clsx from "clsx";
import { Check, CheckCheck, RotateCcw, UserPlus } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "@/api/client";
import { useAlertDetail, useAlertRules, useAlerts, useApiMutation } from "@/api/hooks";
import type { Alert } from "@/api/types";
import { Card, Chip, Empty, ErrorState, Field, KV, Loading, Notice, PageHeader, PriorityBadge, SourceBadge } from "@/components/ui";
import { useShowIn3D } from "@/hooks/useShowIn3D";
import { fmtDateTime, humanize } from "@/lib/format";
import { PRIORITIES, PRIORITY_LABEL } from "@/lib/priority";
import { useUI } from "@/store/ui";

const STATUS_CLS: Record<string, string> = { open: "border-red-400/50 text-red-300", acknowledged: "border-amber-400/50 text-amber-300", resolved: "border-emerald-400/50 text-emerald-300" };

function AlertActions({ a }: { a: Alert }) {
  const [actor, setActor] = useState(() => localStorage.getItem("ss.actor") ?? "");
  const [note, setNote] = useState("");
  const [assignee, setAssignee] = useState(a.assigned_to ?? "");
  const [err, setErr] = useState<string | null>(null);
  const act = useApiMutation((action: string) => {
    try { localStorage.setItem("ss.actor", actor); } catch { /* ignore */ }
    return api(`/alerts/${a.id}/${action}`, { method: "POST", json: { actor, note: note || null, assigned_to: assignee || null } });
  }, ["alerts", "alert", "summary", "events"]);
  const run = (action: string) => { setErr(null); act.mutate(action, { onError: (e) => setErr((e as Error).message), onSuccess: () => setNote("") }); };
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <Field label="Your name"><input className="input" value={actor} onChange={(e) => setActor(e.target.value)} placeholder="Required for audit trail" /></Field>
        <Field label="Assign follow-up to"><input className="input" value={assignee} onChange={(e) => setAssignee(e.target.value)} /></Field>
      </div>
      <Field label="Note / follow-up action / resolution notes"><textarea className="input h-14" value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      <div className="flex flex-wrap gap-2">
        {a.status === "open" && <button className="btn-primary" disabled={!actor} onClick={() => run("acknowledge")}><Check className="h-3.5 w-3.5" />Acknowledge</button>}
        <button className="btn-ghost" disabled={!actor || !assignee} onClick={() => run("assign")}><UserPlus className="h-3.5 w-3.5" />Assign</button>
        {a.status !== "resolved" && <button className="btn-ghost" disabled={!actor || !note} title={!note ? "Resolution notes are required" : ""} onClick={() => run("resolve")}><CheckCheck className="h-3.5 w-3.5" />Resolve</button>}
        {a.status === "resolved" && <button className="btn-ghost" disabled={!actor} onClick={() => run("reopen")}><RotateCcw className="h-3.5 w-3.5" />Reopen</button>}
      </div>
      {err && <div role="alert" className="text-xs text-red-300">{err}</div>}
    </div>
  );
}

function AlertDetailPanel({ id }: { id: string }) {
  const q = useAlertDetail(id);
  const show3d = useShowIn3D();
  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState error={q.error} />;
  const { alert: a, evidence, history } = q.data!;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5"><PriorityBadge p={a.priority} /><Chip className={STATUS_CLS[a.status]}>{a.status}</Chip><SourceBadge source={a.data_source} /></div>
      <div><div className="text-sm font-semibold text-white">{a.title}</div><div className="mono text-slate-400">{a.id}</div></div>
      {a.message && <p className="text-xs text-slate-300">{a.message}</p>}
      <div>
        <KV k="Triggering rule" v={`${a.rule_snapshot?.name ?? a.rule_type} (v${a.rule_version})`} />
        <KV k="Component" v={a.component_id ? <button className="text-accent-soft hover:underline" onClick={() => show3d("component", a.component_id!)}>{a.component_id}</button> : "—"} />
        <KV k="Device" v={a.device_id} mono />
        <KV k="First / last seen" v={`${fmtDateTime(a.first_seen_at)} / ${fmtDateTime(a.last_seen_at)}`} />
        <KV k="Occurrences" v={`${a.occurrence_count} (deduplicated)`} />
        <KV k="Acknowledged" v={a.acknowledged_by ? `${a.acknowledged_by} · ${fmtDateTime(a.acknowledged_at)}` : "—"} />
        <KV k="Assigned" v={a.assigned_to ? `${a.assigned_to}${a.follow_up_action ? ` — ${a.follow_up_action}` : ""}` : "—"} />
        <KV k="Resolution" v={a.resolution_notes ? `${a.resolution_notes} (${a.resolved_by}, ${fmtDateTime(a.resolved_at)})` : "—"} />
        <KV k="Rule params" v={JSON.stringify(a.rule_snapshot?.params ?? {})} mono />
      </div>
      <div>
        <div className="label mb-1">Evidence ({evidence.length})</div>
        <ul className="space-y-1">
          {evidence.map((e) => (
            <li key={e.id} className="rounded border border-white/5 px-2 py-1 text-[11px]">
              <span className="text-slate-400">{humanize(e.evidence_type)}</span>{" "}
              {e.evidence_type === "defect" && e.ref_id ? <button className="mono text-accent-soft hover:underline" onClick={() => show3d("defect", e.ref_id!)}>{e.ref_id}</button>
                : e.evidence_type === "vibration_feature" ? <Link className="mono text-accent-soft hover:underline" to={`/sensors?device=${a.device_id ?? ""}`}>{e.ref_id}</Link>
                : <span className="mono">{e.ref_id}</span>}
              {e.summary && <span className="text-slate-500"> — {e.summary}</span>}
              {e.data?.thresholds && <div className="mono text-[10px] text-slate-500">limit rms_dyn {Number(e.data.thresholds.rms_dyn_limit).toFixed(4)} · k={e.data.thresholds.k_sigma} · {e.data.feature_version}</div>}
            </li>
          ))}
        </ul>
      </div>
      <AlertActions a={a} />
      <div>
        <div className="label mb-1">Audit trail</div>
        <ol className="space-y-1 border-l border-white/10 pl-3">
          {history.map((h) => (
            <li key={h.id} className="text-[11px]"><span className="text-slate-400">{fmtDateTime(h.created_at)}</span> · {humanize(h.event_type)}
              {h.from_status && h.to_status && h.from_status !== h.to_status && <span className="text-slate-400"> {h.from_status} → {h.to_status}</span>}
              {h.actor && <span className="text-slate-500"> by {h.actor}</span>}{h.note && <div className="text-slate-500">{h.note}</div>}</li>
          ))}
        </ol>
      </div>
    </div>
  );
}

export default function Alerts() {
  const assetId = useUI((s) => s.assetId) ?? undefined;
  const [params, setParams] = useSearchParams();
  const [status, setStatus] = useState<string[]>(["open", "acknowledged"]);
  const [priority, setPriority] = useState<string[]>([]);
  const [rule, setRule] = useState("");
  const rules = useAlertRules();
  const q = useAlerts({ asset_id: assetId, status, priority, rule_type: rule ? [rule] : undefined });
  const sel = params.get("id");
  const toggle = (arr: string[], v: string) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);
  return (
    <div className="flex h-full flex-col">
      <PageHeader title="Alerts Center" subtitle="Traceable alerts raised by configurable rules, with deduplication, cooldowns, evidence and audit trail."
        actions={<Link className="btn-ghost" to="/settings#rules">Configure rules</Link>} />
      <div className="mx-5 mb-3 flex flex-wrap items-center gap-3 panel px-3 py-2">
        <div className="flex items-center gap-1"><span className="label mr-1">Status</span>
          {["open", "acknowledged", "resolved"].map((s) => <button key={s} aria-pressed={status.includes(s)} className={clsx("chip", status.includes(s) ? STATUS_CLS[s] : "border-white/10 text-slate-500")} onClick={() => setStatus(toggle(status, s))}>{s}</button>)}
        </div>
        <div className="flex items-center gap-1"><span className="label mr-1">Priority</span>
          {PRIORITIES.filter((p) => p !== "unassessed").map((p) => <button key={p} aria-pressed={priority.includes(p)} className={clsx("chip", priority.includes(p) ? "border-accent/50 text-accent-soft" : "border-white/10 text-slate-500")} onClick={() => setPriority(toggle(priority, p))}>{PRIORITY_LABEL[p]}</button>)}
        </div>
        <select className="input w-56" value={rule} onChange={(e) => setRule(e.target.value)} aria-label="Rule"><option value="">All rules</option>{(rules.data ?? []).map((r) => <option key={r.id} value={r.rule_type}>{r.name}</option>)}</select>
      </div>
      <div className="grid min-h-0 flex-1 gap-3 px-5 pb-5 lg:grid-cols-[1fr_440px]">
        <Card title={`Alerts (${q.data?.length ?? 0})`} bodyClass="overflow-auto">
          {q.isLoading ? <Loading /> : q.isError ? <ErrorState error={q.error} /> : !q.data?.length ? <Empty title="No alerts match">Absence of alerts does not mean the structure is in normal condition — check device status for data gaps.</Empty> : (
            <table className="table-base">
              <thead><tr><th>Priority</th><th>Status</th><th>Alert</th><th>Rule</th><th>Component</th><th>Count</th><th>Last seen</th><th>Data</th></tr></thead>
              <tbody>
                {q.data.map((a) => (
                  <tr key={a.id} className={clsx("row-hover", sel === a.id && "bg-accent/[0.06]")} onClick={() => setParams({ id: a.id })}>
                    <td><PriorityBadge p={a.priority} /></td><td><Chip className={STATUS_CLS[a.status]}>{a.status}</Chip></td>
                    <td><div className="text-slate-100">{a.title}</div><div className="mono text-slate-500">{a.id}</div></td><td>{humanize(a.rule_type)}</td>
                    <td className="mono">{a.component_id ?? a.device_id ?? "—"}</td><td>{a.occurrence_count}</td><td>{fmtDateTime(a.last_seen_at)}</td><td><SourceBadge source={a.data_source} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card title="Alert detail" bodyClass="overflow-auto p-3">
          {sel ? <AlertDetailPanel id={sel} /> : <Empty title="Select an alert" />}
          <Notice className="mt-3">Alerts indicate that a configured rule fired and an engineer should review the evidence. They are not failure predictions.</Notice>
        </Card>
      </div>
    </div>
  );
}
