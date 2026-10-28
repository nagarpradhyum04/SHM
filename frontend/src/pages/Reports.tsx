import { Download, FileText, Printer } from "lucide-react";
import { useState } from "react";
import { api, API_BASE } from "@/api/client";
import { useApiMutation, useReports } from "@/api/hooks";
import type { Report } from "@/api/types";
import { Card, Chip, Empty, ErrorState, Field, Loading, Notice, PageHeader } from "@/components/ui";
import { fmtBytes, fmtDateTime } from "@/lib/format";
import { useUI } from "@/store/ui";

const day = (offset: number) => new Date(Date.now() + offset * 86400000).toISOString().slice(0, 10);

export default function Reports() {
  const assetId = useUI((s) => s.assetId) ?? undefined;
  const q = useReports(assetId);
  const [start, setStart] = useState(day(-30));
  const [end, setEnd] = useState(day(0));
  const [err, setErr] = useState<string | null>(null);
  const gen = useApiMutation(() => api<Report>("/reports", { method: "POST", json: {
    asset_id: assetId, period_start: new Date(start + "T00:00:00").toISOString(), period_end: new Date(end + "T23:59:59").toISOString(),
    actor: localStorage.getItem("ss.actor") || null } }), ["reports", "events"]);
  return (
    <div className="pb-6">
      <PageHeader title="Reports" subtitle="Inspection reports generated from stored records, with data provenance, warnings and an engineering-review disclaimer." />
      <div className="grid gap-3 px-5 lg:grid-cols-[360px_1fr]">
        <Card title="Generate report" bodyClass="space-y-3 p-3">
          <div className="grid grid-cols-2 gap-2">
            <Field label="From"><input type="date" className="input" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
            <Field label="To"><input type="date" className="input" value={end} onChange={(e) => setEnd(e.target.value)} /></Field>
          </div>
          <div className="flex flex-wrap gap-1">
            {[7, 30, 120, 365].map((d) => <button key={d} className="chip border-white/15 text-slate-300 hover:border-accent/50" onClick={() => { setStart(day(-d)); setEnd(day(0)); }}>Last {d} days</button>)}
          </div>
          <button className="btn-primary" disabled={!assetId || gen.isPending} onClick={() => gen.mutate(undefined, { onError: (e) => setErr((e as Error).message), onSuccess: () => setErr(null) })}>
            <FileText className="h-3.5 w-3.5" />{gen.isPending ? "Generating PDF…" : "Generate PDF report"}
          </button>
          {err && <div role="alert" className="text-xs text-red-300">{err}</div>}
          <Notice>Reports include only recorded values. Simulated and demonstration data are flagged on every page. No remaining-useful-life estimate or certified structural assessment is included.</Notice>
        </Card>
        <Card title={`Generated reports (${q.data?.length ?? 0})`} bodyClass="overflow-auto">
          {q.isLoading ? <Loading /> : q.isError ? <ErrorState error={q.error} /> : !q.data?.length ? <Empty title="No reports generated yet" /> : (
            <table className="table-base">
              <thead><tr><th>Report</th><th>Period</th><th>Generated</th><th>Contents</th><th>Warnings</th><th /></tr></thead>
              <tbody>
                {q.data.map((r) => (
                  <tr key={r.id}>
                    <td className="mono">{r.id}{r.includes_simulated && <Chip className="ml-1 border-fuchsia-400/40 text-fuchsia-300">sim/demo data</Chip>}</td>
                    <td>{fmtDateTime(r.period_start)} → {fmtDateTime(r.period_end)}</td>
                    <td>{fmtDateTime(r.generated_at)}<div className="text-[10px] text-slate-500">{r.generated_by ?? ""} · {fmtBytes(r.size_bytes)}</div></td>
                    <td className="text-[11px]">{r.summary?.inspections} inspections · {r.summary?.defects} findings · {r.summary?.alerts} alerts · {r.summary?.anomalies} anomaly windows</td>
                    <td className="max-w-xs text-[11px] text-amber-200/80">{(r.summary?.warnings ?? []).length} warning(s)</td>
                    <td className="whitespace-nowrap">
                      <a className="btn-primary mr-1 py-0.5" href={`${API_BASE}/reports/${r.id}/download`}><Download className="h-3 w-3" />PDF</a>
                      <a className="btn-ghost py-0.5" href={`${API_BASE}/reports/${r.id}/print`} target="_blank" rel="noreferrer"><Printer className="h-3 w-3" />Print view</a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </div>
  );
}
