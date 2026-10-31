import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Calculator, Hourglass } from "lucide-react";
import { type MutableRefObject, useEffect, useMemo, useRef, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, qs } from "@/api/client";
import { useComponents, useDevices } from "@/api/hooks";
import type { RULResult } from "@/api/types";
import { Card, Chip, Empty, ErrorState, Field, KV, Loading, Notice, PageHeader, SourceBadge } from "@/components/ui";
import { fmtDateTime, fmtNum } from "@/lib/format";
import { useUI } from "@/store/ui";

interface RulConfig {
  device_id: string | null; axis: string; stress_per_g_mpa: number | null; factor_source: string; factor_uncertainty_pct: number;
  detail_category_mpa: number | null; gamma_ff: number; gamma_mf: number; prior_damage: number; noise_gate_g: number;
  observation_hours: number; source: string;
}
interface RulOptions { detail_categories_mpa: number[]; defaults: RulConfig }

const STATUS_TEXT: Record<string, { label: string; cls: string }> = {
  estimated: { label: "Estimated", cls: "border-emerald-400/40 text-emerald-300" },
  no_damaging_cycles: { label: "No damaging cycles", cls: "border-sky-400/40 text-sky-300" },
  unavailable: { label: "Not enough inputs", cls: "border-amber-400/40 text-amber-300" },
};

function years(v: number | null | undefined) {
  if (v === null || v === undefined) return "—";
  if (v >= 1000) return `${Math.round(v).toLocaleString()} years`;
  if (v >= 1) return `${v.toFixed(1)} years`;
  return `${(v * 365.25).toFixed(0)} days`;
}

