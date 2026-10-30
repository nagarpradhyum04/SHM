import { Play, Square, Upload, Wand2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, API_BASE } from "@/api/client";
import { useApiMutation, useBaselines, useDevices, useFeatures, useSystemStatus } from "@/api/hooks";
import type { Device } from "@/api/types";
import { FeaturesChart, ReadingsChart, SourceGate } from "@/components/SensorCharts";
import { EnvironmentChart } from "@/components/EnvironmentChart";
import { Card, ConnBadge, Empty, Field, Loading, Notice, PageHeader, Segmented, SourceBadge } from "@/components/ui";
import { fmtDateTime, fmtNum, fmtTime } from "@/lib/format";
import { useUI } from "@/store/ui";
import { useQueryClient } from "@tanstack/react-query";

function FeatureTable({ device, source }: { device: Device; source?: string }) {
  const q = useFeatures(device.id, source, 240);
  const rows = [...(q.data ?? [])].reverse().slice(0, 60);
  if (!rows.length) return <Empty title="No feature windows" />;
  return (
    <table className="table-base">
      <thead><tr><th>Window</th><th>Source</th><th>Samples</th><th>Missing</th><th>Dup/Gaps</th><th>rms_dyn</th><th>peak_dyn</th><th>Ratio</th><th>Baseline</th><th>Result</th></tr></thead>
      <tbody>
        {rows.map((f) => (
          <tr key={f.id} className={f.anomaly ? "bg-red-500/[0.06]" : ""}>
            <td>{fmtTime(f.window_start)}–{fmtTime(f.window_end)}</td><td><SourceBadge source={f.source} /></td><td>{f.sample_count}/{f.expected_count ?? "?"}</td>
            <td>{f.missing_ratio !== null ? `${(f.missing_ratio * 100).toFixed(0)}%` : "—"}</td><td>{f.duplicate_count}/{f.gap_count}</td>
            <td className="mono">{fmtNum(f.rms_dyn, 4)}</td><td className="mono">{fmtNum(f.peak_dyn, 4)}</td><td className="mono">{fmtNum(f.baseline_ratio, 2)}</td>
            <td>{f.baseline_version ? `v${f.baseline_version}` : "—"}</td>
            <td className={f.anomaly ? "text-red-300" : f.data_quality !== "ok" ? "text-amber-300" : "text-slate-400"}>
              {f.anomaly ? (f.anomaly_reasons ?? []).join(", ") : (f.anomaly_reasons ?? []).join(", ") || "within limits"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Baselines({ device, source }: { device: Device; source: string }) {
  const q = useBaselines(device.id);
  const [start, setStart] = useState(() => new Date(Date.now() - 2 * 3600e3).toISOString().slice(0, 16));
  const [end, setEnd] = useState(() => new Date().toISOString().slice(0, 16));
  const [err, setErr] = useState<string | null>(null);
  const create = useApiMutation(() => api(`/sensors/${device.id}/baselines`, { method: "POST", json: {
    source, window_start: new Date(start).toISOString(), window_end: new Date(end).toISOString(), actor: localStorage.getItem("ss.actor") || null } }), ["baselines", "features"]);
  return (
    <div className="space-y-2">
      <table className="table-base">
        <thead><tr><th>Version</th><th>Source</th><th>Windows</th><th>rms_dyn μ ± σ</th><th>Period</th><th>Active</th></tr></thead>
        <tbody>
          {(q.data ?? []).map((b) => (
            <tr key={b.id}><td>v{b.version}</td><td><SourceBadge source={b.source} /></td><td>{b.n_windows}</td>
              <td className="mono">{b.rms_dyn_mean.toFixed(4)} ± {b.rms_dyn_std.toFixed(4)}</td><td>{fmtDateTime(b.window_start)} → {fmtDateTime(b.window_end)}</td><td>{b.active ? "✓" : ""}</td></tr>
          ))}
        </tbody>
      </table>
      {!q.data?.length && <div className="px-3 text-[11px] text-slate-500">No baseline. Anomaly rules are not evaluated until a baseline exists.</div>}
      <div className="flex flex-wrap items-end gap-2 px-1">
        <Field label="Baseline from"><input type="datetime-local" className="input" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
        <Field label="to"><input type="datetime-local" className="input" value={end} onChange={(e) => setEnd(e.target.value)} /></Field>
        <button className="btn-primary" onClick={() => create.mutate(undefined, { onError: (e) => setErr((e as Error).message), onSuccess: () => setErr(null) })}>Create baseline ({source})</button>
      </div>
      {err && <div className="text-xs text-red-300">{err}</div>}
    </div>
  );
}

function SimulationControls({ device }: { device?: Device }) {
  const status = useSystemStatus();
  const live = status.data?.simulation.live_enabled;
  const [minutes, setMinutes] = useState("10");
  const [msg, setMsg] = useState<string | null>(null);
  const toggle = useApiMutation((v: boolean) => api("/simulation", { method: "PUT", json: { live_enabled: v } }), ["system-status"]);
  const gen = useApiMutation((anomaly: boolean) => api<{ generated: number }>("/simulation/generate", { method: "POST", json: { device_id: device?.data_source === "simulated" ? device.id : null, minutes: +minutes, inject_anomaly: anomaly } }),
    ["readings", "features", "alerts", "events", "summary"]);
  return (
    <div className="space-y-2 p-3">
      <Notice>Simulation generates illustrative signals for devices registered as <b>simulated</b>. Data is stored and displayed with source “Simulated”, never as real measurements.</Notice>
      <div className="flex flex-wrap items-center gap-2">
        <button className={live ? "btn-danger" : "btn-primary"} onClick={() => toggle.mutate(!live)}>{live ? <><Square className="h-3.5 w-3.5" />Stop live simulation</> : <><Play className="h-3.5 w-3.5" />Start live simulation</>}</button>
        <input className="input w-20" value={minutes} onChange={(e) => setMinutes(e.target.value)} aria-label="Minutes" />
        <span className="text-[11px] text-slate-400">min</span>
        <button className="btn-ghost" onClick={() => gen.mutate(false, { onSuccess: (r) => setMsg(`${r.generated} simulated samples generated`) })}>Generate history</button>
        <button className="btn-ghost" onClick={() => gen.mutate(true, { onSuccess: (r) => setMsg(`${r.generated} simulated samples generated with an injected anomaly episode`) })}><Wand2 className="h-3.5 w-3.5" />With anomaly</button>
      </div>
      {msg && <div className="text-[11px] text-emerald-300">{msg}</div>}
      {gen.isError && <div className="text-[11px] text-red-300">{(gen.error as Error).message}</div>}
    </div>
  );
}

function CsvUpload({ device }: { device: Device }) {
  const [res, setRes] = useState<string | null>(null);
  const qc = useQueryClient();
  const upload = async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch(`${API_BASE}/sensors/${device.id}/upload`, { method: "POST", body: fd });
    const b = await r.json().catch(() => null);
    setRes(r.ok ? `Accepted ${b.accepted}, rejected ${b.rejected} (duplicates ${b.duplicates}). Stored as UPLOADED.${b.errors?.length ? " Errors: " + b.errors.slice(0, 3).join("; ") : ""}` : `Error: ${b?.detail ?? r.status}`);
    ["readings", "features", "alerts"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  };
  return (
    <div className="space-y-2 p-3">
      <p className="text-[11px] text-slate-400">Upload historical readings (CSV header: <code className="mono">seq,ts,ax,ay,az[,gx,gy,gz,temperature_c]</code>, acceleration in g, ISO-8601 timestamps). Stored with source “Uploaded”.</p>
      <label className="btn-ghost cursor-pointer"><Upload className="h-3.5 w-3.5" />Choose CSV<input type="file" accept=".csv,text/csv" className="hidden" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} /></label>
      {res && <div className="text-[11px] text-slate-300">{res}</div>}
    </div>
  );
}

export default function Sensors() {
  const assetId = useUI((s) => s.assetId) ?? undefined;
  const devices = useDevices(assetId);
  const [params, setParams] = useSearchParams();
  const sensors = useMemo(() => (devices.data ?? []).filter((d) => d.device_type !== "camera"), [devices.data]);
  const [sel, setSel] = useState<string | null>(params.get("device"));
  useEffect(() => { if (!sel && sensors.length) setSel(sensors[0].id); }, [sensors, sel]);
  const device = sensors.find((d) => d.id === sel);
  const [blSource, setBlSource] = useState("real");
  const [envBucket, setEnvBucket] = useState(0);
  const analyze = useApiMutation((src: string) => api(`/sensors/${sel}/analyze?source=${src}`, { method: "POST" }), ["features", "alerts"]);

  return (
    <div className="pb-6">
      <PageHeader title="Sensor Analytics" subtitle="Raw accelerometer readings, derived vibration features (vib-features-v1), baselines and anomaly evaluation (vib-anomaly-v1)." />
      <div className="grid gap-3 px-5 lg:grid-cols-[260px_1fr]">
        <Card title="Sensors">
          {devices.isLoading ? <Loading /> : !sensors.length ? <Empty title="No sensors registered" /> : (
            <ul className="p-2">
              {sensors.map((d) => (
                <li key={d.id}>
                  <button onClick={() => { setSel(d.id); setParams({ device: d.id }); }} className={`mb-1 w-full rounded border px-2 py-1.5 text-left ${d.id === sel ? "border-accent/50 bg-accent/10" : "border-white/5 hover:bg-white/5"}`}>
                    <div className="flex items-center justify-between"><span className="mono">{d.id}</span><ConnBadge status={d.connection?.status} label={d.connection?.label} /></div>
                    <div className="truncate text-[11px] text-slate-400">{d.name}</div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
        {device ? (
          <div className="space-y-3">
            <SourceGate device={device}>{(src) => (
              <>
                {(device.capabilities ?? []).some((c) => c === "temperature" || c === "humidity") && (
                  <Card title="Temperature & humidity" bodyClass="p-3"><EnvironmentChart device={device} source={src} height={200} bucket={envBucket} />
                    <div className="mt-2 flex items-center gap-2 text-[11px]"><span className="label">Resolution</span>
                      <Segmented size="xs" value={String(envBucket)} onChange={(v) => setEnvBucket(+v)} options={[{ value: "0", label: "Raw" }, { value: "3600", label: "Hourly" }, { value: "86400", label: "Daily" }]} />
                    </div>
                  </Card>
                )}
                {(device.capabilities ?? ["acceleration"]).includes("acceleration") && <>
                <Card title={`${device.name} — live readings`} actions={<SourceBadge source={device.data_source} />} bodyClass="p-3"><ReadingsChart device={device} source={src} height={200} /></Card>
                <Card title="Vibration features" actions={<button className="btn-ghost" onClick={() => analyze.mutate(src ?? (device.data_source === "simulated" ? "simulated" : "real"))}>Analyse pending windows</button>} bodyClass="p-3">
                  <FeaturesChart device={device} source={src} height={220} />
                  <Notice className="mt-2">An anomaly flags a window for engineering review. Acceleration spikes may be caused by traffic, wind, temperature or sensor faults and are not, by themselves, evidence of structural damage. Incomplete windows are not evaluated.</Notice>
                </Card>
                <Card title="Feature windows (latest 60)" bodyClass="max-h-80 overflow-auto"><FeatureTable device={device} source={src} /></Card>
                </>}
              </>
            )}</SourceGate>
            <div className="grid gap-3 xl:grid-cols-2">
              <Card title="Baselines" actions={device.data_source === "real" ? (
                <select className="input w-28" value={blSource} onChange={(e) => setBlSource(e.target.value)} aria-label="Baseline source"><option value="real">Real</option><option value="uploaded">Uploaded</option></select>
              ) : undefined}><Baselines device={device} source={device.data_source === "simulated" ? "simulated" : blSource} /></Card>
              {device.data_source === "simulated" ? <Card title="Simulation provider"><SimulationControls device={device} /></Card> : <Card title="Upload historical data"><CsvUpload device={device} /></Card>}
            </div>
          </div>
        ) : <Empty title="Select a sensor" />}
      </div>
    </div>
  );
}