function ResultView({ r }: { r: RULResult }) {
  const st = STATUS_TEXT[r.status] ?? { label: r.status, cls: "" };
  const d = r.details as Record<string, any> | null;
  const hist = d?.histogram ? d.histogram.cycles.map((c: number, i: number) => ({
    bin: `${d.histogram.edges_mpa[i].toFixed(0)}–${d.histogram.edges_mpa[i + 1].toFixed(0)}`, cycles: c })) : [];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <Chip className={st.cls}>{st.label}</Chip>
        {r.validation_status === "demonstration_only" && <Chip className="border-fuchsia-400/40 text-fuchsia-300">demonstration only</Chip>}
        {r.validation_status === "unvalidated_engineering_estimate" && <Chip className="border-amber-400/40 text-amber-300">needs engineer sign-off</Chip>}
        <SourceBadge source={r.data_source} />
        <span className="text-[11px] text-slate-500">{fmtDateTime(r.created_at)}</span>
      </div>
      {r.status === "estimated" && (
        <div className="rounded-lg border border-accent/20 bg-accent/5 p-4">
          <div className="label">Estimated remaining fatigue life</div>
          <div className="text-3xl font-semibold text-white">{years(r.estimate)}</div>
          <div className="text-xs text-slate-400">likely range {years(r.interval_low)} – {years(r.interval_high)} · {r.horizon}</div>
        </div>
      )}
      <p className="text-sm text-slate-200">{r.message}</p>
      {d?.damage_observed !== undefined && (
        <div className="grid gap-3 md:grid-cols-2">
          <div>
            <KV k="Sensor / axis" v={`${d.device_id} · ${d.axis}`} mono />
            <KV k="Data analysed" v={`${(d.observed_s / 3600).toFixed(1)} h · ${d.samples.toLocaleString()} samples · ${(d.data_coverage * 100).toFixed(0)} % complete`} />
            <KV k="Load cycles" v={`${Math.round(d.cycles_counted).toLocaleString()} counted, ${Math.round(d.damaging_cycles).toLocaleString()} above the ${fmtNum(d.cutoff_stress_range_mpa, 1)} MPa cut-off`} />
            <KV k="Largest stress range" v={`${fmtNum(d.max_stress_range_mpa, 1)} MPa`} />
            <KV k="Damage" v={`${d.damage_observed.toExponential(2)} in this period · ${d.damage_per_year.toExponential(2)} per year`} />
            <KV k="Already used" v={`${(d.prior_damage * 100).toFixed(0)} % (entered)`} />
            <KV k="S-N curve" v={`${d.sn_curve.standard}, category ${d.sn_curve.detail_category_mpa} MPa, γ = ${d.sn_curve.gamma}`} />
          </div>
          <div>
            <div className="label mb-1">Load cycles by stress range (MPa)</div>
            <ResponsiveContainer width="100%" height={170}>
              <BarChart data={hist} margin={{ left: -10, right: 4 }}>
                <CartesianGrid stroke="#1e293b" strokeDasharray="2 4" />
                <XAxis dataKey="bin" stroke="#475569" fontSize={9} interval={1} />
                <YAxis stroke="#475569" fontSize={10} scale="log" domain={[0.5, "auto"]} allowDataOverflow />
                <Tooltip contentStyle={{ background: "#060b16", border: "1px solid rgba(34,211,238,.3)", fontSize: 11 }} />
                <Bar dataKey="cycles" fill="#22d3ee" isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
      {r.limitations && r.limitations.length > 0 && (
        <details open={r.status !== "estimated"}>
          <summary className="label cursor-pointer">{r.status === "unavailable" ? "What is missing" : "Assumptions & limitations"}</summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-slate-300">{r.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
        </details>
      )}
    </div>
  );
}

function InputsForm({ componentId, options, onSaved, saveRef }: { componentId: string; options: RulOptions; onSaved: () => void; saveRef: MutableRefObject<(() => Promise<boolean>) | null> }) {
  const q = useQuery({ queryKey: ["rul-config", componentId], queryFn: () => api<RulConfig>(`/rul/config/${componentId}`) });
  const assetId = useUI((s) => s.assetId) ?? undefined;
  const devices = useDevices(assetId);
  const sensors = (devices.data ?? []).filter((d) => d.component_id === componentId && (d.capabilities ?? ["acceleration"]).includes("acceleration") && d.device_type !== "camera");
  const [f, setF] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    if (q.data) setF(Object.fromEntries(Object.entries(q.data).map(([k, v]) => [k, v === null ? "" : String(v)])));
  }, [q.data]);
  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState error={q.error} />;
  const num = (k: string) => (f[k] === "" || f[k] === undefined ? null : Number(f[k]));
  const save = async () => {
    setMsg(null);
    try {
      await api(`/rul/config/${componentId}`, { method: "PUT", json: { actor: localStorage.getItem("ss.actor") || null, value: {
        device_id: f.device_id || null, axis: f.axis, stress_per_g_mpa: num("stress_per_g_mpa"), factor_source: f.factor_source,
        factor_uncertainty_pct: num("factor_uncertainty_pct"), detail_category_mpa: num("detail_category_mpa"), gamma_ff: num("gamma_ff"),
        gamma_mf: num("gamma_mf"), prior_damage: num("prior_damage"), noise_gate_g: num("noise_gate_g"), observation_hours: num("observation_hours"), source: f.source,
      } } });
      onSaved();
      return true;
    } catch (e) {
      setMsg((e as Error).message);
      return false;
    }
  };
  saveRef.current = save;
  const set = (k: string) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <form className="space-y-3" onSubmit={async (e) => { e.preventDefault(); if (await save()) setMsg("Saved"); }}>
      <div className="grid grid-cols-2 gap-2">
        <Field label="S-N detail category (EN 1993-1-9)" hint="Fatigue class of the critical detail, e.g. 71 for a typical welded attachment">
          <select className="input" value={f.detail_category_mpa ?? ""} onChange={set("detail_category_mpa")} required>
            <option value="">Choose…</option>{options.detail_categories_mpa.map((c) => <option key={c} value={c}>Δσc = {c} MPa</option>)}
          </select>
        </Field>
        <Field label="Stress per g (MPa / g)" hint="From a strain-gauge calibration or a validated structural model">
          <input className="input" inputMode="decimal" value={f.stress_per_g_mpa ?? ""} onChange={set("stress_per_g_mpa")} required />
        </Field>
        <Field label="Where the factor comes from"><input className="input" value={f.factor_source ?? ""} onChange={set("factor_source")} placeholder="e.g. strain gauge test 2026-11-02" /></Field>
        <Field label="Factor uncertainty (± %)"><input className="input" inputMode="decimal" value={f.factor_uncertainty_pct ?? ""} onChange={set("factor_uncertainty_pct")} /></Field>
        <Field label="Life already used (0–1)" hint="0 for a new part"><input className="input" inputMode="decimal" value={f.prior_damage ?? ""} onChange={set("prior_damage")} /></Field>
        <Field label="Sensor">
          <select className="input" value={f.device_id ?? ""} onChange={set("device_id")}>
            <option value="">{sensors.length ? "First sensor on this part" : "No sensor on this part"}</option>
            {sensors.map((d) => <option key={d.id} value={d.id}>{d.id}</option>)}
          </select>
        </Field>
      </div>
      <details>
        <summary className="label cursor-pointer">More options</summary>
        <div className="mt-2 grid grid-cols-3 gap-2">
          <Field label="Axis"><select className="input" value={f.axis ?? "z"} onChange={set("axis")}>{["z", "x", "y", "magnitude"].map((a) => <option key={a}>{a}</option>)}</select></Field>
          <Field label="Data"><select className="input" value={f.source ?? "real"} onChange={set("source")}><option value="real">Real</option><option value="uploaded">Uploaded</option><option value="simulated">Simulated (demo)</option></select></Field>
          <Field label="Analyse last (h)"><input className="input" value={f.observation_hours ?? ""} onChange={set("observation_hours")} /></Field>
          <Field label="γFf"><input className="input" value={f.gamma_ff ?? ""} onChange={set("gamma_ff")} /></Field>
          <Field label="γMf"><input className="input" value={f.gamma_mf ?? ""} onChange={set("gamma_mf")} /></Field>
          <Field label="Noise gate (g)"><input className="input" value={f.noise_gate_g ?? ""} onChange={set("noise_gate_g")} /></Field>
        </div>
      </details>
      <div className="flex items-center gap-2">
        <button type="submit" className="btn-ghost">Save inputs</button>
        {msg && <span className={`text-[11px] ${msg === "Saved" ? "text-emerald-300" : "text-red-300"}`}>{msg}</span>}
      </div>
    </form>
  );
}

export default function RemainingLife() {
  const assetId = useUI((s) => s.assetId) ?? undefined;
  const comps = useComponents(assetId);
  const devices = useDevices(assetId);
  const qc = useQueryClient();
  const options = useQuery({ queryKey: ["rul-options"], queryFn: () => api<RulOptions>("/rul/options") });
  const withSensor = useMemo(() => new Set((devices.data ?? []).filter((d) => d.device_type !== "camera" && d.component_id).map((d) => d.component_id!)), [devices.data]);
  const parts = useMemo(() => (comps.data ?? []).filter((c) => c.geometry?.type !== "group")
    .sort((a, b) => Number(withSensor.has(b.id)) - Number(withSensor.has(a.id)) || a.name.localeCompare(b.name)), [comps.data, withSensor]);
  const [sel, setSel] = useState<string>("");
  useEffect(() => { if (!sel && parts.length) setSel(parts[0].id); }, [parts, sel]);
  const results = useQuery({ queryKey: ["rul", sel], queryFn: () => api<RULResult[]>(`/rul/results${qs({ component_id: sel })}`), enabled: !!sel });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const saveRef = useRef<(() => Promise<boolean>) | null>(null);
  const calculate = async () => {
    setBusy(true);
    setErr(null);
    try {
      if (saveRef.current && !(await saveRef.current())) return;
      await api("/rul/estimate", { method: "POST", json: { asset_id: assetId, component_id: sel } });
      qc.invalidateQueries({ queryKey: ["rul"] });
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const latest = results.data?.[0];
  const part = parts.find((p) => p.id === sel);
  return (
    <div className="pb-6">
      <PageHeader title="Remaining Life" subtitle="How long a part can keep carrying the repeated loading measured by its vibration sensor before fatigue damage is used up." />
      <div className="mx-5 mb-3">
        <Notice>
          <b>How it works:</b> the sensor's vibration is split into individual load cycles (rainflow counting); each cycle is turned into a stress range with
          the factor your engineer provides; the S-N curve of the detail says how many such cycles it can take; adding the damage up (Miner's rule) gives how fast
          life is being used, and therefore how much is left — if future loading is like the period measured. It is an engineering estimate, not a guarantee.
        </Notice>
      </div>
      <div className="grid gap-3 px-5 lg:grid-cols-[260px_1fr]">
        <Card title="Parts" bodyClass="max-h-[640px] overflow-auto p-2">
          {comps.isLoading ? <Loading /> : !parts.length ? <Empty title="No parts registered" /> : parts.map((c) => (
            <button key={c.id} onClick={() => setSel(c.id)}
              className={`mb-1 w-full rounded border px-2 py-1.5 text-left ${c.id === sel ? "border-accent/50 bg-accent/10" : "border-white/5 hover:bg-white/5"}`}>
              <div className="truncate text-xs text-slate-100">{c.name}</div>
              <div className="flex items-center justify-between text-[10px] text-slate-500"><span className="mono">{c.id}</span>{withSensor.has(c.id) && <span className="text-emerald-300">sensor</span>}</div>
            </button>
          ))}
        </Card>
        {sel && options.data ? (
          <div className="grid gap-3 xl:grid-cols-2">
            <Card title={`Inputs — ${part?.name ?? sel}`} bodyClass="p-3">
              <InputsForm componentId={sel} options={options.data} saveRef={saveRef} onSaved={() => qc.invalidateQueries({ queryKey: ["rul-config", sel] })} />
              <div className="mt-3 border-t border-white/5 pt-3">
                <button className="btn-primary" disabled={busy} onClick={calculate}><Calculator className="h-3.5 w-3.5" />{busy ? "Calculating…" : "Save & calculate remaining life"}</button>
                {err && <div className="mt-1 text-xs text-red-300">{err}</div>}
              </div>
            </Card>
            <Card title="Result" bodyClass="p-3">
              {results.isLoading ? <Loading /> : latest ? <ResultView r={latest} /> : (
                <Empty title="No calculation yet"><Hourglass className="mx-auto mb-1 h-4 w-4" />Fill in the inputs and press “Save & calculate”.</Empty>
              )}
            </Card>
            {results.data && results.data.length > 1 && (
              <Card title="Previous calculations" className="xl:col-span-2" bodyClass="overflow-auto">
                <table className="table-base">
                  <thead><tr><th>When</th><th>Result</th><th>Range</th><th>Data</th><th>Status</th></tr></thead>
                  <tbody>{results.data.slice(1).map((r) => (
                    <tr key={r.id}><td>{fmtDateTime(r.created_at)}</td><td>{years(r.estimate)}</td><td>{r.interval_low ? `${years(r.interval_low)} – ${years(r.interval_high)}` : "—"}</td>
                      <td><SourceBadge source={r.data_source} /></td><td>{STATUS_TEXT[r.status]?.label ?? r.status}</td></tr>
                  ))}</tbody>
                </table>
              </Card>
            )}
          </div>
        ) : <Loading />}
      </div>
    </div>
  );
}
